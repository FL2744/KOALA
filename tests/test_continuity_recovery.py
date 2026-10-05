import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from koala.books import summarize, finish_summaries
from koala.core import read_json, save
from koala.pipeline import prepare, draft
from test_books import BookProvider, setup_book


class ContinuityRecoveryTests(unittest.TestCase):
    def test_missing_empty_wrong_type_falls_back_once(self):
        text='An opening argument.\nA qualification and conclusion.'
        for raw in ({}, {'summary':None}, {'summary':[]}, {'summary':42}, {'summary':'  '}, []):
            with self.subTest(raw=raw):
                provider=Mock();provider.json.return_value=raw
                self.assertEqual(summarize(provider,'system',text),' '.join(text.split()))
                provider.json.assert_called_once()

    def test_long_summary_is_bounded_with_opening_and_conclusion(self):
        provider=Mock();provider.json.return_value={'summary':'Opening claim. '+ 'Middle detail. '*300 + 'Closing qualification.'}
        result=summarize(provider,'system','saved text',1000)
        self.assertLessEqual(len(result),1000)
        self.assertTrue(result.startswith('Opening claim.'))
        self.assertTrue(result.endswith('Closing qualification.'))
        provider.json.assert_called_once()

    def test_invalid_json_falls_back_but_outage_still_reports(self):
        provider=Mock();provider.json.side_effect=RuntimeError('Model returned invalid JSON; checkpoint retained. Retry or select another model.')
        self.assertEqual(summarize(provider,'system','Saved prose.'),'Saved prose.')
        provider.json.side_effect=RuntimeError('Cannot reach provider')
        with self.assertRaisesRegex(RuntimeError,'Cannot reach'):
            summarize(provider,'system','Saved prose.')

    def test_section_and_chapter_fallbacks_saved_once(self):
        with tempfile.TemporaryDirectory() as d:
            article={'sections':[{'chapter_index':0,'text':'Saved argument. '*300}],
                     'plan':{'chapters':[{}],'sections':[{'chapter_index':0}]}}
            provider=Mock();provider.json.return_value={}
            finish_summaries(provider,article,d,'system')
            saved=read_json(Path(d)/'article.json')
            self.assertLessEqual(len(saved['sections'][0]['continuity_summary']),1000)
            self.assertLessEqual(len(saved['plan']['chapters'][0]['continuity_summary']),1500)
            self.assertEqual(saved['sections'][0]['text'],'Saved argument. '*300)
            self.assertEqual(provider.json.call_count,2)
            finish_summaries(provider,saved,d,'system')
            self.assertEqual(provider.json.call_count,2)

    def test_resume_with_invalid_summary_keeps_saved_prose_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);brief=setup_book(base);provider=BookProvider()
            article=prepare(provider,brief,base/'run',base/'brief.json',True,lambda _:None)
            original=provider.json
            def outage(system,prompt):
                if prompt.startswith('Summarise this completed'):
                    raise RuntimeError('outage')
                return original(system,prompt)
            with patch.object(provider,'json',side_effect=outage), self.assertRaises(RuntimeError):
                draft(provider,article,base/'run',lambda _:None)
            saved=read_json(base/'run/article.json');first=saved['sections'][0]['text']
            def missing(system,prompt):
                if prompt.startswith('Summarise this completed'):
                    return {}
                return original(system,prompt)
            with patch.object(provider,'json',side_effect=missing):
                done=draft(provider,saved,base/'run',lambda _:None)
            self.assertEqual(done['sections'][0]['text'],first)
            self.assertEqual(done['stage'],'drafted')
            self.assertEqual(len([e for e,_ in provider.events if e=='book_section']),len(done['sections']))
