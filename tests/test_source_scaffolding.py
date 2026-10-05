import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from koala.writing_style import source_scaffolding_issues
from koala.pipeline import draft, prepare, system_for
from koala.core import read_json
from test_citation_coverage import article
from test_books import BookProvider, setup_book


class SourceScaffoldingTests(unittest.TestCase):
    def test_reported_variants_are_detected(self):
        for text in [
            'The volume, as summarized in its abstract, addresses virtues [@S001].',
            'The volume, as described in its manuscript, addresses virtues.',
            'Hannah Arendt’s abstract on government describes domination.',
            'The supplied abstract attributed to Diamond discusses measurement.',
            'The available abstract on Ellul emphasizes purpose.',
            'One supplied record lists an author.',
            'This summary cannot stand in for the primary text.',
            'The record does not supply enough evidence.',
            'The attribution is flagged for identity review.',
        ]:
            with self.subTest(text=text):
                self.assertTrue(source_scaffolding_issues(text))

    def test_substantive_uncertainty_and_ordinary_usage_survive(self):
        for text in [
            'The evidence does not establish that the model understands language.',
            'An abstract concept may resist measurement.',
            'A generated summary should faithfully represent its source.',
            'The historical record is incomplete.',
            'Gray argues that liberty is contested [@S001].',
            'The quoted wording is “as summarized in its abstract”.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(source_scaffolding_issues(text), [])

    def test_custom_style_cannot_drop_integrity_guidance(self):
        system = system_for({'writing_prompt': 'Write short sentences.'})
        self.assertIn('as described in its manuscript', system)
        self.assertIn('Omit unsupported examples or attributions', system)

    def test_article_retries_before_acceptance(self):
        a = article(); clean = 'Evidence and interpretation require careful judgment. ' * 40 + '[@S001] [@S002]'
        bad = 'As summarized in its abstract, the work considers judgment. ' + clean
        provider = Mock(); provider.generate.side_effect = [bad] + [clean] * 4
        with tempfile.TemporaryDirectory() as d, patch('koala.pipeline.require_ready'), patch('koala.pipeline.require_complete', side_effect=lambda a,f:a):
            result = draft(provider, a, d, lambda _:None)
            self.assertEqual(len(result['sections']),4)
            self.assertTrue(all(s['text']==clean for s in result['sections']))
            self.assertIn('Source-summary drafting commentary remains', provider.generate.call_args_list[1].args[1])
            attempts = [read_json(p) for p in Path(d).glob('draft-attempts/*/*/*.json')]
            self.assertEqual(sum(not x['accepted'] for x in attempts),1)

    def test_repeated_failure_does_not_accept_bad_prose(self):
        a=article(); provider=Mock()
        provider.generate.return_value='The supplied abstract discusses judgment. '+('Evidence requires careful interpretation. '*60)+' [@S001] [@S002]'
        with tempfile.TemporaryDirectory() as d, patch('koala.pipeline.require_ready'):
            with self.assertRaisesRegex(ValueError, 'Source-summary drafting commentary'):
                draft(provider,a,d,lambda _:None)
            self.assertEqual(provider.generate.call_count,3)
            self.assertEqual(a['sections'],[])
            self.assertEqual(len(list(Path(d).glob('draft-attempts/*/*/*.json'))),3)

    def test_book_retries_before_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); provider=BookProvider(); brief=setup_book(base)
            a=prepare(provider,brief,base/'run',base/'brief.json',True,lambda _:None)
            generate=provider.generate; injected=False
            def respond(system,prompt):
                nonlocal injected
                text=generate(system,prompt.split("\nRevise the previous attempt",1)[0])
                if prompt.startswith('Write one section') and not injected:
                    injected=True
                    return 'The supplied abstract discusses the topic. '+text
                return text
            with patch.object(provider,'generate',side_effect=respond):
                result=draft(provider,a,base/'run',lambda _:None)
            self.assertTrue(injected)
            self.assertTrue(all(not source_scaffolding_issues(s['text']) for s in result['sections']))
            attempts=[read_json(p) for p in (base/'run/draft-attempts').glob('*/*/*.json')]
            self.assertTrue(any(any('Source-summary' in issue for issue in x['issues']) for x in attempts))
