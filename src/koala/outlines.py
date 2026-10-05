"""Local outline import: preserve user structure without an inference call."""
import re
from pathlib import Path

MAX_OUTLINE_CHARS = 60000


def chapter_titles(text):
    titles=[]
    for line in text.splitlines():
        match=re.match(r'^\s*(?:#{1,3}\s*)?(?:chapter\s+(?:\d+|[ivxlcdm]+)\b\s*[:.\-–—]?\s*|\d+[.)]\s+)(.+?)\s*$',line,re.I)
        if not match: continue
        title=re.sub(r'(?:\.{2,}|\t+| {2,})\s*\d+\s*$','',match[1]).strip()
        if title and not re.match(r'^(?:introduction|afterword|appendix)\b',title,re.I): titles.append(title)
    return titles


def outline_extras(text):
    result = {'appendices': []}
    for line in text.splitlines():
        line = re.sub(r'^\s*(?:#{1,3}\s*)?(?:\d+[.)]\s+)?','',line).strip()
        line = re.sub(r'(?:\.{2,}|\t+| {2,})\s*\d+\s*$','',line).strip()
        for kind in ('introduction','afterword'):
            if re.match(r'^'+kind+r'(?:\s*[:.\-–—]|$)',line,re.I): result[kind]=line
        match = re.match(r'^Appendix(?:\s+[A-Z0-9]+)?\s*[:.\-–—]\s*(.+)$',line,re.I)
        if match: result['appendices'].append(match[1].strip())
    return result


def validate_outline(text):
    if not isinstance(text,str): raise ValueError('Chapter outline must be text.')
    if len(text)>MAX_OUTLINE_CHARS:
        raise ValueError('Chapter outline exceeds 60,000 characters. Import just the table of contents or outline.')
    titles=chapter_titles(text)
    if len(titles)>30: raise ValueError('An uploaded outline supports at most 30 main chapters.')
    if len(set(t.casefold() for t in titles)) != len(titles):
        raise ValueError('The outline contains duplicate chapter titles. Edit the outline to give each chapter a distinct title.')
    if any(len(t)>1500 for t in titles): raise ValueError('Chapter titles must be at most 1,500 characters.')
    return titles


def read_outline(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file(): raise ValueError(f'Outline file not found: {path}')
    ext=path.suffix.lower()
    if ext in ('.docx','.pdf'):
        from .documents import docx_paragraphs, pdf_paragraphs
        parts=[];size=0
        for location,text in (docx_paragraphs(path) if ext=='.docx' else pdf_paragraphs(path)):
            size+=len(text)+1
            if size>MAX_OUTLINE_CHARS: raise ValueError('Chapter outline exceeds 60,000 characters. Import just the table of contents or outline.')
            parts.append(text)
        text='\n'.join(parts)
    elif ext in ('.txt','.md'):
        with path.open(encoding='utf-8-sig') as stream: text=stream.read(MAX_OUTLINE_CHARS+1)
    else: raise ValueError('Outline formats: DOCX, PDF, TXT, or Markdown (.md).')
    text=text.strip()
    if not text: raise ValueError('No outline text found. Scanned PDFs need OCR before import.')
    titles=validate_outline(text)
    return {'text':text,'name':path.name,'chapter_titles':titles,
            'chapter_count':len(titles) if titles else None}
