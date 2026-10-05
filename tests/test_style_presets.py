import tempfile
import unittest
from pathlib import Path
from koala.core import save,read_json
from koala.desktop import dispatch
from koala.menu import Menu
from koala.pipeline import system_for
from koala.style_presets import catalog

class StyleTests(unittest.TestCase):
    def test_catalog_and_shared_system(self):
        presets=catalog()
        self.assertEqual(len([p for p in presets if p['category']=='author']),8)
        for p in presets:
            system=system_for({'style_guidance':p['guidance']})
            self.assertIn(p['guidance'],system)
            self.assertIn('citation',system)
            self.assertIn('living authors',system)
        self.assertIn('My own traits',system_for({'style_guidance':'My own traits','writing_prompt':'Custom system'}))
    def test_save_style_preserves_completed_work(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project'
            view=dispatch({'action':'create','folder':str(folder),'brief':{}})
            self.assertEqual(view['style_presets'],catalog())
            menu=Menu(write=lambda _:None);menu.open_project(folder)
            brief=menu.brief();article={'brief':brief,'plan':{'title':'Keep plan'},'abstract':'Keep abstract','sections':[{'text':'Keep prose'}],'sources':[],'stage':'drafting'}
            save(folder/'article.json',article)
            brief={**brief,'style_guidance':'Plain language and concrete examples.'}
            menu.save_brief(brief)
            updated=read_json(folder/'article.json')
            for key in ('plan','abstract','sections','stage'):self.assertEqual(updated[key],article[key])
            self.assertEqual(updated['brief']['style_guidance'],brief['style_guidance'])
