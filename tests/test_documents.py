import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile

from koala import DISCLAIMER
from koala.cli import main
from koala.core import DEFAULT_BRIEF, read_json, save
from koala.documents import (FIELDS, paragraphs, chunks, analyse_document,
                             validate_analysis, add_documents, merge)
from koala.pipeline import prepare, draft, incorporate_documents, continue_prepare
from test_koala import FakeProvider, source


def write_docx(path, texts, notes=False):
    def p(t):
        return f'<w:p><w:r><w:t>{escape(t)}</w:t></w:r></w:p>'
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', f'<w:document {ns}><w:body>' +
                   ''.join(p(t) for t in texts) + '<w:tbl><w:tr><w:tc>' + p('Table evidence') +
                   '</w:tc></w:tr></w:tbl></w:body></w:document>')
        if notes:
            z.writestr('word/footnotes.xml', f'<w:footnotes {ns}><w:footnote w:id="1">' +
                       p('Footnote evidence') + '</w:footnote></w:footnotes>')
            z.writestr('word/endnotes.xml', f'<w:endnotes {ns}><w:endnote w:id="1">' +
                       p('Endnote evidence') + '</w:endnote></w:endnotes>')
    return path


class DocumentProvider(FakeProvider):
    def __init__(self):
        self.events = []
        self.calls = 0

    def check_model(self):
        pass

    def json(self, instructions, prompt):
        self.calls += 1
        if prompt.startswith('Analyse this document chunk.'):
            self.events.append(('analyse', prompt))
            content = prompt.split('\n', 1)[1]
            options = json.loads(content) if content.startswith('{') else None
            if options:
                content = '\n'.join(options.values())
            line = next((line for line in content.splitlines() if line.strip() and not line.startswith('[')), content)
            evidence = line[:100]
            raw = {'overview': 'A document about memory.', **{field: [] for field in FIELDS}}
            raw['themes'] = [{'text': 'Memory and belonging', 'evidence': evidence}]
            for field, text in [('authors', 'Scholar'), ('citations', 'Scholar (2020).')]:
                if text in content:
                    raw[field] = [{'text': text, 'evidence': text}]
            if options:
                for field in FIELDS:
                    for item in raw[field]:
                        item['evidence_id'] = next(k for k, v in options.items() if item['evidence'] in v)
                        item.pop('evidence')
            return raw
        if prompt.startswith('Combine these analyses'):
            self.events.append(('merge', prompt))
            inputs = json.loads(prompt.split('\n', 1)[1])
            ids = []
            for field in FIELDS:
                findings = [x['id'] for item in inputs for x in item[field]]
                ids.extend(list(dict.fromkeys(findings))[-6:])
            return {'overview': 'Combined document inspiration.', 'selected_ids': ids}
        if prompt.startswith('Select the most relevant'):
            return {'source_ids': ['S001'], 'limitations': []}
        self.events.append(('plan', prompt))
        return super().json(instructions, prompt)

    def generate(self, instructions, prompt):
        self.events.append(('generate', prompt))
        return super().generate(instructions, prompt)


class DocumentExtractionTests(unittest.TestCase):
    def test_paragraphs_tables_and_notes(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(Path(d)/'input.docx', ['First', 'Renée and memory'], notes=True)
            extracted = list(paragraphs(path))
            self.assertEqual([t for _, t in extracted], ['First', 'Renée and memory', 'Table evidence',
                                                        'Footnote evidence', 'Endnote evidence'])
            self.assertEqual(extracted[1][0], 'word/document.xml:p2')

    def test_large_paragraph_bounded_chunks_without_loss(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(Path(d)/'large.docx', ['START ' + ('memory and place ' * 50000) + ' END'])
            parts = list(chunks(path))
            self.assertGreater(len(parts), 50)
            self.assertTrue(all(len(p['text']) <= 6000 for p in parts))
            reconstructed = parts[0]['text']
            for previous, current in zip(parts, parts[1:]):
                overlap = previous['end'] - current['start']
                self.assertEqual(previous['text'][-overlap:], current['text'][:overlap])
                reconstructed += current['text'][overlap:]
            expected = ''.join(f'[{loc}]\n{text}\n' for loc, text in paragraphs(path))
            self.assertEqual(reconstructed, expected)

    def test_bad_docx(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'bad.docx'
            path.write_text('not a zip')
            with self.assertRaisesRegex(ValueError, 'Cannot read DOCX'):
                list(chunks(path))
            with ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', '<!DOCTYPE x [<!ENTITY x "bad">]><x/>')
            with self.assertRaisesRegex(ValueError, 'DTD/entity'):
                list(chunks(path))

    def test_empty_document(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'empty.docx'
            with ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', '<document/>')
            with self.assertRaisesRegex(ValueError, 'no readable'):
                analyse_document(DocumentProvider(), path, Path(d)/'run', lambda _: None)

    def test_hallucinated_reference_rejected(self):
        raw = {'overview': 'A summary', **{field: [] for field in FIELDS}}
        raw['citations'] = [{'text': 'Invented Book (2025)', 'evidence': 'Memory'}]
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            validate_analysis(raw, {'text': 'Memory', 'id': 'c000001'}, 'hash')
        raw['citations'] = []
        raw['themes'] = [{'text': 'Memory', 'evidence': 'invented quotation'}]
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            validate_analysis(raw, {'text': 'Memory', 'id': 'c000001'}, 'hash')


class DocumentAnalysisTests(unittest.TestCase):
    def test_cached_analysis_and_full_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(Path(d)/'input.docx', ['Memory connects people. Scholar (2020).'] * 400)
            p = DocumentProvider()
            manifest = analyse_document(p, path, d, lambda _: None)
            self.assertGreater(manifest['chunk_count'], 1)
            self.assertEqual(manifest['disclaimer'], DISCLAIMER)
            finding = manifest['digest']['citations'][0]
            self.assertEqual(finding['verification'], 'document-derived; unverified')
            self.assertEqual(finding['document_sha256'], manifest['sha256'])
            before = p.calls
            self.assertEqual(analyse_document(p, path, d, lambda _: None), manifest)
            self.assertEqual(p.calls, before)

    def test_resume_after_local_merge_interruption_keeps_map_results(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(Path(d)/'input.docx', ['Memory connects people. Scholar (2020).'] * 500)
            p = DocumentProvider()
            with patch('koala.documents.merge', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    analyse_document(p, path, d, lambda _: None)
            self.assertEqual(p.calls, 1)
            manifest = analyse_document(p, path, d, lambda _: None)
            self.assertEqual(p.calls, manifest['chunk_count'])

    def test_dedup_and_changed_document(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(Path(d)/'input.docx', ['Memory'])
            p = DocumentProvider()
            result, added = add_documents(p, {}, [path, path], d, lambda _: None)
            self.assertTrue(added)
            self.assertEqual(len(result['documents']), 1)
            _, added = add_documents(p, {'inspiration': result}, [path], d, lambda _: None)
            self.assertFalse(added)
            write_docx(path, ['Changed memory'])
            result, added = add_documents(p, {'inspiration': result}, [path], d, lambda _: None)
            self.assertTrue(added)
            self.assertEqual(len(result['documents']), 2)

    def test_merge_is_local_and_preserves_only_existing_findings(self):
        summary = {'overview': 'x', **{field: [] for field in FIELDS}}
        summary['themes'] = [{'id': str(i), 'text': f'Theme {i}', 'evidence': 'x'} for i in range(20)]
        p = DocumentProvider()
        with patch.object(p, 'json', side_effect=AssertionError('No synthesis call allowed')):
            result = merge(p, summary, summary)
        self.assertEqual(len(result['themes']), 6)
        self.assertTrue(all(item in summary['themes'] for item in result['themes']))


class InspirationPipelineTests(unittest.TestCase):
    def setup_run(self, d):
        base = Path(d)
        save(base/'sources.json', [source()])
        brief = {**DEFAULT_BRIEF, 'sources_file': 'sources.json', 'citation_target': 1, 'target_words': 1000}
        path = write_docx(base/'inspiration.docx', ['Memory connects people. Scholar (2020).'])
        return base, brief, path

    def test_document_precedes_plan_abstract_and_draft(self):
        with tempfile.TemporaryDirectory() as d:
            base, brief, path = self.setup_run(d)
            p = DocumentProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None, documents=[path])
            self.assertEqual(p.events[0][0], 'analyse')
            plan_prompt = next(text for event, text in p.events if event == 'plan')
            self.assertIn('Memory and belonging', plan_prompt)
            a = draft(p, a, base/'run', lambda _: None)
            self.assertTrue(all('document_inspiration' in text for event, text in p.events if event == 'generate'))
            self.assertEqual(a['audit']['issues'], [])
            self.assertEqual(len(a['sources']), 1)  # extracted citations are not directly trusted

    def test_docx_in_source_files_and_inspiration_files(self):
        for field in ('source_files', 'inspiration_files'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                base, brief, path = self.setup_run(d)
                brief[field] = [path.name]
                a = prepare(DocumentProvider(), brief, base/'run', base/'brief.json', True, lambda _: None)
                self.assertEqual(len(a['inspiration']['documents']), 1)

    def test_late_document_preserves_old_draft_and_rebuilds(self):
        with tempfile.TemporaryDirectory() as d:
            base, brief, path = self.setup_run(d)
            p = DocumentProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            a = draft(p, a, base/'run', lambda _: None)
            (base/'run/article.txt').write_text('old export')
            updated = incorporate_documents(p, a, [path], base/'run', lambda _: None)
            self.assertEqual(updated['stage'], 'planning')
            self.assertEqual(updated['sections'], [])
            archive = Path(updated['revision_history'][-1])
            self.assertEqual(read_json(archive/'article.json')['sections'], a['sections'])
            self.assertEqual((archive/'article.txt').read_text(), 'old export')
            self.assertFalse((base/'run/article.txt').exists())
            updated = continue_prepare(p, updated, base/'run', base, True, lambda _: None)
            updated = draft(p, updated, base/'run', lambda _: None)
            self.assertEqual(len(updated['sections']), 4)
            self.assertEqual(updated['sources'][0]['id'], 'S001')

    def test_ingest_cli_before_abstract_and_after_abstract(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base, brief, path = self.setup_run(d)
            save(base/'brief.json', brief)
            with patch('koala.cli.Provider', return_value=DocumentProvider()):
                result = main(['ingest', str(path), '--brief', str(base/'brief.json'), '--out', str(base/'run')])
                self.assertEqual(result, 0)
                a = read_json(base/'run/article.json')
                self.assertEqual(a['stage'], 'planning')
                self.assertFalse(a['abstract'])
                result = main(['abstract', '--out', str(base/'run'), '--resume', '--formats', 'txt'])
                self.assertEqual(result, 0)
                self.assertTrue((base/'run/abstract.txt').exists())
                new_path = write_docx(base/'new.docx', ['A new direction for memory'])
                result = main(['ingest', str(new_path), '--out', str(base/'run')])
                self.assertEqual(result, 0)
                self.assertEqual(read_json(base/'run/article.json')['stage'], 'planning')

    def test_document_flag_on_new_run_and_partial_resume(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base, brief, path = self.setup_run(d)
            save(base/'brief.json', brief)
            with patch('koala.cli.Provider', return_value=DocumentProvider()):
                self.assertEqual(main(['abstract', '--document', str(path), '--brief', str(base/'brief.json'),
                                       '--out', str(base/'run'), '--formats', 'txt']), 0)
                a = read_json(base/'run/article.json')
                a['sections'] = [{'heading': 'Prior manual section', 'text': 'Preserve this in archive.'}]
                a['stage'] = 'drafting'
                a['sources'][0]['notes'] = 'Human research note'
                save(base/'run/article.json', a)
                new = write_docx(base/'later.docx', ['New material about memory'])
                self.assertEqual(main(['generate', '--resume', '--document', str(new), '--out', str(base/'run'),
                                       '--no-research', '--formats', 'txt']), 0)
                revised = read_json(base/'run/article.json')
                self.assertEqual(len(revised['sections']), 4)
                self.assertEqual(revised['sources'][0]['notes'], 'Human research note')
                archive = read_json(Path(revised['revision_history'][-1])/'article.json')
                self.assertEqual(archive['sections'], a['sections'])
                self.assertEqual(archive['pending_documents'], [])

    def test_old_checkpoint_brief_compatible(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base, brief, path = self.setup_run(d)
            old = {k: v for k, v in brief.items() if k != 'inspiration_files'}
            save(base/'brief.json', old)
            a = prepare(DocumentProvider(), old, base/'run', base/'brief.json', True, lambda _: None)
            with patch('koala.cli.Provider', return_value=DocumentProvider()):
                self.assertEqual(main(['abstract', '--resume', '--brief', str(base/'brief.json'),
                                       '--out', str(base/'run'), '--formats', 'txt']), 0)

    def test_failure_does_not_erase_article(self):
        with tempfile.TemporaryDirectory() as d:
            base, brief, path = self.setup_run(d)
            p = DocumentProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            before = (base/'run/article.json').read_bytes()
            with patch.object(p, 'json', side_effect=RuntimeError('outage')):
                with self.assertRaises(RuntimeError):
                    incorporate_documents(p, a, [path], base/'run', lambda _: None)
            self.assertEqual((base/'run/article.json').read_bytes(), before)

    def test_extracted_citations_reach_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            base, brief, path = self.setup_run(d)
            brief['sources_file'] = ''
            with patch('koala.pipeline.discover', return_value=([source()], [])) as discovery:
                prepare(DocumentProvider(), brief, base/'run', base/'brief.json', False, lambda _: None, documents=[path])
            passed_brief = discovery.call_args.args[0]
            self.assertIn('Scholar (2020).', passed_brief['possible_citations'])
            self.assertIn('Scholar', passed_brief['important_authors'])

if __name__ == '__main__':
    unittest.main()
