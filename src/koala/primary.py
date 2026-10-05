"""Primary works: author-field discovery, library authority names, and public texts."""
import csv
import gzip
import io
import xml.etree.ElementTree as ET
import hashlib
import re
import time
import threading
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener
from .providers import request_json, NoRedirect
from .coverage import same_author, author_matches, has_evidence
from .core import read_json, save
from .research import Crossref


def identity(source):
    # Editions/translations must not inherit evidence from a different edition.
    return (source.get('doi','').lower() or source.get('edition_key') or source.get('gutenberg_id')
            or '|'.join([' '.join(source.get('title','').casefold().split()),
                         ';'.join(source.get('authors',[])).casefold(),str(source.get('year',''))]))


def relevance(source, topic):
    terms=set(re.findall(r'\w{5,}',topic.casefold()))-{'these','those','their','about','which','would','should'}
    text=' '.join(str(source.get(k,'')) for k in ('title','subjects','abstract')).casefold()
    return -sum(t in text for t in terms)


def excerpt_text(text, topic, limit=4):
    start=re.search(r'\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*',text,re.I|re.S)
    end=re.search(r'\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG',text,re.I)
    if not start or not end or end.start()<=start.end(): return []
    body=text[start.end():end.start()]
    paragraphs=[re.sub(r'\s+',' ',p).strip() for p in re.split(r'\n\s*\n',body)]
    terms=set(re.findall(r'\w{5,}',topic.casefold()))-{'their','there','which','these','about','would','should'}
    candidates=[(i,p) for i,p in enumerate(paragraphs,1) if len(p)>180]
    candidates.sort(key=lambda x:(-sum(t in x[1].casefold() for t in terms),x[0]))
    # Local offsets are not published paragraph or page numbers.
    return [{'id':f'pg_excerpt_{i}','text':p[:1200],
             'retrieval_location':f'Locally parsed paragraph {i}; not a published locator'} for i,p in candidates[:limit]]


class PrimaryDiscovery:
    def __init__(self, cache_dir=None, progress=None):
        self.cache=Path(cache_dir) if cache_dir else None
        self.progress=progress or (lambda _:None)
        self.warnings=[]
        self.catalog=None
        self.birth_years={}
        self.ambiguous=set()
        self.failures={}
        self.gates={k:threading.Lock() for k in ("library","mirror","catalog")}
        self.last_request={}
        self.cache_locks=defaultdict(threading.Lock)

    def cached(self, kind, query, call):
        with self.cache_locks[(kind,query)]:
            return self._cached(kind,query,call)

    def _cached(self, kind, query, call):
        digest=hashlib.sha256((kind+query).encode()).hexdigest()
        path=self.cache/(digest+'.json') if self.cache else None
        if path and path.exists():return read_json(path)
        result=call()
        if path:save(path,result)
        return result

    def pause(self,service,seconds):
        with self.gates[service]:
            time.sleep(max(0,seconds-(time.monotonic()-self.last_request.get(service,0))))
            self.last_request[service]=time.monotonic()

    def library(self,name,topic):
        def get(url):
            self.pause('library',1.05)
            return request_json(url,timeout=25)
        authority=self.cached('primary-authority-v1',name,lambda:get('https://openlibrary.org/search/authors.json?'+urlencode({'q':name,'limit':10})))
        choices=[a for a in authority.get('docs',[]) if any(same_author(name,n) for n in [a.get('name','')]+a.get('alternate_names',[]))]
        if not choices and len(name.split())>1:
            surname=name.split()[-1]
            broader=self.cached('primary-authority-surname-v1',surname,lambda:get('https://openlibrary.org/search/authors.json?'+urlencode({'q':surname,'limit':30})))
            choices=[a for a in broader.get('docs',[]) if any(same_author(name,n) for n in [a.get('name','')]+a.get('alternate_names',[]))]
            enriched=[]
            for a in choices[:3]:
                aid=a.get('key','').split('/')[-1]
                if not re.fullmatch(r'OL\d+A',aid):continue
                detail=self.cached('primary-author-details-v1',aid,lambda:get('https://openlibrary.org/authors/'+aid+'.json'))
                enriched.append(dict(a,**detail))
            if enriched:choices=enriched

        # Ambiguous authority results are left for review instead of silently selecting a homonym.
        aliases=[name]; author_key=None
        def birth(author):
            value=author.get('birth_date','') or ''
            if value.startswith('fl.'):return None
            numbers=re.findall(r'\b\d{3,4}\b',value)
            return (-1 if 'BC' in value.upper() else 1)*int(numbers[-1]) if numbers else None
        dated=[(a,birth(a)) for a in choices if birth(a) is not None]
        years={year for _,year in dated}
        if len(years)>1:
            self.ambiguous.add(name)
            self.warnings.append(f'{name}: multiple library identities; review catalog/DOI candidates. Automatic public-domain text retrieval skipped.')
        selected=choices[0] if len(choices)==1 else next((a for a,y in dated),None) if len(years)==1 else None
        if selected:
            aliases=list(dict.fromkeys([name,selected['name']]+selected.get('alternate_names',[])))
            author_key=selected.get('key','').split('/')[-1]
            self.birth_years[name]=birth(selected)
        if choices and not author_key:
            aliases=list(dict.fromkeys([name]+[a.get('name','') for a in choices]+[n for a in choices for n in a.get('alternate_names',[])]))
        params={'author':choices[0]['name'] if choices else name,'limit':12,'lang':'en','fields':'key,title,author_name,author_key,first_publish_year,subject,editions,editions.key,editions.ebook_access'}
        if author_key and re.fullmatch(r'OL\d+A',author_key):
            params.pop('author');params['q']='author_key:'+author_key
        def find_editions():
            previous=self.cache/(hashlib.sha256(('primary-library-search-v1'+name).encode()).hexdigest()+'.json') if self.cache else None
            if previous and previous.exists():
                earlier=read_json(previous)
                docs=[w for w in earlier.get('docs',[]) if not author_key or author_key in w.get('author_key',[])]
                if docs:return dict(earlier,docs=docs)
            return get('https://openlibrary.org/search.json?'+urlencode(params))
        data=self.cached('primary-library-search-v3',name+'|'+urlencode(params),find_editions)
        found=[]
        works=sorted(data.get('docs',[]),key=lambda w:relevance({'title':w.get('title',''),'subjects':w.get('subject',[])},topic))
        for work in works:
            if not any(same_author(a,b) for a in aliases for b in work.get('author_name',[])):continue
            for ed in work.get('editions',{}).get('docs',[])[:1]:
                key=ed.get('key','')
                if not re.fullmatch(r'/books/OL\d+M',key):continue
                item=self.cached('primary-edition-v1',key,lambda:get('https://openlibrary.org'+key+'.json'))
                year=re.search(r'\b\d{4}\b',item.get('publish_date',''))
                if not year:continue
                # The edition must actually retain the matched author; work-level bylines alone can include editors.
                edition_authors={a.get('key','').split('/')[-1] for a in item.get('authors',[])}
                matched_keys={k for k,n in zip(work.get('author_key',[]),work.get('author_name',[])) if any(same_author(a,n) for a in aliases)}
                if author_key:matched_keys={author_key}
                if not edition_authors.intersection(matched_keys):continue
                access=ed.get('ebook_access','unknown')
                source={'title':item.get('title') or work['title'],'authors':[n for k,n in zip(work.get('author_key',[]),work['author_name']) if k in edition_authors],'year':year[0],
                    'publisher':'; '.join(item.get('publishers',[])),'type':'book','doi':'',
                    'edition':item.get('edition_name',''),'edition_key':key,'isbn':next(iter(item.get('isbn_13',[])),''),
                    'url':'https://openlibrary.org'+key,'abstract':'','notes':'',
                    'subjects':work.get('subject',[])[:30], 'author_aliases':aliases if author_key else [],
                    'identity_provenance':'https://openlibrary.org/authors/'+author_key if author_key else 'Name match; identity needs review',
                    'access_status':{'public':'Public reading link; text not retrieved','borrowable':'Borrowing available; text not retrieved','printdisabled':'Restricted accessible edition; text not retrieved'}.get(access,'Catalog record; text not retrieved'),
                    'access_links':[{'label':'View edition / reading options','url':'https://openlibrary.org'+key}],
                    'provenance':'Open Library edition and author authority metadata','verification':'metadata-only'}
                found.append(source)
            if len(found)>=3:break
        return found,aliases

    def mirror_bytes(self,path,maximum=8_000_000):
        url='https://gutenberg.pglaf.org/'+path
        self.pause('mirror',2)
        try:
            with build_opener(NoRedirect).open(Request(url,headers={'User-Agent':'KOALA scholarly research'}),timeout=45) as response:
                raw=response.read(maximum+1)
            if len(raw)>maximum:raise RuntimeError('Public download exceeds size limit.')
            return raw
        except OSError as exc:raise RuntimeError(f'Gutenberg mirror unavailable: {type(exc).__name__}') from None

    def catalog_books(self):
        with self.gates["catalog"]:
            return self._catalog_books()

    def _catalog_books(self):
        if self.catalog is not None:return self.catalog
        path=self.cache/'primary-catalog'/'pg_catalog.csv.gz' if self.cache else None
        if path and path.exists():raw=path.read_bytes()
        else:raw=self.mirror_bytes('cache/epub/feeds/pg_catalog.csv.gz',12_000_000)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded=stream.read(100_000_001)
        if len(decoded)>100_000_000:raise RuntimeError('Gutenberg catalog exceeds size limit.')
        self.catalog=list(csv.DictReader(io.StringIO(decoded.decode('utf-8-sig'))))
        if path and not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(path)
        return self.catalog

    def gutenberg(self,name,aliases,topic):
        if name in self.ambiguous:return []
        matches=[]
        for row in self.catalog_books():
            if row.get('Type')!='Text' or 'en' not in row.get('Language','').split(';'):continue
            names=[re.sub(r',\s*(?:[?\d-]+|B\.?C\.?).*$','',a.strip()).strip() for a in row.get('Authors','').split(';')]
            names=[re.sub(r'\s*\([^)]*\)','',a).strip() for a in names]
            if not any(same_author(a,b) for a in aliases for b in names):continue
            if not row.get('Text#','').isdigit():continue
            matches.append(({'id':int(row['Text#']),'title':row['Title'],'subjects':row.get('Subjects','')},names))
        matches.sort(key=lambda pair:relevance(pair[0],topic))
        found=[]
        for book,names in matches[:2]:
            bid=book.get('id')
            if not isinstance(bid,int) or bid<1:continue
            # Check the authoritative creator and rights record before retrieving content.
            ns={'d':'http://purl.org/dc/terms/','p':'http://www.gutenberg.org/2009/pgterms/','m':'http://id.loc.gov/vocabulary/relators/'}
            metadata=self.cached('primary-gutenberg-rdf-v1',str(bid),lambda:{'xml':self.mirror_bytes(f'cache/epub/{bid}/pg{bid}.rdf',500_000).decode('utf-8')})
            root=ET.fromstring(metadata['xml'])
            if root.findtext('.//d:rights',namespaces=ns)!='Public domain in the USA.':continue
            names=[n.text for n in root.findall('.//d:creator/p:agent/p:name',ns) if n.text]
            if not any(same_author(a,b) for a in aliases for b in names):continue
            expected_birth=self.birth_years.get(name)
            actual_births={int(n.text) for n in root.findall('.//d:creator/p:agent/p:birthdate',ns) if n.text and re.fullmatch(r'-?\d+',n.text)}
            if expected_birth is not None and expected_birth not in actual_births:continue
            translators=[n.text for n in root.findall('.//m:trl/p:agent/p:name',ns) if n.text]
            url=f'https://gutenberg.pglaf.org/cache/epub/{bid}/pg{bid}.txt'
            try:text=self.cached('primary-gutenberg-text-v1',str(bid),lambda:{'text':self.mirror_bytes(f'cache/epub/{bid}/pg{bid}.txt').decode('utf-8-sig',errors='replace')})['text']
            except RuntimeError as exc:self.warnings.append(str(exc));continue
            date=re.search(r'\b(?:19|20)\d{2}\b',root.findtext('.//d:issued',default='',namespaces=ns))
            passages=excerpt_text(text,topic)
            if not date or not passages:continue
            for p in passages:p['source_url']=url
            found.append({'title':book['title'],'authors':names,'author_aliases':[name] if not any(same_author(name,n) for n in names) else [],
                'year':date[0],'publisher':'Project Gutenberg','edition':f'Electronic edition #{bid}; year is ebook release year, not original publication',
                'type':'book','gutenberg_id':str(bid),'doi':'','abstract':'','notes':'','passages':passages,
                'translators':translators,
                'url':f'https://www.gutenberg.org/ebooks/{bid}',
                'access_links':[{'label':'Read public-domain edition','url':f'https://www.gutenberg.org/ebooks/{bid}'}],
                'access_status':'Public-domain text retrieved; selected excerpts available',
                'provenance':'Project Gutenberg creator/rights metadata and public-domain text; name variants checked against library authority',
                'verification':'retrieved-primary-excerpts; review translation and passage context'})
        return found

    def author(self,name,topic=''):
        found=[];aliases=[name]
        for label,call in [('library',lambda:self.library(name,topic)),
                           ('crossref',lambda:self.cached('primary-crossref-v1',name,lambda:Crossref().primary(name))),
                           ('gutenberg',lambda:self.gutenberg(name,aliases,topic))]:
            if self.failures.get(label,0)>=3:continue
            try:
                self.progress(f'Primary literature: {name} — {label}…')
                result=call()
                if label=='library':records,aliases=result
                else:records=result
                found.extend(records)
                self.failures[label]=0
            except (RuntimeError,ValueError,OSError,ET.ParseError) as exc:
                self.failures[label]=self.failures.get(label,0)+1
                self.warnings.append(f'{name} / {label}: {exc}')
                if self.failures[label]>=3:
                    message=f'{label} is unavailable; skipping this service for the rest of this run. Retry Expand research later.'
                    self.warnings.append(message);self.progress(message)
        seen=set();result=[]
        for s in found:
            if name in self.ambiguous:s['identity_warning']='Multiple people share this name; verify the author identity before citing.'
            k=identity(s)
            if k not in seen and author_matches(name,s):seen.add(k);result.append(s)
        if self.cache:
            save(self.cache/(hashlib.sha256(('primary-results-v3'+name+topic).encode()).hexdigest()+'.json'),result)
        return result
