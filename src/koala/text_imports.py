"""Readable inspiration text from local HTML, RTF and plain-text documents.

No browser, JavaScript execution, remote resources or external conversions.
"""
import codecs
import re
from html.parser import HTMLParser
from pathlib import Path

INSPIRATION_EXTENSIONS = ('.docx', '.pdf', '.rtf', '.txt', '.html', '.htm')
FORMAT_LABEL = 'DOCX, RTF, TXT, HTML or PDF'
MAX_TEXT_BYTES = 32 * 1024 * 1024


class ReadableHTML(HTMLParser):
    # Exclude executable content, metadata, embedded media and page furniture.
    SKIP = {'head','script','style','template','noscript','iframe','object','svg','canvas',
            'nav','footer','aside','form','pre','code'}
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    BLOCK = {'address','article','blockquote','br','dd','div','dl','dt','figcaption','figure',
             'h1','h2','h3','h4','h5','h6','hr','li','main','ol','p','section','table','td','th','tr','ul'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]; self.parts=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        hidden=('hidden' in attrs or attrs.get('aria-hidden','').lower()=='true' or
                re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',attrs.get('style',''),re.I))
        suppressed=bool((self.stack and self.stack[-1][1]) or tag in self.SKIP or hidden)
        if tag in self.BLOCK and not (self.stack and self.stack[-1][1]): self.parts.append('\n')
        if tag not in self.VOID: self.stack.append((tag,suppressed))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:];break
        if tag in self.BLOCK and not (self.stack and self.stack[-1][1]): self.parts.append('\n')

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]): self.parts.append(data)

    def text(self):
        return '\n'.join(line for raw in ''.join(self.parts).splitlines() if (line:=' '.join(raw.split())))


def decode_text(raw, html=False):
    if raw.startswith((codecs.BOM_UTF32_LE,codecs.BOM_UTF32_BE)): return raw.decode('utf-32'),'utf-32'
    if raw.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)): return raw.decode('utf-16'),'utf-16'
    if html:
        match=re.search(br'<meta\b[^>]*charset\s*=\s*["\']?\s*([a-zA-Z0-9_-]+)',raw[:8192],re.I)
        if match:
            encoding=match[1].decode('ascii')
            try: return raw.decode(encoding),encoding
            except (LookupError,UnicodeError): pass
    try: return raw.decode('utf-8-sig'),'utf-8'
    except UnicodeDecodeError: return raw.decode('cp1252'),'cp1252'


def text_paragraphs(path, report=None):
    path=Path(path)
    with path.open('rb') as stream: raw=stream.read(MAX_TEXT_BYTES+1)
    if len(raw)>MAX_TEXT_BYTES: raise ValueError('TXT, RTF and HTML inspiration files must be at most 32 MiB. Split this file before importing.')
    extension=path.suffix.lower()
    try:
        if extension=='.rtf':
            from striprtf.striprtf import rtf_to_text
            if not raw.lstrip().startswith(b'{\\rtf'): raise ValueError('Invalid RTF document: missing RTF header.')
            match=re.search(br'\\ansicpg(\d+)',raw[:4096])
            encoding='cp'+match[1].decode() if match else 'cp1252'
            # Preserve literal bytes through the declared RTF codepage; Unicode escapes
            # and font tables are handled by the RTF parser.
            text=rtf_to_text(raw.decode(encoding),encoding=encoding,errors='strict')
            text=text.encode('utf-16','surrogatepass').decode('utf-16')
        else:
            text,encoding=decode_text(raw,html=extension in ('.html','.htm'))
            if '\x00' in text: raise ValueError('This file contains binary data. Save it as plain text, HTML or RTF before importing.')
            if extension in ('.html','.htm'):
                parser=ReadableHTML();parser.feed(text);parser.close();text=parser.text()
    except (UnicodeError,LookupError) as exc:
        raise ValueError(f'Cannot decode {path.name}. Save the text as UTF-8 or re-export the RTF document.') from exc
    if report is not None:
        report.update(encoding=encoding, text_only=True)
        if extension in ('.html','.htm'): report['html_cleaned']=True
    prefix='html' if extension=='.htm' else extension[1:]
    for number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if line: yield f'{prefix}:line:{number}',line
