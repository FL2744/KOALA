import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from koala.core import save,read_json,normalize_brief
from koala.rewrite import rewrite,apply,current
from koala.desktop import dispatch
from test_manuscript_repair import fixture

class RewriteTests(unittest.TestCase):
    def setup_project(self,folder):
        a=fixture();a['brief']=normalize_brief(a['brief'])
        save(folder/'article.json',a);save(folder/'brief.json',a['brief']);save(folder/'sources.json',{'sources':a['sources']})
        (folder/'manuscript.txt').write_text('Existing export')
        return a
    def provider(self,a):
        p=Mock();p.generate.side_effect=[s['text'].replace('broader','wider') for s in a['sections']]+[' '.join(['Proposed']*270)]
        return p
    def test_review_before_apply_with_backups(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);a=self.setup_project(folder);before=(folder/'article.json').read_bytes()
            state=rewrite(self.provider(a),a,folder,{'style_guidance':'Direct and clear'},progress=lambda _:None)
            self.assertTrue(state['complete']);self.assertEqual((folder/'article.json').read_bytes(),before)
            self.assertEqual((folder/'manuscript.txt').read_text(),'Existing export');self.assertTrue((folder/'sources.json').exists())
            self.assertEqual(read_json(Path(state['archive'])/'article.json'),a)
            self.assertIn('Before',Path(state['report']).read_text())
            apply(folder);updated=read_json(folder/'article.json')
            self.assertEqual(updated['brief']['style_guidance'],'Direct and clear')
            self.assertIn('wider',updated['sections'][0]['text']);self.assertTrue(current(folder)['applied'])
            with self.assertRaises(ValueError):apply(folder)
    def test_network_resume_no_redraft_and_parameter_guard(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);a=self.setup_project(folder);p=Mock();p.generate.side_effect=[a['sections'][0]['text'],RuntimeError('offline')]
            with self.assertRaises(RuntimeError):rewrite(p,a,folder,{'topic':'New topic'},progress=lambda _:None)
            self.assertEqual(current(folder)['processed'],1)
            with self.assertRaisesRegex(ValueError,'Parameters changed'):rewrite(p,a,folder,{'topic':'Different'})
            p=Mock();p.generate.side_effect=[s['text'] for s in a['sections'][1:]]+[' '.join(['Proposed']*270)]
            state=rewrite(p,a,folder,progress=lambda _:None);self.assertTrue(state['complete']);self.assertEqual(p.generate.call_count,4)
    def test_invalid_citations_preserve_original_and_continue(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);a=self.setup_project(folder);p=Mock();p.generate.side_effect=['Invalid [@S999]']+[s['text'] for s in a['sections'][1:]]+['Too short']
            state=rewrite(p,a,folder,{},progress=lambda _:None)
            self.assertEqual(state['candidate']['sections'][0]['text'],a['sections'][0]['text'])
            self.assertEqual(state['entries'][0]['status'],'original retained');self.assertTrue(state['complete'])
            self.assertEqual(state['candidate']['abstract'],a['abstract'])
    def test_changed_original_blocks_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);a=self.setup_project(folder)
            rewrite(self.provider(a),a,folder,{},progress=lambda _:None)
            a['sections'][0]['text']+=' User edit.';save(folder/'article.json',a)
            with self.assertRaisesRegex(ValueError,'active manuscript changed'):apply(folder)
            with self.assertRaises(ValueError):rewrite(Mock(),a,folder,{'chapter_count':8})
    def test_bridge_exposes_rewrite_and_accepts(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);a=self.setup_project(folder)
            with patch('koala.desktop.Provider',return_value=self.provider(a)):
                result=dispatch({'action':'rewrite_manuscript','folder':str(folder),'parameters':{'style_guidance':'Precise'}})
            self.assertTrue(result['rewrite']['complete']);self.assertNotIn('candidate',result['rewrite'])
            result=dispatch({'action':'apply_rewrite','folder':str(folder)})
            self.assertEqual(result['brief']['style_guidance'],'Precise')
