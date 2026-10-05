import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from koala import DISCLAIMER
from koala.cli import main
from koala.core import DEFAULT_BRIEF, audit, load_brief, save, validate_sources, words
from koala.exporters import blocks, export, rtf_escape
from koala.pipeline import prepare, draft, make_abstract
from koala.providers import Provider
from koala.research import discover, normalize


def source(i=1):
    return {'id': f'S{i:03}', 'title': 'Interpretation and cultural memory',
            'authors': ['Renée Scholar'], 'year': '2020', 'doi': f'10.1234/example{i}',
            'abstract': 'A test fixture, not a real scholarly reference.'}


def article():
    return {'title': 'Cultural memory and interpretation', 'disclaimer': DISCLAIMER,
            'abstract': ' '.join(['Scholarship'] * 270),
            'sections': [{'heading': 'Discussion', 'text': 'Interpretation matters [@S001].'}],
            'sources': [source()], 'brief': {**DEFAULT_BRIEF, 'citation_target': 1, 'target_words': 1000}}


class FakeProvider:
    name = 'openai'
    model = 'test-fixture'

    def json(self, instructions, prompt):
        return {'title': 'Cultural memory', 'topic': 'Cultural memory', 'discipline': 'Literary studies',
                'style_guidance': 'Academic', 'research_question': 'How is memory narrated?',
                'assumptions': ['Topic inferred'], 'target_journals': ['Literary studies journals'],
                'search_queries': ['cultural memory'],
                'sections': [{'heading': f'Section {i}', 'purpose': 'Develop argument'} for i in range(4)]}

    def generate(self, instructions, prompt):
        if '250–300' in prompt:
            return ' '.join(['Memory'] * 270)
        return ' '.join(['Interpretation'] * 249) + ' [@S001]'


class CoreTests(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(words("It's a well-known idea."), 4)

    def test_brief_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'brief.json'
            for value in ({'citation_target': 0}, {'target_words': 'long'}, {'unknown': 1}, {'topic': []}):
                save(p, value)
                with self.assertRaises(ValueError):
                    load_brief(p)
            save(p, {})
            self.assertEqual(load_brief(p)['citation_target'], 75)

    def test_unknown_and_shortfall(self):
        a = article()
        a['sections'][0]['text'] += ' [@S999] [@oops]'
        report = audit(a)
        self.assertEqual(report['unknown_ids'], ['S999'])
        self.assertTrue(any('Malformed' in x for x in report['issues']))

    def test_distinct_is_not_occurrences(self):
        a = article()
        a['sections'][0]['text'] *= 5
        result = audit(a)
        self.assertEqual(result['distinct_cited_works'], 1)
        self.assertEqual(result['citation_occurrences'], 5)

    def test_seventy_five_distinct_citations(self):
        a = article()
        a['sources'] = [source(i) for i in range(1, 76)]
        a['sections'][0]['text'] = ' '.join(f'Claim [@S{i:03}]' for i in range(1, 76))
        a['brief']['citation_target'] = 75
        result = audit(a)
        self.assertEqual(result['distinct_cited_works'], 75)
        self.assertFalse(any('shortfall' in issue for issue in result['issues']))
        self.assertEqual(len([k for k, _ in blocks(a) if k == 'reference']), 75)

    def test_partial_draft_detected(self):
        a = article()
        a['plan'] = {'sections': [{}, {}]}
        self.assertTrue(any('incomplete' in x for x in audit(a)['issues']))

    def test_duplicate_sources_rejected(self):
        with self.assertRaises(ValueError):
            validate_sources([source(), source()])

    def test_abstract_retry(self):
        provider = FakeProvider()
        with patch.object(provider, 'generate', side_effect=['too short', ' '.join(['Word'] * 275)]):
            a = article()
            a.update(plan={}, excerpts=[])
            self.assertEqual(words(make_abstract(provider, a)), 275)

    def test_abstract_failure(self):
        provider = FakeProvider()
        with patch.object(provider, 'generate', return_value='too short'):
            a = article()
            a.update(plan={}, excerpts=[])
            with self.assertRaises(ValueError):
                make_abstract(provider, a)

    def test_pipeline_resume(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            save(base / 'sources.json', [source()])
            brief = {**DEFAULT_BRIEF, 'target_words': 1000, 'citation_target': 1, 'sources_file': 'sources.json'}
            a = prepare(FakeProvider(), brief, base / 'run', base / 'brief.json', True, lambda _: None)
            self.assertEqual(a['stage'], 'abstract')
            self.assertEqual(a['brief_directory'], str(base.resolve()))
            a = draft(FakeProvider(), a, base / 'run', lambda _: None)
            self.assertEqual(len(a['sections']), 4)
            self.assertEqual(a['audit']['issues'], [])
            with patch.object(FakeProvider, 'generate', side_effect=AssertionError('should not redraft')):
                draft(FakeProvider(), a, base / 'run', lambda _: None)
            self.assertTrue((base / 'run/audit.json').exists())

    def test_init_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            p = str(Path(d) / 'brief.json')
            self.assertEqual(main(['init', p]), 0)
            self.assertEqual(main(['init', p]), 2)


class ProviderTests(unittest.TestCase):
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'ARC_API_KEY': 'test-key'})
    def test_defaults_and_discovery(self):
        p = Provider()
        self.assertEqual(p.model, 'gpt-6-luna')
        with patch('koala.providers.request_json', return_value={'data': [{'id': p.model}, {'id': 'other'}]}):
            p.check_model()
            self.assertIn('other', p.models())
        with patch('koala.providers.request_json', return_value={'data': []}):
            with self.assertRaisesRegex(ValueError, 'No model was substituted'):
                p.check_model()
        self.assertEqual(Provider('arc').base, 'https://llm-api.arc.vt.edu/api/v1')

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'})
    def test_responses_payload_and_incomplete(self):
        p = Provider()
        data = {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': 'result'}]}]}
        with patch('koala.providers.request_json', return_value=data) as req:
            self.assertEqual(p.generate('system', 'prompt'), 'result')
            self.assertFalse(req.call_args.args[1]['store'])
            self.assertTrue(req.call_args.args[0].endswith('/responses'))
        with patch('koala.providers.request_json', return_value={'status': 'incomplete'}):
            with self.assertRaises(RuntimeError):
                p.generate('system', 'prompt')

    @patch.dict('os.environ', {'ARC_API_KEY': 'test-key'})
    def test_arc_payload(self):
        p = Provider('arc', 'test')
        with patch('koala.providers.request_json', return_value={'choices': [{'finish_reason': 'stop', 'message': {'content': 'result'}}]}) as req:
            self.assertEqual(p.generate('system', 'prompt'), 'result')
            self.assertEqual(req.call_args.args[1]['max_tokens'], 8000)

    @patch.dict('os.environ', {}, clear=True)
    def test_missing_key(self):
        with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
            Provider()

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'})
    def test_https(self):
        with self.assertRaises(ValueError):
            Provider(base_url='http://example.com')


class ResearchTests(unittest.TestCase):
    def test_metadata_normalization(self):
        s = normalize({'DOI': '10.1/ABC', 'title': ['<i>Memory</i>'], 'author': [{'given': 'A', 'family': 'Writer'}],
                       'published': {'date-parts': [[2020]]}, 'abstract': '<jats:p>A study.</jats:p>'})
        self.assertEqual(s['title'], 'Memory')
        self.assertEqual(s['verification'], 'metadata-only')
        self.assertEqual(s['abstract'], 'A study.')

    def test_discovery_deduplicates(self):
        class FakeCrossref:
            def query(self, query, rows):
                return [source(), source()]
        sources, warnings = discover(DEFAULT_BRIEF, {'search_queries': ['memory', 'narrative']}, FakeCrossref())
        self.assertEqual(len(sources), 1)
        self.assertTrue(any('target of 75' in warning for warning in warnings))


class ExportTests(unittest.TestCase):
    def test_all_exports_disclaimers_and_unicode(self):
        with tempfile.TemporaryDirectory() as d:
            paths = export(article(), d)
            self.assertEqual(len(paths), 5)
            for extension in ('txt', 'html', 'rtf'):
                self.assertIn(DISCLAIMER, (Path(d)/f'article.{extension}').read_text())
            with ZipFile(Path(d)/'article.docx') as z:
                self.assertIn(DISCLAIMER, z.read('word/document.xml').decode())
            from pypdf import PdfReader
            text = '\n'.join(p.extract_text() for p in PdfReader(Path(d)/'article.pdf').pages)
            self.assertIn(DISCLAIMER, text)
            self.assertIn('Renée', text)

    def test_html_escaping(self):
        a = article()
        a['title'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as d:
            export(a, d, ['html'])
            text = (Path(d)/'article.html').read_text()
            self.assertNotIn('<script>', text)
            self.assertIn('&lt;script&gt;', text)

    def test_invalid_citation_blocks_exports(self):
        a = article()
        a['sections'][0]['text'] += ' [@S999]'
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                export(a, d)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_strict_blocks_short_article(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                export(article(), d, ['txt'], strict=True)

    def test_numeric_and_unused_bibliography(self):
        a = article()
        a['brief']['citation_style'] = 'numeric'
        a['sources'].append(source(2))
        rendered = blocks(a)
        self.assertIn('[1]', rendered[5][1])
        self.assertEqual(len([k for k, _ in rendered if k == 'reference']), 1)

    def test_rtf_escapes(self):
        self.assertEqual(rtf_escape('{é}'), r'\{\u233?\}')
        self.assertEqual(rtf_escape('😀'), r'\u-10179?\u-8704?')

    def test_abstract_export_disclaimer(self):
        with tempfile.TemporaryDirectory() as d:
            export(article(), d, ['txt'], abstract_only=True)
            text = (Path(d)/'abstract.txt').read_text()
            self.assertIn(DISCLAIMER, text)
            self.assertNotIn('References', text)

if __name__ == '__main__':
    unittest.main()
