"""Secondary-literature links grounded in retrieved text, never fabricated bylines."""
from functools import lru_cache
import re
import unicodedata


@lru_cache(maxsize=16384)
def normalized(text):
    text=''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+',text))


@lru_cache(maxsize=2048)
def name_forms(name, surname=False):
    from .coverage import name_tokens
    bits=name_tokens(name);forms=[' '.join(bits)]
    if len(bits)>2 and len(bits[0])>1: forms.append(bits[0]+' '+bits[-1])
    if surname and bits: forms.append(bits[-1])
    return [x for x in forms if x]


def mentions(name,text,surname=False):
    hay=' '+normalized(text)+' '
    return any(' '+form+' ' in hay for form in name_forms(name,surname))


def secondary_evidence(name,source):
    """Require a name in available prose, or an explicit title plus available prose.

    A byline or a references-only entry does not establish discussion of that author.
    The match is a documented lead; homonyms and scholarly relevance need review.
    """
    bodies=[(k,source.get(k,'')) for k in ('abstract','notes')]
    bodies += [('passage:'+p.get('id',''),p.get('text','')) for p in source.get('passages',[]) if isinstance(p,dict)]
    for field,text in bodies:
        if isinstance(text,str) and text.strip() and mentions(name,text):
            # Keep the entire supplied field: a name late in an abstract must not be truncated away.
            return {'author':name,'kind':'secondary-discussion','field':field,'evidence':text,
                    'attribution':'Cite this secondary source; do not imply access to the original author’s work.'}
    if mentions(name,source.get('title','')) and any(isinstance(t,str) and t.strip() for _,t in bodies):
        return {'author':name,'kind':'secondary-title','field':'title','evidence':source['title'],
                'attribution':'The title identifies the subject. Use the accompanying source text only for supported claims.'}
    return None


def annotate(names, source):
    from .coverage import author_matches
    source['author_links']=[link for name in dict.fromkeys(names) if not author_matches(name,source)
                            and (link:=secondary_evidence(name,source))]
    return source


def secondary_cited(name,source_id,text,all_names=()):
    from .core import cited_ids
    from .coverage import name_tokens
    surname=name_tokens(name)[-1] if name_tokens(name) else ''
    ambiguous=sum(bool(name_tokens(n)) and name_tokens(n)[-1]==surname for n in set(all_names))>1
    return any(source_id in cited_ids(paragraph) and mentions(name,paragraph,surname=not ambiguous)
               for paragraph in text.split('\n\n'))
