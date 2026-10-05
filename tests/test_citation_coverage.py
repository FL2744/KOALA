import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from koala.core import normalize_brief, load_brief, cited_ids, audit, save, read_json, validate_sources
from koala.coverage import (same_author, resolve_authors, preserve_authors, author_coverage,
                            citation_readiness, require_ready, section_budget, coverage_issues)
from koala.citations import render_csl, locator_issues
from koala.exporters import export, blocks
from koala.pipeline import draft, select_article_sources
from koala.repair import repair_citations
from koala.research import discover
from koala.menu import Menu


def source(i, author=None):
    return {'id':f'S{i:03}', 'title':f'Evidence Study {i}', 'authors':[author or f'Researcher {i}'],
            'year':'2020', 'publisher':'Example Press', 'type':'book',
            'notes':'Synthetic evidence supplied for regression testing.', 'doi':''}


def article(n=2):
    return {'title':'Citation fixture', 'brief':normalize_brief({'citation_target':n,'target_words':1000}),
            'plan':{'sections':[{'heading':str(i),'purpose':'Examine evidence'} for i in range(4)]},
            'abstract':' '.join(['word']*260), 'sources':[source(i) for i in range(1,n+1)],
            'sections':[], 'excerpts':[], 'warnings':[], 'stage':'abstract', 'provider':'openai','model':'test'}


class AuthorTests(unittest.TestCase):
    def test_matching_diacritics_initials_and_homonyms(self):
        self.assertTrue(same_author('Slavoj Žižek','Zizek, Slavoj'))
        self.assertTrue(same_author('Theodor W. Adorno','Theodor Adorno'))
        self.assertTrue(same_author('H. P. Lovecraft','Howard Phillips Lovecraft'))
        self.assertFalse(same_author('Sam Harris','Tristan Harris'))
        self.assertFalse(same_author('John Gray','Jonathan Gray'))
        self.assertFalse(same_author('Aristotle','Alex Aristotle'))

    def test_plain_file_name_is_loaded_not_treated_as_author(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'authors.txt').write_text('Sam Harris; Tristan Harris\nSlavoj Žižek')
            save(folder/'brief.json',{'important_authors':['authors.txt']})
            self.assertEqual(load_brief(folder/'brief.json')['important_authors'],['Sam Harris','Tristan Harris','Slavoj Žižek'])
            with self.assertRaisesRegex(ValueError,'Author-list file not found'):
                resolve_authors({'important_authors':['missing.txt']},folder)

    def test_every_author_searched_beyond_old_cap_and_title_mentions_do_not_count(self):
        names=[f'Writer {i}' for i in range(1,66)]
        client=Mock()
        def query(name, rows):
            i=names.index(name)+1 if name in names else 100
            return [source(i,name),dict(source(i+100,'Unrelated Scholar'),title='About '+name)]
        client.query.side_effect=query
        brief=normalize_brief({'important_authors':names})
        candidates,_=discover(brief,{'search_queries':['subject']},client)
        queried=[call.args[0] for call in client.query.call_args_list]
        self.assertTrue(set(names)<=set(queried))
        self.assertEqual(len([s for s in candidates if s['authors'][0] in names]),65)
        rows=author_coverage(brief,candidates)
        self.assertTrue(all(r['supported_ids'] for r in rows))

    def test_model_cannot_drop_required_authors(self):
        candidates=[source(1,'Sam Harris'),source(2,'Tristan Harris')]
        selected=preserve_authors({'important_authors':['Sam Harris','Tristan Harris']},candidates,[candidates[0]])
        self.assertEqual(len(selected),2)

    def test_missing_work_missing_evidence_and_uncited_are_distinct(self):
        s=source(1,'Sam Harris');s['notes']=''
        rows=author_coverage({'important_authors':['Sam Harris','Tristan Harris','John Gray']},[s,source(2,'Tristan Harris')])
        self.assertEqual([r['status'] for r in rows],['missing_evidence','not_cited','missing_work'])

    def test_readiness_stops_before_inference(self):
        a=article(75);a['sources']=a['sources'][:5];p=Mock()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'5 works have evidence available; 75'):
                draft(p,a,d)
            p.generate.assert_not_called()
            self.assertTrue((Path(d)/'citation-coverage.json').exists())

    def test_batch_selection_resumes(self):
        sources=[source(i) for i in range(1,86)];p=Mock()
        p.json.side_effect=[{'source_ids':['S001']},RuntimeError('offline')]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError): select_article_sources(p,{}, {},sources,d,lambda _:None)
            p.json.side_effect=[{'source_ids':['S041']},{'source_ids':['S081']}]
            result=select_article_sources(p,{}, {},sources,d,lambda _:None)
            self.assertEqual(result['source_ids'],['S001','S041','S081'])
            self.assertEqual(p.json.call_count,4)

    def test_same_author_mention_without_citation_does_not_pass(self):
        a=article(1);a['brief']['important_authors']=['Sam Harris'];a['sources']=[source(1,'Sam Harris')]
        a['sections']=[{'text':'Sam Harris is discussed here.','heading':'Test'}]
        self.assertEqual(audit(a)['missing_authors'],['Sam Harris'])

    def test_budget_requires_new_works_not_repeated_markers(self):
        a=article(8);a['sections']=[{'text':'[@S001]','heading':'1'}]
        budget=section_budget(a,1)
        self.assertEqual(budget['minimum_new_works'],3)
        self.assertTrue(coverage_issues('[@S001] '*30,budget))

    def test_article_reaches_75_unique_sources(self):
        a=article(75);a['brief']['important_authors']=['Researcher 75']
        p=Mock()
        def generate(system,prompt):
            context=json.loads(prompt.split('\n',1)[1])
            required=context['citation_budget']['suggested_source_ids']
            return ' '.join(['Evidence']*250)+' '+ ' '.join(f'[@{i}]' for i in required)
        p.generate.side_effect=generate
        with tempfile.TemporaryDirectory() as d:
            result=draft(p,a,d,lambda _:None)
            self.assertEqual(result['audit']['distinct_cited_works'],75)
            self.assertEqual(result['audit']['missing_authors'],[])

    def test_uncited_draft_continues_and_shortfalls_are_saved(self):
        a=article(2);p=Mock();p.generate.return_value=' '.join(['Word']*250)
        with tempfile.TemporaryDirectory() as d:
            result=draft(p,a,d,lambda _:None)
            self.assertEqual(p.generate.call_count,4)
            self.assertEqual(len(list(Path(d).rglob('attempt-*.json'))),4)
            self.assertEqual(len(result['citation_shortfalls']),4)
            self.assertEqual(result['stage'],'citation_review')

    def test_changing_style_does_not_discard_draft(self):
        a=article(1);a['sections']=[{'text':'Original [@S001].','heading':'1'}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);save(path/'article.json',a);save(path/'brief.json',a['brief'])
            menu=Menu(write=lambda _:None);menu.open_project(path)
            brief={**a['brief'],'citation_style':'mla'};menu.save_brief(brief)
            saved=read_json(path/'article.json')
            self.assertEqual(saved['sections'],a['sections'])
            self.assertEqual(saved['brief']['citation_style'],'mla')


class FormattingTests(unittest.TestCase):
    def fixture(self):
        a=article(2);a['sources']=[source(1,'Sam Harris'),source(2,'Tristan Harris')]
        a['sources'][0]['passages']=[{'id':'P1','text':'A supplied passage.','locator':'42','label':'page'}]
        a['sections']=[{'heading':'Discussion','text':'One claim [@S001#P1]. Another [@S002].'}]
        return a

    def test_mla_locator_and_same_surname_disambiguation(self):
        a=self.fixture();a['brief']['citation_style']='mla'
        result=blocks(a);body=' '.join(t for k,t in result if k=='paragraph')
        self.assertIn('(S. Harris 42)',body);self.assertIn('(T. Harris)',body)
        self.assertIn(('heading','Works Cited'),result)
        self.assertTrue(any(italic for k,t in result if k=='reference' for _,italic in t.spans))

    def test_chicago_author_date_page_and_no_comma_before_year(self):
        a=self.fixture();a['brief']['citation_style']='chicago-author-date';a['sources'][1]['authors']=['Hannah Arendt']
        result=blocks(a);body=' '.join(t for k,t in result if k=='paragraph')
        self.assertIn('(Harris 2020, 42)',body);self.assertIn('(Arendt 2020)',body)

    def test_two_authors_and_three_authors(self):
        sources=[dict(source(1),authors=['Richard Wilkinson','Kate Pickett']),
                 dict(source(2),authors=['Helen Pluckrose','James Lindsay','Peter Boghossian'])]
        for style in ['mla','chicago-author-date']:
            rendered,_=render_csl(['Together [@S001]. Another [@S002].'],sources,style)
            self.assertIn('Wilkinson and Pickett',rendered[0]);self.assertIn('Pluckrose et al.',rendered[0])

    def test_same_author_year_and_mla_titles(self):
        sources=[source(1,'John Gray'),source(2,'John Gray')]
        rendered,refs=render_csl(['A [@S001]. B [@S002].'],sources,'chicago-author-date')
        self.assertIn('2020a',rendered[0]);self.assertIn('2020b',rendered[0])
        rendered,refs=render_csl(['A [@S001]. B [@S002].'],sources,'mla')
        self.assertIn('Evidence Study 1',rendered[0]);self.assertIn('Evidence Study 2',rendered[0])

    def test_locators_never_come_from_publication_page_range(self):
        s=source(1,'Sam Harris');s['pages']='1-100'
        rendered,_=render_csl(['A [@S001].'],[s],'mla')
        self.assertEqual(str(rendered[0]),'A (Harris).')
        self.assertTrue(locator_issues('A [@S001#invented].',[s]))

    def test_marker_accounting_and_malformed_locators(self):
        self.assertEqual(cited_ids('[@S001#P1] [@S002]'),['S001','S002'])
        a=self.fixture();a['sections'][0]['text']='Unknown [@S001#P7].'
        self.assertTrue(any('Unsupported locator' in i for i in audit(a)['issues']))
        with self.assertRaisesRegex(ValueError,'Unsupported locator'): blocks(a)

    def test_rich_formatting_and_disclosure_in_all_exports(self):
        a=self.fixture();a['brief']['citation_style']='mla'
        with tempfile.TemporaryDirectory() as d:
            paths=export(a,d)
            self.assertEqual(len(paths),5)
            text=(Path(d)/'article.txt').read_text();self.assertIn('S. Harris 42',text)
            self.assertIn('artificial intelligence',text)
            html=(Path(d)/'article.html').read_text();self.assertIn('<i>Evidence Study 1</i>',html)
            self.assertIn('\\i ',(Path(d)/'article.rtf').read_text())
            with ZipFile(Path(d)/'article.docx') as z:
                xml=z.read('word/document.xml').decode();self.assertIn('<w:i',xml);self.assertIn('S. Harris',xml)
            from pypdf import PdfReader
            pdf=' '.join(p.extract_text() for p in PdfReader(Path(d)/'article.pdf').pages)
            self.assertIn('Harris 42',pdf);self.assertIn('Works Cited',pdf)


class RepairTests(unittest.TestCase):
    def test_repair_keeps_original_and_resumes_after_network_failure(self):
        a=article(4)
        a['sections']=[{'heading':str(i),'text':' '.join(['Evidence']*250)+' [@S001].'} for i in range(4)]
        p=Mock();p.generate.side_effect=RuntimeError('network down')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);save(path/'article.json',a)
            with self.assertRaises(RuntimeError): repair_citations(p,a,path,True,lambda _:None)
            current=read_json(path/'article.json');state=current['citation_repair']
            archived=read_json(Path(state['archive'])/'article.json')
            self.assertEqual(archived['sections'],a['sections'])
            self.assertEqual(state['processed'],1)
            def generate(system,prompt):
                context=json.loads(prompt.split('\n',1)[1]);budget=context['citation_budget']
                return context['original']+' '+' '.join(f'[@{sid}]' for sid in budget['suggested_source_ids'])
            p.generate.side_effect=generate
            result=repair_citations(p,current,path,True,lambda _:None)
            self.assertEqual(result['audit']['distinct_cited_works'],4)
            self.assertEqual(result['sections'][0],archived['sections'][0])
            self.assertEqual(result['stage'],'drafted')

    def test_missing_evidence_does_not_destroy_original(self):
        a=article(2);a['sources'][1]['notes']=''
        a['sections']=[{'heading':'One','text':'Saved manuscript [@S001].'}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);save(p/'article.json',a)
            with self.assertRaisesRegex(ValueError,'Citation research is incomplete'):
                repair_citations(Mock(),a,p,True,lambda _:None)
            self.assertEqual(read_json(p/'article.json')['sections'],a['sections'])

class BookAuthorCoverageTests(unittest.TestCase):
    def test_200_work_book_includes_100_required_authors(self):
        from test_books import setup_book, BookProvider
        from koala.pipeline import prepare
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            brief=setup_book(base,important_authors=[f'Author {i}' for i in range(1,101)])
            p=BookProvider();a=prepare(p,brief,base/'book',base/'brief.json',True,lambda _:None)
            a=draft(p,a,base/'book',lambda _:None)
            self.assertEqual(a['audit']['distinct_cited_works'],200)
            self.assertEqual(a['audit']['missing_authors'],[])
            self.assertTrue(all(row['status']=='cited' for row in a['audit']['author_coverage']))
