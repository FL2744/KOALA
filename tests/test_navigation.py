import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.core import save, normalize_brief
from koala.menu import Menu
from test_menu import scripted


class NavigationTests(unittest.TestCase):
    def setup_menu(self, folder, inputs):
        save(folder/'brief.json',normalize_brief({}))
        output=[]
        menu=Menu(folder,read=scripted(inputs),write=output.append)
        return menu, output

    def test_help_and_blank_do_not_start_work(self):
        with tempfile.TemporaryDirectory() as d:
            menu,output=self.setup_menu(Path(d),['','?','q'])
            with patch.object(menu,'workflow',side_effect=AssertionError('No generation')):
                self.assertEqual(menu.run(),0)
            self.assertGreaterEqual(sum('Project dashboard' in line for line in output),3)
            self.assertTrue(any('Blank redisplays' in line for line in output))

    def test_continue_selects_action_from_saved_state(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            menu,_=self.setup_menu(folder,[]);menu.open_project(folder)
            self.assertEqual(menu.next_step()[1],'abstract')
            for stage,sections,label,action in [('abstract',[],'Start manuscript','generate'),
                    ('drafting',[{'text':'saved'}],'Resume manuscript','generate'),
                    ('drafted',[{'text':'saved'}],'Review completed','review')]:
                save(folder/'article.json',{'abstract':'guiding abstract','sections':sections,'stage':stage})
                actual=menu.next_step()
                self.assertTrue(actual[0].startswith(label));self.assertEqual(actual[1],action)

    def test_continue_calls_abstract_only_on_explicit_selection(self):
        with tempfile.TemporaryDirectory() as d:
            menu,_=self.setup_menu(Path(d),['1','q'])
            with patch.object(menu,'workflow') as workflow:
                menu.run()
            workflow.assert_called_once_with('abstract')

    def test_back_from_inspiration_retains_project_and_home_closes_view(self):
        with tempfile.TemporaryDirectory() as d:
            menu,output=self.setup_menu(Path(d),['3','b','6','h','q'])
            menu.run()
            self.assertIsNone(menu.folder)
            self.assertTrue(any('/ Inspiration' in line for line in output))
            self.assertTrue(any('/ Review project' in line for line in output))
            self.assertGreaterEqual(sum('Main menu' in line for line in output),1)

    def test_quit_from_nested_menu_exits(self):
        with tempfile.TemporaryDirectory() as d:
            menu,output=self.setup_menu(Path(d),['8','q'])
            self.assertEqual(menu.run(),0)
            self.assertIn('Goodbye.',output)

    def test_inspiration_routes_to_import_and_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            menu,_=self.setup_menu(Path(d),['3','1','2','b','q'])
            with patch.object(menu,'import_documents') as add,patch.object(menu,'reuse_inspiration') as reuse:
                menu.run()
            add.assert_called_once();reuse.assert_called_once()
