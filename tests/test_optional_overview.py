import json
import tempfile
import unittest
from pathlib import Path
from koala.documents import collect_analysis, evidence_options, analyse_document, FIELDS
from test_documents import DocumentProvider, write_docx


class OptionalOverviewTests(unittest.TestCase):
    def test_missing_overview_retains_grounded_findings(self):
        chunk = {'id': 'c000001', 'text': 'Memory connects people.'}
        raw = {'themes': [{'text': 'Memory', 'evidence_id': 'E0001'}]}
        result, warnings = collect_analysis(raw, chunk, 'sha', evidence_options(chunk))
        self.assertEqual(result['themes'][0]['evidence'], chunk['text'])
        self.assertIn('Memory', result['overview'])
        self.assertFalse(warnings)

    def test_nontext_or_empty_overview_is_derived_locally(self):
        chunk = {'id': 'c000001', 'text': 'Memory connects people.'}
        for overview in (None, [], {}, 42, '', '   '):
            with self.subTest(overview=overview):
                raw = {'overview': overview, 'themes': [{'text': 'Memory', 'evidence_id': 'E0001'}]}
                result, _ = collect_analysis(raw, chunk, 'sha', evidence_options(chunk))
                self.assertEqual(result['overview'], 'Document findings: Memory')

    def test_missing_overview_does_not_admit_unsupported_findings(self):
        chunk = {'id': 'c000001', 'text': 'Memory connects people.'}
        result, warnings = collect_analysis({'themes':[{'text':'Invented','evidence_id':'unknown'}]},
                                            chunk, 'sha', evidence_options(chunk))
        self.assertFalse(any(result[f] for f in FIELDS))
        self.assertTrue(warnings)
        self.assertEqual(result['overview'], 'No grounded findings retained from this chunk.')

    def test_multichunk_import_without_overview_calls_once_per_chunk(self):
        class Provider(DocumentProvider):
            def json(self, instructions, prompt):
                self.calls += 1
                options = json.loads(prompt.split('\n', 1)[1])
                return {'themes': [{'text': 'Memory', 'evidence_id': next(iter(options))}]}
        with tempfile.TemporaryDirectory() as folder:
            path = write_docx(Path(folder)/'input.docx', ['Memory connects people. '*100]*10)
            provider = Provider()
            result = analyse_document(provider, path, folder, lambda _:None)
            self.assertGreater(result['chunk_count'], 1)
            self.assertEqual(provider.calls, result['chunk_count'])
            self.assertTrue(result['digest']['themes'])
            self.assertEqual(analyse_document(provider, path, folder), result)
            self.assertEqual(provider.calls, result['chunk_count'])
