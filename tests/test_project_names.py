import tempfile
import unittest
from pathlib import Path
from koala.desktop import dispatch
from koala.core import save


class ProjectNameTests(unittest.TestCase):
    def test_create_rename_reopen_and_preserve_files(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'Book'
            result=dispatch({'action':'create','folder':str(folder),'name':'Nihilism Study','brief':{'project_type':'book'}})
            self.assertEqual(result['project_name'],'Nihilism Study')
            (folder/'saved-draft.txt').write_text('Existing prose')
            brief=(folder/'brief.json').read_bytes()
            renamed=dispatch({'action':'rename_project','folder':str(folder),'name':' New Title '})
            self.assertEqual(renamed['project_name'],'New Title')
            old_folder=folder;folder=folder.with_name('New Title')
            self.assertFalse(old_folder.exists())
            self.assertEqual(renamed['folder'],str(folder.resolve()))
            self.assertEqual((folder/'brief.json').read_bytes(),brief)
            self.assertEqual((folder/'saved-draft.txt').read_text(),'Existing prose')
            self.assertEqual(dispatch({'action':'load','folder':str(folder)})['project_name'],'New Title')

    def test_legacy_fallback_and_invalid_names(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'Sample Book'
            dispatch({'action':'create','folder':str(folder)})
            (folder/'.koala-project.json').unlink()
            self.assertEqual(dispatch({'action':'load','folder':str(folder)})['project_name'],'Sample Book')
            for bad in ['', ' ', '../escape', 'Bad:Name', 'Bad\nName', 'x'*121]:
                with self.assertRaises(ValueError):dispatch({'action':'rename_project','folder':str(folder),'name':bad})
            self.assertFalse((folder/'.koala-project.json').exists())

    def test_rename_relocates_paths_and_rejects_collision(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'Original'
            dispatch({'action':'create','folder':str(folder),'brief':{}})
            save(folder/'paths.json',{'path':str(folder/'revisions'/'report.html'),'text':'The Original argument remains.'})
            (folder/'data').mkdir();save(folder/'data'/'original.json',{'value':str(folder)})
            renamed=dispatch({'action':'rename_project','folder':str(folder),'name':'Revised'})
            import json
            new=Path(renamed['folder']);record=json.loads((new/'paths.json').read_text())
            self.assertEqual(record['path'],str(new/'revisions'/'report.html'))
            self.assertEqual(record['text'],'The Original argument remains.')
            self.assertEqual(json.loads((new/'data'/'original.json').read_text())['value'],str(folder))
            (new.parent/'Occupied').mkdir()
            with self.assertRaisesRegex(ValueError,'already exists'):
                dispatch({'action':'rename_project','folder':str(new),'name':'Occupied'})
            self.assertTrue(new.exists())
