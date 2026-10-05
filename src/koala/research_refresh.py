"""Expand an existing ledger using cached research and targeted secondary searches."""
import copy
import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from . import disclaimer_for
from .core import read_json, save, validate_sources, audit
from .coverage import author_matches, author_coverage, citation_readiness, has_evidence
from .secondary import annotate, secondary_evidence
from .research import Crossref
from .primary import PrimaryDiscovery, identity


def key(source):
    return identity(source)


def expand_research(article, folder, progress=print, client=None, online=True, primary=None):
    import threading
    output_lock=threading.Lock()
    output=progress
    def report_progress(message):
        with output_lock:output(message)
    progress=report_progress
    real_client=client is None
    folder=Path(folder);article=copy.deepcopy(article);client=client or Crossref()
    names=article['brief'].get('important_authors',[])
    cache=folder/'research-cache';cache.mkdir(exist_ok=True)
    pool={}
    def add(records):
        for source in records:
            if not isinstance(source,dict) or not source.get('title') or not source.get('authors') or not source.get('year'):continue
            k=key(source)
            if k not in pool:pool[k]=copy.deepcopy(source)
            else:
                for field in ('abstract','notes','passages','references','access_links','access_status','author_aliases','identity_provenance','identity_warning','identity_review_required'):
                    if source.get(field) and not pool[k].get(field):pool[k][field]=source[field]
    add(article.get('sources',[]))
    for path in sorted(cache.glob('*.json')):
        data=read_json(path)
        if isinstance(data,list): add(data)
    progress(f'Recovered {len(pool)} distinct research records from the existing cache.')
    warnings=[]
    if online and (real_client or primary is not None):
        injected=primary is not None
        primary=primary or PrimaryDiscovery(cache,progress)
        topic=article['brief'].get('topic','')+' '+article['brief'].get('research_guidance','')
        if not injected and len(names)>1:
            from concurrent.futures import ThreadPoolExecutor
            # Overlap independent services; PrimaryDiscovery throttles shared public endpoints.
            workers=ThreadPoolExecutor(max_workers=3)
            try:
                for index,(name,records) in enumerate(zip(names,workers.map(lambda n:primary.author(n,topic),names)),1):
                    add(records);progress(f'Primary works searched: {index}/{len(names)} ({name}).')
            finally:
                workers.shutdown(wait=True,cancel_futures=True)
        else:
            for index,name in enumerate(names,1):
                progress(f'Finding primary works {index}/{len(names)}: {name}…')
                add(primary.author(name,topic))
        warnings.extend(primary.warnings)
        ambiguous=getattr(primary,'ambiguous',set())
        if isinstance(ambiguous,set):
            for source in pool.values():
                if source.get('gutenberg_id') and any(author_matches(name,source) for name in ambiguous):
                    source['identity_review_required']=True
                    source['identity_warning']='Same-name author unresolved. These excerpts do not count as primary evidence until identity is verified.'
    def supported(name):
        return any(has_evidence(s) and (author_matches(name,s) or secondary_evidence(name,s)) for s in pool.values())
    missing=[name for name in names if not supported(name)]
    progress(f'Primary/secondary evidence leads available for {len(names)-len(missing)} of {len(names)} required authors; searching the remaining {len(missing)}.')
    if online:
        for index,name in enumerate(missing,1):
            progress(f'Secondary literature {index}/{len(missing)}: {name}…')
            # Cache both successes and empty results; restart never repeats completed queries.
            digest=hashlib.sha256(('secondary-abstract-v1'+name).encode()).hexdigest()
            path=cache/(digest+'.json')
            try:
                if path.exists(): records=read_json(path)
                else:
                    records=client.secondary(name,rows=50);save(path,records);time.sleep(.35)
                add(records)
            except (RuntimeError,OSError,ValueError) as exc:
                warnings.append(f'{name}: {exc}');progress(f'Search unavailable for {name}; continuing with saved records.')
    terms=set(re.findall(r'\w{5,}',(article['brief'].get('topic','')+' '+article['brief'].get('research_guidance','')).casefold()))-{'their','there','which','these','those','about','would','should','could','human','study','research','author','authors','chapter','chapters','writing','write','scholarly','project','ideas'}
    def rank(s):
        text=(s['title']+' '+s.get('abstract','')+' '+s.get('notes','')).casefold()
        overlap=sum(term in text for term in terms)
        return (-overlap,0 if s.get('abstract') else 1,key(s))
    chosen={key(s) for s in article.get('sources',[])}
    for name in names:
        matches=sorted((s for s in pool.values() if has_evidence(s) and (author_matches(name,s) or secondary_evidence(name,s))),key=rank)
        chosen.update(key(s) for s in matches[:3])
        primary_matches=sorted((s for s in pool.values() if author_matches(name,s)),key=lambda s:(not has_evidence(s),*rank(s)))
        chosen.update(key(s) for s in primary_matches[:3])
    # Add supported topic matches as candidates, not unrelated filler merely to hit a number.
    goal=article['brief'].get('citation_target') or 75
    count=sum(has_evidence(pool[k]) for k in chosen)
    for source in sorted(pool.values(),key=rank):
        if count>=goal:break
        k=key(source)
        if k not in chosen and has_evidence(source) and -rank(source)[0]>=2:
            chosen.add(k);count+=1
    sources=copy.deepcopy(article.get('sources',[]));by_key={key(s):s for s in sources}
    next_id=max((int(s['id'][1:]) for s in sources),default=0)+1
    for k in sorted(chosen):
        incoming=pool[k]
        if k in by_key:
            source=by_key[k]
            for field in ('abstract','notes','passages','references','access_links','access_status','author_aliases','identity_provenance','identity_warning','identity_review_required'):
                if incoming.get(field) and not source.get(field):source[field]=incoming[field]
        else:
            source=copy.deepcopy(incoming);source['id']=f'S{next_id:03}';next_id+=1
            source['relevance_status']='Candidate: review identity, relevance, and claims against source text.'
            sources.append(source)
        annotate(names,source)
    validate_sources(sources)
    article['sources']=sources
    article['warnings']=list(dict.fromkeys(article.get('warnings',[])+warnings))
    article.pop('citation_repair',None)
    if article.get('sections'): article['stage']='citation_review'
    before=citation_readiness(read_json(folder/'article.json')) if (folder/'article.json').exists() else {}
    report=citation_readiness(article)
    snapshot=folder/'revisions'/('research-'+uuid.uuid4().hex);snapshot.mkdir(parents=True)
    for name in ('article.json','sources.json','citation-coverage.json','audit.json'):
        if (folder/name).exists():shutil.copy2(folder/name,snapshot/name)
    article.setdefault('research_history',[]).append(str(snapshot))
    article['research_engine_version']=3
    article['audit']=audit(article) if article.get('sections') else article.get('audit',{})
    summary={'disclaimer':disclaimer_for(article),'before_supported':len(before.get('supported_source_ids',[])),
             'supported_sources':len(report['supported_source_ids']),'total_sources':len(sources),
             'authors_with_supported_sources':sum(bool(r['supported_ids']) for r in report['authors']),
             'required_authors':len(report['authors']),
             'primary_catalog_authors':sum(bool(r['primary_ids']) for r in report['authors']),
             'primary_supported_authors':sum(bool(set(r['primary_ids']) & set(r['supported_ids'])) for r in report['authors']),
             'primary_unresolved_authors':[r['author'] for r in report['authors'] if not set(r['primary_ids']) & set(r['supported_ids'])],
             'secondary_covered_authors':sum(bool(r['secondary_ids']) for r in report['authors']),
             'unresolved_authors':[r['author'] for r in report['authors'] if not r['supported_ids']],
             'note':'Coverage is based on retrieved primary/secondary text. Review identities and relevance; metadata matching is not a scholarly quality assessment.',
             'warnings':warnings,'original_checkpoint':str(snapshot)}
    article['research_expansion']=summary
    save(folder/'sources.json',{'disclaimer':disclaimer_for(article),'sources':sources})
    save(folder/'article.json',article)
    save(folder/'citation-coverage.json',dict(report,disclaimer=disclaimer_for(article)))
    save(folder/'research-expansion.json',summary)
    progress(f'Research expanded: {summary["authors_with_supported_sources"]}/{summary["required_authors"]} authors have primary or secondary evidence leads; {summary["supported_sources"]} sources have supporting text.')
    progress(f'Primary works: {summary["primary_catalog_authors"]}/{len(names)} authors have records; {summary["primary_supported_authors"]}/{len(names)} have supporting primary text or abstracts.')
    if summary['unresolved_authors']:progress('Still unresolved: '+'; '.join(summary['unresolved_authors']))
    return article
