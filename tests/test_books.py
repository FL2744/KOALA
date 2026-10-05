import copy
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from koala import BOOK_DISCLAIMER, is_book
from koala.core import audit, load_brief, normalize_brief, prose_words, save, read_json
from koala.books import (allocate_outline, validate_book_plan, select_context_sources,
                         research_book, chapter_label)
from koala.cli import main
from koala.pipeline import prepare, draft, SYSTEM, incorporate_documents, continue_prepare
from koala.exporters import export, blocks
from koala.research import discover
from test_documents import DocumentProvider, write_docx


def book_sources(n=200):
    return [{'id': f'S{i:03}', 'title': f'Memory study {i}', 'authors': [f'Author {i}'],
             'year': '2020', 'doi': f'10.1234/fixture{i}',
             'notes': 'Synthetic testing metadata, not real scholarship.'} for i in range(1, n+1)]


def book_plan(brief):
    chapters = [{'kind': 'introduction', 'heading': 'Introduction', 'purpose': 'Set out scope and central argument'}]
    chapters += [{'kind': 'chapter', 'heading': f'Memory and place {i}', 'purpose': f'Develop distinct argument {i}'}
                 for i in range(1, brief['chapter_count']+1)]
    if brief['include_afterword']:
        chapters.append({'kind': 'afterword', 'heading': 'Afterword', 'purpose': 'Reflect on implications'})
    chapters += [{'kind': 'appendix', 'heading': title, 'purpose': 'Document supplementary material'} for title in brief['appendices']]
    return {'title': 'Memory and place', 'topic': 'Cultural memory', 'discipline': 'Literary studies',
            'style_guidance': 'Scholarly Australian English', 'research_question': 'How is place remembered?',
            'assumptions': [], 'target_publishers': ['Scholarly presses'],
            'search_queries': [f'cultural memory theme {i}' for i in range(20)], 'chapters': chapters}


class BookProvider(DocumentProvider):
    def json(self, system, prompt):
        if prompt.startswith('Plan a scholarly book'):
            context = json.loads(prompt.split('Context:\n', 1)[1])
            self.events.append(('book_plan', prompt))
            return book_plan(context['brief'])
        if prompt.startswith('Develop exactly'):
            n = int(re.search(r'Develop exactly (\d+)', prompt)[1])
            self.events.append(('chapter_plan', prompt))
            return {'sections': [{'heading': f'Argument {i+1}', 'purpose': f'Explain memory argument {i+1}'} for i in range(n)]}
        if prompt.startswith('Summarise this completed'):
            self.events.append(('summary', prompt))
            return {'summary': 'The argument connects memory and place, maintaining the stated scope and qualifications.'}
        if prompt.startswith('Select up to'):
            quota = int(re.search(r'Select up to (\d+)', prompt)[1])
            context = json.loads(prompt.split('\n', 1)[1])
            self.events.append(('select', prompt))
            return {'source_ids': [s['id'] for s in context['candidates'][:quota]]}
        return super().json(system, prompt)

    def generate(self, system, prompt):
        if prompt.startswith('Write one section of a scholarly book.'):
            self.events.append(('book_section', prompt))
            target = int(re.search(r'Target (\d+) prose', prompt)[1])
            context = json.loads(prompt.split('\n', 1)[1])
            return ' '.join(['Memory'] * target) + ' ' + ' '.join(f'[@{s["id"]}]' for s in context['sources'])
        return super().generate(system, prompt)


def setup_book(base, target=40000, citations=200, **kwargs):
    brief = normalize_brief({'project_type': 'book', 'target_words': target, 'citation_target': citations,
                             'chapter_count': 5, 'sources_file': 'sources.json', **kwargs})
    save(base/'sources.json', book_sources(citations))
    return brief


class BookConfigurationTests(unittest.TestCase):
    def test_defaults_and_scaling(self):
        self.assertEqual(normalize_brief({})['target_words'], 6500)
        for target, expected in ((40000, 200), (65000, 450), (100000, 800)):
            brief = normalize_brief({'project_type': 'book', 'target_words': target})
            self.assertEqual(brief['citation_target'], expected)
            self.assertEqual(brief['chapter_count'], 6)
        self.assertEqual(normalize_brief({'project_type': 'book', 'citation_target': 275})['citation_target'], 275)

    def test_ranges_and_types(self):
        for field, value in (('target_words', 39999), ('target_words', 100001), ('chapter_count', 4),
                             ('chapter_count', 9), ('citation_target', 199), ('citation_target', 801),
                             ('include_afterword', 'yes'), ('appendices', [''])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                normalize_brief({'project_type': 'book', field: value})

    def test_init_book_auto_citations(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            path = Path(d)/'brief.json'
            self.assertEqual(main(['init', str(path), '--type', 'book', '--words', '80000', '--chapters', '8',
                                   '--afterword', '--appendix', 'Archive inventory']), 0)
            self.assertIsNone(read_json(path)['citation_target'])
            brief = load_brief(path)
            self.assertEqual(brief['citation_target'], 600)
            self.assertTrue(brief['include_afterword'])
            self.assertEqual(brief['appendices'], ['Archive inventory'])

    def test_exact_allocation_all_sizes(self):
        for target in (40000, 65000, 100000):
            for n in (5, 8):
                brief = normalize_brief({'project_type': 'book', 'target_words': target, 'chapter_count': n,
                                         'include_afterword': True, 'appendices': ['A', 'B']})
                plan = allocate_outline(validate_book_plan(book_plan(brief), brief), brief)
                validate_book_plan(plan, brief)
                self.assertEqual(sum(s['target_words'] for s in plan['sections']), target)
                self.assertEqual(sum(c['target_words'] for c in plan['chapters']), target)
                self.assertTrue(all(100 <= s['target_words'] <= 1200 for s in plan['sections']))
                self.assertEqual(len(plan['chapters']), n+4)

    def test_missing_intro_and_unrequested_extras_rejected(self):
        brief = normalize_brief({'project_type': 'book'})
        p = book_plan(brief)
        p['chapters'] = p['chapters'][1:]
        with self.assertRaises(ValueError):
            validate_book_plan(p, brief)
        p = book_plan(brief)
        p['chapters'].append({'kind': 'afterword', 'heading': 'Afterword', 'purpose': 'Reflect'})
        with self.assertRaises(ValueError):
            validate_book_plan(p, brief)

    def test_bad_saved_section_budget_rejected(self):
        brief = normalize_brief({'project_type': 'book'})
        p = allocate_outline(book_plan(brief), brief)
        p['sections'][0]['target_words'] = 2
        with self.assertRaises(ValueError):
            validate_book_plan(p, brief)


class BookResearchTests(unittest.TestCase):
    def test_discovery_can_exceed_old_750_limit(self):
        class Crossref:
            count = 0
            def query(self, query, rows):
                result = book_sources(rows)
                for item in result:
                    self.count += 1
                    item['doi'] = f'10.1234/{self.count}'
                return result
        brief = normalize_brief({'project_type': 'book', 'target_words': 100000})
        candidates, _ = discover(brief, book_plan(brief), Crossref())
        self.assertGreaterEqual(len(candidates), 1600)

    def test_selection_batches_and_cached_resume(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            brief = normalize_brief({'project_type': 'book', 'target_words': 100000})
            a = {'brief': brief, 'plan': allocate_outline(book_plan(brief), brief), 'warnings': []}
            p = BookProvider()
            with patch('koala.research.discover', return_value=(book_sources(1200), [])) as search:
                sources = research_book(p, a, brief, folder, SYSTEM, lambda _: None)
                self.assertEqual(len(sources), 800)
                self.assertEqual(len([e for e, _ in p.events if e == 'select']), 30)
                with patch.object(p, 'json', side_effect=AssertionError('must use cached selection')):
                    self.assertEqual(research_book(p, a, brief, folder, SYSTEM, lambda _: None), sources)
                self.assertEqual(search.call_count, 1)

    def test_partial_selection_resumes_after_completed_batch(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            brief = normalize_brief({'project_type': 'book', 'target_words': 40000})
            a = {'brief': brief, 'plan': allocate_outline(book_plan(brief), brief), 'warnings': []}
            p = BookProvider()
            original = p.json
            attempts = [0]
            def interrupted(system, prompt):
                attempts[0] += 1
                if attempts[0] == 2:
                    raise RuntimeError('temporary outage')
                return original(system, prompt)
            with patch('koala.research.discover', return_value=(book_sources(400), [])) as search:
                with patch.object(p, 'json', side_effect=interrupted), self.assertRaises(RuntimeError):
                    research_book(p, a, brief, folder, SYSTEM, lambda _: None)
                self.assertEqual(read_json(folder/'book-selection.json')['processed'], 40)
                selected = research_book(p, a, brief, folder, SYSTEM, lambda _: None)
                self.assertEqual(len(selected), 200)
                self.assertEqual(len([e for e, _ in p.events if e == 'select']), 10)
                self.assertEqual(search.call_count, 1)

    def test_source_context_bounded_and_all_assigned(self):
        brief = normalize_brief({'project_type': 'book'})
        a = {'brief': brief, 'plan': allocate_outline(book_plan(brief), brief), 'sources': book_sources(800), 'sections': []}
        seen = set()
        for i in range(len(a['plan']['sections'])):
            selected = select_context_sources(a, i, 'memory')
            self.assertLessEqual(len(selected), 40)
            seen.update(s['id'] for s in selected)
        self.assertEqual(len(seen), 800)


class BookDraftTests(unittest.TestCase):
    def test_full_40000_word_book_and_noop_resume(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base)
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            a = draft(p, a, base/'run', lambda _: None)
            self.assertEqual(a['audit']['body_words'], 40000)
            self.assertEqual(a['audit']['distinct_cited_works'], 200)
            self.assertEqual(a['audit']['issues'], [])
            self.assertEqual(a['audit']['disclaimer'], BOOK_DISCLAIMER)
            prompts = [t for event, t in p.events if event == 'book_section']
            self.assertLess(max(map(len, prompts)), 100000)
            self.assertNotIn('earlier_sections', prompts[-1])
            with patch.object(p, 'generate', side_effect=AssertionError('no redraft')):
                draft(p, a, base/'run', lambda _: None)

    def test_full_100000_word_book_with_800_citations_and_extras(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base, target=100000, citations=800, chapter_count=8,
                               include_afterword=True, appendices=['Evidence catalogue', 'Methodological notes'])
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            a = draft(p, a, base/'run', lambda _: None)
            self.assertEqual(a['audit']['body_words'], 100000)
            self.assertEqual(a['audit']['distinct_cited_works'], 800)
            self.assertEqual(a['audit']['issues'], [])
            self.assertEqual(len(a['audit']['chapters']), 12)
            self.assertLess(max(len(text) for event, text in p.events if event == 'book_section'), 150000)

    def test_variable_section_lengths_stay_within_book_range(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base)
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            original = p.generate
            count = [0]
            def varied(system, prompt):
                if not prompt.startswith('Write one section'):
                    return original(system, prompt)
                text = original(system, prompt)
                low, high = map(int, re.search(r'acceptable range (\d+)–(\d+)', prompt).groups())
                count[0] += 1
                target = low if count[0] % 2 else high
                citations = re.findall(r'\[@S\d+\]', text)
                return ' '.join(['Memory'] * target) + ' ' + ' '.join(citations)
            with patch.object(p, 'generate', side_effect=varied):
                a = draft(p, a, base/'run', lambda _: None)
            self.assertGreaterEqual(a['audit']['body_words'], 40000)
            self.assertLessEqual(a['audit']['body_words'], 44000)
            self.assertEqual(a['audit']['issues'], [])

    def test_resume_after_summary_failure_does_not_redraft_saved_prose(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base)
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            original = p.json
            def fail(system, prompt):
                if prompt.startswith('Summarise this completed'):
                    raise RuntimeError('outage')
                return original(system, prompt)
            with patch.object(p, 'json', side_effect=fail), self.assertRaises(RuntimeError):
                draft(p, a, base/'run', lambda _: None)
            saved = read_json(base/'run/article.json')
            self.assertEqual(len(saved['sections']), 1)
            first = saved['sections'][0]['text']
            done = draft(p, saved, base/'run', lambda _: None)
            self.assertEqual(done['sections'][0]['text'], first)
            self.assertEqual(len([e for e, _ in p.events if e == 'book_section']), len(done['sections']))

    def test_short_section_fails_instead_of_claiming_book_complete(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base)
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            with patch.object(p, 'generate', return_value='too short'), self.assertRaisesRegex(ValueError, '3 attempts'):
                draft(p, a, base/'run', lambda _: None)
            self.assertEqual(a['sections'], [])

    def test_late_inspiration_archives_book_state(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            brief = setup_book(base)
            p = BookProvider()
            a = prepare(p, brief, base/'run', base/'brief.json', True, lambda _: None)
            (base/'run/manuscript.txt').write_text('previous manuscript')
            (base/'run/book-selection.json').write_text('{}')
            doc = write_docx(base/'notes.docx', ['Memory connects people.'])
            updated = incorporate_documents(p, a, [doc], base/'run', lambda _: None)
            archive = Path(updated['revision_history'][-1])
            self.assertTrue((archive/'manuscript.txt').exists())
            self.assertTrue((archive/'book-selection.json').exists())
            self.assertEqual(updated['stage'], 'planning')
            updated = continue_prepare(p, updated, base/'run', base, True, lambda _: None)
            self.assertEqual(len(updated['plan']['chapters']), 6)

    def test_cli_book_abstract_and_refuses_changed_resume(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base = Path(d)
            brief = setup_book(base)
            save(base/'brief.json', brief)
            with patch('koala.cli.Provider', return_value=BookProvider()):
                self.assertEqual(main(['abstract', '--brief', str(base/'brief.json'), '--out', str(base/'run'), '--formats', 'txt']), 0)
                self.assertIn(BOOK_DISCLAIMER, (base/'run/abstract.txt').read_text())
                self.assertEqual(main(['generate', '--resume', '--out', str(base/'run'), '--words', '70000']), 2)


class BookExportTests(unittest.TestCase):
    def fixture(self):
        brief = normalize_brief({'project_type': 'book', 'include_afterword': True, 'appendices': ['Evidence inventory']})
        plan = allocate_outline(book_plan(brief), brief)
        return {'brief': brief, 'plan': plan, 'title': 'Memory and place', 'abstract': 'A synthetic layout fixture.',
                'sources': book_sources(1), 'sections': [
                    {'chapter_index': i, 'heading': 'Evidence and interpretation',
                     'text': 'This is a synthetic paragraph used to verify manuscript formatting [@S001].'}
                    for i in range(len(plan['chapters']))]}

    def test_all_book_exports_structure_and_disclosure(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.fixture()
            paths = export(a, d)
            self.assertEqual({p.name for p in paths}, {'manuscript.'+fmt for fmt in ('txt','html','rtf','docx','pdf')})
            for fmt in ('txt','html','rtf'):
                text = (Path(d)/f'manuscript.{fmt}').read_text()
                self.assertIn(BOOK_DISCLAIMER, text)
                self.assertIn('Chapter 6', text)
                self.assertIn('Afterword', text)
                self.assertIn('Appendix A', text)
            with ZipFile(Path(d)/'manuscript.docx') as z:
                xml = z.read('word/document.xml').decode()
                self.assertIn('pageBreakBefore', xml)
                self.assertIn(BOOK_DISCLAIMER, xml)
                self.assertIn('Heading2', xml)
            from pypdf import PdfReader
            reader = PdfReader(Path(d)/'manuscript.pdf')
            text = '\n'.join(p.extract_text() for p in reader.pages)
            self.assertIn(BOOK_DISCLAIMER, text)
            self.assertGreaterEqual(len(reader.pages), 11)
            self.assertIn('Contents', text)
            self.assertIn('Chapter 6', text)

    def test_author_date_bibliography_disambiguates_without_duplicate_labels(self):
        a = self.fixture()
        a['brief']['citation_style'] = 'author-date'
        second = copy.deepcopy(a['sources'][0])
        second.update(id='S002', title='A different study')
        a['sources'].append(second)
        a['sections'][0]['text'] += ' Related work [@S002].'
        rendered = blocks(a)
        text = '\n'.join(t for _, t in rendered)
        self.assertIn('(Author 1, 2020a)', text)
        self.assertIn('(Author 1, 2020b)', text)
        references = [t for k, t in rendered if k == 'reference']
        self.assertTrue(any('Author 1 (2020a).' in t for t in references))
        self.assertTrue(any('Author 1 (2020b).' in t for t in references))
        self.assertFalse(any(t.startswith('(Author') for t in references))

    def test_audit_catches_absolute_length_and_wrong_chapters(self):
        a = self.fixture()
        report = audit(a)
        self.assertTrue(any('40,000' in x for x in report['issues']))
        a['sections'][0]['chapter_index'] = 4
        self.assertTrue(any('assignments' in x for x in audit(a)['issues']))

    def test_strict_book_export_blocks_partial_draft(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            export(self.fixture(), d, ['txt'], strict=True)

if __name__ == '__main__':
    unittest.main()
