"""PDF export must preserve Unicode punctuation using an installed fallback."""
import tempfile
import unittest
from pathlib import Path
from koala.exporters import write_format

class PDFFontTests(unittest.TestCase):
    @unittest.skipUnless(Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf').exists(), 'macOS Unicode fallback font unavailable')
    def test_unicode_hyphen_falls_back_without_changing_text(self):
        from pypdf import PdfReader
        text='Arendt’s account: meaning‐making, Žižek, René, α.'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.pdf'
            write_format(path,[('title','Unicode font test'),('body',text)],'pdf')
            extracted=''.join(page.extract_text() for page in PdfReader(path).pages)
            self.assertIn(text,extracted)

    def test_missing_font_character_error_identifies_character(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'U\\+10FFFF'):
                write_format(Path(folder)/'sample.pdf',[('title','Unsupported \U0010ffff')],'pdf')
