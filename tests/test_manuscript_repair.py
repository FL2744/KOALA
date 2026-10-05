import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from koala.core import read_json,save
from koala.manuscript_repair import repair_manuscript,validate_edits,DEFAULT_REPAIR
from koala.desktop import dispatch
from koala.cli import main
from test_citation_coverage import article

BEFORE='The abstract describes political judgment as a public activity [@S001].'
AFTER='Arendt describes political judgment as a public activity [@S001].'

def fixture():
    a=article(2);a['brief']['citation_target']=75
    a['sources'][0]['authors']=['Hannah Arendt']
    a['sections']=[{'heading':f'Section {i}','text':BEFORE+'\n\n'+('The broader philosophical context remains important. '*35),'continuity_summary':'Old summary'} for i in range(4)]
    a['stage']='drafted'
    return a

def proposal():return {'edits':[{'before':BEFORE,'after':AFTER}]}

class ManuscriptRepairTests(unittest.TestCase):
    def test_exact_patches_keep_everything_else_and_citations(self):
        original=fixture()['sections'][0]['text']
        revised,edits=validate_edits(original,proposal())
        self.assertEqual(revised,original.replace(BEFORE,AFTER));self.assertEqual(len(edits),1)
        self.assertEqual(validate_edits(original,{'edits':[]})[0],original)

    def test_ambiguous_overlapping_citation_and_quote_changes_rejected(self):
        original=fixture()['sections'][0]['text']
        cases=[{'edits':[{'before':'The broader','after':'The wider'}]},
               {'edits':[{'before':BEFORE,'after':AFTER.replace('S001','S002')}]},
               {'edits':[{'before':BEFORE,'after':AFTER},{'before':'political judgment','after':'social judgment'}]}]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):validate_edits(original,case)
        with self.assertRaises(ValueError):validate_edits('He wrote “politics matters”.',{'edits':[{'before':'“politics matters”','after':'“politics is trivial”'}]})

    def test_full_rewrite_rejected(self):
        original=fixture()['sections'][0]['text']
        with self.assertRaisesRegex(ValueError,'rewrites too much'):
            validate_edits(original,{'edits':[{'before':original,'after':('Completely new wording. '*100)+' [@S001]'}]})

    def test_archives_original_and_reports_changes_without_research_gate(self):
        a=fixture();before=copy.deepcopy(a);p=Mock();p.json.side_effect=[proposal(),{'edits':[]},proposal(),{'edits':[]}]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);save(root/'article.json',a);(root/'manuscript.txt').write_text('Original export')
            result=repair_manuscript(p,a,root,progress=lambda _:None)
            state=result['manuscript_repair'];self.assertTrue(state['complete']);self.assertEqual(state['changed'],2)
            self.assertEqual(a,before);self.assertEqual(result['sources'],before['sources']);self.assertEqual(result['brief'],before['brief']);self.assertEqual(result['abstract'],before['abstract'])
            self.assertEqual(result['sections'][1],before['sections'][1])
            self.assertEqual(read_json(Path(state['archive'])/'article.json'),before)
            self.assertEqual((Path(state['archive'])/'manuscript.txt').read_text(),'Original export')
            self.assertEqual((root/'manuscript.txt').read_text(),'Original export')
            report=Path(state['report']).read_text();self.assertIn('Before',report);self.assertIn('After',report);self.assertIn('artificial intelligence',report)
            self.assertEqual(p.json.call_count,4)

    def test_rejected_edit_keeps_original_and_continues(self):
        a=fixture();p=Mock();p.json.side_effect=[{'edits':[{'before':BEFORE,'after':AFTER.replace('S001','S999')}]},proposal(),{'edits':[]},{'edits':[]}]
        with tempfile.TemporaryDirectory() as d:
            result=repair_manuscript(p,a,d,progress=lambda _:None)
            self.assertEqual(result['sections'][0],a['sections'][0]);self.assertEqual(result['manuscript_repair']['needs_review'],1)
            self.assertEqual(result['manuscript_repair']['processed'],4)
            self.assertIn(AFTER,result['sections'][1]['text'])

    def test_interrupt_resume_and_completed_pass_are_idempotent(self):
        a=fixture();p=Mock();p.json.side_effect=[proposal(),RuntimeError('connection lost')]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):repair_manuscript(p,a,d,progress=lambda _:None)
            saved=read_json(Path(d)/'article.json');archive=saved['manuscript_repair']['archive']
            self.assertEqual(saved['manuscript_repair']['processed'],1)
            next_provider=Mock();next_provider.json.return_value={'edits':[]}
            result=repair_manuscript(next_provider,saved,d,progress=lambda _:None)
            self.assertEqual(next_provider.json.call_count,3);self.assertEqual(result['manuscript_repair']['archive'],archive)
            repair_manuscript(next_provider,result,d,progress=lambda _:None)
            self.assertEqual(next_provider.json.call_count,3)

    def test_changed_manuscript_requires_new_pass(self):
        a=fixture();p=Mock();p.json.side_effect=RuntimeError('pause')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):repair_manuscript(p,a,d,progress=lambda _:None)
            saved=read_json(Path(d)/'article.json');saved['sections'][0]['text']+=' New user edit.'
            with self.assertRaisesRegex(ValueError,'changed after'):repair_manuscript(p,saved,d,progress=lambda _:None)
            p.json.side_effect=None;p.json.return_value={'edits':[]}
            result=repair_manuscript(p,saved,d,restart=True,progress=lambda _:None)
            self.assertIn('New user edit.',result['sections'][0]['text']);self.assertEqual(len(result['manuscript_repair_history']),1)

    def test_report_escapes_manuscript_markup(self):
        a=fixture();a['sections'][0]['text']=a['sections'][0]['text'].replace(BEFORE,BEFORE+' <script>alert(1)</script>')
        p=Mock();p.json.side_effect=[{'edits':[{'before':BEFORE+' <script>alert(1)</script>','after':AFTER+' <script>alert(1)</script>'}]}]+[{'edits':[]}]*3
        with tempfile.TemporaryDirectory() as d:
            result=repair_manuscript(p,a,d,progress=lambda _:None);report=Path(result['manuscript_repair']['report']).read_text()
            self.assertNotIn('<script>',report);self.assertIn('&lt;script&gt;',report)

    def test_desktop_routes_custom_instructions_and_preserves_exports(self):
        a=fixture()
        with tempfile.TemporaryDirectory() as d,patch('koala.cli.Provider') as provider:
            root=Path(d);save(root/'article.json',a);save(root/'brief.json',a['brief'])
            provider.return_value.json.side_effect=[proposal()]+[{'edits':[]}]*3
            result=dispatch({'action':'repair-manuscript','folder':d,'repair_instructions':DEFAULT_REPAIR})
            self.assertTrue(result['article']['manuscript_repair']['complete'])
            self.assertEqual(result['article']['manuscript_repair']['instructions'],DEFAULT_REPAIR)
            self.assertFalse((root/'manuscript.docx').exists())
            self.assertIn('default_manuscript_repair',result)

    def test_edit_inside_quotation_cannot_bypass_quote_protection(self):
        for original in ['He wrote “politics matters”.','He wrote ‘politics matters’.',"He wrote 'politics matters'."]:
            with self.subTest(original=original),self.assertRaisesRegex(ValueError,'quoted material'):
                validate_edits(original,{'edits':[{'before':'politics matters','after':'politics is trivial'}]})
