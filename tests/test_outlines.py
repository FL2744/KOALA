import io
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
from koala.outlines import read_outline, chapter_titles, validate_outline
from koala.core import normalize_brief, save, read_json
from koala.books import plan_book, detail_chapter
from koala.desktop import dispatch
from koala.cli import main
from test_books import BookProvider, book_plan
from test_documents import write_docx

TEXT='Introduction: The problem\nChapter 1: Origins .... 5\n  1.1 Earlier disputes\nChapter 2: Meaning\nChapter 3: Responses\nAfterword: Further questions\nAppendix A: Timeline'

class OutlineTests(unittest.TestCase):
    def test_numbered_titles_and_page_leaders(self):
        self.assertEqual(chapter_titles(TEXT),['Origins','Meaning','Responses'])
        self.assertEqual(chapter_titles('1. Introduction\n2. Origins\n3. Meaning'),['Origins','Meaning'])

    def test_book_structure_and_custom_count(self):
        b=normalize_brief({'project_type':'book','chapter_outline':TEXT})
        self.assertEqual(b['chapter_count'],3)
        self.assertTrue(b['include_afterword']);self.assertEqual(b['appendices'],['Timeline'])
        with self.assertRaises(ValueError):normalize_brief({'project_type':'article','chapter_outline':TEXT})
        with self.assertRaises(ValueError):normalize_brief({'project_type':'book','chapter_count':3})

    def test_import_local_formats_and_snapshot_survives_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            for ext in ('.txt','.md','.docx'):
                p=folder/('outline'+ext)
                if ext=='.docx':write_docx(p,TEXT.splitlines())
                else:p.write_text(TEXT)
                data=dispatch({'action':'read_outline','path':str(p)})
                self.assertEqual(data['chapter_count'],3)
                p.unlink();self.assertIn('Earlier disputes',data['text'])

    def test_pdf_import(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'outline.pdf';c=canvas.Canvas(str(p))
            for i,line in enumerate(TEXT.splitlines()):c.drawString(60,760-i*20,line)
            c.save();self.assertEqual(read_outline(p)['chapter_count'],3)

    def test_invalid_empty_and_oversize(self):
        with self.assertRaisesRegex(ValueError,'60,000'):validate_outline('x'*60001)
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_outline('Chapter 1: Same\nChapter 2: Same')
        with self.assertRaisesRegex(ValueError,'30'):validate_outline('\n'.join(f'Chapter {i}: Topic {i}' for i in range(31)))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'empty.txt';p.write_text('')
            with self.assertRaisesRegex(ValueError,'No outline text'):read_outline(p)

    def test_outline_reaches_planning_and_chapter_detail(self):
        b=normalize_brief({'project_type':'book','chapter_outline':TEXT})
        p=BookProvider();a={'brief':b,'excerpts':[],'abstract':'Guiding abstract'}
        a['plan']=plan_book(p,a,'system')
        main=[c['heading'] for c in a['plan']['chapters'] if c['kind']=='chapter']
        self.assertEqual(main,['Origins','Meaning','Responses'])
        self.assertEqual(a['plan']['chapters'][0]['heading'],'Introduction: The problem')
        with tempfile.TemporaryDirectory() as d:detail_chapter(p,a,1,d,'system')
        for event,prompt in p.events:
            if event in ('book_plan','chapter_plan'):self.assertIn('Earlier disputes',prompt)
        self.assertEqual(sum(s['target_words'] for s in a['plan']['sections']),65000)

    def test_cli_import_archives_existing_prose_without_inference(self):
        b=normalize_brief({'project_type':'book'})
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            folder=Path(d);p=folder/'outline.txt';p.write_text(TEXT)
            save(folder/'brief.json',b)
            a={'brief':b,'title':'Original','abstract':'Old abstract','plan':book_plan(b),
               'sections':[{'heading':'Original','text':'Keep me.'}],'sources':[], 'stage':'drafting','provider':'openai','model':'test'}
            save(folder/'article.json',a)
            with patch('koala.cli.Provider') as provider:
                self.assertEqual(main(['import-outline',str(p),'--out',str(folder)]),0)
                provider.assert_not_called()
            current=read_json(folder/'article.json')
            self.assertEqual(current['stage'],'planning');self.assertEqual(current['brief']['chapter_count'],3)
            old=read_json(Path(current['revision_history'][-1])/'article.json')
            self.assertEqual(old['sections'],a['sections'])
            self.assertEqual(read_json(folder/'brief.json')['chapter_count'],3)
