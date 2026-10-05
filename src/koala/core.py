"""Data validation, durable checkpoints, and citation auditing."""
import json
import re
from pathlib import Path
from . import DISCLAIMER, is_book, disclaimer_for

from .citations import MARKER, STYLES, locator_issues

MAX_AUTHORS = 999

DEFAULT_BRIEF = {
    "project_type": "article", "chapter_count": 6, "include_afterword": False,
    "chapter_outline": "", "appendices": [], "target_publishers": [], "similar_books": [],
    "manuscript_title": "", "topic": "", "discipline": "", "target_journals": [],
    "similar_articles": [], "possible_citations": [], "important_authors": [],
    "important_ideas": [], "research_guidance": "", "style_guidance": "", "writing_prompt": "", "writing_prompt_name": "KOALA default",
    "target_words": 6500, "citation_target": 75, "citation_style": "mla",
    "source_files": [], "sources_file": "", "inspiration_files": []
}


def words(text):
    return len(re.findall(r"\b[\w]+(?:[’'-][\w]+)*\b", text))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def scaled_citations(target_words):
    return max(200, min(800, 200 + round((target_words - 40000) / 100)))


def normalize_brief(supplied, overrides=None):
    if not isinstance(supplied, dict):
        raise ValueError("Brief must be a JSON object.")
    supplied = {**supplied, **(overrides or {})}
    unknown = set(supplied) - set(DEFAULT_BRIEF)
    if unknown:
        raise ValueError(f"Unknown brief fields: {', '.join(sorted(unknown))}")
    book = supplied.get('project_type') == 'book'
    defaults = {**DEFAULT_BRIEF}
    if book:
        defaults.update(target_words=65000, citation_target=None)
    brief = {**defaults, **supplied}
    for key, default in DEFAULT_BRIEF.items():
        if key == 'citation_target' and brief[key] is None:
            continue
        if type(brief[key]) is not type(default):
            raise ValueError(f"{key} must be a {type(default).__name__}.")
        if isinstance(default, list) and any(not isinstance(x, str) for x in brief[key]):
            raise ValueError(f"{key} must contain strings.")
    if len(brief['manuscript_title'])>300 or '\n' in brief['manuscript_title']:
        raise ValueError('Manuscript title must be a single line of at most 300 characters.')
    if len(brief['writing_prompt']) > 30000 or len(brief['writing_prompt_name']) > 120:
        raise ValueError('Writing prompts support up to 30,000 characters and names up to 120 characters.')
    if len(brief['important_authors']) > MAX_AUTHORS:
        raise ValueError(f'important_authors accepts at most {MAX_AUTHORS} authors.')
    if brief['project_type'] not in ('article', 'book'):
        raise ValueError('project_type must be article or book.')
    from .outlines import validate_outline, outline_extras
    supplied_titles = validate_outline(brief['chapter_outline'])
    if brief['chapter_outline'].strip() and not book:
        raise ValueError('Chapter outlines are for book projects.')
    if book:
        if supplied_titles: brief['chapter_count'] = len(supplied_titles)
        extras = outline_extras(brief['chapter_outline'])
        if extras.get('afterword'): brief['include_afterword'] = True
        if extras['appendices']: brief['appendices'] = extras['appendices']
        if not 40000 <= brief['target_words'] <= 100000:
            raise ValueError('Book target_words must be between 40000 and 100000.')
        lower, upper = (1,30) if brief['chapter_outline'].strip() else (5,8)
        if not lower <= brief['chapter_count'] <= upper:
            raise ValueError(f'Book chapter_count must be between {lower} and {upper}, excluding the introduction.')
        if len(brief['appendices']) > 8 or any(not title.strip() for title in brief['appendices']):
            raise ValueError('Provide up to 8 nonempty appendix titles.')
        if brief['citation_target'] is None:
            brief['citation_target'] = scaled_citations(brief['target_words'])
        if not 200 <= brief['citation_target'] <= 800:
            raise ValueError('Book citation_target must be between 200 and 800, or null for automatic scaling.')
    else:
        if brief['citation_target'] is None:
            brief['citation_target'] = 75
        if not 1 <= brief['citation_target'] <= 200:
            raise ValueError("citation_target must be between 1 and 200.")
        if not 1000 <= brief['target_words'] <= 20000:
            raise ValueError("target_words must be between 1000 and 20000.")
    if brief['citation_style'] not in STYLES:
        raise ValueError("citation_style must be mla, chicago-author-date, author-date (legacy), or numeric.")
    return brief


def load_brief(path, overrides=None):
    from .coverage import resolve_authors
    raw = read_json(path) if path else {}
    return normalize_brief(resolve_authors(raw, Path(path).resolve().parent if path else Path.cwd()), overrides)


def prose_words(text):
    return words(MARKER.sub('', text))


def validate_sources(sources):
    if not isinstance(sources, list):
        raise ValueError("Sources must be a JSON list.")
    seen = set()
    for s in sources:
        if not isinstance(s, dict) or not re.fullmatch(r'S\d{3,}', s.get('id', '')):
            raise ValueError("Every source requires an ID such as S001.")
        if s['id'] in seen:
            raise ValueError(f"Duplicate source ID: {s['id']}")
        seen.add(s['id'])
        if not s.get('title') or 'authors' not in s or not s.get('year'):
            raise ValueError(f"{s['id']} needs title, an authors list (empty for an anonymous work), and year.")
        if not isinstance(s['authors'], list) or not all(isinstance(a, str) and a.strip() for a in s['authors']):
            raise ValueError("Source authors must be a list of names.")
        if not isinstance(s.get('author_aliases',[]),list) or not all(isinstance(a,str) and a.strip() for a in s.get('author_aliases',[])):
            raise ValueError('author_aliases must contain verified name strings.')
        if not isinstance(s.get('csl',{}),dict): raise ValueError('csl metadata must be an object.')
        passages = s.get('passages', [])
        if not isinstance(passages, list): raise ValueError('Source passages must be a list.')
        passage_ids = set()
        for passage in passages:
            if not isinstance(passage,dict) or not re.fullmatch(r'[A-Za-z0-9_-]+',str(passage.get('id',''))) or passage['id'] in passage_ids:
                raise ValueError('Each source passage needs a unique alphanumeric ID.')
            passage_ids.add(passage['id'])
            if not isinstance(passage.get('text'),str) or not passage['text'].strip():
                raise ValueError('Each source passage needs nonempty text.')
            if passage.get('locator') is not None and not isinstance(passage['locator'],str):
                raise ValueError('Passage locators must be strings.')
            if passage.get('label','page') not in ('page','chapter','section','paragraph','line'):
                raise ValueError('Unsupported passage locator label.')
    return sources


def cited_ids(text):
    return [m[1] for m in MARKER.finditer(text)]


def audit(article):
    body = '\n\n'.join(s['text'] for s in article.get('sections', []))
    ids = cited_ids(body)
    known = {s['id'] for s in article.get('sources', [])}
    unknown = sorted(set(ids) - known)
    abstract_count = words(article.get('abstract', ''))
    issues = []
    if not 250 <= abstract_count <= 300:
        issues.append(f"Abstract has {abstract_count} words; required range is 250–300.")
    if unknown:
        issues.append(f"Unknown citation IDs: {', '.join(unknown)}")
    residue = MARKER.sub('', body)
    if '[@' in residue:
        issues.append("Malformed citation marker(s).")
    target = article.get('brief', {}).get('citation_target', 75)
    distinct = len(set(ids) & known)
    if distinct < target:
        issues.append(f"Citation shortfall: {distinct} distinct works cited; target {target}.")
    from .coverage import author_coverage, has_evidence
    authors = author_coverage(article.get('brief', {}), article.get('sources', []), ids, body)
    missing_authors = [r['author'] for r in authors if r['status'] != 'cited']
    if missing_authors:
        issues.append('Required authors not cited: ' + '; '.join(missing_authors))
    unsupported = [s['id'] for s in article.get('sources', []) if s['id'] in ids and not has_evidence(s)]
    if unsupported:
        issues.append('Citations without source evidence: ' + ', '.join(unsupported))
    issues.extend(locator_issues(body, article.get('sources', [])))
    body_words = prose_words(body)
    target_words = article.get('brief', {}).get('target_words', 6500)
    tolerance = 0.1 if is_book(article) else 0.2
    if not (1 - tolerance) * target_words <= body_words <= (1 + tolerance) * target_words:
        issues.append(f"Body has {body_words} words; target {target_words} (±{int(tolerance*100)}%).")
    expected_sections = article.get('plan', {}).get('sections', [])
    if expected_sections and len(article.get('sections', [])) != len(expected_sections):
        issues.append('Draft is incomplete: section count does not match the plan.')
    if not article.get('sections'):
        issues.append("No article sections have been drafted.")
    chapter_report = []
    if is_book(article):
        if not 40000 <= body_words <= 100000:
            issues.append('Book body must contain 40,000–100,000 words, excluding abstract and references.')
        from .books import validate_book_plan
        try:
            validate_book_plan(article.get('plan', {}), article['brief'])
        except ValueError as exc:
            issues.append(f'Book structure: {exc}')
        for index, chapter in enumerate(article.get('plan', {}).get('chapters', [])):
            text = '\n'.join(s['text'] for s in article.get('sections', []) if s.get('chapter_index') == index)
            chapter_report.append({'heading': chapter['heading'], 'kind': chapter['kind'],
                                   'words': prose_words(text), 'target_words': chapter.get('target_words'),
                                   'distinct_cited_works': len(set(cited_ids(text)) & known)})
        for i, section in enumerate(article.get('sections', [])):
            if i >= len(expected_sections) or section.get('chapter_index') != expected_sections[i].get('chapter_index'):
                issues.append('Book section order/chapter assignments do not match the plan.')
                break
    return {"disclaimer": disclaimer_for(article), "chapters": chapter_report, "abstract_words": abstract_count,
            "body_words": body_words, "distinct_cited_works": distinct,
            "citation_target": target, "author_coverage": authors, "missing_authors": missing_authors,
            "citation_occurrences": len(ids), "unknown_ids": unknown, "issues": issues,
            "note": "Metadata matching does not verify that a source supports a claim. Human review is required."}
