import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from koala.core import save,read_json,normalize_brief
from koala.desktop import dispatch
from koala.menu import Menu
from koala.development import generate_proposal,apply_proposal,development_view

class TitleTests(unittest.TestCase):
    def setup_project(self,folder):
        dispatch({'action':'create','folder':str(folder),'brief':{}})
        menu=Menu(write=lambda _:None);menu.open_project(folder)
        p=Mock();p.name='openai';p.model='test';p.generate.return_value='\n'.join(f'{i}. Title choice {i}' for i in range(1,11))
        return menu,p
    def test_ten_titles_choose_and_preserve_manuscript(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);menu,p=self.setup_project(folder)
            a={'brief':menu.brief(),'title':'Old','plan':{'title':'Old'},'sections':[{'text':'Keep this prose'}],'abstract':'Original','sources':[],'stage':'drafted'}
            save(folder/'article.json',a)
            proposal=generate_proposal(menu,p,'titles')
            self.assertEqual(len(proposal['titles']),10);self.assertEqual(proposal['text'],'')
            self.assertTrue(development_view(menu)['proposals']['titles']['can_apply'])
            apply_proposal(menu,'titles','Title choice 7')
            updated=read_json(folder/'article.json');self.assertEqual(updated['title'],'Title choice 7')
            self.assertEqual(updated['sections'],a['sections']);self.assertEqual(menu.brief()['manuscript_title'],'Title choice 7')
            with self.assertRaises(ValueError):apply_proposal(menu,'titles','Not in choices')
    def test_malformed_titles_leave_saved_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);menu,p=self.setup_project(folder);generate_proposal(menu,p,'titles')
            before=(folder/'development.json').read_bytes()
            for value in ('Only one title','\n'.join(['Same']*10)):
                p.generate.return_value=value
                with self.assertRaises(ValueError):generate_proposal(menu,p,'titles')
                self.assertEqual(before,(folder/'development.json').read_bytes())
    def test_stale_content_not_applicable(self):
        with tempfile.TemporaryDirectory() as d:
            menu,p=self.setup_project(Path(d));generate_proposal(menu,p,'titles')
            brief=menu.brief();brief['topic']='New subject';menu.save_brief(brief)
            self.assertFalse(development_view(menu)['proposals']['titles']['can_apply'])
            with self.assertRaises(ValueError):apply_proposal(menu,'titles','Title choice 1')
    def test_title_validation_and_defaults(self):
        self.assertEqual(normalize_brief({})['manuscript_title'],'')
        with self.assertRaises(ValueError):normalize_brief({'manuscript_title':'x'*301})
