from .coverage import record_coverage_shortfall
"""Resumable citation repair that archives the original manuscript before editing."""
import copy
import json
import shutil
import uuid
from pathlib import Path
from .core import read_json, save, normalize_brief, prose_words, cited_ids, validate_sources
from .coverage import resolve_authors, require_ready, citation_readiness, section_budget, coverage_issues, require_complete, has_evidence
from .citations import locator_issues
from . import disclaimer_for


def repair_citations(provider, article, folder, no_research=False, progress=print):
    from .pipeline import system_for, continue_prepare, source_context
    SYSTEM = system_for(article['brief'])
    from .books import select_context_sources, normalize_citation_groups, section_issues
    folder=Path(folder)
    if not article.get('sections'):
        raise ValueError('Draft manuscript sections before using Repair citations.')
    if not article.get('citation_repair'):
        revision=folder/'revisions'/('citations-'+uuid.uuid4().hex)
        revision.mkdir(parents=True)
        for name in ('article.json','brief.json','sources.json','audit.json'):
            if (folder/name).exists(): shutil.copy2(folder/name, revision/name)
        for stem in ('article','manuscript','abstract'):
            for ext in ('docx','pdf','html','txt','rtf'):
                if (folder/f'{stem}.{ext}').exists(): shutil.copy2(folder/f'{stem}.{ext}',revision/f'{stem}.{ext}')
        article['citation_repair']={'archive':str(revision),'processed':0,'research_done':False}
        progress(f'Original manuscript preserved in {revision}')
    state=article['citation_repair']
    article['brief']=normalize_brief(resolve_authors(article['brief'], article.get('brief_directory',folder)))
    article['stage']='citation_review'
    # User-edited ledger data can resolve evidence gaps without repeating discovery.
    ledger=article['brief'].get('sources_file')
    path=(Path(article.get('brief_directory',folder))/ledger) if ledger else folder/'sources.json'
    if path.exists():
        raw=read_json(path);incoming=validate_sources(raw.get('sources',[]) if isinstance(raw,dict) else raw)
        existing={s['id']:s for s in article['sources']}
        by_key={(s.get('doi') or s['title']).casefold():s for s in article['sources']}
        next_id=max((int(s['id'][1:]) for s in article['sources']),default=0)+1
        for source in incoming:
            key=(source.get('doi') or source['title']).casefold()
            if key in by_key:
                by_key[key].update({k:v for k,v in source.items() if k!='id' and v})
            else:
                source=dict(source,id=f'S{next_id:03}');next_id+=1
                article['sources'].append(source);by_key[key]=source
    save(folder/'article.json',article)
    if not no_research and not state['research_done'] and (citation_readiness(article)['blockers'] or article.get('bibliography_research_pending')):
        working=copy.deepcopy(article);working['stage']='planned';working['inherited_sources']=copy.deepcopy(article['sources'])
        # Explicit curated ledgers stay authoritative; otherwise refresh discovery.
        try:
            working=continue_prepare(provider,working,folder,Path(article.get('brief_directory',folder)),False,progress,research_only=True)
        except BaseException:
            # Research caches survive; the live manuscript remains intact on failure.
            save(folder/'article.json',article)
            raise
        article['sources']=working['sources'];article['warnings']=working.get('warnings',[])
    state['research_done']=True
    article.pop('bibliography_research_pending',None)
    save(folder/'article.json',article)
    save(folder/'sources.json',{'disclaimer':disclaimer_for(article),'sources':article['sources']})
    require_ready(article,folder)
    for index in range(state['processed'],len(article['sections'])):
        section=article['sections'][index]
        context_article={**article,'sections':article['sections'][:index]}
        query=section['heading']+' '+article['plan']['sections'][index].get('purpose','')
        budget=section_budget(context_article,index,query)
        original=section['text']
        supported={s['id'] for s in article['sources'] if has_evidence(s)}
        invalid=set(cited_ids(original))-supported
        if not coverage_issues(original,budget) and not locator_issues(original,article['sources']) and not invalid:
            state['processed']=index+1;save(folder/'article.json',article);continue
        sources=select_context_sources(context_article,index,query)
        present={s['id'] for s in sources}
        sources += [s for s in article['sources'] if s['id'] in set(cited_ids(original)) & supported and s['id'] not in present]
        allowed={s['id'] for s in sources};count=prose_words(original)
        prompt=('Repair citation coverage in this manuscript section. Preserve effective prose, its argument, qualifications, and heading. '
                'Integrate substantive discussion supported by the supplied evidence for the citation budget; do not append a reference dump. '
                'Preserve valid existing citations and their relationships; replace unsupported claims only with evidence-supported analysis. '
                f'Keep approximately {count} prose words (80–120%). Use [@S001] or supplied passage IDs [@S001#P1]. Return complete prose only.\n'+
                json.dumps({'original':original,'brief':article['brief'],'abstract':article['abstract'],
                            'section':article['plan']['sections'][index], 'citation_budget':budget,
                            'sources':source_context(sources)},ensure_ascii=False))
        progress(f'Repairing citations: section {index+1}/{len(article["sections"])} — {section["heading"]}')
        text,issues='',[]
        attempt_folder=folder/'citation-repair-attempts'/f'section-{index+1:04}'/uuid.uuid4().hex
        for attempt in range(3):
            correction=('\nCorrect these issues: '+' '.join(issues)+'\n'+text) if attempt else ''
            text=normalize_citation_groups(provider.generate(SYSTEM,prompt+correction))
            issues=section_issues(text,int(.8*count),int(1.2*count),allowed)+locator_issues(text,sources)
            lost=(set(cited_ids(original)) & supported)-set(cited_ids(text))
            if lost: issues.append('Preserve existing supported citations: '+', '.join(sorted(lost)))
            save(attempt_folder/f'attempt-{attempt+1}.json',{'text':text,'issues':issues,'coverage_warnings':coverage_issues(text,budget),'disclaimer':disclaimer_for(article)})
            if not issues: break
        else: raise ValueError('Citation repair paused: '+' '.join(issues)+'. Saved progress can be resumed.')
        record_coverage_shortfall(article,index,coverage_issues(text,budget),progress)
        section['text']=text;section.pop('continuity_summary',None)
        state['processed']=index+1;save(folder/'article.json',article)
    for chapter in article.get('plan',{}).get('chapters',[]): chapter.pop('continuity_summary',None)
    return require_complete(article,folder)
