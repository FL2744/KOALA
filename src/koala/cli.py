"""KOALA command-line interface."""
import argparse
import json
import sys
from pathlib import Path
from . import DISCLAIMER, __version__, is_book, disclaimer_for
from .core import DEFAULT_BRIEF, audit, load_brief, normalize_brief, read_json, save, words
from .exporters import FORMATS, export
from .pipeline import continue_prepare, draft, prepare
from .providers import Provider
from .coverage import ResearchApprovalRequired, authorize_research, citation_readiness


def parser():
    p = argparse.ArgumentParser(prog='koala', description='KOALA — Knowledge-Oriented Australian Literary Analysis')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command')
    menu = sub.add_parser('menu', help='Open the interactive project menus (default)')
    menu.add_argument('project', nargs='?', type=Path, help='Optional project folder to open')
    init = sub.add_parser('init', help='Create an editable JSON research brief')
    init.add_argument('path', nargs='?', default='brief.json')
    init.add_argument('--interactive', action='store_true')
    manuscript_options(init)
    models = sub.add_parser('models', help='Fetch models available to your provider account')
    provider_options(models)
    for command in ('abstract', 'generate', 'ingest', 'repair-citations', 'repair-manuscript'):
        run = sub.add_parser(command, help={'abstract': 'Create a guiding abstract', 'generate': 'Research and draft an article or book',
                                                'ingest': 'Add DOCX/RTF/TXT/HTML/PDF inspiration before or during manuscript production',
                                                'repair-citations': 'Research and repair citation coverage in saved prose', 'repair-manuscript':'Apply conservative global prose fixes to saved sections'}[command])
        if command == 'repair-manuscript':
            run.add_argument('--instructions',help='Global repair instructions; defaults to fixing abstract/record wording or resuming saved instructions')
            run.add_argument('--restart-repair',action='store_true',help='Archive current prose and start a new repair pass')
        if command == 'ingest':
            run.add_argument('documents', nargs='+', type=Path, help='DOCX/RTF/TXT/HTML/PDF files to analyse and incorporate')
        run.add_argument('--document', action='append', type=Path, default=[],
                         help='Add a DOCX/RTF/TXT/HTML/PDF inspiration document (repeatable)')
        run.add_argument('--brief', type=Path)
        run.add_argument('--out', type=Path, default=Path('output'))
        if command == 'generate':
            run.add_argument('--allow-incomplete-research',action='store_true',help='Authorize a provisional draft despite source/author shortfalls, after printing the warning')
            run.add_argument('--research-approval',help=argparse.SUPPRESS)
        run.add_argument('--resume', action='store_true', help='Continue the saved project in --out')
        run.add_argument('--no-research', action='store_true', help='Use a curated or inherited source ledger without new discovery')
        run.add_argument('--formats', nargs='+', choices=FORMATS, default=['docx', 'html', 'txt', 'rtf', 'pdf'])
        run.add_argument('--pdf-font', type=Path)
        run.add_argument('--strict', action='store_true', help='Do not export a manuscript with audit issues')
        provider_options(run)
        manuscript_options(run)
    exp = sub.add_parser('export', help='Export an existing article without inference')
    exp.add_argument('article', type=Path)
    exp.add_argument('--out', type=Path)
    exp.add_argument('--formats', nargs='+', choices=FORMATS, default=list(FORMATS))
    exp.add_argument('--abstract-only', action='store_true')
    exp.add_argument('--pdf-font', type=Path)
    exp.add_argument('--strict', action='store_true')
    exp.add_argument('--citation-style', choices=('mla','chicago-author-date','author-date','numeric'))
    outline = sub.add_parser('import-outline', help='Import a book outline locally; archive existing prose before replanning')
    outline.add_argument('path', type=Path)
    outline.add_argument('--out', type=Path, required=True, help='Existing book project folder')
    check = sub.add_parser('audit', help='Check abstract length, citations, and article length')
    check.add_argument('article', type=Path)
    return p


def manuscript_options(p):
    p.add_argument('--citation-style', choices=('mla','chicago-author-date','author-date','numeric'))
    p.add_argument('--authors-file', type=Path, help='Required authors, separated by semicolons or newlines')
    p.add_argument('--type', dest='project_type', choices=('article', 'book'), help='Project form (default: article)')
    p.add_argument('--words', dest='target_words', type=int, help='Body word target; books: 40000–100000')
    p.add_argument('--chapters', dest='chapter_count', type=int, help='Book main chapters: 5–8, plus introduction')
    p.add_argument('--citations', dest='citation_target', type=int, help='Distinct cited works; book default scales 200–800')
    p.add_argument('--afterword', dest='include_afterword', action='store_true', default=None, help='Include a book afterword')
    p.add_argument('--appendix', dest='appendices', action='append', help='Appendix title (repeatable)')


def brief_overrides(args):
    overrides = {key: getattr(args, key) for key in ('project_type', 'target_words', 'chapter_count',
            'citation_target', 'include_afterword', 'appendices', 'citation_style') if getattr(args, key, None) is not None}

    if getattr(args,'authors_file',None):
        from .coverage import resolve_authors
        overrides['important_authors'] = resolve_authors({'important_authors':[str(args.authors_file.resolve())]},Path.cwd())['important_authors']
    return overrides


def provider_options(p):
    p.add_argument('--provider', choices=('openai', 'arc'), default=None)
    p.add_argument('--model', help='Exact provider model ID; OpenAI default: gpt-6-luna')
    p.add_argument('--base-url', help='Override provider HTTPS API base URL')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in (None, 'menu'):
            from .menu import run_menu
            return run_menu(getattr(args, 'project', None))
        if args.command == 'import-outline':
            from .menu import Menu
            from .outlines import read_outline
            menu = Menu(); menu.open_project(args.out)
            brief = menu.brief()
            if not is_book(brief): raise ValueError('Open a book project to import a chapter outline.')
            data = read_outline(args.path)
            menu.save_brief({**brief, 'chapter_outline': data['text']})
            print(f'Imported {data["name"]}; {data["chapter_count"] or "no explicit"} numbered chapters detected.')
            return 0
        if args.command == 'init':
            path = Path(args.path)
            if path.exists():
                raise ValueError(f'{path} already exists; choose another path.')
            brief = normalize_brief({}, brief_overrides(args))
            if is_book(brief) and args.citation_target is None:
                brief['citation_target'] = None
            if args.interactive:
                for key in ('topic', 'discipline', 'target_publishers' if is_book(brief) else 'target_journals',
                            'similar_books' if is_book(brief) else 'similar_articles',
                            'possible_citations', 'important_authors', 'important_ideas',
                            'research_guidance', 'style_guidance'):
                    answer = input(f'{key.replace("_", " ").capitalize()} (blank = infer; lists separated by ;): ').strip()
                    brief[key] = [v.strip() for v in answer.split(';') if v.strip()] if isinstance(brief[key], list) else answer
            save(path, brief)
            print(f'Created {path.resolve()}')
            return 0
        if args.command == 'models':
            provider = Provider(args.provider or 'openai', args.model, args.base_url)
            print('\n'.join(provider.models()))
            return 0
        if args.command == 'audit':
            report = audit(read_json(args.article))
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1 if report['issues'] else 0
        if args.command == 'export':
            article = read_json(args.article)
            if args.citation_style: article['brief']['citation_style'] = args.citation_style
            paths = export(article, args.out or args.article.parent, args.formats,
                           args.abstract_only, args.pdf_font, args.strict)
        else:
            incoming = args.document + (args.documents if args.command == 'ingest' else [])
            if args.command == 'repair-manuscript' and incoming:
                raise ValueError('Import inspiration separately before repairing manuscript prose.')
            resuming = args.command in ('repair-citations','repair-manuscript') or args.resume or (args.command == 'ingest' and (args.out / 'article.json').exists())
            if resuming:
                article = read_json(args.out / 'article.json')
                saved_brief = normalize_brief(article['brief'])
                requested = load_brief(args.brief, brief_overrides(args)) if args.brief else normalize_brief(article['brief'], brief_overrides(args))
                if requested != saved_brief and args.command != 'repair-citations':
                    raise ValueError('Resume brief differs from the checkpoint. Start a new output directory for a changed brief.')
                provider = Provider(args.provider or article['provider'], args.model or article['model'], args.base_url)
                provider.check_model()
                if incoming:
                    article['pending_documents'] = list(dict.fromkeys(article.get('pending_documents', []) +
                        [str(p.expanduser().resolve()) for p in incoming]))
                    save(args.out / 'article.json', article)
                base = Path(article.get('brief_directory', '.'))
                if args.command == 'repair-manuscript':
                    from .manuscript_repair import repair_manuscript
                    article=repair_manuscript(provider,article,args.out,args.instructions,args.restart_repair,lambda text:print(text,file=sys.stderr))
                    print('Change report: '+article['manuscript_repair']['report'])
                    print(disclaimer_for(article))
                    return 0
                elif args.command == 'repair-citations':
                    from .repair import repair_citations
                    if requested != saved_brief:
                        article.pop('citation_repair',None)
                        article['brief'] = requested
                    article = repair_citations(provider, article, args.out, args.no_research, lambda text: print(text,file=sys.stderr))
                    save(args.out/'brief.json',article['brief'])
                else:
                    article = continue_prepare(provider, article, args.out, base, args.no_research,
                                               lambda text: print(text, file=sys.stderr), ingest_only=args.command == 'ingest')
            else:
                brief = load_brief(args.brief, brief_overrides(args))
                provider = Provider(args.provider or 'openai', args.model, args.base_url)
                provider.check_model()
                article = prepare(provider, brief, args.out, args.brief, args.no_research,
                                  lambda text: print(text, file=sys.stderr), documents=incoming,
                                  ingest_only=args.command == 'ingest')
            if args.command == 'ingest':
                print(disclaimer_for(article))
                for document in article.get('inspiration', {}).get('documents', []):
                    print(f"{document['name']}: {document['chunk_count']} chunks; {document['analysis_file']}")
                digest = article.get('inspiration', {}).get('digest') or {}
                print(digest.get('overview', ''))
                for field in ('ideas', 'themes', 'authors', 'citations', 'research_questions', 'style_notes'):
                    if digest.get(field):
                        print(field.replace('_', ' ').capitalize() + ':')
                        for finding in digest[field]:
                            print('  - ' + finding['text'])
                print(f'Continue with: koala generate --out {str(args.out)!r} --resume')
                return 0
            if args.command == 'generate':
                if args.allow_incomplete_research or args.research_approval:
                    for warning in citation_readiness(article)['blockers']:print('Research warning: '+warning,file=sys.stderr)
                    authorize_research(article,args.out,args.research_approval,args.allow_incomplete_research)
                article = draft(provider, article, args.out, lambda text: print(text, file=sys.stderr))
                for issue in article['audit']['issues']:
                    print(f'Review: {issue}', file=sys.stderr)
            for warning in article.get('warnings', []):
                print(f'Research note: {warning}', file=sys.stderr)
            paths = export(article, args.out, args.formats, args.command == 'abstract', args.pdf_font,
                           args.strict and args.command != 'abstract')
            print(f'Abstract: {words(article["abstract"])} words')
        print(disclaimer_for(article))
        for path in paths:
            print(path.resolve())
        return 0
    except ResearchApprovalRequired as exc:
        print(f'KOALA: {exc}',file=sys.stderr)
        return 3 if args.command == 'generate' else 2
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError) as exc:
        print(f'KOALA: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('\nInterrupted. Resume from the last saved checkpoint with --resume.', file=sys.stderr)
        return 130
