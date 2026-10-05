import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from koala.core import save,read_json
from koala.coverage import require_ready,authorize_research,research_authorized,ResearchApprovalRequired,section_budget,require_complete
from koala.pipeline import draft
from koala.books import section_issues
from koala.citations import locator_issues
from koala.cli import main
from koala.desktop import dispatch
from test_citation_coverage import article,source

class ResearchConsentTests(unittest.TestCase):
    def fixture(self):
        a=article(2);a['sources']=[source(1)];a['brief']['important_authors']=['Missing Author']
        return a

    def test_no_drafting_before_consent_and_valid_token_resumes(self):
        a=self.fixture();p=Mock()
        with tempfile.TemporaryDirectory() as d:
            save(Path(d)/'article.json',a)
            with self.assertRaises(ResearchApprovalRequired):draft(p,a,d)
            p.generate.assert_not_called()
            notice=read_json(Path(d)/'research-approval-needed.json')
            self.assertEqual(notice['missing_authors'],['Missing Author'])
            authorize_research(a,d,notice['token'])
            self.assertTrue(research_authorized(read_json(Path(d)/'article.json')))
            require_ready(a,d)
            budget=section_budget(a,0)
            self.assertEqual(budget['minimum_new_works'],0);self.assertFalse(budget['required_source_ids'])

    def test_stale_token_refreshes_warning_without_authorizing(self):
        a=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ResearchApprovalRequired):require_ready(a,d)
            token=read_json(Path(d)/'research-approval-needed.json')['token']
            a['brief']['citation_target']=10
            with self.assertRaises(ResearchApprovalRequired):authorize_research(a,d,token)
            self.assertNotEqual(token,read_json(Path(d)/'research-approval-needed.json')['token'])
            self.assertFalse(research_authorized(a))

    def test_approval_survives_prose_but_not_requirements_or_evidence_edits(self):
        a=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            authorize_research(a,d,explicit=True)
            a['sections']=[{'heading':'Test','text':'New prose'}];self.assertTrue(research_authorized(a))
            a['sources'][0]['notes']='Changed evidence';self.assertFalse(research_authorized(a))

    def test_zero_sources_can_draft_and_remains_marked_for_review(self):
        a=self.fixture();a['sources']=[];p=Mock();p.generate.return_value=' '.join(['Conceptual']*250)
        with tempfile.TemporaryDirectory() as d:
            authorize_research(a,d,explicit=True)
            result=draft(p,a,d,lambda _:None)
            self.assertEqual(len(result['sections']),4);self.assertEqual(result['stage'],'citation_review')
            self.assertTrue(any(i.startswith('Citation shortfall:') for i in result['audit']['issues']))
            self.assertTrue(section_issues('Claim [@S999].',0,100,set()))
            self.assertTrue(locator_issues('Claim [@S001#FAKE].',[source(1)]))

    def test_cli_returns_confirmation_then_accepts_explicit_authorization(self):
        a=self.fixture()
        with tempfile.TemporaryDirectory() as d,patch('koala.cli.Provider') as provider,patch('koala.cli.continue_prepare',side_effect=lambda p,a,*args,**kwargs:a),patch('koala.cli.export',return_value=[]):
            save(Path(d)/'article.json',a)
            provider.return_value.generate.return_value=' '.join(['Conceptual']*250)
            args=['generate','--out',d,'--resume']
            self.assertEqual(main(args),3)
            self.assertNotIn('research_authorization',read_json(Path(d)/'article.json'))
            self.assertEqual(main(args+['--allow-incomplete-research']),0)
            self.assertTrue(research_authorized(read_json(Path(d)/'article.json')))

    def test_desktop_returns_reviewable_notice_instead_of_generic_error(self):
        a=self.fixture()
        with tempfile.TemporaryDirectory() as d,patch('koala.cli.Provider'),patch('koala.cli.continue_prepare',side_effect=lambda p,a,*args,**kwargs:a):
            save(Path(d)/'article.json',a);save(Path(d)/'brief.json',a['brief'])
            result=dispatch({'action':'generate','folder':d})
            self.assertIn('research_confirmation',result)
            self.assertNotIn('research_authorization',read_json(Path(d)/'article.json'))

    def test_strict_export_only_waives_authorized_coverage_shortfall(self):
        from koala.exporters import export
        a=self.fixture();a['sections']=[{'heading':str(i),'text':' '.join(['Conceptual']*250)} for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            authorize_research(a,d,explicit=True)
            paths=export(a,d,['txt'],strict=True);self.assertTrue(paths)
            a['sections'][0]['text']+=' [@S999]'
            with self.assertRaises(ValueError):export(a,d,['txt'],strict=True)

    def test_book_completes_provisional_draft_without_source_minimum(self):
        from test_books import setup_book,BookProvider
        from koala.pipeline import prepare
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);brief=setup_book(base);p=BookProvider()
            a=prepare(p,brief,base/'run',base/'brief.json',True,lambda _:None)
            a['sources']=[]
            with self.assertRaises(ResearchApprovalRequired):draft(p,a,base/'run',lambda _:None)
            authorize_research(a,base/'run',explicit=True)
            result=draft(p,a,base/'run',lambda _:None)
            self.assertEqual(result['audit']['body_words'],40000)
            self.assertEqual(result['stage'],'citation_review')
            self.assertEqual(result['audit']['distinct_cited_works'],0)

    def test_menu_requires_yes_and_cancel_does_not_retry(self):
        from koala.menu import Menu
        for answer,count in [('no',1),('yes',2)]:
            with self.subTest(answer=answer),tempfile.TemporaryDirectory() as d:
                folder=Path(d);a=self.fixture();save(folder/'article.json',a);save(folder/'brief.json',a['brief'])
                try:require_ready(a,folder)
                except ResearchApprovalRequired:pass
                execute=Mock(side_effect=[3,0]);menu=Menu(read=lambda _:answer,write=lambda _:None,execute=execute)
                menu.open_project(folder)
                with patch.object(menu,'client'):menu.workflow('generate')
                self.assertEqual(execute.call_count,count)
                if answer=='yes':self.assertIn('--research-approval',execute.call_args.args[0])

    def test_book_six_citations_against_seven_goal_never_retries_or_stops(self):
        import json,re
        from test_books import setup_book,BookProvider
        from koala.pipeline import prepare
        from koala.coverage import section_budget as real_budget
        class SixSources(BookProvider):
            def generate(self,system,prompt):
                if prompt.startswith('Write one section of a scholarly book.'):
                    self.events.append(('book_section',prompt))
                    target=int(re.search(r'Target (\d+) prose',prompt)[1])
                    context=json.loads(prompt.split('\n',1)[1])
                    return ' '.join(['Memory']*target)+' '+' '.join('[@'+s['id']+']' for s in context['sources'][:6])
                return super().generate(system,prompt)
        def budget(*args,**kwargs):
            b=real_budget(*args,**kwargs);b['minimum_new_works']=7;return b
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);p=SixSources();brief=setup_book(base)
            a=prepare(p,brief,base/'run',base/'brief.json',True,lambda _:None)
            with patch('koala.books.section_budget',side_effect=budget):
                result=draft(p,a,base/'run',lambda _:None)
            self.assertEqual(len(result['sections']),len(result['plan']['sections']))
            self.assertEqual(len([e for e in p.events if e[0]=='book_section']),len(result['sections']))
            self.assertTrue(result['citation_shortfalls'])
            self.assertTrue(any('this attempt cites 6' in w for w in result['citation_shortfalls']['0']))
            self.assertTrue(all(read_json(path)['accepted'] for path in (base/'run/draft-attempts').rglob('attempt-*.json')))

    def test_shortfall_does_not_excuse_invented_citation_ids(self):
        a=article(2);p=Mock();p.generate.return_value=' '.join(['Conceptual']*250)+' [@S999]'
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Unavailable source IDs'):draft(p,a,d,lambda _:None)
            self.assertFalse(a['sections'])
