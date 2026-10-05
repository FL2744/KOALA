import copy
import getpass
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from koala.cli import main
from koala.core import normalize_brief, save, read_json
from koala.menu import Menu, private_key, path_input
from koala.pipeline import prepare, draft
from test_koala import source
from test_documents import DocumentProvider, write_docx


def scripted(values):
    iterator = iter(values)
    def read(prompt=''):
        try:
            item = next(iterator)
        except StopIteration:
            raise EOFError()
        if isinstance(item, BaseException):
            raise item
        return item
    return read


def project_fixture(folder):
    save(folder/'sources.json', [source()])
    brief = normalize_brief({'topic': 'Memory', 'target_words': 1000, 'citation_target': 1,
                              'sources_file': str(folder/'sources.json')})
    save(folder/'brief.json', brief)
    return brief


class MenuNavigationTests(unittest.TestCase):
    def test_no_arguments_and_explicit_menu_dispatch(self):
        with patch('koala.menu.run_menu', return_value=0) as run:
            self.assertEqual(main([]), 0)
            run.assert_called_once_with(None)
        with patch('koala.menu.run_menu', return_value=0) as run:
            self.assertEqual(main(['menu', '/tmp/example']), 0)
            run.assert_called_once_with(Path('/tmp/example'))

    def test_invalid_choice_then_quit(self):
        output = []
        m = Menu(read=scripted(['garbage', '-1', '0']), write=output.append)
        self.assertEqual(m.run(), 0)
        self.assertEqual(sum('Enter a number' in s for s in output), 2)
        self.assertIn('Goodbye.', output)

    def test_eof_exits_without_looping(self):
        output = []
        self.assertEqual(Menu(read=scripted([]), write=output.append).run(), 0)
        self.assertTrue(any('Leaving the menu' in s for s in output))

    def test_interrupt_cancels_and_returns_to_menu(self):
        output = []
        self.assertEqual(Menu(read=scripted([KeyboardInterrupt(), '0']), write=output.append).run(), 0)
        self.assertTrue(any('Cancelled' in s for s in output))

    def test_new_article_through_menus_without_credentials(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            folder = Path(d)/'article'
            m = Menu(read=scripted(['1', str(folder), 'Cultural memory', '1000', '0', '0']), write=lambda _: None)
            self.assertEqual(m.run(), 0)
            brief = read_json(folder/'brief.json')
            self.assertEqual(brief['topic'], 'Cultural memory')
            self.assertEqual(brief['target_words'], 1000)
            self.assertFalse((folder/'article.json').exists())

    def test_new_book_options_and_word_validation(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)/'book'
            m = Menu(read=scripted(['2', str(folder), '', '2000', '80000', '8', 'y', 'Catalogue; Methods', '0', '0']), write=lambda _: None)
            self.assertEqual(m.run(), 0)
            brief = read_json(folder/'brief.json')
            self.assertEqual(normalize_brief(brief)['citation_target'], 600)
            self.assertEqual(brief['chapter_count'], 8)
            self.assertTrue(brief['include_afterword'])
            self.assertEqual(brief['appendices'], ['Catalogue', 'Methods'])

    def test_new_project_does_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder/'important.txt').write_text('keep')
            m = Menu(read=scripted([str(folder)]), write=lambda _: None)
            with self.assertRaises(ValueError):
                m.new_project('article')
            self.assertEqual((folder/'important.txt').read_text(), 'keep')

    def test_open_old_checkpoint_without_menu_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            save(folder/'article.json', {'brief': {'topic': 'Memory'}, 'provider': 'arc', 'model': 'arc-model', 'stage': 'planned'})
            m = Menu(write=lambda _: None)
            m.open_project(folder/'article.json')
            self.assertEqual(m.settings['provider'], 'arc')
            self.assertEqual(m.settings['model'], 'arc-model')
            self.assertEqual(m.folder, folder.resolve())

    def test_quoted_paths(self):
        self.assertEqual(path_input('"/tmp/a path.docx"'), Path('/tmp/a path.docx').resolve())


class MenuSettingsTests(unittest.TestCase):
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    def test_live_models_filter_and_pagination(self):
        class Client:
            def models(self):
                return [f'model-{i:02}' for i in range(30)]
        with tempfile.TemporaryDirectory() as d:
            m = Menu(read=scripted(['model', 'n', '21']), write=lambda _: None,
                     provider_factory=lambda *args: Client())
            m.folder = Path(d)
            m.choose_model()
            self.assertEqual(m.settings['model'], 'model-20')
            self.assertEqual(read_json(Path(d)/'.koala-menu.json')['model'], 'model-20')

    def test_provider_switch_resets_default_and_endpoint(self):
        m = Menu(read=scripted(['1', '2', '0']), write=lambda _: None)
        m.settings['base_url'] = 'https://example.org/v1'
        m.provider_menu()
        self.assertEqual(m.settings['provider'], 'arc')
        self.assertEqual(m.settings['model'], 'gpt-oss-120b')
        self.assertIsNone(m.settings['base_url'])

    @patch.dict(os.environ, {}, clear=True)
    def test_api_key_session_only_and_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            project_fixture(folder)
            output = []
            m = Menu(folder, read=scripted(['8', '4', '0', '0', '0']), write=output.append,
                     secret=lambda _: 'secret-test-value')
            self.assertEqual(m.run(), 0)
            self.assertNotIn('OPENAI_API_KEY', os.environ)
            self.assertNotIn('secret-test-value', (folder/'.koala-menu.json').read_text())
            self.assertFalse(any('secret-test-value' in text for text in output))

    def test_echoed_password_fallback_is_blocked(self):
        with patch('koala.menu.getpass.getpass', side_effect=getpass.GetPassWarning('echoed')):
            with self.assertRaisesRegex(ValueError, 'Hidden key entry'):
                private_key('Key:')

    def test_endpoint_does_not_save_url_credentials(self):
        output = []
        m = Menu(read=scripted(['5', 'https://name:secret@example.com/v1', '0']), write=output.append)
        m.provider_menu()
        self.assertIsNone(m.settings['base_url'])
        self.assertTrue(any('without credentials' in s for s in output))


class MenuWorkflowTests(unittest.TestCase):
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    def test_full_menu_abstract_draft_review_and_export(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            folder = Path(d)
            project_fixture(folder)
            m = Menu(folder, read=scripted(['4', '5', '6', '6', '0', '7', '1', '3', 'y', '0', '0']),
                     write=lambda _: None, provider_factory=lambda *args: DocumentProvider())
            with patch('koala.cli.Provider', return_value=DocumentProvider()):
                self.assertEqual(m.run(), 0)
            a = read_json(folder/'article.json')
            self.assertEqual(a['stage'], 'drafted')
            self.assertTrue((folder/'article.txt').exists())
            self.assertEqual(a['audit']['distinct_cited_works'], 1)
            self.assertEqual(read_json(folder/'.koala-menu.json')['formats'], ['txt'])

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    def test_import_docx_runs_shared_ingest(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            folder = Path(d)
            project_fixture(folder)
            doc = write_docx(folder/'inspiration.docx', ['Memory connects people.'])
            m = Menu(read=scripted([str(doc), '']), write=lambda _: None,
                     provider_factory=lambda *args: DocumentProvider())
            m.open_project(folder)
            with patch('koala.cli.Provider', return_value=DocumentProvider()):
                m.import_documents()
            a = read_json(folder/'article.json')
            self.assertEqual(len(a['inspiration']['documents']), 1)
            self.assertEqual(a['stage'], 'planning')

    def test_brief_editor_changes_style_without_json_editing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            project_fixture(folder)
            m = Menu(read=scripted(['9', 'Precise scholarly prose', '0']), write=lambda _: None)
            m.open_project(folder)
            m.edit_brief()
            self.assertEqual(read_json(folder/'brief.json')['style_guidance'], 'Precise scholarly prose')

    def test_brief_change_archives_draft_and_preserves_source_notes(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            brief = project_fixture(folder)
            p = DocumentProvider()
            a = prepare(p, brief, folder, folder/'brief.json', True, lambda _: None)
            a = draft(p, a, folder, lambda _: None)
            a['sources'][0]['notes'] = 'Human research note'
            save(folder/'article.json', a)
            (folder/'article.txt').write_text('old prose')
            m = Menu(write=lambda _: None)
            m.open_project(folder)
            changed = copy.deepcopy(brief)
            changed['research_guidance'] = 'New research direction'
            m.save_brief(changed)
            updated = read_json(folder/'article.json')
            self.assertEqual(updated['stage'], 'planning')
            self.assertEqual(updated['sections'], [])
            self.assertEqual(updated['inherited_sources'][0]['notes'], 'Human research note')
            revision = Path(updated['revision_history'][-1])
            self.assertEqual((revision/'article.txt').read_text(), 'old prose')
            self.assertEqual(read_json(revision/'article.json')['sections'], a['sections'])

    def test_invalid_brief_edit_leaves_checkpoint_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            brief = project_fixture(folder)
            prepare(DocumentProvider(), brief, folder, folder/'brief.json', True, lambda _: None)
            before = (folder/'article.json').read_bytes()
            m = Menu(write=lambda _: None)
            m.open_project(folder)
            with self.assertRaises(ValueError):
                m.save_brief({**brief, 'target_words': 1})
            self.assertEqual((folder/'article.json').read_bytes(), before)

    def test_edit_abstract_keeps_prior_version(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            brief = project_fixture(folder)
            a = prepare(DocumentProvider(), brief, folder, folder/'brief.json', True, lambda _: None)
            m = Menu(read=scripted([' '.join(['Revised'] * 270), '.']), write=lambda _: None)
            m.open_project(folder)
            m.edit_abstract()
            revised = read_json(folder/'article.json')
            self.assertTrue(revised['abstract'].startswith('Revised'))
            self.assertEqual(revised['stage'], 'abstract')
            self.assertEqual(read_json(Path(revised['revision_history'][-1])/'article.json')['abstract'], a['abstract'])
            self.assertTrue((folder/'sources.json').exists())

    def test_export_selection_requires_no_api_key(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            folder = Path(d)
            brief = project_fixture(folder)
            prepare(DocumentProvider(), brief, folder, folder/'brief.json', True, lambda _: None)
            calls = []
            m = Menu(read=scripted(['2', 'bad', '1,3']), write=lambda _: None, execute=lambda args: calls.append(args) or 0)
            m.open_project(folder)
            m.export_menu()
            self.assertEqual(calls[0], ['export', str(folder.resolve()/'article.json'), '--formats', 'docx', 'txt', '--abstract-only'])


if __name__ == '__main__':
    unittest.main()
