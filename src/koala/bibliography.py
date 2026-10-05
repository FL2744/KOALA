"""Local bibliography intake. Imported text is a research lead, never evidence."""
import re
from pathlib import Path
from .core import cited_ids, save
from .coverage import has_evidence

MAX_CHARS = 180000
MAX_REFERENCES = 1000


def references(text):
    if not isinstance(text, str) or len(text) > MAX_CHARS:
        raise ValueError('Bibliographies support up to 180,000 characters.')
    # Blank lines delimit references; wrapped lines within a reference stay together.
    entries = [' '.join(block.split()) for block in re.split(r'\n\s*\n', text.strip())]
    result, seen = [], set()
    for entry in entries:
        key = entry.casefold()
        if entry and key not in seen:
            result.append(entry); seen.add(key)
    if not result:
        raise ValueError('No references found. Add one reference per block, separated by a blank line.')
    if len(result) > MAX_REFERENCES:
        raise ValueError('Import at most 1,000 references at a time.')
    if any(len(entry) > 4000 for entry in result):
        raise ValueError('A reference exceeds 4,000 characters. Separate references with blank lines in the preview.')
    return result


def read_bibliography(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file(): raise ValueError(f'Bibliography not found: {path}')
    ext = path.suffix.lower()
    if ext in ('.docx', '.pdf'):
        from .documents import docx_paragraphs, pdf_paragraphs
        parts, size = [], 0
        for _, text in (docx_paragraphs(path) if ext == '.docx' else pdf_paragraphs(path)):
            size += len(text) + 2
            if size > MAX_CHARS: raise ValueError('Bibliography exceeds 180,000 characters. Import a smaller bibliography.')
            parts.append(text.strip())
        text = '\n\n'.join(parts)
    elif ext in ('.txt', '.md'):
        with path.open(encoding='utf-8-sig') as stream: text = stream.read(MAX_CHARS + 1)
        if len(text) > MAX_CHARS: raise ValueError('Bibliography exceeds 180,000 characters.')
        # A single-spaced list is common in plain-text exports.
        if not re.search(r'\n\s*\n', text.strip()):
            text = '\n\n'.join(line.strip() for line in text.splitlines() if line.strip())
    else: raise ValueError('Bibliography formats: DOCX, text-based PDF, TXT, or Markdown (.md).')
    if not text.strip(): raise ValueError('No bibliography text found. Scanned PDFs need OCR before import.')
    # Preserve extraction for review, including ambiguous PDF line breaks.
    return {'text': text.strip(), 'name': path.name,
            'note': 'Separate references with a blank line. Remove headings and join wrapped references before importing. PDF layout may require editing.'}


def import_bibliography(menu, text, mode='replan'):
    if mode not in ('replan', 'repair'): raise ValueError('Choose replan or repair for bibliography import.')
    entries = references(text)
    brief = menu.brief()
    # A curated source file bypasses discovery; do not silently ignore imported leads.
    if brief.get('sources_file'):
        raise ValueError('This project uses a curated source ledger, which bypasses reference discovery. Clear Curated source ledger path in Brief before importing research candidates.')
    existing = brief.get('possible_citations', [])
    seen = {' '.join(x.split()).casefold() for x in existing}
    additions = [x for x in entries if x.casefold() not in seen]
    if not additions:
        menu.write('These references are already in this project. No changes made.')
        return
    combined = existing + additions
    if len(combined) > MAX_REFERENCES or sum(len(x) + 2 for x in combined) > MAX_CHARS:
        raise ValueError('The combined candidate bibliography exceeds 1,000 references or 180,000 characters. Edit Possible citations in Brief first.')
    brief['possible_citations'] = combined
    menu.save_brief(brief, force_replan=(mode == 'replan'))
    article = menu.checkpoint()
    if article and mode == 'repair' and article.get('sections'):
        article['bibliography_research_pending'] = True
        save(menu.folder/'article.json', article)
    menu.write(f'Added {len(additions)} reference candidates. Research will check their metadata and relevance; importing does not mark them as cited or verified.')


def bibliography_view(brief, article):
    article = article or {}
    cited = set(cited_ids('\n\n'.join(s.get('text','') for s in article.get('sections',[]))))
    return {'candidates': brief.get('possible_citations', []),
            'sources': [{**s, 'cited': s['id'] in cited, 'has_evidence': has_evidence(s)}
                        for s in (article.get('sources') or article.get('inherited_sources', []))]}
