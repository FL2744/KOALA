import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.documents import paragraphs, chunks, analyse_document
from koala.text_imports import ReadableHTML
from koala.menu import read_inputs
from koala.core import normalize_brief
from test_documents import DocumentProvider


class TextImportsTests(unittest.TestCase):
    def text(self, path): return '\n'.join(t for _,t in paragraphs(path))

    def test_html_cleans_executable_and_hidden_content(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.html'
            path.write_text('''<!doctype html><html><head><title>Site</title><script>head_secret</script><style>.a{color:red}</style></head>
            <body><nav>nav_secret</nav><main><h1>Memory &amp; place</h1><p>First <em>important</em> idea.</p>
            <script>const secret = "<p>javascript_secret</p>";</script><style>style_secret</style><!--comment_secret-->
            <div hidden><p>hidden_secret</p></div><span style="display:none !important">css_secret</span>
            <div aria-hidden="true">aria_secret</div><template>template_secret</template>
            <pre><code>code_secret</code></pre><iframe src="https://example.invalid">frame_secret</iframe>
            <object>object_secret</object><svg><text>svg_secret</text></svg><p onclick="event_secret()">Second&nbsp;idea.</p>
            <table><tr><td>Author</td><td>Work</td></tr></table></main><footer>footer_secret</footer></body></html>''')
            text=self.text(path)
            self.assertIn('Memory & place',text);self.assertIn('First important idea.',text)
            self.assertIn('Second idea.',text);self.assertIn('Author\nWork',text)
            self.assertNotIn('secret',text);self.assertNotIn('<',text);self.assertNotIn('color:red',text)

    def test_html_entities_encodings_and_unclosed_script(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.htm'
            path.write_bytes(b'<meta charset="windows-1252"><p>Ren\xe9e &amp; memory</p><script>ignored forever')
            self.assertEqual(self.text(path),'Renée & memory')

    def test_plain_text_utf16_and_large_chunking(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.txt';path.write_text('Renée and memory.\nSecond paragraph.',encoding='utf-16')
            self.assertIn('Renée and memory.',self.text(path))
            path.write_text('START '+('memory and place '*4000)+' END',encoding='utf-8')
            data=list(chunks(path));self.assertGreater(len(data),5)
            self.assertTrue(all(len(c['text'])<=6000 for c in data));self.assertIn('END',data[-1]['text'])

    def test_rtf_formatting_unicode_and_embedded_objects(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.rtf'
            path.write_text(r"{\rtf1\ansi\ansicpg1252{\fonttbl{\f0 font_secret;}}Ren\'e9e \b studies\b0  memory.\par Unicode: \u945?{\pict picture_secret}{\*\generator generator_secret;}}",encoding='ascii')
            text=self.text(path)
            self.assertIn('Renée studies memory.',text);self.assertIn('α',text)
            self.assertNotIn('secret',text);self.assertNotIn('\\rtf',text)
            path.write_text('Not RTF')
            with self.assertRaisesRegex(ValueError,'Invalid RTF'): self.text(path)

    def test_limits_and_binary_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.txt';path.write_bytes(b'ab\x00cd')
            with self.assertRaisesRegex(ValueError,'binary'): self.text(path)
            with patch('koala.text_imports.MAX_TEXT_BYTES',2):
                with self.assertRaisesRegex(ValueError,'32 MiB'): self.text(path)

    def test_formats_enter_inspiration_and_rich_source_paths(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            for ext in ('txt','rtf','html','htm'): (base/f'input.{ext}').write_text('Memory')
            brief=normalize_brief({'inspiration_files':[f'input.{ext}' for ext in ('txt','rtf','html','htm')]})
            self.assertEqual(len(read_inputs(brief,base)[1]),4)
            brief=normalize_brief({'source_files':['input.html','input.rtf','input.txt']})
            excerpts,docs=read_inputs(brief,base)
            self.assertEqual(len(docs),2);self.assertEqual(len(excerpts),1)

    def test_html_analysis_only_sends_clean_text_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reading.html';folder=Path(d)/'project'
            path.write_text('<p>Memory connects people.</p><script>'+('secretJavascript();'*10000)+'</script>')
            provider=DocumentProvider();seen=[];original=provider.json
            def inspect(system,prompt):
                seen.append(prompt);self.assertNotIn('secretJavascript',prompt)
                return original(system,prompt)
            provider.json=inspect
            result=analyse_document(provider,path,folder,lambda _:None)
            self.assertTrue(result['complete']);self.assertEqual(result['chunk_count'],1)
            self.assertTrue(result['extraction']['html_cleaned'])
            calls=len(seen);analyse_document(provider,path,folder,lambda _:None);self.assertEqual(len(seen),calls)
