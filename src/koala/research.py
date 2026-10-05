"""Crossref discovery; never ask a language model to invent bibliography records."""
import html
import os
import math
from itertools import zip_longest
from . import is_book
import re
from urllib.parse import quote, urlencode
from .providers import request_json
from .core import validate_sources


def clean(text):
    return html.unescape(re.sub('<[^>]+>', '', text or '')).strip()


def normalize(item):
    parts = item.get('published', item.get('issued', {})).get('date-parts', [[None]])
    return {'title': clean(' '.join(item.get('title', []))),
            'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) or a.get('name', '')
                        for a in item.get('author', [])],
            'year': str(parts[0][0]) if parts and parts[0] and parts[0][0] else '',
            'container': clean(' '.join(item.get('container-title', []))),
            'volume': item.get('volume', ''), 'issue': item.get('issue', ''),
            'pages': item.get('page', ''), 'publisher': item.get('publisher', ''),
            'doi': item.get('DOI', '').lower(), 'abstract': clean(item.get('abstract', '')),
            'type': item.get('type','article-journal'),
            'references': item.get('reference',[]),
            'author_names': [{k:a[k] for k in ('given','family') if a.get(k)} if a.get('family') else {'literal':a.get('name','')} for a in item.get('author',[])],
            'notes': '', 'provenance': 'Crossref metadata', 'verification': 'metadata-only'}


class Crossref:
    def query(self, query, rows=20):
        params = {'query.bibliographic': query, 'rows': rows}
        if os.environ.get('CROSSREF_MAILTO'):
            params['mailto'] = os.environ['CROSSREF_MAILTO']
        result = request_json('https://api.crossref.org/works?' + urlencode(params), timeout=60)
        return [normalize(item) for item in result['message']['items']]

    def primary(self, name, rows=50):
        from .coverage import author_matches
        params={'query.author':name,'rows':rows}
        if os.environ.get('CROSSREF_MAILTO'):params['mailto']=os.environ['CROSSREF_MAILTO']
        data=request_json('https://api.crossref.org/works?'+urlencode(params),timeout=30)
        found=[]
        for item in data['message']['items']:
            source=normalize(item)
            if not author_matches(name,source):continue
            source['access_status']='Source abstract available; full text not retrieved' if source.get('abstract') else 'Metadata only; follow publisher access link'
            source['access_links']=[{'label':'Publisher / DOI','url':'https://doi.org/'+source['doi']}]
            found.append(source)
        return found

    def secondary(self, name, rows=50):
        params={'query':name,'filter':'has-abstract:true','rows':rows}
        if os.environ.get('CROSSREF_MAILTO'): params['mailto']=os.environ['CROSSREF_MAILTO']
        result=request_json('https://api.crossref.org/works?'+urlencode(params),timeout=45)
        return [normalize(item) for item in result['message']['items']]

    def doi(self, doi):
        result = request_json('https://api.crossref.org/works/' + quote(doi, safe=''), timeout=60)
        return normalize(result['message'])


def discover(brief, plan, crossref=None, openlibrary=None, progress=None, cache_dir=None, primary=None):
    from .coverage import author_matches
    from .secondary import secondary_evidence, annotate
    from .core import read_json, save
    from pathlib import Path
    import hashlib
    real_client = crossref is None
    crossref = crossref or Crossref()
    library = openlibrary if openlibrary is not None else (OpenLibrary() if real_client else None)
    progress = progress or (lambda message: None)
    def cached(kind, query, call):
        key=hashlib.sha256((kind+query).encode()).hexdigest()
        path=Path(cache_dir)/(key+'.json') if cache_dir else None
        if path and path.exists(): return read_json(path)
        records=call()
        if path: save(path,records)
        return records
    from .primary import PrimaryDiscovery, identity
    primary = primary or (PrimaryDiscovery(cache_dir, progress) if real_client else None)
    found, warnings, seen = [], [], set()
    if is_book(brief):
        groups = (plan['search_queries'], brief['possible_citations'], brief['important_authors'],
                  brief.get('similar_books', []), brief['similar_articles'])
        queries = list(dict.fromkeys(brief['important_authors'] + [x for row in zip_longest(*groups) for x in row if x]))
        planned_rows = min(100, max(25, math.ceil(brief['citation_target'] * 2 / max(1, len(plan['search_queries'])))))
    else:
        queries = list(dict.fromkeys(brief['important_authors'] + brief['possible_citations'] +
                                    brief['similar_articles'] + plan['search_queries']))
        planned_rows = 25
    for query in queries:
        progress(f'Researching {queries.index(query)+1}/{len(queries)}: {query}')
        match = re.search(r'10\.\d{4,9}/\S+', query)
        try:
            rows = planned_rows if query in plan['search_queries'] else 25
            records = cached('crossref-'+str(rows), query, lambda: [crossref.doi(match.group().rstrip('.,'))] if match else crossref.query(query, rows))
        except RuntimeError as exc:
            warnings.append(f"Search failed for {query!r}: {exc}")
            records = []
        if query in brief['important_authors']:
            if primary:
                records += primary.author(query,brief.get('topic','')+' '+brief.get('research_guidance',''))
            records = [r for r in records if author_matches(query,r) or secondary_evidence(query,r)]
            if library and not primary and not any(r.get('abstract') or r.get('notes') for r in records):
                try:
                    records += cached('openlibrary',query,lambda:library.author(query))
                except RuntimeError as exc:
                    warnings.append(f'Book search failed for {query!r}: {exc}')
            if not any(r.get('abstract') or r.get('notes') for r in records) and hasattr(crossref,'secondary'):
                try:
                    secondary=cached('secondary-abstract-v1',query,lambda:crossref.secondary(query))
                    records += [r for r in secondary if secondary_evidence(query,r)]
                except RuntimeError as exc: warnings.append(f'Secondary search failed for {query}: {exc}')
            if not records: warnings.append(f'No matching primary or secondary source found for {query}.')
        for record in records:
            key = identity(record)
            if key in seen or not record['title'] or not record['authors'] or not record['year']:
                continue
            seen.add(key)
            record['id'] = f'S{len(found)+1:03}'
            record['discovered_by'] = query
            found.append(annotate(brief['important_authors'],record))
    if primary: warnings.extend(primary.warnings)
    if len(found) < brief['citation_target']:
        warnings.append(f"Discovered {len(found)} candidate works for a target of {brief['citation_target']}; consider a curated source ledger.")
    return validate_sources(found), warnings

class OpenLibrary:
    """Edition-specific book metadata for authors poorly represented in Crossref."""
    def author(self, name):
        import time
        from .coverage import same_author
        params = urlencode({'author':name,'fields':'key,title,author_name,editions,editions.key','limit':5})
        time.sleep(1.05)
        data = request_json('https://openlibrary.org/search.json?'+params, timeout=60)
        found=[]
        for work in data.get('docs', []):
            if not any(same_author(name,a) for a in work.get('author_name', [])): continue
            for edition in work.get('editions', {}).get('docs', [])[:1]:
                key=edition.get('key','')
                if not re.fullmatch(r'/books/OL\d+M',key): continue
                time.sleep(1.05)  # Open Library's public, unidentified-client rate limit.
                record=request_json('https://openlibrary.org'+key+'.json', timeout=60)
                year=re.search(r'\b\d{4}\b',record.get('publish_date',''))
                if not year: continue
                # Metadata alone is deliberately not promoted to supporting evidence.
                found.append({'title':record.get('title') or work['title'], 'authors':work['author_name'],
                    'year':year[0], 'publisher':'; '.join(record.get('publishers',[])), 'type':'book',
                    'edition':record.get('edition_name',''), 'isbn':next(iter(record.get('isbn_13',[])),''),
                    'url':'https://openlibrary.org'+key, 'doi':'','abstract':'','notes':'',
                    'provenance':'Open Library edition metadata', 'verification':'metadata-only'})
            if len(found)>=3: break
        return found
