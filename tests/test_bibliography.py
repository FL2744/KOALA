import tempfile
import unittest
from pathlib import Path
from koala.bibliography import references, read_bibliography, bibliography_view
from koala.desktop import dispatch
from koala.core import save, read_json
from koala.books import brief_context
from test_documents import write_docx


class BibliographyTests(unittest.TestCase):
    def test_wrapped_references_and_duplicates(self):
        self.assertEqual(references('Adorno. A work.\nPublisher.\n\nCamus. Another work.\n\nadorno. A work. Publisher.'),
                         ['Adorno. A work. Publisher.', 'Camus. Another work.'])
        for bad in ('', 'x'*4001, '\n\n'.join(str(i) for i in range(1001))):
            with self.assertRaises(ValueError): references(bad)

    def test_docx_and_text_preview(self):
        with tempfile.TemporaryDirectory() as d:
            path=write_docx(Path(d)/'refs.docx',['Adorno. Work one.','Camus. Work two.'])
            self.assertEqual(references(read_bibliography(path)['text']),['Adorno. Work one.','Camus. Work two.','Table evidence'])
            path=Path(d)/'refs.txt';path.write_text('Adorno. Work one.\nCamus. Work two.')
            self.assertEqual(len(references(read_bibliography(path)['text'])),2)
            path.write_text('')
            with self.assertRaisesRegex(ValueError,'No bibliography text'): read_bibliography(path)

    def project(self, folder, drafted=False):
        data=dispatch({'action':'create','folder':str(folder),'brief':{'topic':'Meaning'}})
        article={'brief':data['brief'],'plan':{'title':'Original'},'title':'Original',
                 'abstract':'original abstract','sections':[{'heading':'Section','text':'Original prose.'}] if drafted else [],
                 'sources':[], 'stage':'drafted' if drafted else 'abstract','excerpts':[],'warnings':[]}
        save(folder/'article.json',article)
        return article

    def test_import_replans_and_archives_without_inference(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';original=self.project(folder,True)
            result=dispatch({'action':'import_bibliography','folder':str(folder),'text':'Adorno. Work one.\n\nCamus. Work two.'})
            self.assertEqual(result['article']['stage'],'planning')
            self.assertEqual(result['article']['sections'],[])
            self.assertEqual(result['brief']['possible_citations'],['Adorno. Work one.','Camus. Work two.'])
            archives=list((folder/'revisions').rglob('article.json'))
            self.assertTrue(any(read_json(p)['sections']==original['sections'] for p in archives))
            before=(folder/'article.json').read_bytes()
            dispatch({'action':'import_bibliography','folder':str(folder),'text':'Adorno. Work one.'})
            self.assertEqual((folder/'article.json').read_bytes(),before)

    def test_keep_draft_and_early_import(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';original=self.project(folder,True)
            result=dispatch({'action':'import_bibliography','folder':str(folder),'text':'Camus. A work.','mode':'repair'})
            self.assertEqual(result['article']['sections'],original['sections'])
            self.assertTrue(result['article']['bibliography_research_pending'])
            self.assertEqual(result['article']['stage'],'citation_review')
            early=Path(d)/'early';self.project(early)
            result=dispatch({'action':'import_bibliography','folder':str(early),'text':'Camus. A work.','mode':'repair'})
            self.assertEqual(result['article']['stage'],'planning')

    def test_ledger_bypass_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';self.project(folder)
            brief=read_json(folder/'brief.json');brief['sources_file']='sources.json';save(folder/'brief.json',brief)
            with self.assertRaisesRegex(ValueError,'curated source ledger'):
                dispatch({'action':'import_bibliography','folder':str(folder),'text':'Camus. A work.'})

    def test_planning_receives_all_candidates_and_view_distinguishes_evidence(self):
        brief={'possible_citations':[f'Work {i}' for i in range(120)]}
        self.assertEqual(len(brief_context(brief,planning=True)['possible_citations']),120)
        self.assertEqual(len(brief_context(brief)['possible_citations']),30)
        view=bibliography_view(brief,{'sources':[{'id':'S001','title':'Work','authors':['Author'],'year':'2000'}],
                                     'sections':[{'text':'Claim [@S001].'}]})
        self.assertTrue(view['sources'][0]['cited'])
        self.assertFalse(view['sources'][0]['has_evidence'])

    def test_pdf_preview(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'refs.pdf'
            pdf=canvas.Canvas(str(path));pdf.drawString(72,720,'Camus. The Myth of Sisyphus.');pdf.save()
            self.assertIn('The Myth of Sisyphus',read_bibliography(path)['text'])

    def test_pending_import_triggers_research_even_with_coverage(self):
        from unittest.mock import patch, Mock
        from koala.repair import repair_citations
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';article=self.project(folder,True)
            article['bibliography_research_pending']=True
            with patch('koala.repair.citation_readiness',return_value={'blockers':[]}), patch('koala.pipeline.continue_prepare',side_effect=RuntimeError('research reached')) as research:
                with self.assertRaisesRegex(RuntimeError,'research reached'):
                    repair_citations(Mock(),article,folder,progress=lambda _:None)
                research.assert_called_once()
            self.assertEqual(read_json(folder/'article.json')['sections'],article['sections'])
