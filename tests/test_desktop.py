import contextlib
import fcntl
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.desktop import dispatch, main
from koala.core import read_json, save
from test_documents import DocumentProvider, write_docx
from test_koala import source


class DesktopTests(unittest.TestCase):
    def create(self, folder, kind='article'):
        return dispatch({'action':'create','folder':str(folder), 'brief':{'project_type':kind}})

    def test_new_book_and_open_existing_preserve_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'book';result=self.create(folder,'book')
            self.assertEqual(result['brief']['target_words'],65000)
            self.assertIsNone(result['brief']['citation_target'])
            self.assertIsNone(read_json(folder/'brief.json')['citation_target'])
            self.assertEqual(result['next'][1],'abstract')
            self.assertEqual(dispatch({'action':'load','folder':str(folder)})['brief'],result['brief'])
            with self.assertRaises(ValueError):self.create(folder)

    def test_save_brief_999_authors(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';data=self.create(folder)
            data['brief']['important_authors']=[f'Author {i}' for i in range(999)]
            result=dispatch({'action':'save_brief','folder':str(folder),'brief':data['brief']})
            self.assertEqual(len(result['brief']['important_authors']),999)

    def test_settings_exclude_secrets_and_validate_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';self.create(folder)
            dispatch({'action':'settings','folder':str(folder),'settings':{'model':'custom','api_key':'must-not-save'}})
            self.assertNotIn('must-not-save',(folder/'.koala-menu.json').read_text())
            with self.assertRaises(ValueError):
                dispatch({'action':'settings','folder':str(folder),'settings':{'base_url':'https://user:password@example.test/v1'}})

    def test_project_lock_blocks_other_writer(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';result=self.create(folder)
            with (folder/'.koala-desktop.lock').open('a') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError,'busy'):
                    dispatch({'action':'save_brief','folder':str(folder),'brief':result['brief']})

    @patch.dict(os.environ,{'OPENAI_API_KEY':'test-key'})
    def test_complete_article_workflow_and_export_through_bridge(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            folder=Path(d)/'project';data=self.create(folder)
            save(folder/'sources.json',[source()])
            data['brief'].update(target_words=1000,citation_target=1,sources_file='sources.json')
            dispatch({'action':'save_brief','folder':str(folder),'brief':data['brief']})
            with patch('koala.cli.Provider',return_value=DocumentProvider()):
                abstract=dispatch({'action':'abstract','folder':str(folder),'formats':['txt']})
                self.assertTrue(abstract['article']['abstract'])
                drafted=dispatch({'action':'generate','folder':str(folder),'formats':['txt']})
                self.assertEqual(len(drafted['article']['sections']),4)
            result=dispatch({'action':'export','folder':str(folder),'formats':['txt','html'],'strict':True})
            self.assertTrue(any(p.endswith('.html') for p in result['exports']))
            updated=dispatch({'action':'save_abstract','folder':str(folder),'text':' '.join(['Revised']*270)})
            self.assertEqual(updated['article']['sections'],[])
            self.assertTrue(updated['article']['revision_history'])

    def test_reuse_without_provider(self):
        from koala.documents import analyse_document
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            folder=Path(d)/'target';self.create(folder)
            doc=write_docx(Path(d)/'inspiration.docx',['Memory connects people.'])
            src=Path(d)/'source';analyse_document(DocumentProvider(),doc,src,lambda _:None)
            results=dispatch({'action':'reuse_list','source':str(src)})
            item=results['analyses'][0]
            result=dispatch({'action':'reuse','folder':str(folder),'source':str(src),'analyses':[item['path']]})
            self.assertEqual(len(result['article']['inspiration']['documents']),1)

    def test_models_discovery(self):
        with patch('koala.desktop.Provider') as provider:
            provider.return_value.models.return_value=['model-a','model-b']
            self.assertEqual(dispatch({'action':'models'})['models'],['model-a','model-b'])

    def test_json_protocol_reports_errors_not_tracebacks(self):
        output=io.StringIO()
        with patch('sys.stdin',io.StringIO(json.dumps({'action':'load','folder':'/nonexistent/koala-project'}))),contextlib.redirect_stdout(output):
            code=main()
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(code,1);self.assertEqual(events[-1]['event'],'error')
        self.assertNotIn('Traceback',output.getvalue())

    def test_json_protocol_streams_progress_and_result(self):
        output=io.StringIO()
        def action(request):
            print('Progress line')
            return {'finished':True}
        with patch('sys.stdin',io.StringIO('{"action":"test"}')),contextlib.redirect_stdout(output),patch('koala.desktop.dispatch',side_effect=action):
            self.assertEqual(main(),0)
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([e['event'] for e in events],['progress','result'])

    def test_interrupt_is_explicit_and_does_not_retry(self):
        output=io.StringIO()
        with patch('sys.stdin',io.StringIO('{"action":"test"}')),contextlib.redirect_stdout(output),patch('koala.desktop.dispatch',side_effect=KeyboardInterrupt) as action:
            self.assertEqual(main(),130)
        self.assertTrue(json.loads(output.getvalue())['cancelled']);action.assert_called_once()
