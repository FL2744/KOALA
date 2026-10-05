"""Copy completed document analyses between projects without inference or credentials."""
import copy
import re
import shutil
import uuid
from pathlib import Path
from . import disclaimer_for
from .core import read_json, save
from .documents import FIELDS, merge, source_excerpt
from .pipeline import incorporate_inspiration


def completed_analyses(folder):
    folder = Path(folder).expanduser().resolve()
    if folder.is_file():
        folder = folder.parent
    documents = folder / 'documents'
    if not documents.is_dir():
        raise ValueError('That project has no document analyses.')
    results = []
    for path in sorted(documents.glob('*/*/analysis.json')):
        if not path.resolve().is_relative_to(documents.resolve()):
            continue
        manifest = read_json(path)
        if manifest.get('complete') is True:
            results.append((path, manifest))
    if not results:
        raise ValueError('No completed analyses found. Finish analysing a document in that project first.')
    return results


def validate_cache(path, manifest):
    digest = manifest.get('sha256', '')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('The saved analysis has an invalid document hash.')
    if manifest.get('complete') is not True:
        raise ValueError('Only completed analyses can be reused.')
    summary = manifest.get('digest')
    if not isinstance(summary, dict) or not isinstance(summary.get('overview'), str):
        raise ValueError('The saved analysis has no readable digest.')
    for field in FIELDS:
        values = summary.get(field)
        if not isinstance(values, list):
            raise ValueError(f'Invalid saved {field} list.')
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text']:
                raise ValueError('Invalid saved finding.')
            chunk = item.get('chunk', '')
            if not isinstance(chunk, str) or not re.fullmatch(r'c\d{6,}', chunk):
                raise ValueError('Invalid finding provenance.')
            chunk_path = path.parent/'chunks'/f'{chunk}.json'
            if not chunk_path.is_file() or not chunk_path.resolve().is_relative_to(path.parent.resolve()):
                raise ValueError('The saved analysis is missing its evidence cache.')
            record = read_json(chunk_path)
            text = record.get('text', '')
            if (not isinstance(text, str) or item.get('document_sha256') != digest or
                    not isinstance(item.get('id'), str) or
                    source_excerpt(item.get('evidence'), text) is None or
                    (field in ('authors', 'citations') and source_excerpt(item['text'], text) is None)):
                raise ValueError('The saved analysis has inconsistent evidence or provenance.')
    # Copy only the expected JSON artifacts; never follow links outside this cache.
    files = [path] + list((path.parent/'chunks').glob('*.json'))
    if (path.parent/'progress.json').exists():
        files.append(path.parent/'progress.json')
    if any(not f.resolve().is_relative_to(path.parent.resolve()) for f in files):
        raise ValueError('Analysis cache contains an external file link.')
    return files


def reuse_analyses(article, selected, folder, progress=print):
    folder = Path(folder).resolve()
    inspiration = copy.deepcopy(article.get('inspiration', {'documents': [], 'digest': None}))
    seen = {m['sha256'] for m in inspiration['documents']}
    pending = []
    for path, _ in selected:
        path = Path(path).resolve()
        if path.is_relative_to(folder):
            raise ValueError('Choose a different source project.')
        manifest = read_json(path)  # Recheck after menu selection.
        files = validate_cache(path, manifest)
        if manifest['sha256'] in seen:
            progress(f'Already incorporated: {manifest.get("name", "document")}')
            continue
        pending.append((path, manifest, files))
        seen.add(manifest['sha256'])
    if not pending:
        return article
    # Validate every selection before copying anything or revising the destination.
    for path, manifest, files in pending:
        cache = folder/'documents'/manifest['sha256']/('reused-' + uuid.uuid4().hex)
        cache.mkdir(parents=True)
        for source in files:
            target = cache/source.relative_to(path.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied = copy.deepcopy(manifest)
        copied['analysis_file'] = str(cache/'analysis.json')
        copied['reused_from'] = str(path)
        copied['disclaimer'] = disclaimer_for(article)
        save(cache/'analysis.json', copied)
        inspiration['documents'].append(copied)
        inspiration['digest'] = merge(None, inspiration['digest'], copied['digest'])
        progress(f'Reused {copied.get("name", "document")} — no model calls.')
    return incorporate_inspiration(article, inspiration, folder, progress)
