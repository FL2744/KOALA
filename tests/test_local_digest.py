import hashlib
import tempfile
import unittest
from pathlib import Path
from koala.core import save, read_json
from koala.documents import chunks, file_hash, merge, analyse_document, collect_analysis, evidence_options, FIELDS
from test_documents import DocumentProvider, write_docx


class LocalDigestTests(unittest.TestCase):
    def test_overfull_lists_are_bounded_without_synthesis(self):
        chunk = {'id': 'c000001', 'text': 'Memory connects people.'}
        raw = {'overview': 'Memory', 'themes': [{'text': f'Theme {i}', 'evidence_id': 'E0001'} for i in range(20)]}
        result, warnings = collect_analysis(raw, chunk, 'sha', evidence_options(chunk))
        self.assertEqual(len(result['themes']), 6)
        self.assertFalse(warnings)
        self.assertTrue(all(item['evidence'] == chunk['text'] for item in result['themes']))

    def test_stable_sample_includes_all_batches_without_growth(self):
        summaries = [{'overview':'x', **{field: [] for field in FIELDS},
                      'themes':[{'id': str(i), 'text': f'Theme {i}', 'evidence':'original'}]}
                     for i in range(100)]
        left = None
        for summary in summaries:
            left = merge(None, left, summary)
            self.assertLessEqual(len(left['themes']), 6)
        right = None
        for summary in reversed(summaries):
            right = merge(None, right, summary)
        self.assertEqual(left['themes'], right['themes'])

    def test_legacy_failed_merge_reuses_chunk_and_keeps_original_boundaries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_docx(root/'legacy.docx', ['Memory connects people. '*100]*30)
            provider = DocumentProvider()
            digest = file_hash(path)
            key = hashlib.sha256(f'v1:{provider.name}:{provider.model}'.encode()).hexdigest()[:12]
            cache = root/'documents'/digest/key
            parts = list(chunks(path, size=12000, overlap=400))
            summary = {'overview': 'Legacy summary', **{field: [] for field in FIELDS}}
            save(cache/'progress.json', {'processed':2, 'digest':summary})
            save(cache/'chunks/c000003.json', {**parts[2], 'analysis':summary})
            class StopProvider:
                name, model = provider.name, provider.model
                def json(self, *args):
                    raise RuntimeError('stop at next uncached chunk')
            with self.assertRaisesRegex(RuntimeError, 'next uncached'):
                analyse_document(StopProvider(), path, root, lambda _:None)
            state = read_json(cache/'progress.json')
            self.assertEqual(state['processed'], 3)
            self.assertEqual(state['chunk_chars'], 12000)
            self.assertEqual(state['overlap'], 400)
