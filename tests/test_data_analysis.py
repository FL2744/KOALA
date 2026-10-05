import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from koala import data_analysis as data
from koala.desktop import dispatch
from koala.core import save,read_json
from koala.documents import inspiration_context

class DataTests(unittest.TestCase):
    def test_full_workflow_and_non_destructive_integration(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';dispatch({'action':'create','folder':str(folder),'brief':{}})
            file=Path(d)/'sample.csv';file.write_text('group,value\na,1\na,3\nb,\nb,7\n')
            view=dispatch({'action':'import_data','folder':str(folder),'path':str(file)})
            item=view['data_workspace']['datasets'][0];ident=item['id']
            result=data.analyze(folder,ident,'summary');self.assertIn('3.666',result['result'])
            freq=data.analyze(folder,ident,'frequencies','group');self.assertIn('top_50',freq['result'])
            compare=data.analyze(folder,ident,'compare','value','group');self.assertIn('2.0',compare['result'])
            article={'brief':{},'sections':[{'text':'Keep original text.'}]};save(folder/'article.json',article)
            data.integrate(folder,ident,result['id'],True,'discussion','Consider limits')
            updated=read_json(folder/'article.json');self.assertEqual(updated['sections'],article['sections'])
            self.assertEqual(inspiration_context(updated)['user_dataset_findings'][0]['placement'],'discussion')
            data.integrate(folder,ident,result['id'],False,'discussion','');self.assertFalse(read_json(folder/'article.json')['data_findings'])
    def test_text_sampling_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);p=folder/'text.txt';p.write_text('Evidence. '*4000)
            item=data.import_data(folder,p);provider=Mock();provider.model='test';provider.generate.return_value='Provisional findings.'
            result=data.analyze(folder,item['id'],'themes',provider=provider)
            self.assertFalse(result['included']);self.assertIn('Not a random sample',provider.generate.call_args.args[1])
            with self.assertRaises(ValueError):data.analyze(folder,item['id'],'summary')
            with self.assertRaises(ValueError):data.dataset(folder,'../other')
    def test_bad_headers_nested_json_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);p=folder/'bad.csv';p.write_text('x,x\n1,2')
            with self.assertRaises(ValueError):data.import_data(folder,p)
            p=folder/'bad.json';p.write_text('[{"x": [1]}]')
            with self.assertRaises(ValueError):data.import_data(folder,p)
            result=data.describe([{'x':'nan'},{'x':2},{'x':''}],['x'])['x']
            self.assertEqual(result['numeric_count'],1);self.assertEqual(result['missing'],1)
