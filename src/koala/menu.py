"""Terminal menus for the entire scholarly manuscript workflow."""
import copy
import getpass
import os
import shutil
import sys
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlparse
from . import __version__, is_book, disclaimer_for
from .coverage import resolve_authors
from .core import normalize_brief, read_json, save, audit, words
from .exporters import FORMATS
from .providers import Provider
from .text_imports import INSPIRATION_EXTENSIONS, FORMAT_LABEL

DEFAULT_SETTINGS = {'provider': 'openai', 'model': 'gpt-6-luna', 'base_url': None,
                    'formats': list(FORMATS), 'strict': False}
FIELDS = [('topic', 'Subject / topic'), ('discipline', 'Discipline'),
          ('target_journals', 'Target journals or journal types'), ('target_publishers', 'Publishers / series'),
          ('similar_articles', 'Comparable articles'), ('similar_books', 'Comparable books'),
          ('possible_citations', 'Candidate citations / DOIs'), ('important_authors', 'Important authors'),
          ('important_ideas', 'Important ideas / themes'), ('research_guidance', 'Research guidance'),
          ('style_guidance', 'Writing style'), ('writing_prompt', 'Main writing prompt (blank uses default)'), ('writing_prompt_name', 'Writing prompt name'), ('target_words', 'Target word count'),
          ('citation_target', 'Target distinct cited works'), ('citation_style', 'Citation style'),
          ('chapter_count', 'Main chapters'), ('include_afterword', 'Include afterword'),
          ('appendices', 'Appendix titles'), ('source_files', 'Text excerpts / document paths'),
          ('sources_file', 'Curated source ledger path'), ('inspiration_files', 'DOCX/RTF/TXT/HTML/PDF inspiration paths'), ('chapter_outline', 'Chapter outline / table of contents')]


class HomeRequested(Exception):
    pass


class QuitRequested(Exception):
    pass


class Cancelled(Exception):
    pass


def path_input(value):
    return Path(value.strip().strip('"\'')).expanduser().resolve()


def private_key(prompt):
    # Never allow getpass's echoed-stdin fallback for API keys.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise ValueError('Hidden key entry needs a terminal. Set the API key environment variable instead.') from None


def archive(folder, project):
    """Preserve every active artifact before an intentional menu revision."""
    destination = folder / 'revisions' / uuid.uuid4().hex
    destination.mkdir(parents=True)
    save(destination / 'article.json', project)
    if (folder / 'brief.json').exists():
        shutil.copy2(folder / 'brief.json', destination / 'brief.json')
    for name in ('audit.json', 'sources.json', 'candidates.json', 'book-selection.json'):
        if (folder / name).exists():
            shutil.move(str(folder / name), str(destination / name))
    for stem in ('article', 'manuscript', 'abstract'):
        for extension in FORMATS:
            path = folder / f'{stem}.{extension}'
            if path.exists():
                shutil.move(str(path), str(destination / path.name))
    return destination


def read_inputs(brief, base):
    excerpts, documents = [], []
    for name in brief['source_files']:
        path = (base / name).expanduser().resolve()
        if path.suffix.lower() in ('.docx', '.pdf', '.rtf', '.html', '.htm'):
            if not path.is_file():
                raise ValueError(f'Inspiration document not found or unsupported: {path}')
            documents.append(str(path))
        elif path.suffix.lower() in ('.txt', '.md'):
            text = path.read_text(encoding='utf-8')
            if len(text) > 100000:
                raise ValueError('Each text excerpt must be at most 100,000 characters.')
            excerpts.append({'file': path.name, 'text': text})
        else:
            raise ValueError('Source files must be TXT/MD excerpts or DOCX, RTF, HTML or PDF documents.')
    if sum(len(e['text']) for e in excerpts) > 200000:
        raise ValueError('Combined text excerpts must be at most 200,000 characters.')
    for name in brief['inspiration_files']:
        path = (base / name).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in INSPIRATION_EXTENSIONS:
            raise ValueError(f'Inspiration document not found or unsupported: {path}')
        documents.append(str(path))
    if brief['sources_file'] and not (base / brief['sources_file']).expanduser().is_file():
        raise ValueError('Curated source ledger file not found.')
    return excerpts, list(dict.fromkeys(documents))


class Menu:
    def __init__(self, project=None, read=None, write=None, secret=None, provider_factory=None, execute=None):
        self.read = read or input
        self.write = write or print
        self.secret = secret or private_key
        self.provider_factory = provider_factory or Provider
        if execute is None:
            from .cli import main
            execute = main
        self.execute = execute
        self.folder = None
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.changed_keys = {}
        self.initial_project = project

    def ask(self, prompt, default=None):
        suffix = f' [{default}]' if default is not None else ''
        result = self.read(prompt + suffix + ': ').strip()
        return str(default) if not result and default is not None else result

    def choice(self, title, items, back='Back'):
        if self.folder and not title.startswith('Home /'):
            title = f'Home / {self.folder.name} / {title}'
        while True:
            self.write('\n' + title)
            for index, item in enumerate(items, 1):
                self.write(f'  {index}. {item}')
            self.write(f'  0. {back}')
            value = self.ask('Choose').casefold()
            if value in ('q', 'quit'):
                raise QuitRequested()
            if value in ('h', 'home'):
                raise HomeRequested()
            if value in ('b', 'back'):
                return 0
            if value in ('?', 'help'):
                self.write('Choose a number to perform the named action. Blank redisplays this menu. '
                           'Back returns one level; Home closes the current project view; Quit exits KOALA. '
                           'Saved work is retained. In a project, Continue suggests the next workflow step. '
                           'These shortcuts apply at menus, not when entering text or paths.')
                continue
            if not value:
                continue
            if value.isdigit() and 0 <= int(value) <= len(items):
                return int(value)
            self.write(f'Enter a number from 0 to {len(items)}, or use a navigation shortcut.')

    def integer(self, label, default, lower, upper):
        while True:
            value = self.ask(label, default)
            try:
                number = int(value)
                if lower <= number <= upper:
                    return number
            except ValueError:
                pass
            self.write(f'Enter a whole number between {lower:,} and {upper:,}.')

    def yes(self, label, default=False):
        while True:
            value = self.ask(label + ' (y/n)', 'y' if default else 'n').casefold()
            if value in ('yes', 'y', 'no', 'n'):
                return value in ('y', 'yes')
            self.write('Enter y or n.')

    def checkpoint(self):
        path = self.folder / 'article.json'
        return read_json(path) if path.exists() else None

    def brief(self):
        path = self.folder / 'brief.json'
        if path.exists():
            return read_json(path)
        project = self.checkpoint()
        brief = copy.deepcopy(project['brief'])
        base = Path(project.get('brief_directory', self.folder))
        for key in ('source_files', 'inspiration_files'):
            brief[key] = [str((base / name).expanduser().resolve()) for name in brief.get(key, [])]
        if brief.get('sources_file'):
            brief['sources_file'] = str((base / brief['sources_file']).expanduser().resolve())
        return brief

    def store_settings(self):
        if self.folder:
            save(self.folder / '.koala-menu.json', self.settings)

    def open_project(self, path):
        folder = path_input(str(path))
        if folder.is_file():
            folder = folder.parent
        if not (folder / 'article.json').exists() and not (folder / 'brief.json').exists():
            raise ValueError('Choose a project folder containing brief.json or article.json.')
        project = read_json(folder / 'article.json') if (folder / 'article.json').exists() else None
        normalize_brief(project['brief'] if project else read_json(folder / 'brief.json'))
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        if project:
            settings.update(provider=project.get('provider', 'openai'), model=project.get('model', 'gpt-6-luna'))
        if (folder / '.koala-menu.json').exists():
            raw = read_json(folder / '.koala-menu.json')
            if not isinstance(raw, dict):
                raise ValueError('Invalid menu settings.')
            settings.update({k: raw[k] for k in DEFAULT_SETTINGS if k in raw})
        if settings['provider'] not in ('openai', 'arc') or not isinstance(settings['model'], str) or not settings['model'].strip():
            raise ValueError('Invalid saved provider/model settings.')
        if (not isinstance(settings['formats'], list) or not settings['formats'] or
                any(f not in FORMATS for f in settings['formats'])):
            raise ValueError('Invalid saved export formats.')
        if type(settings['strict']) is not bool or (settings['base_url'] is not None and not isinstance(settings['base_url'], str)):
            raise ValueError('Invalid saved menu settings.')
        self.folder, self.settings = folder, settings
        self.write(f'Opened {folder}')

    def new_project(self, kind):
        parent = Path.cwd() / 'output'
        folder = parent / kind
        n = 2
        while folder.exists():
            folder = parent / f'{kind}-{n}'
            n += 1
        self.write(f'\nNew {kind}. Leave subject guidance blank to let KOALA infer it.')
        destination = path_input(self.ask('Project folder', str(folder)))
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError('That folder is not empty. Open it as an existing project or choose a new folder.')
        brief = normalize_brief({'project_type': kind})
        brief['topic'] = self.ask('Subject / topic (optional)')
        brief['target_words'] = self.integer('Target words', brief['target_words'],
                                             40000 if kind == 'book' else 1000, 100000 if kind == 'book' else 20000)
        brief['citation_target'] = None  # Resolve automatically as the word budget changes.
        if kind == 'book':
            brief['chapter_count'] = self.integer('Main chapters (plus introduction)', 6, 5, 8)
            brief['include_afterword'] = self.yes('Include an afterword')
            brief['appendices'] = [x.strip() for x in self.ask('Optional appendix titles, separated by ;').split(';') if x.strip()]
        normalize_brief(brief)
        save(destination / 'brief.json', brief)
        self.folder = destination
        self.store_settings()
        self.write(f'Created {destination}. Use Edit brief to add authors, citations, style, and other guidance.')

    def choose_project(self):
        candidates = []
        for parent in (Path.cwd(), Path.cwd() / 'output', Path.cwd() / 'projects'):
            if parent.is_dir():
                for path in sorted(parent.iterdir()):
                    if path.is_dir() and ((path/'brief.json').exists() or (path/'article.json').exists()):
                        if path not in candidates:
                            candidates.append(path)
        items = [str(p) for p in candidates[:20]] + ['Enter a project folder path']
        selected = self.choice('Open project', items)
        if not selected:
            return
        path = candidates[selected-1] if selected <= min(20, len(candidates)) else self.ask('Project folder')
        if path:
            self.open_project(path)

    def next_step(self):
        project = self.checkpoint()
        if not project or not project.get('abstract'):
            return 'Create guiding abstract', 'abstract'
        if project.get('stage') == 'citation_review':
            return 'Repair citation coverage', 'repair-citations'
        if project.get('stage') in ('drafted', 'complete'):
            return 'Review completed manuscript', 'review'
        if project.get('sections'):
            return 'Resume manuscript', 'generate'
        return 'Start manuscript from the abstract', 'generate'

    def status(self):
        brief = normalize_brief(self.brief())
        project = self.checkpoint()
        self.write(f'\nHome / {self.folder.name} ({brief["project_type"].title()})')
        self.write(f'Folder: {self.folder}')
        self.write(f'Target: {brief["target_words"]:,} words | {brief["citation_target"]} cited works | '
                   f'{self.settings["provider"]} / {self.settings["model"]}')
        self.write('Workflow: Brief → Inspiration (optional) → Abstract → Manuscript → Review → Export')
        if project:
            completed = len(project.get('sections', []))
            total = len(project.get('plan', {}).get('sections', []))
            self.write(f'Abstract: {words(project.get("abstract", ""))} words | '
                       f'Sections saved: {completed}' + (f'/{total}' if total else '') +
                       f' | Documents: {len(project.get("inspiration", {}).get("documents", []))}')
        self.write('Suggested next step: ' + self.next_step()[0])

    def inspiration_menu(self):
        while True:
            selected = self.choice(f'Home / {self.folder.name} / Inspiration',
                                   ['Add inspiration documents', 'Reuse analysis from another project'])
            if not selected:
                return
            if selected == 1:
                self.import_documents()
            else:
                self.reuse_inspiration()

    def save_brief(self, brief, force_replan=False):
        brief = resolve_authors(brief, self.folder)
        old = self.checkpoint()
        previous_brief = old['brief'] if old else self.brief()
        if previous_brief.get('chapter_outline') and not brief.get('chapter_outline') and not 5 <= brief['chapter_count'] <= 8:
            brief['chapter_count'] = 6
        normalized = normalize_brief(brief)
        base = self.folder
        excerpts, documents = read_inputs(normalized, base)
        changed = {k for k,v in normalized.items() if not old or normalize_brief(old['brief']).get(k) != v}
        if old and changed and changed <= {'writing_prompt','writing_prompt_name','style_guidance','manuscript_title'}:
            old['brief'] = normalized
            if 'manuscript_title' in changed and normalized['manuscript_title'].strip():
                old['title']=normalized['manuscript_title'].strip()
                if old.get('plan'):old['plan']['title']=old['title']
            save(self.folder/'article.json', old)
            save(self.folder/'brief.json', brief)
            self.write('Writing prompt saved for future generation. Existing prose and checkpoints retained.')
            return
        if old and old.get('sections') and not force_replan and changed and changed <= {'citation_style','citation_target','important_authors','sources_file','possible_citations'}:
            old['brief'] = normalized
            if changed != {'citation_style'}:
                old['stage'] = 'citation_review'
                old.pop('citation_repair', None)
            old['audit'] = audit(old)
            save(self.folder/'article.json',old)
            save(self.folder/'brief.json',brief)
            self.write('Citation guidance saved; existing prose retained. Use Repair citations for coverage changes, or Export to apply formatting.')
            return
        if old and normalized != normalize_brief(old['brief']):
            revised = copy.deepcopy(old)
            if old.get('plan') or old.get('abstract') or old.get('sections'):
                revision = archive(self.folder, old)
                revised.setdefault('revision_history', []).append(str(revision))
                self.write(f'Previous version preserved in {revision}')
            revised.update(brief=normalized, plan={}, title='', abstract='', sections=[], sources=[],
                           stage='planning', excerpts=excerpts, pending_documents=documents, brief_directory=str(base),
                           previous_direction={'title': old.get('title'), 'abstract': old.get('abstract'), 'plan': old.get('plan')})
            old_name = old['brief'].get('sources_file')
            old_source = (Path(old.get('brief_directory', self.folder)) / old_name).resolve() if old_name else None
            new_source = (base / normalized['sources_file']).resolve() if normalized['sources_file'] else None
            if new_source == old_source:
                revised['inherited_sources'] = old.get('sources') or old.get('inherited_sources', [])
            else:
                revised.pop('inherited_sources', None)
            revised.pop('audit', None)
            save(self.folder/'article.json', revised)
        for key in ('chapter_count','include_afterword','appendices'):
            brief[key] = normalized[key]
        save(self.folder/'brief.json', brief)
        self.write('Brief saved. The next generation uses this guidance.')

    def edit_brief(self):
        self.write('Changes to a started project preserve the prior version and restart planning. Blank keeps a value; - clears it.')
        while True:
            brief = self.brief()
            book = is_book(brief)
            fields = [(k, label) for k, label in FIELDS if book or k not in ('chapter_count', 'include_afterword', 'appendices', 'target_publishers', 'similar_books', 'chapter_outline')]
            labels = []
            for key, label in fields:
                value = brief.get(key, normalize_brief(brief).get(key))
                if key == 'important_authors':
                    labels.append(f'{label}: {len(value)}/999 authors')
                    continue
                shown = 'automatic' if value is None else '; '.join(value) if isinstance(value, list) else str(value)
                labels.append(f'{label}: {shown[:65] or "(infer)"}')
            selected = self.choice('Edit brief', labels)
            if not selected:
                return
            key, label = fields[selected-1]
            value = brief.get(key, normalize_brief(brief).get(key))
            if key == 'include_afterword':
                new = self.yes(label, value)
            else:
                extra = ' (separate entries with ;)' if isinstance(value, list) else ' (number or auto)' if key == 'citation_target' else ''
                if key == 'important_authors':
                    extra = ' (required authors, up to 999; separate with ; or enter @path to a UTF-8 text file)'
                if key == 'chapter_outline': extra = ' (paste notes or enter @path to DOCX/PDF/TXT/MD; - clears)'
                if key == 'citation_style': extra = ' (mla or chicago-author-date; legacy: author-date, numeric)'
                answer = self.ask(label + extra)
                if not answer:
                    continue
                if key == 'chapter_outline' and answer.startswith('@'):
                    try:
                        from .outlines import read_outline
                        new = read_outline(path_input(answer[1:]))['text']
                    except (ValueError,OSError) as exc:
                        self.write(f'Outline not imported: {exc}')
                        continue
                elif key == 'important_authors' and answer.startswith('@'):
                    try:
                        content = path_input(answer[1:]).read_text(encoding='utf-8-sig')
                        new = [name.strip() for line in content.splitlines() for name in line.split(';') if name.strip()]
                    except (OSError, UnicodeError) as exc:
                        self.write(f'Not saved: {exc}')
                        continue
                elif isinstance(value, list):
                    new = [] if answer == '-' else [x.strip() for x in answer.split(';') if x.strip()]
                elif key == 'citation_target' and answer.casefold() in ('auto', '-'):
                    new = None
                elif key in ('target_words', 'citation_target', 'chapter_count'):
                    try:
                        new = int(answer)
                    except ValueError:
                        self.write('Enter a whole number, or auto for the citation target.')
                        continue
                else:
                    new = '' if answer == '-' else answer
            changed = copy.deepcopy(brief)
            changed[key] = new
            try:
                self.save_brief(changed)
            except (ValueError, OSError) as exc:
                self.write(f'Not saved: {exc}')

    def set_key(self):
        name = 'OPENAI_API_KEY' if self.settings['provider'] == 'openai' else 'ARC_API_KEY'
        value = self.secret(f'{name} (hidden; blank cancels): ').strip()
        if value:
            self.changed_keys.setdefault(name, os.environ.get(name))
            os.environ[name] = value
            self.write('Key is available for this menu session only; it was not saved to disk.')

    def client(self):
        name = 'OPENAI_API_KEY' if self.settings['provider'] == 'openai' else 'ARC_API_KEY'
        if not os.environ.get(name):
            self.write(f'{name} is not set. Enter it securely or leave blank to return to the menu.')
            self.set_key()
        return self.provider_factory(self.settings['provider'], self.settings['model'], self.settings['base_url'])

    def choose_model(self):
        models = self.client().models()
        needle = self.ask('Filter available models (blank shows all)').casefold()
        models = [m for m in models if needle in m.casefold()]
        if not models:
            self.write('No models match. No model was changed.')
            return
        self.write('Choose a text generation model compatible with this provider.')
        page = 0
        while True:
            self.write('\nAvailable models')
            for i in range(page*20, min(len(models), (page+1)*20)):
                self.write(f'  {i+1}. {models[i]}')
            answer = self.ask('Model number, n=next, p=previous, 0=back', '0').casefold()
            if answer in ('q', 'quit'):
                raise QuitRequested()
            if answer in ('h', 'home'):
                raise HomeRequested()
            if answer in ('0', 'b', 'back'):
                return
            if answer in ('?', 'help'):
                self.write('Select a model number; n/p changes pages. b returns, h goes home, q quits.')
                continue
            if answer == 'n' and (page+1)*20 < len(models):
                page += 1
            elif answer == 'p' and page:
                page -= 1
            elif answer.isdigit() and 1 <= int(answer) <= len(models):
                self.settings['model'] = models[int(answer)-1]
                self.store_settings()
                self.write(f'Selected {self.settings["model"]}')
                return
            else:
                self.write('Choose a listed model number or an available page.')

    def provider_menu(self):
        while True:
            selected = self.choice(f'Inference — {self.settings["provider"]} / {self.settings["model"]}',
                                   ['Choose provider', 'Choose from live model list', 'Enter model ID',
                                    'Enter API key securely for this session', 'Set custom API endpoint'])
            if selected == 0:
                return
            if selected == 1:
                choice = self.choice('Provider', ['OpenAI', 'Virginia Tech ARC'])
                if choice:
                    name = 'openai' if choice == 1 else 'arc'
                    if name != self.settings['provider']:
                        self.settings.update(provider=name, model='gpt-6-luna' if name == 'openai' else 'gpt-oss-120b', base_url=None)
            elif selected == 2:
                self.choose_model()
            elif selected == 3:
                model = self.ask('Exact model ID (blank keeps current)')
                if model:
                    self.settings['model'] = model
            elif selected == 4:
                self.set_key()
            elif selected == 5:
                value = self.ask('HTTPS API base URL (- restores default; blank keeps current)')
                if value == '-':
                    self.settings['base_url'] = None
                elif value:
                    parsed = urlparse(value)
                    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                        self.write('Use an HTTPS base URL without credentials, query parameters, or a fragment.')
                        continue
                    self.settings['base_url'] = value.rstrip('/')
            self.store_settings()

    def workflow(self, command, documents=None, extra_args=None):
        # The menu invokes the same tested CLI workflow, never a second drafting implementation.
        self.client()  # Offer secure key entry before invoking CLI validation.
        args = [command, '--out', str(self.folder), '--provider', self.settings['provider'], '--model', self.settings['model']]
        if self.checkpoint():
            args.append('--resume')
        else:
            args += ['--brief', str(self.folder/'brief.json')]
        if self.settings['base_url']:
            args += ['--base-url', self.settings['base_url']]
        if documents:
            args += [str(p) for p in documents]
        if command != 'ingest':
            args += ['--formats', *self.settings['formats']]
            if self.settings['strict'] and command == 'generate':
                args.append('--strict')
        args += extra_args or []
        self.write('Running… Ctrl+C stops the current operation; completed checkpoints are retained.')
        code = self.execute(args)
        if code == 3 and command == 'generate':
            notice=read_json(self.folder/'research-approval-needed.json')
            self.write(notice['message'])
            answer=self.ask('Generate with available evidence anyway? Type yes to authorize',default='no')
            if answer.strip().lower()=='yes':
                code=self.execute(args+['--research-approval',notice['token']])
            else:
                self.write('Generation cancelled. Your research and checkpoints are retained.')
                return
        self.write('Finished.' if code == 0 else 'The operation did not finish. See the message above; you can retry from this menu.')

    def import_documents(self):
        paths = []
        self.write('Enter DOCX/RTF/TXT/HTML/PDF paths one at a time. Blank starts analysis; no entries returns to the menu.')
        while True:
            answer = self.ask('Inspiration file')
            if not answer:
                break
            path = path_input(answer)
            if path.suffix.lower() not in INSPIRATION_EXTENSIONS or not path.is_file():
                self.write('Choose an existing DOCX, RTF, TXT, HTML or PDF file.')
            else:
                paths.append(path)
        if paths:
            self.workflow('ingest', paths)

    def reuse_inspiration(self):
        from .reuse import completed_analyses, reuse_analyses
        answer = self.ask('Source project folder (blank cancels)')
        if not answer:
            return
        source = path_input(answer)
        if source.is_file():
            source = source.parent
        if source == self.folder.resolve():
            raise ValueError('Choose a different source project.')
        choices = completed_analyses(source)
        selected = self.choice('Completed inspiration analyses',
                               [f'{m.get("name", "document")} — {m.get("provider", "unknown")} / {m.get("model", "unknown")}'
                                for _, m in choices] + ['Reuse all completed analyses'])
        if not selected:
            return
        chosen = choices if selected == len(choices)+1 else [choices[selected-1]]
        article = self.checkpoint()
        if not article:
            brief = normalize_brief(self.brief())
            excerpts, documents = read_inputs(brief, self.folder)
            article = {'schema_version': 3, 'disclaimer': disclaimer_for(brief), 'brief': brief,
                       'plan': {}, 'title': '', 'abstract': '', 'sections': [], 'sources': [],
                       'warnings': [], 'excerpts': excerpts, 'provider': self.settings['provider'],
                       'model': self.settings['model'], 'brief_directory': str(self.folder),
                       'stage': 'planning', 'pending_documents': documents}
        reuse_analyses(article, chosen, self.folder, self.write)
        self.write('Inspiration reused. Create/resume the abstract or manuscript to use it.')

    def edit_abstract(self):
        project = self.checkpoint()
        if not project or not project.get('abstract'):
            raise ValueError('Create the guiding abstract first.')
        self.write('Paste a 250–300-word abstract. Enter a line containing only . to finish. Empty input cancels.')
        lines = []
        while True:
            line = self.read('')
            if line.strip() == '.':
                break
            lines.append(line)
        text = '\n'.join(lines).strip()
        if not text:
            return
        count = words(text)
        if not 250 <= count <= 300 or '[@' in text:
            raise ValueError(f'Abstract has {count} words; use 250–300 words and no citation markers.')
        revision = archive(self.folder, project)
        project.setdefault('revision_history', []).append(str(revision))
        project.update(abstract=text, sections=[], stage='abstract')
        project.pop('audit', None)
        for chapter in project.get('plan', {}).get('chapters', []):
            chapter.pop('continuity_summary', None)
            chapter.pop('detailed', None)
        save(self.folder/'article.json', project)
        save(self.folder/'sources.json', {'disclaimer': disclaimer_for(project), 'sources': project.get('sources', [])})
        self.write('Abstract saved. Previous prose was archived; generation will redraft from this abstract.')

    def review(self):
        while True:
            selected = self.choice('Review project', ['Status', 'Read guiding abstract', 'Edit guiding abstract',
                                   'Read outline', 'Browse source ledger', 'Citation and length audit', 'Read document inspiration', 'Repair citations / required authors', 'Repair manuscript — global prose fixes'])
            if not selected:
                return
            project = self.checkpoint()
            if selected == 1:
                self.status()
            elif not project:
                self.write('No manuscript checkpoint yet. Create the abstract or import a document first.')
            elif selected == 9:
                from .manuscript_repair import DEFAULT_REPAIR
                prior=project.get('manuscript_repair',{})
                instructions=self.ask('What should be fixed throughout the manuscript?',default=prior.get('instructions') or DEFAULT_REPAIR)
                extra=['--instructions',instructions]
                if prior.get('complete'):
                    if not self.yes('Start a new repair pass on the current manuscript?'):continue
                    extra.append('--restart-repair')
                self.workflow('repair-manuscript',extra_args=extra)
            elif selected == 8:
                self.workflow('repair-citations')
            elif selected == 2:
                self.write(project.get('abstract') or 'No abstract yet.')
            elif selected == 3:
                self.edit_abstract()
            elif selected == 4:
                plan = project.get('plan', {})
                self.write(plan.get('title', 'No outline yet.'))
                for item in plan.get('chapters', plan.get('sections', [])):
                    self.write(f'• {item["heading"]}: {item["purpose"]}')
            elif selected == 5:
                sources = project.get('sources', [])
                for start in range(0, len(sources), 20):
                    for s in sources[start:start+20]:
                        self.write(f'{s["id"]} — {s["title"]} ({s["year"]}); {s.get("verification", "unverified")}')
                    if start+20 < len(sources) and self.ask('Enter for next page, 0 to stop') == '0':
                        break
                if not sources:
                    self.write('No source ledger yet.')
            elif selected == 6:
                report = audit(project)
                self.write(f'Body: {report["body_words"]:,} words | Abstract: {report["abstract_words"]} words | '
                           f'Cited works: {report["distinct_cited_works"]} | Citation occurrences: {report["citation_occurrences"]}')
                for issue in report['issues']:
                    self.write('• ' + issue)
                if not report['issues']:
                    self.write('Automated checks passed.')
                self.write(report['note'])
            elif selected == 7:
                digest = project.get('inspiration', {}).get('digest') or {}
                self.write(digest.get('overview', 'No document inspiration yet.'))
                for field in ('ideas', 'themes', 'authors', 'citations', 'research_questions', 'style_notes'):
                    for item in digest.get(field, []):
                        self.write(f'{field.replace("_", " ")}: {item["text"]}')

    def export_menu(self):
        if not self.checkpoint():
            raise ValueError('Create a manuscript or abstract before exporting.')
        selected = self.choice('Export', ['Manuscript', 'Guiding abstract only'])
        if not selected:
            return
        self.write('Formats: ' + ', '.join(f'{i+1}={fmt.upper()}' for i, fmt in enumerate(FORMATS)))
        while True:
            value = self.ask('Format numbers separated by commas, or all', 'all').casefold()
            try:
                if value == 'all':
                    formats = list(FORMATS)
                else:
                    numbers = [int(n.strip()) for n in value.split(',')]
                    if not numbers or any(n < 1 or n > len(FORMATS) for n in numbers):
                        raise ValueError()
                    formats = list(dict.fromkeys(FORMATS[n-1] for n in numbers))
                break
            except ValueError:
                self.write('Choose format numbers 1–5, or all.')
        strict = self.yes('Require a clean manuscript audit before export') if selected == 1 else False
        self.settings.update(formats=formats, strict=strict)
        self.store_settings()
        args = ['export', str(self.folder/'article.json'), '--formats', *formats]
        if selected == 2:
            args.append('--abstract-only')
        if strict:
            args.append('--strict')
        self.execute(args)

    def run(self):
        self.write(f'\nKOALA {__version__} — Knowledge-Oriented Australian Literary Analysis')
        self.write('Scholarly articles and books. Menus: b back, h home, q quit, ? help.')
        try:
            if self.initial_project:
                self.open_project(self.initial_project)
            while True:
                try:
                    if self.folder is None:
                        choice = self.choice('Main menu', ['Create an article', 'Create a book', 'Open a project', 'Provider and model settings'], 'Quit')
                        if choice == 0:
                            break
                        if choice in (1, 2):
                            self.new_project('article' if choice == 1 else 'book')
                        elif choice == 3:
                            self.choose_project()
                        else:
                            self.provider_menu()
                    else:
                        try:
                            self.status()
                        except (ValueError, OSError, KeyError, TypeError):
                            self.folder = None
                            raise
                        label, action = self.next_step()
                        choice = self.choice('Project dashboard', [f'Continue — {label}',
                            'Brief — topic, authors, citations and style',
                            'Inspiration — add documents or reuse analysis',
                            'Abstract — create or resume', 'Manuscript — generate or resume',
                            'Review — read/edit abstract, outline, sources and audit',
                            'Export — Word, PDF, HTML, text or RTF',
                            'Settings — provider, model and API key'], 'Back to home')
                        if choice == 0:
                            self.folder = None
                        elif choice == 1:
                            if action == 'review':
                                self.review()
                            else:
                                self.workflow(action)
                        elif choice == 2:
                            self.edit_brief()
                        elif choice == 3:
                            self.inspiration_menu()
                        elif choice == 4:
                            self.workflow('abstract')
                        elif choice == 5:
                            self.workflow('generate')
                        elif choice == 6:
                            self.review()
                        elif choice == 7:
                            self.export_menu()
                        else:
                            self.provider_menu()
                except HomeRequested:
                    self.folder = None
                except (Cancelled, KeyboardInterrupt):
                    self.write('\nCancelled. Returning to the menu; saved work is retained.')
                except (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError) as exc:
                    self.write(f'KOALA: {exc}')
        except (EOFError, KeyboardInterrupt, QuitRequested):
            self.write('\nLeaving the menu; saved work is retained.')
        finally:
            for name, original in self.changed_keys.items():
                if original is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = original
        self.write('Goodbye.')
        return 0


def run_menu(project=None):
    return Menu(project).run()
