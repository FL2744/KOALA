import json
import tempfile
import unittest
from pathlib import Path
from koala.documents import FIELDS, validate_analysis, source_excerpt, evidence_options, analyse_document
from test_documents import DocumentProvider, write_docx


def analysis(evidence):
    return {'overview': 'Memory', **{f: [] for f in FIELDS},
            'themes': [{'text': 'Memory', 'evidence': evidence}]}


class EvidenceRecoveryTests(unittest.TestCase):
    def test_typography_is_restored_to_original_source(self):
        source = 'She called it “cultural\n  memory” and Scholar’s work.'
        raw = analysis('"cultural memory"')
        raw['authors'] = [{'text': "Scholar's", 'evidence': "Scholar's work"}]
        result = validate_analysis(raw, {'id': 'c000001', 'text': source}, 'sha')
        self.assertEqual(result['themes'][0]['evidence'], '“cultural\n  memory”')
        self.assertEqual(result['authors'][0]['text'], 'Scholar’s')
        for field in FIELDS:
            for finding in result[field]:
                self.assertIn(finding['evidence'], source)

    def test_paraphrases_case_changes_and_oversize_still_fail(self):
        source = 'Memory is not universal.'
        for quote in ('Memory is universal.', 'memory is not universal.', 'Memory ... universal.', '', ' '*3, 'x'*401):
            self.assertIsNone(source_excerpt(quote, source))
        self.assertIsNone(source_excerpt('a b', 'a'+' '*400+'b'))

    def test_evidence_bank_is_bounded_and_grounded(self):
        chunk = {'text': '[word/document.xml:p1]\n' + 'word '*2500 + '\nSecond paragraph.'}
        options = evidence_options(chunk)
        self.assertGreater(len(options), 30)
        for text in options.values():
            self.assertLessEqual(len(text), 300)
            self.assertIn(text, chunk['text'])
            self.assertNotIn('word/document.xml', text)

    def test_bad_finding_is_reported_without_aborting_good_findings(self):
        class Provider(DocumentProvider):
            def json(self, instructions, prompt):
                self.calls += 1
                options = json.loads(prompt.split('\n', 1)[1])
                result = analysis('An invented quotation')
                result['themes'].append({'text': 'Memory', 'evidence_id': next(iter(options))})
                return result
        with tempfile.TemporaryDirectory() as folder:
            doc = write_docx(Path(folder)/'input.docx', ['Memory connects people.'])
            provider = Provider()
            result = analyse_document(provider, doc, folder, lambda _: None)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(len(result['warnings']), 1)
            self.assertEqual(result['digest']['themes'][0]['evidence'], 'Memory connects people.')

    def test_ids_used_on_first_call_and_cache_reused(self):
        class Provider(DocumentProvider):
            def json(self, instructions, prompt):
                self.calls += 1
                options = json.loads(prompt.split('\n', 1)[1])
                result = analysis('ignored invented quote')
                result['themes'][0]['evidence_id'] = next(iter(options))
                return result
        with tempfile.TemporaryDirectory() as folder:
            doc = write_docx(Path(folder)/'input.docx', ['Memory connects people.'])
            provider = Provider()
            result = analyse_document(provider, doc, folder, lambda _: None)
            self.assertEqual(result['digest']['themes'][0]['evidence'], 'Memory connects people.')
            self.assertEqual(provider.calls, 1)
            self.assertEqual(analyse_document(provider, doc, folder), result)
            self.assertEqual(provider.calls, 1)

    def test_invalid_id_and_invented_author_rejected(self):
        chunk = {'id': 'c000001', 'text': 'Memory connects people.'}
        options = evidence_options(chunk)
        raw = analysis('Memory connects people.')
        raw['themes'][0]['evidence_id'] = 'E9999'
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            validate_analysis(raw, chunk, 'sha', options)
        raw['themes'][0]['evidence_id'] = 'E0001'
        raw['authors'] = [{'text': 'Invented Scholar', 'evidence_id': 'E0001'}]
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            validate_analysis(raw, chunk, 'sha', options)

    def test_no_grounded_findings_is_explicit_and_not_invented(self):
        class Provider(DocumentProvider):
            def json(self, instructions, prompt):
                self.calls += 1
                return analysis('Invented evidence')
        with tempfile.TemporaryDirectory() as folder:
            doc = write_docx(Path(folder)/'input.docx', ['Memory connects people.'])
            provider = Provider()
            result = analyse_document(provider, doc, folder, lambda _: None)
            self.assertEqual(provider.calls, 1)
            self.assertTrue(result['warnings'])
            self.assertIn('No grounded findings', result['digest']['overview'])
            self.assertFalse(any(result['digest'][field] for field in FIELDS))
