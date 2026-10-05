import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter
from koala.documents import paragraphs, chunks, analyse_document
from koala.core import read_json, save
from koala.menu import Menu, read_inputs
from test_documents import DocumentProvider, InspirationPipelineTests as BasePipelineTests
from test_menu import scripted, project_fixture


def write_pdf(path, pages):
    canvas = Canvas(str(path))
    for text in pages:
        if text:
            obj = canvas.beginText(50, 750)
            for line in text.splitlines():
                obj.textLine(line)
            canvas.drawText(obj)
        canvas.showPage()
    canvas.save()
    return path


class PDFPipelineTests(BasePipelineTests):
    # Run the established early/late import and revision contract against PDF inputs.
    def setup_run(self, d):
        base, brief, old = super().setup_run(d)
        path = write_pdf(base/'inspiration.pdf', ['Memory connects people. Scholar (2020).'])
        return base, brief, path


# Avoid collecting the imported base class a second time.
del BasePipelineTests


class PDFExtractionTests(unittest.TestCase):
    def test_page_provenance_and_empty_page_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_pdf(Path(d)/'input.PDF', ['First page Scholar (2020).', '', 'Third page'])
            report = {}
            result = list(paragraphs(path, report))
            self.assertEqual([p for p, _ in result], ['pdf:page:1', 'pdf:page:3'])
            self.assertEqual(report, {'page_count': 3, 'pages_without_text': [2]})
            messages = []
            manifest = analyse_document(DocumentProvider(), path, d, messages.append)
            self.assertEqual(manifest['extraction'], report)
            self.assertTrue(any('Warning' in m for m in messages))

    def test_large_pdf_chunking_and_cached_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_pdf(Path(d)/'large.pdf', ['Memory connects people. Scholar (2020).\n'*50]*20)
            parts = list(chunks(path))
            self.assertGreater(len(parts), 3)
            self.assertTrue(all(len(p['text']) <= 6000 for p in parts))
            rebuilt = parts[0]['text']
            for previous, current in zip(parts, parts[1:]):
                rebuilt += current['text'][previous['end']-current['start']:]
            self.assertEqual(rebuilt, ''.join(f'[{loc}]\n{text}\n' for loc, text in paragraphs(path)))
            provider = DocumentProvider()
            with patch('koala.documents.merge', side_effect=RuntimeError('Interrupted combination')):
                with self.assertRaises(RuntimeError):
                    analyse_document(provider, path, d, lambda _: None)
            self.assertEqual(provider.calls, 1)
            manifest = analyse_document(provider, path, d, lambda _: None)
            self.assertEqual(sum(e == 'analyse' for e, _ in provider.events), len(parts))
            calls = provider.calls
            self.assertEqual(analyse_document(provider, path, d), manifest)
            self.assertEqual(provider.calls, calls)

    def test_empty_pdf_requires_ocr_without_model_calls(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_pdf(Path(d)/'empty.pdf', [''])
            provider = DocumentProvider()
            with self.assertRaisesRegex(ValueError, 'OCR'):
                analyse_document(provider, path, d)
            self.assertEqual(provider.calls, 0)

    def test_corrupt_and_password_protected_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'bad.pdf'
            path.write_bytes(b'%PDF-1.7\nbroken')
            with self.assertLogs('pypdf', level='WARNING'), self.assertRaisesRegex(ValueError, 'Cannot read PDF'):
                list(paragraphs(path))
            plain = write_pdf(Path(d)/'plain.pdf', ['Memory'])
            writer = PdfWriter()
            writer.append(PdfReader(plain))
            writer.encrypt('secret')
            writer.write(path)
            with self.assertRaisesRegex(ValueError, 'unlocked copy'):
                list(paragraphs(path))

    def test_menu_and_brief_paths_accept_pdf(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            folder = Path(d)
            brief = project_fixture(folder)
            path = write_pdf(folder/'inspiration.pdf', ['Memory connects people.'])
            for field in ('source_files', 'inspiration_files'):
                changed = {**brief, field: [path.name]}
                _, documents = read_inputs(changed, folder)
                self.assertEqual(documents, [str(path.resolve())])
            menu = Menu(read=scripted([str(path), '']), write=lambda _: None,
                        provider_factory=lambda *args: DocumentProvider())
            menu.open_project(folder)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('koala.cli.Provider', return_value=DocumentProvider()):
                menu.import_documents()
            article = read_json(folder/'article.json')
            self.assertEqual(article['inspiration']['documents'][0]['format'], 'pdf')
            self.assertEqual(article['stage'], 'planning')
