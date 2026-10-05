import tempfile
import unittest
from pathlib import Path
from koala.documents import analyse_document, collect_analysis, evidence_options
from koala.core import read_json
from test_documents import DocumentProvider


class AnalysisReportingTests(unittest.TestCase):
    def test_literal_author_surface_is_retained_without_invented_expansion(self):
        chunk={'id':'c000001','text':'Nietzsche discusses values.'}
        options=evidence_options(chunk)
        raw={'authors':[{'text':'Friedrich Nietzsche','source_text':'Nietzsche','evidence_id':'E0001'}]}
        analysis,warnings=collect_analysis(raw,chunk,'hash',options)
        self.assertEqual(analysis['authors'][0]['text'],'Nietzsche')
        self.assertFalse(warnings)
        raw['authors'][0]['source_text']='Invented Person'
        analysis,warnings=collect_analysis(raw,chunk,'hash',options)
        self.assertFalse(analysis['authors']);self.assertIn('verbatim',warnings[0])

    def test_exact_failure_reason_saved_without_repeated_progress_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.txt';path.write_text('Memory connects people.\n'*400)
            provider=DocumentProvider();original=provider.json
            def response(system,prompt):
                raw=original(system,prompt)
                raw['authors']=[{'text':'Invented Person','evidence_id':'E0001'}]
                return raw
            provider.json=response;messages=[]
            result=analyse_document(provider,path,Path(d)/'out',messages.append)
            self.assertGreater(result['chunk_count'],1)
            self.assertEqual(result['omitted_entries'],result['chunk_count'])
            self.assertEqual(result['finding_counts']['themes'],result['chunk_count'])
            self.assertEqual(len([m for m in messages if 'Skipped' in m]),1)
            self.assertFalse(any('unsupported/malformed' in m for m in messages))
            self.assertIn('verbatim',result['warnings'][0])
            record=read_json(Path(result['analysis_file']).parent/'chunks/c000001.json')
            self.assertIn('model_response',record)
            self.assertEqual(provider.calls,result['chunk_count'])
