"""Required-author tracking and explicit, evidence-aware citation budgets."""
from functools import lru_cache
import math
import re
import unicodedata
from pathlib import Path


def resolve_authors(brief, base):
    result = dict(brief)
    names = []
    for entry in brief.get('important_authors', []):
        if isinstance(entry, str) and entry.strip().lower().endswith('.txt'):
            path = Path(entry.strip()).expanduser()
            if not path.is_absolute(): path = Path(base) / path
            if not path.is_file():
                raise ValueError(f'Author-list file not found: {path}. Import the file or paste the names, separated by semicolons.')
            entry = path.read_text(encoding='utf-8-sig')
        names.extend(x.strip() for x in re.split(r'[;\n]+', entry) if x.strip())
    if len(names) > 999:
        raise ValueError('important_authors accepts at most 999 authors.')
    result['important_authors'] = list(dict.fromkeys(names))
    if len(result['important_authors']) > 999:
        raise ValueError('important_authors accepts at most 999 authors.')
    return result


@lru_cache(maxsize=16384)
def name_tokens(name):
    if ',' in name:
        family, given = name.split(',', 1)
        name = given + ' ' + family
    text = ''.join(c for c in unicodedata.normalize('NFKD', name.casefold()) if not unicodedata.combining(c))
    return re.findall(r'\w+', text)


def same_author(requested, actual):
    a, b = name_tokens(requested), name_tokens(actual)
    if not a or not b: return False
    if a == b: return True
    # Never equate Sam Harris with Tristan Harris or John Gray with another Gray.
    if len(a) == 1 or len(b) == 1: return False
    if a[-1] != b[-1]: return False
    def compatible(x, y): return x == y or (min(len(x), len(y)) == 1 and x[0] == y[0])
    if not compatible(a[0], b[0]): return False
    short, long = sorted((a[:-1], b[:-1]), key=len)
    iterator = iter(long)
    return all(any(compatible(x, y) for y in iterator) for x in short)


def author_matches(name, source):
    return any(same_author(name, a) for a in source.get('authors', []) + source.get('author_aliases', []))


def has_evidence(source):
    if source.get("identity_review_required"):return False
    return any(isinstance(source.get(k), str) and source[k].strip() for k in ('abstract', 'notes')) or any(
        isinstance(p, dict) and isinstance(p.get('text'), str) and p['text'].strip() for p in source.get('passages', []))


def author_coverage(brief, sources, used=(), body=''):
    from .secondary import secondary_evidence, secondary_cited, mentions
    used = set(used)
    result = []
    names=list(dict.fromkeys(brief.get('important_authors', [])))
    for name in names:
        primary = [s for s in sources if author_matches(name,s)]
        secondary = [s for s in sources if not author_matches(name,s) and secondary_evidence(name,s)]
        matches = primary + secondary
        supported = [s for s in matches if has_evidence(s)]
        cited = [s['id'] for s in supported if s['id'] in used and
                 (author_matches(name,s) or secondary_cited(name,s['id'],body,names))]
        status = ('cited' if cited else 'not_cited' if supported else 'missing_evidence' if matches else 'missing_work')
        result.append({'author': name, 'status': status, 'source_ids': [s['id'] for s in matches],
                       'supported_ids': [s['id'] for s in supported], 'cited_ids': cited,
                       'primary_ids':[s['id'] for s in primary], 'secondary_ids':[s['id'] for s in secondary]})
    return result


def preserve_authors(brief, candidates, selected):
    """Keep at least one matching work per requested author through relevance selection."""
    ids = {s['id'] for s in selected}
    for row in author_coverage(brief, candidates, ids):
        primary_supported=[sid for sid in row['primary_ids'] if sid in row['supported_ids']]
        choices = primary_supported or row['supported_ids'] or row['primary_ids'] or row['source_ids']
        if choices and not set(choices) & ids: ids.add(choices[0])
    return [s for s in candidates if s['id'] in ids]


def citation_readiness(article):
    from .core import cited_ids
    used = set(cited_ids('\n'.join(s['text'] for s in article.get('sections', []))))
    sources = article.get('sources', [])
    rows = author_coverage(article['brief'], sources, used, '\n\n'.join(s['text'] for s in article.get('sections',[])))
    required = set()
    for row in rows:
        choices = row['supported_ids']
        if choices: required.add(next((sid for sid in choices if sid in used), choices[0]))
    goal = max(article['brief'].get('citation_target') or 75, len(required))
    supported = [s['id'] for s in sources if has_evidence(s)]
    blockers = []
    if len(supported) < goal:
        blockers.append(f'{len(supported)} works have evidence available; {goal} distinct cited works are required. Add source abstracts, research notes, or passages to the source ledger.')
    unresolved = [r['author'] for r in rows if not r['supported_ids']]
    if unresolved:
        blockers.append('Requested authors needing a primary or secondary source with supporting text: ' + '; '.join(unresolved))
    return {'target': goal, 'supported_source_ids': supported, 'required_source_ids': sorted(required),
            'authors': rows, 'blockers': blockers}


class ResearchApprovalRequired(ValueError):
    pass


def research_signature(article):
    import hashlib,json
    # Approval covers these requirements and this evidence, not later brief changes.
    data={'brief':article['brief'],'sources':article.get('sources',[])}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def research_authorized(article):
    approval=article.get('research_authorization',{})
    return approval.get('signature')==research_signature(article) and approval.get('authorized') is True


def authorize_research(article, folder, token=None, explicit=False):
    from .core import save
    from datetime import datetime,timezone
    report=citation_readiness(article)
    if not report['blockers'] or research_authorized(article):return
    if not explicit and token!=research_signature(article):
        require_ready(article,folder)  # Save a fresh notice/token before asking again.
    article['research_authorization']={'authorized':True,'signature':research_signature(article),
        'authorized_at':datetime.now(timezone.utc).isoformat(),'shortfalls':report['blockers'],
        'available_works':len(report['supported_source_ids']),'target':report['target']}
    save(Path(folder)/'article.json',article)


def require_ready(article, folder):
    from .core import save
    from . import disclaimer_for
    report=citation_readiness(article)
    report['disclaimer']=disclaimer_for(article)
    save(Path(folder)/'citation-coverage.json',report)
    if report['blockers'] and not research_authorized(article):
        missing=[r['author'] for r in report['authors'] if not r['supported_ids']]
        details=f"{len(report['supported_source_ids'])} works have evidence available; {report['target']} are requested. {len(missing)} of {len(report['authors'])} required authors lack supporting sources."
        if missing:details+=' Missing: '+'; '.join(missing[:8])+(' …' if len(missing)>8 else '')+'. Review the full author list in citation coverage.'
        notice={'token':research_signature(article),'message':
            'Citation research is incomplete. '+details+
            ' You may generate a provisional manuscript using only available evidence. Source and author targets will remain unmet and visible in the audit. No missing sources or citations will be invented.',
            'available_works':len(report['supported_source_ids']),'target':report['target'],
            'missing_authors':[r['author'] for r in report['authors'] if not r['supported_ids']]}
        save(Path(folder)/'research-approval-needed.json',notice)
        raise ResearchApprovalRequired(notice['message'])
    return report


def section_budget(article, index, query=''):
    from .core import cited_ids
    report = citation_readiness(article)
    if research_authorized(article):
        used=set(cited_ids('\n'.join(s['text'] for s in article.get('sections',[])[:index])))
        return {'minimum_new_works':0,'required_source_ids':[],'required_author_mentions':[],
                'all_required_authors':article['brief'].get('important_authors',[]),
                'suggested_source_ids':report['supported_source_ids'][:12], 'already_cited':sorted(used),
                'research_shortfall_authorized':True,
                'guidance':'Use relevant available evidence. Citation counts and author coverage are advisory for this authorized provisional draft; acknowledge gaps and never invent references.'}
    used = set(cited_ids('\n'.join(s['text'] for s in article.get('sections', [])[:index])))
    remaining = max(1, len(article['plan']['sections']) - min(index,len(article.get('sections',[]))))
    unused = set(report['supported_source_ids']) - used
    minimum = min(len(unused), math.ceil(max(0, report['target'] - len(used & set(report['supported_source_ids']))) / remaining))
    tokens = set(re.findall(r'\w{4,}', query.casefold()))
    def score(s):
        text = ' '.join(str(s.get(k,'')) for k in ('title','abstract','notes')).casefold()
        return (-sum(t in text for t in tokens), s['id'])
    pending = set(report['required_source_ids']) - used
    ranked = sorted((s for s in article['sources'] if s['id'] in unused), key=score)
    required = [s['id'] for s in ranked if s['id'] in pending][:math.ceil(len(pending)/remaining)]
    missing_authors=[r for r in report['authors'] if r['status']!='cited' and r['supported_ids']]
    mentions=[]
    for row in missing_authors[:math.ceil(len(missing_authors)/remaining)]:
        primary=[sid for sid in row['supported_ids'] if sid in row['primary_ids']]
        sid=(primary or row['supported_ids'])[0]
        if sid not in required: required.append(sid)
        if not primary: mentions.append({'author':row['author'],'source_id':sid})
    suggested = required + [s['id'] for s in ranked if s['id'] not in required]
    return {'minimum_new_works': max(minimum, len(set(required)-used)), 'required_source_ids': required,
            'required_author_mentions':mentions, 'all_required_authors':article['brief'].get('important_authors',[]),
            'suggested_source_ids': suggested[:max(minimum, len(required))], 'already_cited': sorted(used)}


def coverage_issues(text, budget):
    from .core import cited_ids
    ids = set(cited_ids(text))
    issues = []
    missing = set(budget['required_source_ids']) - ids
    if missing: issues.append('Integrate supported discussion citing required author works: ' + ', '.join(sorted(missing)) + '.')
    from .secondary import secondary_cited
    for mention in budget.get('required_author_mentions',[]):
        if not secondary_cited(mention['author'],mention['source_id'],text,budget.get('all_required_authors',[])):
            issues.append('Discuss '+mention['author']+' and cite secondary source '+mention['source_id']+' in the same paragraph, with accurate attribution.')
    count = len(ids - set(budget['already_cited']))
    if count < budget['minimum_new_works']:
        issues.append(f'Cite at least {budget["minimum_new_works"]} previously uncited works in supported, relevant discussion; this attempt cites {count}. Do not append a citation dump or invent claims.')
    return issues


def record_coverage_shortfall(article, index, warnings, progress=print):
    records=article.setdefault('citation_shortfalls',{})
    if warnings:
        records[str(index)]=list(warnings)
        progress(f'Section {index+1}: citation coverage below goal; keeping the text and continuing. Details saved for review.')
    else:records.pop(str(index),None)


def require_complete(article, folder):
    from .core import audit, save
    report = audit(article)
    article['audit'] = report
    problems = [x for x in report['issues'] if x.startswith(('Citation shortfall:', 'Required authors', 'Citations without'))]
    article['stage'] = 'citation_review' if problems else 'drafted'
    save(Path(folder)/'article.json', article); save(Path(folder)/'audit.json', report)
    blocking=[p for p in problems if p.startswith('Citations without')]
    if blocking: raise ValueError('Citation requirements remain incomplete. ' + ' '.join(problems) + ' Use Repair citations to revise saved prose.')
    return article
