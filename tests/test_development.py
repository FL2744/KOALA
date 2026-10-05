import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from koala.core import save, read_json
from koala.desktop import dispatch
from koala.development import generate_proposal, apply_proposal, randomize_brief, load_development
from koala.menu import Menu
from test_koala import source


class DevelopmentTests(unittest.TestCase):
    def project(self, folder, brief=None):
        dispatch({'action':'create','folder':str(folder),'brief':brief or {}})
        menu=Menu(write=lambda _:None);menu.open_project(folder)
        return menu

    def provider(self, result):
        provider=Mock();provider.name='openai';provider.model='test-model';provider.json.return_value=result;provider.generate.return_value=result.get("text", "")
        return provider

    def test_ideas_review_apply_and_stale_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project')
            provider=self.provider({'text':'Explore memory through public monuments.'})
            original=(menu.folder/'brief.json').read_bytes()
            generate_proposal(menu,provider,'ideas')
            self.assertEqual((menu.folder/'brief.json').read_bytes(),original)
            apply_proposal(menu,'ideas','Study conflicting memories of public monuments.')
            self.assertIn('conflicting memories',menu.brief()['research_guidance'])
            self.assertTrue(load_development(menu.folder)['proposals']['ideas']['applied'])
            brief=menu.brief();brief['topic']='Changed';menu.save_brief(brief)
            with self.assertRaisesRegex(ValueError,'brief changed'):
                apply_proposal(menu,'ideas','Old direction')

    def test_authors_and_book_contents(self):
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project',{'project_type':'book','important_authors':['Hannah Arendt']})
            generate_proposal(menu,self.provider({'authors':['Albert Camus','Hannah Arendt']}),'authors')
            apply_proposal(menu,'authors','Albert Camus\nHannah Arendt')
            self.assertEqual(menu.brief()['important_authors'],['Hannah Arendt','Albert Camus'])
            toc='Introduction\n'+'\n'.join(f'Chapter {i}: Topic {i}' for i in range(1,7))
            generate_proposal(menu,self.provider({'text':toc}),'contents')
            apply_proposal(menu,'contents',toc)
            self.assertEqual(menu.brief()['chapter_outline'],toc)
            with self.assertRaisesRegex(ValueError,'chapter count'):
                generate_proposal(menu,self.provider({'text':'Chapter 1: Only one'}),'contents')

    def test_abstract_bounds_and_application_as_guidance(self):
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project');text=' '.join(['Proposed']*270)
            generate_proposal(menu,self.provider({'text':text}),'abstract')
            provider=self.provider({'text':text})
            generate_proposal(menu,provider,'abstract')
            provider.json.assert_not_called()
            self.assertIn('plain text',provider.generate.call_args.args[0])
            apply_proposal(menu,'abstract',text)
            self.assertIn(text,menu.brief()['research_guidance'])
            with self.assertRaisesRegex(ValueError,'250–300'):
                generate_proposal(menu,self.provider({'text':'Too short'}),'abstract')

    def test_bibliography_uses_retrieved_records_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as d, patch('koala.research.Crossref') as crossref:
            menu=self.project(Path(d)/'project')
            crossref.return_value.query.return_value=[source(),source()]
            p=generate_proposal(menu,self.provider({'queries':['cultural memory','public monuments']}),'bibliography')
            self.assertEqual(len(p['records']),1)
            self.assertIn('10.1234/example1',p['text'])
            apply_proposal(menu,'bibliography',p['text'])
            self.assertEqual(len(menu.brief()['possible_citations']),1)
            self.assertFalse((menu.folder/'sources.json').exists())

    def test_cancel_requires_confirmation_before_any_provider_call(self):
        with tempfile.TemporaryDirectory() as d, patch('koala.desktop.Provider') as provider:
            folder=Path(d)/'project';self.project(folder)
            with self.assertRaisesRegex(ValueError,'Confirm'):
                dispatch({'action':'random_generate','folder':str(folder),'confirmed':False})
            provider.assert_not_called()

    def test_random_preserves_constraints_and_archives(self):
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project',{'project_type':'book','topic':'Nihilism',
                'important_authors':['Albert Camus'],'target_words':65000,'citation_target':450,'research_guidance':'Compare carefully.'})
            brief=menu.brief()
            original={'brief':brief,'plan':{'title':'Old'},'title':'Old','abstract':'Old abstract',
                      'sections':[{'heading':'Old section','text':'Preserve this prose.'}],'sources':[], 'stage':'drafted'}
            save(menu.folder/'article.json',original)
            provider=self.provider({'topic':'Unwanted topic','discipline':'Philosophy','important_ideas':['Absurdity'],
                                    'research_guidance':'Explore a comparison within nihilism.'})
            randomize_brief(menu,provider,True)
            new=menu.brief()
            for field in ('topic','important_authors','target_words','citation_target','chapter_count','project_type'):
                self.assertEqual(new[field],brief[field])
            self.assertTrue(new['research_guidance'].startswith('Compare carefully.'))
            self.assertEqual(new['discipline'],'Philosophy')
            self.assertEqual(read_json(menu.folder/'article.json')['stage'],'planning')
            self.assertTrue(any(read_json(p)['sections']==original['sections'] for p in (menu.folder/'revisions').rglob('article.json')))
            self.assertIn('seed',load_development(menu.folder)['proposals']['random'])

    def test_confirmed_random_enters_normal_generation(self):
        with tempfile.TemporaryDirectory() as d, patch('koala.desktop.Provider') as provider, patch('koala.cli.main',return_value=0) as cli:
            folder=Path(d)/'project';self.project(folder)
            provider.return_value=self.provider({'topic':'Memory','discipline':'History','important_ideas':['Archives'],
                                                'research_guidance':'Study the archives.'})
            dispatch({'action':'random_generate','folder':str(folder),'confirmed':True})
            args=cli.call_args.args[0]
            self.assertEqual(args[0],'generate');self.assertIn('--brief',args)
            self.assertEqual(read_json(folder/'brief.json')['topic'],'Memory')

    def test_invalid_random_result_leaves_brief_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project');before=(menu.folder/'brief.json').read_bytes()
            with self.assertRaises(ValueError): randomize_brief(menu,self.provider({'topic':'Only a topic'}),True)
            self.assertEqual((menu.folder/'brief.json').read_bytes(),before)

    def test_abstract_wrappers_and_invalid_result_preserve_saved_proposal(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            menu=self.project(Path(d)/'project');text=' '.join(['Proposed']*270)
            for raw in (text, '```text\n'+text+'\n```', json.dumps({'text':text})):
                provider=self.provider({});provider.generate.return_value=raw
                proposal=generate_proposal(menu,provider,'abstract')
                self.assertEqual(proposal['text'],text)
            before=(menu.folder/'development.json').read_bytes()
            for raw in ('{"text": "broken', '[]', 'Too short', text+' [@s1]'):
                provider.generate.return_value=raw
                with self.assertRaises(ValueError):generate_proposal(menu,provider,'abstract')
                self.assertEqual((menu.folder/'development.json').read_bytes(),before)
