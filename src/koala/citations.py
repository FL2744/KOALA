"""Citation markers, evidence locators, and offline CSL rendering via Pandoc."""
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

MARKER = re.compile(r'\[@(S\d{3,})(?:#([A-Za-z0-9_-]+))?!?\]')
STYLES = ('mla', 'chicago-author-date', 'author-date', 'numeric')
STYLE_FILES = {'mla': 'modern-language-association.csl', 'chicago-author-date': 'chicago-author-date.csl'}


def locator_issues(text, sources):
    by_id = {s['id']: s for s in sources}
    issues = []
    for match in MARKER.finditer(text):
        sid, pid = match.groups()
        if not pid: continue
        passage = next((p for p in by_id.get(sid, {}).get('passages', []) if p.get('id') == pid), None)
        if not passage or not passage.get('text') or not passage.get('locator'):
            issues.append(f'Unsupported locator {sid}#{pid}: provide a source passage and its exact locator.')
    return issues


def parse_name(name):
    if ',' in name:
        family, given = name.split(',', 1)
        return {'family': family.strip(), 'given': given.strip()}
    bits = name.split()
    if len(bits) == 1: return {'literal': name}
    # Preserve particles; structured CSL author names can override this fallback.
    split = len(bits)-1
    while split > 1 and bits[split-1].lower() in ('de','von','van','der','den','di','da','del','la'):
        split -= 1
    return {'given': ' '.join(bits[:split]), 'family': ' '.join(bits[split:])}


def csl_record(source):
    record = dict(source.get('csl', {}))
    record.update(id=source['id'], title=source['title'])
    kind = source.get('type') or ('article-journal' if source.get('container') else 'book')
    kind = {'journal-article':'article-journal', 'book-chapter':'chapter', 'monograph':'book',
            'edited-book':'book', 'reference-book':'book', 'book-part':'chapter', 'book-section':'chapter',
            'reference-entry':'entry-encyclopedia', 'proceedings-article':'paper-conference',
            'posted-content':'article', 'dissertation':'thesis', 'report-component':'report', 'component':'article'}.get(kind, kind)
    record.setdefault('type', kind)
    record.setdefault('author', source.get('author_names') or [parse_name(a) for a in source['authors']])
    year = re.fullmatch(r'-?\d{1,4}', str(source['year']))
    record.setdefault('issued', {'date-parts': [[int(year[0])]]} if year else {'literal':str(source['year'])})
    for src, dst in [('container','container-title'),('volume','volume'),('issue','issue'),('pages','page'),
                     ('publisher','publisher'),('doi','DOI'),('url','URL'),('edition','edition'),('isbn','ISBN')]:
        if source.get(src): record.setdefault(dst,str(source[src]))
    for role in ('editor','translator'):
        names=source.get(role) or source.get(role+'s')
        if names: record.setdefault(role, [parse_name(a) for a in names])
    return record


class RichText(str):
    """Plain-text compatible value with safe, formatted spans for rich exports."""
    def __new__(cls, spans):
        merged = []
        for text, italic in spans:
            if merged and merged[-1][1] == italic:
                merged[-1] = (merged[-1][0]+text, italic)
            else: merged.append((text,italic))
        value = super().__new__(cls, ''.join(text for text, italic in merged))
        value.spans = merged
        return value


def spans(text):
    return getattr(text, 'spans', [(str(text), False)])


def rich_html(text):
    return ''.join(('<i>'+html.escape(t)+'</i>') if italic else html.escape(t) for t,italic in spans(text))


def inline_spans(inlines, italic=False):
    result = []
    for node in inlines:
        t, c = node['t'], node.get('c')
        if t == 'Str': result.append((c,italic))
        elif t in ('Space','SoftBreak','LineBreak'): result.append((' ',italic))
        elif t in ('Emph','Strong','SmallCaps','Superscript','Subscript','Strikeout','Underline'):
            result.extend(inline_spans(c, italic or t == 'Emph'))
        elif t == 'Cite': result.extend(inline_spans(c[1],italic))
        elif t in ('Span','Link'): result.extend(inline_spans(c[1],italic))
        elif t == 'Quoted':
            double = c[0]['t'] == 'DoubleQuote'
            result += [('“' if double else '‘',italic)] + inline_spans(c[1],italic) + [('”' if double else '’',italic)]
        elif t == 'Code': result.append((c[1],italic))
        else: raise ValueError(f'Unsupported citation formatting node: {t}')
    return result


def plain_inlines(text):
    return [{'t':'Space'} if token.isspace() else {'t':'Str','c':token} for token in re.findall(r'\s+|\S+',text)]


def narrative_author(prefix, source):
    """Recognize clear sentence-leading attribution; do not scan arbitrary mentions."""
    authors = csl_record(source).get('author', [])
    if not authors:return False
    short = [a.get('family') or a.get('literal','') for a in authors]
    full = [' '.join(filter(None,(a.get('given'),a.get('family')))) or a.get('literal','') for a in authors]
    if len(authors)==1: forms=[short[0],full[0]]
    elif len(authors)==2: forms=[' and '.join(short),' and '.join(full)]
    else:forms=[short[0]+' et al.',full[0]+' et al.']
    verbs=r"(?:argues?|argued|writes?|wrote|states?|stated|describes?|described|suggests?|suggested|observes?|observed|notes?|noted|explores?|explored|contends?|contended|claims?|claimed|explains?|explained|shows?|showed|concludes?|concluded|examines?|examined)"
    for name in forms:
        if not name:continue
        # An immediately preceding name, or a clear attribution beginning this sentence.
        if re.search(r'(?<!\w)'+re.escape(name)+r'\s*$',prefix):return True
        if re.search(r'(?:^|[.!?]\s+)(?:According to\s+)?'+re.escape(name)+r'(?:\s+'+verbs+r'\b|,)[^.!?]*$',prefix):return True
    return False


def render_csl(paragraphs, sources, style):
    """Render all citations together so disambiguation and bibliography order are global."""
    import pypandoc
    by_id = {s['id']: s for s in sources}
    problems = locator_issues('\n'.join(paragraphs),sources)
    if problems: raise ValueError(' '.join(problems))
    blocks = []
    empty_narrative_ids = set()
    for text in paragraphs:
        nodes, start = [], 0
        # Adjacent markers form one citation cluster, rather than repeated parentheses.
        for cluster in re.finditer(r'\[@S\d{3,}(?:#[A-Za-z0-9_-]+)?!?\](?:\s*\[@S\d{3,}(?:#[A-Za-z0-9_-]+)?!?\])*', text):
            nodes.extend(plain_inlines(text[start:cluster.start()]))
            citations=[]
            for marker in MARKER.finditer(cluster[0]):
                sid,pid=marker.groups(); suffix=[]
                if sid not in by_id: raise ValueError(f'Unknown citation ID: {sid}')
                if pid:
                    p=next(p for p in by_id[sid]['passages'] if p['id']==pid)
                    label={'page':'p.','chapter':'chap.','section':'sec.','paragraph':'para.','line':'l.'}.get(p.get('label','page'))
                    if not label: raise ValueError('Passage locator label must be page, chapter, section, paragraph, or line.')
                    suffix=plain_inlines(label+' '+str(p['locator']))
                narrative = marker[0].endswith('!]') or (len(list(MARKER.finditer(cluster[0]))) == 1 and narrative_author(text[:cluster.start()],by_id[sid]))
                if narrative and not pid and style == 'mla':empty_narrative_ids.add(sid)
                citations.append({'citationId':sid,'citationPrefix':[],'citationSuffix':suffix,
                                  'citationMode':{'t':'SuppressAuthor' if narrative else 'NormalCitation'},'citationNoteNum':0,'citationHash':0})
            nodes.append({'t':'Cite','c':[citations,[]]});start=cluster.end()
        nodes.extend(plain_inlines(text[start:]));blocks.append({'t':'Para','c':nodes})
    # Ask the installed Pandoc for its supported AST version, avoiding a pinned schema.
    binary = pypandoc.get_pandoc_path()
    empty = subprocess.run([binary,'-f','markdown','-t','json'],input='',text=True,capture_output=True,check=True)
    document=json.loads(empty.stdout);document['blocks']=blocks
    document['meta']={'lang':{'t':'MetaString','c':'en-US'}}
    with tempfile.TemporaryDirectory(prefix='koala-csl-') as folder:
        bibliography=Path(folder)/'sources.json';bibliography.write_text(json.dumps([csl_record(s) for s in sources]))
        result=subprocess.run([binary,'-f','json','-t','json','--citeproc','--bibliography',str(bibliography),
                               '--csl',str(Path(__file__).parent/'styles'/STYLE_FILES[style])],
                              input=json.dumps(document),text=True,capture_output=True,timeout=120)
    warnings=[line for line in result.stderr.splitlines() if line.strip() and not any(line.strip() == '[WARNING] Citeproc: Citation with no printed form: '+sid for sid in empty_narrative_ids)]
    if result.returncode or warnings:
        raise ValueError('Citation formatting failed: '+result.stderr.strip())
    output=json.loads(result.stdout)['blocks']
    rendered=[]
    for block in output[:len(paragraphs)]:
        nodes=block['c']
        for i in range(len(nodes)-1,-1,-1):
            if nodes[i]['t']=='Cite' and not ''.join(t for t,_ in inline_spans(nodes[i]['c'][1])).strip():
                del nodes[i]
                if i and nodes[i-1]['t']=='Space':del nodes[i-1]
        rendered.append(RichText(inline_spans(nodes)))
    references=[]
    def collect(nodes):
        for node in nodes:
            if node['t'] in ('Para','Plain'): references.append(RichText(inline_spans(node['c'])))
            elif node['t']=='Div': collect(node['c'][1])
    collect(output[len(paragraphs):])
    return rendered,references
