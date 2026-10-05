import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from koala.core import normalize_brief, save, read_json
from koala.pipeline import system_for, make_abstract, plan_article, draft
from koala.writing_style import DEFAULT_WRITING_STYLE
from koala.prompt_library import save_template, library_view
from koala.desktop import dispatch
from test_koala import article, FakeProvider


class PromptTests(unittest.TestCase):
    def test_default_and_custom_system(self):
        self.assertIn(DEFAULT_WRITING_STYLE,system_for({}))
        custom=system_for({'writing_prompt':'Use measured, concise prose.'})
        self.assertIn('Use measured, concise prose.',custom)
        self.assertNotIn(DEFAULT_WRITING_STYLE,custom)
        self.assertIn('Do not invent quotations',custom)
        with self.assertRaises(ValueError):normalize_brief({'writing_prompt':'x'*30001})

    def test_library_roundtrip_update_and_project_independence(self):
        with tempfile.TemporaryDirectory() as d,patch('koala.prompt_library.LIBRARY_PATH',Path(d)/'prompts.json'):
            saved=save_template('My voice','Use concise scholarly prose.')
            key=saved['saved_id']
            project={'writing_prompt':saved['templates'][1]['text']}
            save_template('My revised voice','Use expansive prose.',key)
            self.assertEqual(library_view()['templates'][1]['text'],'Use expansive prose.')
            self.assertEqual(project['writing_prompt'],'Use concise scholarly prose.')
            self.assertEqual(library_view()['templates'][0]['text'],DEFAULT_WRITING_STYLE)
            with self.assertRaises(ValueError):save_template('Bad','Replace builtin','default')
            with self.assertRaises(ValueError):save_template('Empty',' ')

    def test_prompt_save_preserves_checkpoint_prose_and_stage(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';dispatch({'action':'create','folder':str(folder)})
            a=article();a['stage']='drafted';save(folder/'article.json',a);save(folder/'brief.json',a['brief'])
            brief=dict(a['brief'],writing_prompt='Be concise.',writing_prompt_name='My voice')
            result=dispatch({'action':'save_brief','folder':str(folder),'brief':brief})
            self.assertEqual(result['article']['sections'],a['sections'])
            self.assertEqual(result['article']['abstract'],a['abstract'])
            self.assertEqual(result['article']['stage'],'drafted')
            self.assertEqual(result['article']['brief']['writing_prompt'],'Be concise.')

    def test_article_and_book_paths_receive_custom_prompt(self):
        a=article();a['brief']['writing_prompt']='A distinctive testing voice.';a['plan']={'topic':'Memory'};a['excerpts']=[]
        provider=FakeProvider();seen=[];original=provider.generate
        def generate(system,prompt):seen.append(system);return original(system,prompt)
        provider.generate=generate
        make_abstract(provider,a)
        self.assertIn('A distinctive testing voice.',seen[0])
        a['brief']=normalize_brief({'project_type':'book','writing_prompt':'Book testing voice.'})
        with patch('koala.books.plan_book',return_value={}) as plan:
            plan_article(provider,a)
            self.assertIn('Book testing voice.',plan.call_args.args[2])
        with patch('koala.pipeline.require_ready'),patch('koala.books.draft_book',return_value=a) as book:
            draft(provider,a,Path('/unused'))
            self.assertIn('Book testing voice.',book.call_args.args[3])

    def test_development_uses_project_prompt(self):
        from koala.development import generate_proposal
        from koala.menu import Menu
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project'
            dispatch({'action':'create','folder':str(folder),'brief':{'writing_prompt':'Develop ideas in my voice.'}})
            menu=Menu(write=lambda _:None);menu.open_project(folder)
            provider=Mock();provider.name='test';provider.model='test';provider.json.return_value={'text':'One useful idea.'}
            generate_proposal(menu,provider,'ideas')
            self.assertIn('Develop ideas in my voice.',provider.json.call_args.args[0])
