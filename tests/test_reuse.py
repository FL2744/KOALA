import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.core import save, read_json, normalize_brief
from koala.documents import analyse_document
from koala.menu import Menu
from koala.reuse import completed_analyses, reuse_analyses
from test_documents import DocumentProvider, write_docx
from test_menu import scripted


class ReuseTests(unittest.TestCase):
    def setup_projects(self, directory):
        base = Path(directory).resolve()
        source, target = base/'source', base/'target'
        source.mkdir(); target.mkdir()
        doc = write_docx(base/'input.docx', ['Memory connects people. Scholar (2020).'])
        analyse_document(DocumentProvider(), doc, source, lambda _:None)
        save(target/'brief.json', normalize_brief({'project_type':'book'}))
        return source, target, doc

    def import_menu(self, source, target):
        menu = Menu(read=scripted([str(source), '1']), write=lambda _:None)
        menu.open_project(target)
        menu.settings.update(provider='arc', model='different-destination-model')
        with patch.dict(os.environ, {}, clear=True), patch('koala.providers.Provider', side_effect=AssertionError('No API')):
            menu.reuse_inspiration()
        return read_json(target/'article.json')

    def test_import_is_independent_of_provider_key_and_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,doc = self.setup_projects(directory)
            doc.unlink()
            article = self.import_menu(source,target)
            manifest = article['inspiration']['documents'][0]
            self.assertEqual(article['brief']['project_type'], 'book')
            self.assertEqual(article['stage'], 'planning')
            self.assertEqual(article['provider'], 'arc')
            self.assertEqual(article['model'], 'different-destination-model')
            self.assertTrue(Path(manifest['analysis_file']).is_relative_to(target))
            self.assertEqual(manifest['provider'], DocumentProvider.name)
            self.assertIn('book manuscript',manifest['disclaimer'])
            import shutil
            shutil.rmtree(source)
            self.assertTrue(Path(manifest['analysis_file']).exists())
            self.assertTrue(list(Path(manifest['analysis_file']).parent.glob('chunks/*.json')))

    def test_duplicate_does_not_restart_or_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_ = self.setup_projects(directory)
            article=self.import_menu(source,target)
            before=(target/'article.json').read_bytes()
            reused = reuse_analyses(article,completed_analyses(source),target,lambda _:None)
            self.assertEqual(reused,article)
            self.assertEqual((target/'article.json').read_bytes(),before)
            self.assertEqual(len(list((target/'documents').glob('*/*/analysis.json'))),1)

    def test_existing_draft_is_archived_and_notes_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            article={'brief':normalize_brief({}), 'plan':{'title':'Old'}, 'title':'Old',
                     'abstract':'Old abstract','sections':[{'text':'old prose'}],
                     'sources':[{'id':'S001','notes':'Human notes'}], 'stage':'complete'}
            save(target/'article.json',article); (target/'article.txt').write_text('Old export')
            updated=reuse_analyses(article,completed_analyses(source),target,lambda _:None)
            archive=Path(updated['revision_history'][-1])
            self.assertEqual((archive/'article.txt').read_text(),'Old export')
            self.assertEqual(read_json(archive/'article.json')['sections'],article['sections'])
            self.assertEqual(updated['inherited_sources'],article['sources'])
            self.assertEqual(updated['sections'],[])

    def test_incomplete_and_self_import_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            selected=completed_analyses(source)
            with self.assertRaisesRegex(ValueError,'different'):
                reuse_analyses({},selected,source)
            path,manifest=selected[0];manifest['complete']=False;save(path,manifest)
            with self.assertRaisesRegex(ValueError,'No completed'):
                completed_analyses(source)

    def test_missing_evidence_does_not_change_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            selected=completed_analyses(source)
            next(selected[0][0].parent.glob('chunks/*.json')).unlink()
            with self.assertRaisesRegex(ValueError,'evidence cache'):
                reuse_analyses({},selected,target)
            self.assertFalse((target/'article.json').exists())
            self.assertFalse((target/'documents').exists())

    def test_cancel_leaves_project_unmodified(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            menu=Menu(read=scripted([str(source),'0']),write=lambda _:None)
            menu.open_project(target);menu.reuse_inspiration()
            self.assertFalse((target/'article.json').exists())

    def test_reuse_is_available_in_inspiration_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            menu=Menu(target,read=scripted(['3','2',str(source),'1','0','0','0']),write=lambda _:None)
            self.assertEqual(menu.run(),0)
            self.assertTrue(read_json(target/'article.json')['inspiration']['documents'])

    def test_reuse_all_completed_analyses(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target,_=self.setup_projects(directory)
            second=write_docx(source/'second.docx',['Another memory.'])
            analyse_document(DocumentProvider(),second,source,lambda _:None)
            menu=Menu(read=scripted([str(source),'3']),write=lambda _:None)
            menu.open_project(target);menu.reuse_inspiration()
            self.assertEqual(len(read_json(target/'article.json')['inspiration']['documents']),2)
