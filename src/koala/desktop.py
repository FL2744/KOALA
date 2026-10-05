"""One-request JSON-line bridge for the native macOS application.

The application owns UI and credentials. This module reuses the CLI/pipeline and
emits progress, results, and errors. No shell, HTTP server, or terminal is involved.
"""
import contextlib
import fcntl
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from . import __version__, disclaimer_for
from .core import normalize_brief, read_json, save, words, audit
from .menu import Menu, DEFAULT_SETTINGS, read_inputs, archive
from .providers import Provider
from .coverage import citation_readiness
from .reuse import completed_analyses, reuse_analyses


from .bibliography import bibliography_view
from .development import load_development, development_view
from .writing_style import DEFAULT_WRITING_STYLE
from .manuscript_repair import DEFAULT_REPAIR


def validate_project_name(name):
    if not isinstance(name,str) or not name.strip() or len(name.strip())>120 or any(ord(c)<32 for c in name) or any(c in name for c in '/\\:') or name.strip() in ('.','..'):
        raise ValueError('Enter a project name of 1–120 characters without slashes, colons, or control characters.')
    return name.strip()


def project_view(folder):
    menu = Menu(write=lambda _: None)
    menu.open_project(folder)
    raw_brief = menu.brief()
    brief = normalize_brief(raw_brief)
    if raw_brief.get('citation_target', 'default') is None:
        brief['citation_target'] = None
    metadata = read_json(menu.folder/'.koala-project.json') if (menu.folder/'.koala-project.json').exists() else {}
    article = menu.checkpoint()
    preview, preview_error = [], ''
    if article and article.get('sections'):
        try:
            from .exporters import blocks
            paragraphs = iter(t for kind,t in blocks(article) if kind == 'paragraph')
            next(paragraphs, None)  # abstract
            preview = ['\n\n'.join(next(paragraphs) for p in section['text'].split('\n\n') if p.strip()) for section in article['sections']]
        except (ValueError, RuntimeError, OSError, StopIteration) as exc:
            preview_error = str(exc)
    return {'project_name': metadata.get('name') or menu.folder.name, 'style_presets': __import__('koala.style_presets',fromlist=['catalog']).catalog(), 'default_writing_prompt': DEFAULT_WRITING_STYLE, 'default_manuscript_repair':DEFAULT_REPAIR, 'folder': str(menu.folder), 'brief': brief, 'settings': menu.settings,
            'data_workspace': __import__('koala.data_analysis',fromlist=['load']).load(menu.folder), 'bibliography': bibliography_view(brief, article), 'development': development_view(menu),
            'rewrite': __import__('koala.rewrite',fromlist=['public_state']).public_state(menu.folder), 'article': article, 'formatted_sections':preview, 'citation_preview_error':preview_error,
            'citation_readiness':citation_readiness(article) if article else None, 'next': list(menu.next_step()),
            'audit': audit(article) if article and article.get('sections') else None,
            'exports': [str(p) for stem in ('article', 'manuscript', 'abstract')
                        for ext in ('docx', 'pdf', 'html', 'txt', 'rtf')
                        if (p := menu.folder / f'{stem}.{ext}').is_file()]}


def initial_article(menu):
    if menu.checkpoint():
        return menu.checkpoint()
    brief = normalize_brief(menu.brief())
    excerpts, documents = read_inputs(brief, menu.folder)
    return {'schema_version': 3, 'disclaimer': disclaimer_for(brief), 'brief': brief,
            'plan': {}, 'title': '', 'abstract': '', 'sections': [], 'sources': [],
            'warnings': [], 'excerpts': excerpts, 'provider': menu.settings['provider'],
            'model': menu.settings['model'], 'brief_directory': str(menu.folder),
            'stage': 'planning', 'pending_documents': documents}


def settings_for(raw):
    result = {**DEFAULT_SETTINGS, **{k:v for k,v in raw.items() if k in DEFAULT_SETTINGS}}
    if result['provider'] not in ('openai', 'arc') or not isinstance(result['model'], str) or not result['model'].strip():
        raise ValueError('Choose a provider and enter a model ID.')
    url = result.get('base_url')
    if url:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTPS API endpoint without credentials, query parameters, or fragments.')
    return result


def dispatch(request):
    action = request['action']
    if action == 'prompt_library':
        from .prompt_library import library_view
        return library_view()
    if action == 'save_prompt_template':
        from .prompt_library import save_template
        return save_template(request.get('name'), request.get('text'), request.get('id'))
    if action == 'read_bibliography':
        from .bibliography import read_bibliography
        return read_bibliography(request['path'])
    if action == 'read_outline':
        from .outlines import read_outline
        return read_outline(request['path'])
    if action == 'info':
        return {'version': __version__}
    if action == 'models':
        settings = settings_for(request.get('settings', {}))
        return {'models': Provider(settings['provider'],settings['model'],settings['base_url']).models()}
    if action == 'reuse_list':
        return {'analyses': [{'path':str(p),'name':m.get('name','Document'),
                              'provider':m.get('provider',''),'model':m.get('model',''),
                              'chunks':m.get('chunk_count',0)} for p,m in completed_analyses(request['source'])]}
    folder = Path(request['folder']).expanduser().resolve()
    if action == 'create':
        name = validate_project_name(request.get('name', folder.name))
        supplied = request.get('brief', {})
        brief = normalize_brief(supplied)
        if supplied.get('citation_target', 'default') is None or (brief['project_type'] == 'book' and 'citation_target' not in supplied):
            brief['citation_target'] = None
        settings = settings_for(request.get('settings', {}))
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise ValueError('Choose a new or empty project folder.')
        save(folder/'.koala-project.json', {'name':name})
        save(folder/'brief.json', brief)
        save(folder/'.koala-menu.json', settings)
        return project_view(folder)
    if action == 'load':
        return project_view(folder)
    if not folder.is_dir():
        raise ValueError('Open or create a project first.')
    # Two native app windows/processes cannot mutate the same project concurrently.
    with (folder/'.koala-desktop.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This project is busy in another KOALA app window.') from None
        menu = Menu(write=print)
        menu.open_project(folder)
        if action == 'random_generate':
            if request.get('confirmed') is not True:
                raise ValueError('Confirm lucky-seven generation before contacting the model.')
            from .development import randomize_brief
            settings = settings_for(request.get('settings', menu.settings))
            provider = Provider(settings['provider'],settings['model'],settings['base_url'])
            provider.check_model()
            randomize_brief(menu, provider, True)
            action = 'generate'
        if action == 'expand_research':
            from .research_refresh import expand_research
            article = menu.checkpoint()
            if not article or not article.get('plan'):
                raise ValueError('Create the researched abstract first, then expand its research here.')
            expand_research(article,folder,print)
        elif action in ('import_data','analyze_data','integrate_data'):
            from . import data_analysis
            if action == 'import_data':
                data_analysis.import_data(folder,request.get('path',''))
            elif action == 'analyze_data':
                provider=None
                if request.get('mode') in ('interpret','themes'):
                    settings=settings_for(request.get('settings',menu.settings))
                    provider=Provider(settings['provider'],settings['model'],settings['base_url'])
                    provider.check_model()
                data_analysis.analyze(folder,request.get('dataset'),request.get('mode'),request.get('column',''),request.get('group',''),request.get('question',''),provider)
            else:
                if not menu.checkpoint():save(folder/'article.json',initial_article(menu))
                data_analysis.integrate(folder,request.get('dataset'),request.get('analysis'),request.get('included') is True,request.get('placement','findings'),request.get('notes',''))
        elif action in ('rewrite_manuscript','apply_rewrite'):
            from . import rewrite
            if action == 'apply_rewrite':rewrite.apply(folder)
            else:
                settings=settings_for(request.get('settings',menu.settings))
                provider=Provider(settings['provider'],settings['model'],settings['base_url'])
                provider.check_model()
                rewrite.rewrite(provider,menu.checkpoint() or {},folder,request.get('parameters'),request.get('restart') is True,print)
        elif action == 'rename_project':
            name = validate_project_name(request.get('name'))
            from .project_rename import rename_project
            folder=rename_project(folder,name)
        elif action == 'develop':
            from .development import generate_proposal
            settings = settings_for(request.get('settings', menu.settings))
            provider = Provider(settings['provider'],settings['model'],settings['base_url'])
            provider.check_model()
            generate_proposal(menu, provider, request.get('kind'))
        elif action == 'apply_development':
            from .development import apply_proposal
            apply_proposal(menu,request.get('kind'),request.get('text'))
        elif action == 'import_bibliography':
            from .bibliography import import_bibliography
            import_bibliography(menu, request.get('text',''), request.get('mode','replan'))
        elif action == 'save_brief':
            menu.save_brief(request['brief'])
        elif action == 'settings':
            menu.settings = settings_for(request['settings'])
            menu.store_settings()
        elif action == 'save_abstract':
            article = menu.checkpoint()
            text = request.get('text','').strip()
            if not article or not article.get('abstract'):
                raise ValueError('Create the guiding abstract first.')
            if not 250 <= words(text) <= 300 or '[@' in text:
                raise ValueError(f'Abstract has {words(text)} words. Use 250–300 words without citation markers.')
            revision = archive(folder, article)
            article.setdefault('revision_history', []).append(str(revision))
            article.update(abstract=text, sections=[], stage='abstract')
            article.pop('audit',None)
            for chapter in article.get('plan',{}).get('chapters',[]):
                chapter.pop('continuity_summary',None); chapter.pop('detailed',None)
            save(folder/'article.json',article)
            save(folder/'sources.json',{'disclaimer':disclaimer_for(article),'sources':article.get('sources',[])})
        elif action == 'reuse':
            source = Path(request['source']).expanduser().resolve()
            if source == folder:
                raise ValueError('Choose another source project.')
            available = completed_analyses(source)
            selected = set(request.get('analyses', []))
            choices = [(p,m) for p,m in available if str(p) in selected]
            if not choices or len(choices) != len(selected):
                raise ValueError('Select completed analyses from the source project.')
            reuse_analyses(initial_article(menu), choices, folder)
        elif action in ('abstract','generate','ingest','export','repair-citations','repair-manuscript'):
            from .cli import main
            formats = request.get('formats', ['docx','pdf','html','txt','rtf'])
            if action == 'export':
                args = ['export',str(folder/'article.json'),'--formats',*formats]
                if request.get('citation_style'): args += ['--citation-style',request['citation_style']]
                if request.get('abstract_only'): args.append('--abstract-only')
                if request.get('strict'): args.append('--strict')
            else:
                menu.settings = settings_for(request.get('settings',menu.settings))
                menu.store_settings()
                args = [action,'--out',str(folder),'--provider',menu.settings['provider'],'--model',menu.settings['model']]
                if menu.settings['base_url']:args += ['--base-url',menu.settings['base_url']]
                if action == 'repair-manuscript':
                    if 'repair_instructions' in request:args += ['--instructions',request['repair_instructions']]
                    if request.get('restart_repair') is True:args.append('--restart-repair')
                if action == 'generate' and request.get('research_approval'):
                    args += ['--research-approval',str(request['research_approval'])]
                if menu.checkpoint():args.append('--resume')
                else:args += ['--brief',str(folder/'brief.json')]
                if action == 'ingest':
                    documents = request.get('documents',[])
                    if not documents:raise ValueError('Select at least one DOCX, RTF, TXT, HTML or PDF document.')
                    args += documents
                else:args += ['--formats',*formats]
            diagnostic = DiagnosticStream(sys.stderr)
            with contextlib.redirect_stderr(diagnostic):
                try:
                    code = main(args)
                finally:
                    diagnostic.flush()
            if code == 3 and action == 'generate':
                result=project_view(folder)
                result['research_confirmation']=read_json(folder/'research-approval-needed.json')
                return result
            if code:
                if code == 130: raise KeyboardInterrupt()
                raise ValueError(diagnostic.error or 'The operation stopped without a detailed error. See the activity log; saved checkpoints are retained.')
        else:
            raise ValueError('Unknown desktop action.')
    return project_view(folder)


class DiagnosticStream(io.TextIOBase):
    """Forward CLI progress while retaining the actual failure for the native dialog."""
    def __init__(self, target):
        self.target, self.buffer, self.error = target, '', ''
    def write(self, text):
        self.target.write(text)
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n',1)
            self.capture(line)
        self.buffer = self.buffer[-64000:]
        return len(text)
    def capture(self, line):
        if line.startswith('KOALA: '): self.error = line[len('KOALA: '):].strip()
    def flush(self):
        if self.buffer:
            self.capture(self.buffer); self.buffer = ''
        self.target.flush()


class ProgressStream(io.TextIOBase):
    def __init__(self, emit):
        self.emit, self.buffer = emit, ''
    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line,self.buffer = self.buffer.split('\n',1)
            if line.strip():self.emit('progress',message=line)
        return len(text)
    def flush(self):
        if self.buffer.strip():self.emit('progress',message=self.buffer)
        self.buffer=''


def main():
    output = sys.stdout
    def emit(event, **data):
        output.write(json.dumps({'event':event,**data},ensure_ascii=False)+'\n');output.flush()
    stream=ProgressStream(emit)
    try:
        request=json.load(sys.stdin)
        with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
            result=dispatch(request)
        stream.flush();emit('result',data=result)
        return 0
    except KeyboardInterrupt:
        stream.flush();emit('error',message='Stopped. Completed checkpoints are retained; resume when ready.',cancelled=True)
        return 130
    except Exception as exc:
        stream.flush();emit('error',message=str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
