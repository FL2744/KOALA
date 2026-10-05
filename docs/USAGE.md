# KOALA usage guide

**Knowledge-Oriented Australian Literary Analysis**

A menu-driven Python tool for abstract-led scholarly articles and books in the humanities and social sciences. The name reflects its default subject when no brief is supplied; you can work in any humanities or social-science discipline.

KOALA accepts target journals or journal types, comparable articles, candidate references, important authors and ideas, subject/research guidance, and prose style. Blank fields are inferred and recorded in the research plan. Article defaults are 6,500 words and 75 distinct cited works. Book defaults are 65,000 words, six chapters plus an introduction, and 450 distinct cited works. Abstracts must contain 250–300 words before drafting proceeds.

Every exported article and article abstract includes this exact statement:

> This article was generated with the assistance of artificial intelligence.

## Install

Python 3.10 or later is required.

```sh
cd ~/VIBES/KOALA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
koala
```

Windows activation: `.venv\Scripts\activate`. The core CLI uses Python's standard library; DOCX and PDF exports use python-docx and ReportLab. No Pandoc or office suite is required.

## Menu-driven quick start

On macOS, double-click **Start KOALA.command** in this folder after installation. Or launch from a terminal:

```sh
cd ~/VIBES/KOALA
source .venv/bin/activate
koala
```

Choose a numbered option to create an article, create a book, open a project, or configure your inference provider. Each project has menus for editing the brief, importing DOCX/PDF inspiration, creating the guiding abstract, drafting/resuming, reviewing results, and exporting DOCX, HTML, TXT, RTF, and PDF. No JSON editing is required. Blank subject guidance lets KOALA infer a direction.

Use **Settings** to select OpenAI or Virginia Tech ARC, enter an API key with hidden input, and fetch/filter the provider’s available models. The default OpenAI model is `gpt-6-luna`; availability depends on your account. Keys entered here last only for the menu session and are never saved. Provider/model and export preferences are saved per project in `.koala-menu.json`. Existing environment variables also work.

Import a DOCX or PDF before creating the abstract or between later stages. Use **Review** to read the abstract, outline, source ledger, inspiration notes, and citation/length audit. Editing a started brief or abstract archives the previous draft and exports under `revisions/` before restarting affected work. Drafting can resume from saved checkpoints. Enter **0** to go back; Ctrl+C cancels the current action and returns to the menu.

To open an existing project directly:

```sh
koala menu output/my-project
```

## Project dashboard navigation

The project dashboard shows your folder, progress, and suggested next step. Choose **1 — Continue** to create the abstract, start/resume the manuscript, or review a finished manuscript. Other actions remain available directly: **2 Brief**, **3 Inspiration**, **4 Abstract**, **5 Manuscript**, **6 Review**, **7 Export**, **8 Settings**. Inspiration groups new document imports and cross-project reuse. Menu paths show your location. At menus use `b`/`0` for back, `h` for home, `q` to quit, and `?` for help; blank input redisplays the menu. Shortcuts do not apply to free-text fields.

## Commands for scripting

All previous commands remain available. `koala --help` lists them.

Set your key in the shell (it is never written to output files). The `.env.example` file documents environment variables; it is not loaded automatically.

```sh
export OPENAI_API_KEY='your-api-key'
koala models --provider openai
koala init brief.json --interactive
# Edit brief.json as needed.
koala abstract --brief brief.json --out output/memory
# Review/edit the abstract in output/memory/article.json, then continue:
koala generate --out output/memory --resume
```

Or run all stages together:

```sh
koala generate --brief brief.json --out output/article
```

To let KOALA infer all subject choices:

```sh
koala generate --out output/inferred
```

Each run folder must be new unless `--resume` is supplied. Inference and research require internet access. OpenAI usage is billed to your API account. A run uses planning, source selection, abstract generation, and one request per article section, with bounded corrective retries.

## Book manuscripts

```sh
koala init book.json --type book --words 65000 --chapters 6
koala generate --brief book.json --out output/book
```

Book mode supports **40,000–100,000 words**, **5–8 main chapters plus an introduction**, optional `--afterword` and repeatable `--appendix "Title"`, and **200–800 distinct cited works**. Citation targets scale automatically with length unless overridden using `--citations`. The 250–300-word abstract, DOCX/PDF inspiration, source research, and provider choices work in both modes.

Books are drafted in short sections with checkpoints and continuity summaries. Exports use `manuscript.*`, include a contents list and chapter structure, and state: “This book manuscript was generated with the assistance of artificial intelligence.” See [the book guide](BOOKS.md) for examples, word accounting, resume behaviour, audits, and limitations.

## DOCX/PDF inspiration at any stage

Import one or more Word or PDF documents by path. In this CLI, importing a local file is the equivalent of uploading it. Documents can supply ideas, themes, important authors, candidate citations, research questions, and style observations. No topic or brief is required to begin.

Start with a document before writing the abstract:

```sh
koala ingest "inspiration.docx" --out output/my-article
koala abstract --out output/my-article --resume
koala generate --out output/my-article --resume
```

Or include it directly in article or abstract creation:

```sh
koala generate --document "inspiration.docx" --out output/new-article
koala abstract --brief brief.json --document "inspiration.docx" --out output/new-abstract
```

Add documents after planning, after the abstract, during drafting, or after completing the article:

```sh
koala ingest "another-document.docx" --out output/my-article
koala generate --out output/my-article --resume
# Alternatively, incorporate and regenerate in one command:
koala generate --out output/my-article --resume --document "another-document.docx"
```

`ingest` analyses and attaches the document, then stops before planning or drafting. When a document changes an existing article, KOALA archives its checkpoint, exports, and audit in `revisions/<revision-id>/`, retains its existing source ledger, and marks the active article for replanning. The next `abstract` or `generate --resume` rebuilds the plan and abstract using the new inspiration. `generate` also redrafts all sections so completed sections can reflect the new material. Previous manually edited prose remains in the archive; it is not automatically retained verbatim in the new draft. Repeated imports of identical content are ignored. Use these commands between runs; do not concurrently write to the same run directory.

Multiple documents work with `koala ingest first.docx second.pdf --out output/my-article`, repeated `--document` options, or an `inspiration_files` list in the brief. Paths in the brief are relative to the brief file; CLI paths are relative to your current directory. `.docx` and `.pdf` entries in `source_files` are also automatically routed through document analysis. Existing briefs and checkpoints remain compatible.

### Large documents and evidence

For DOCX, KOALA reads body paragraphs, tables, footnotes, and endnotes. For PDF, it extracts text page by page with pypdf. It splits text into chunks of at most 6,000 characters with a 200-character overlap, including when a single paragraph is unusually long. It analyses each chunk once under normal operation, then combines findings locally into a bounded digest without synthesis calls. Older cached imports retain their original chunk boundaries so completed analyses can be reused. The complete document is never sent in one model request. Completed chunk analyses and combination progress are cached; rerun the same command after a failure to continue. A content hash detects revised documents, and analysis caches are separated by provider/model.

The digest deduplicates and keeps a stable sample of up to six findings per category; it is not a relevance ranking or exhaustive index. All chunk findings and extracted chunk text remain available under `documents/<document-hash>/<analysis-cache>/chunks/`. `analysis.json` in that folder contains the final digest, document hash, provider/model, chunk count, and limitations. `article.json` records the attached documents and active digest. These generated JSON files include the AI disclosure.

Findings retain supporting verbatim excerpts and document/chunk identifiers. Minor spacing and curly/straight quotation-mark differences are matched back to the original source text. KOALA gives the model numbered source excerpts on the first request and copies the selected evidence directly. Unsupported quotations, names, and references are omitted with warnings recorded in chunk files and the final manifest; valid findings continue to be analysed. Oversized lists are capped locally rather than triggering a retry. A chunk with no retained findings is marked explicitly. Network and malformed-response errors still stop the run with saved progress available. DOCX locations refer to XML paragraphs. PDF locations use one-based file page indices (for example `pdf:page:3`), which may differ from printed page labels. Extracted author names and citation strings must occur in the input text. Citation candidates feed source discovery and remain unverified until matched/reviewed; they are never automatically inserted into the authoritative bibliography. The source ledger can still be curated by the user. `--no-research` uses a supplied or inherited ledger without looking up new citation candidates.

The original file is read locally. Extracted text and summary findings are sent to your selected inference provider, and candidate searches can be sent to Crossref. Local analysis caches contain document text. Images, charts, equations, comments, headers/footers, and page layout are not analysed; image-only documents require OCR first. Each uncompressed DOCX XML part has a 256 MiB limit. PDFs must be readable without a password; unlock protected files before importing. PDF reading order, table text, and character encoding can be imperfect. Pages with no extractable text are recorded in `analysis.json` under `extraction.pages_without_text` and reported after analysis; these may be blank or scanned pages. Scanned/image-only files require OCR before import. Large documents require more model calls: normally one analysis per uncached chunk. Combining chunks and documents requires no model calls.

## Models and providers

OpenAI defaults to **`gpt-6-luna`** through the Responses API. Models are fetched live from `/v1/models`, and the chosen model is checked before inference. KOALA never silently substitutes a different model. Model listing can include non-text models; choose a model supporting text generation through Responses.

```sh
koala models --provider openai
koala generate --brief brief.json --out output/custom --model MODEL_ID
```

Virginia Tech ARC uses its OpenAI-compatible Chat Completions API:

```sh
export ARC_API_KEY='your-personal-arc-key'
koala models --provider arc
koala generate --provider arc --model MODEL_ID --brief brief.json --out output/arc
```

The ARC default is `gpt-oss-120b`, checked against the live model list. Obtain your personal key at [llm.arc.vt.edu](https://llm.arc.vt.edu), under User profile → Settings → Account → API keys. The documented API base is `https://llm-api.arc.vt.edu/api/v1`. `--base-url`, `ARC_BASE_URL`, and `OPENAI_BASE_URL` can override HTTPS endpoints. An explicit custom endpoint receives that provider's API key. For scripted commands, endpoint overrides must be supplied again on resume. The menu saves its endpoint preference per project; API keys are not persisted.

ARC output is divided into sections with requests capped at 8,000 tokens. Incomplete responses fail rather than being treated as finished text. Very large briefs, excerpt sets, or source pools may exceed a selected model's context limit; use focused excerpts and a curated source ledger for such runs.

## Brief fields

See [the example brief](../examples/brief.json). All fields are optional. List fields contain strings.

| Field | Purpose |
| --- | --- |
| `topic`, `discipline` | Subject and scholarly field |
| `target_journals` | Journal names, types, or descriptions |
| `similar_articles` | Titles, DOIs, or descriptions of comparable work |
| `possible_citations` | Candidate titles, bibliographic descriptions, or DOIs |
| `important_authors`, `important_ideas` | Authors and concepts to address |
| `research_guidance` | Question, scope, approach, constraints, and evidence |
| `style_guidance` | Academic tone, structure, spelling, and prose preferences |
| `target_words` | Article: 1,000–20,000; book: 40,000–100,000 |
| `project_type` | `article` (default) or `book` |
| `chapter_count` | Book main chapters, 5–8; default 6 |
| `include_afterword`, `appendices` | Optional book afterword (boolean) and appendix titles (list) |
| `target_publishers`, `similar_books` | Book audience, presses/series, and comparable works |
| `citation_target` | Article: 1–200 (default 75); book: 200–800, or null for automatic scaling |
| `citation_style` | `mla`, `chicago-author-date` (default), or legacy `author-date` / `numeric` |
| `source_files` | UTF-8 `.txt`/`.md` excerpts or DOCX/RTF/HTML/PDF documents, relative to the brief |
| `inspiration_files` | `.docx`/`.rtf`/`.txt`/`.html`/`.htm`/`.pdf` inspiration documents, relative to the brief |
| `sources_file` | Optional curated JSON source list, relative to the brief |

Prose style is separate from bibliography style. MLA 9 and Chicago 18 author–date use a CSL processor; Chicago footnotes/endnotes and OCR are not implemented. See [Citations and repair](CITATIONS.md). Links in a brief are search hints, not automatically read full texts. Supply excerpts to guide close reading or style comparisons.

## Research and source integrity

KOALA searches Crossref using the brief and generated research queries, deduplicates DOI records, then asks the model to select relevant candidates. It never asks the model to invent bibliographic metadata. Set `CROSSREF_MAILTO` to identify your requests to Crossref's polite pool.

The source ledger distinguishes **metadata-only** records from supplied evidence. Crossref metadata verifies a registered record's existence, not whether a claim is supported, and its coverage of books, archives, and non-English scholarship is uneven. Search matches may be irrelevant; inspect `candidates.json` and `sources.json`. The system may return fewer sources than requested and reports shortfalls instead of padding references.

For substantive interpretation, provide source abstracts, focused excerpts, or your research notes. Associate notes/excerpts with source IDs (for example `S001`). Bibliographic existence, source relevance, quotation accuracy, and claim support still require human review. KOALA does not perform fieldwork, experiments, or archival visits and is instructed not to invent such work. Its output is a draft, not a validated or publication-ready research article.

To use a curated library instead of Crossref:

```json
[
  {
    "id": "S001",
    "title": "The exact title of a real work",
    "authors": ["Author's full name"],
    "year": "2020",
    "container": "Journal or book title",
    "doi": "",
    "abstract": "A supplied abstract, if available",
    "notes": "Your grounded notes and page-located evidence",
    "verification": "user-supplied"
  }
]
```

The example above is a schema illustration, not a citation. Reference the file with `sources_file` in your brief, then run `koala generate --brief brief.json --no-research --out output/curated`. IDs must be unique and match `S` followed by at least three digits. A curated file replaces automatic discovery and is not independently verified. Imported sources are sent to the selected model provider along with the brief and excerpts. Research queries are sent to Crossref.

## Outputs and audit

```sh
koala export output/article/article.json --formats docx html txt rtf pdf
koala audit output/article/article.json
koala export output/article/article.json --strict
```

Outputs: `article.docx`, `article.html`, `article.txt`, `article.rtf`, and `article.pdf`. The abstract command creates `abstract.*` equivalents. Use `--formats html txt` to choose a subset. `--pdf-font /path/to/font.ttf` supplies a TrueType font for scripts absent from the default font. Missing PDF glyphs cause an explicit error.

`article.json` is the editable checkpoint and contains the brief, inferred assumptions, plan, abstract, sections, sources, disclosure, and provider/model provenance. `sources.json` is the source ledger. `candidates.json` records discovered candidates. `audit.json` records abstract/body length, distinct cited works, citation occurrences, unknown IDs, and shortfalls. The JSON research outputs carry the AI disclosure too. User input/configuration files are not generated articles.

Internally, citations use `[@S001]`. Export converts them to readable author-date or numbered citations and includes only cited works in the bibliography. Unknown or malformed markers block export. The audit counts only these structured markers; it cannot detect every unsupported claim or stray model-written citation. Do not replace markers with manually formatted citations before exporting.

Abstract length is a hard drafting prerequisite. Article body length and citation shortfalls produce review messages by default; book drafting also enforces section word budgets, and book audits check the absolute 40,000–100,000-word range; `--strict` blocks manuscript export if any audit issue remains. A failed strict export still leaves the checkpoint available for revision. `koala audit` exits 1 on issues, 0 on success; operational errors exit 2.

## Resume and revise

```sh
koala generate --out output/article --resume
```

Checkpoints are saved after planning, source research, the abstract, and every complete section. Retry transient failures with `--resume`. Edit the checkpoint abstract before drafting; its 250–300 word count is checked again. If you change the abstract or plan after drafting, clear the `sections` list in a copy of the checkpoint to redraft all sections. Do not run two processes against the same output folder. Start a new run for a changed brief. Provider/model overrides on resume are recorded in the checkpoint.

## Development and verification

```sh
python -m pip install pypdf
PYTHONPATH=src python -m unittest discover -s tests -v
```

The document tests additionally cover large DOCX chunking, notes/tables, grounded extraction, cached retries, pre-abstract input, late-stage revisions, and source-discovery integration.

Tests use synthetic fixtures and mocked inference, with no API charges. They cover provider payloads, model discovery, abstract retries, resumable drafting, DOI deduplication, citation checks, all five exports, Unicode, HTML escaping, and the required disclosure. See [VALIDATION.md](../VALIDATION.md) for the build's verification and live-test limitations.

## API references

- [OpenAI model listing](https://developers.openai.com/api/reference/resources/models/methods/list)
- [OpenAI text generation](https://developers.openai.com/api/docs/guides/text)
- [Virginia Tech ARC API](https://docs.arc.vt.edu/ai/011_llm_api_arc_vt_edu.html)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)

PDF extraction uses [pypdf](https://pypdf.readthedocs.io/en/latest/user/extract-text.html); it does not perform OCR.

## Reuse inspiration across projects

Choose project menu option **3 — Inspiration → 2 — Reuse analysis from another project**, enter a source project folder, and choose a completed analysis or all completed analyses. No inference, API key, provider match, or original source document is required. The analysis and evidence cache are copied locally with original model provenance; the source project is not changed. Reimports of the same document hash are skipped. Existing destination drafts and exports are archived using the standard inspiration revision workflow. Then create/resume the destination abstract or manuscript. Incomplete caches are not offered: complete analysis in the source project first.

## Large author lists

`important_authors` accepts up to 999 strings for articles and books. The menu shows the saved count. In **Brief → Important authors**, paste semicolon-separated names or enter `@/path/to/authors.txt` (UTF-8; semicolons or newlines separate names). File import replaces the existing list and uses the normal brief-revision workflow. Lists over 999 are rejected without changing the saved brief. Book prompt context retains all authors rather than the former first-30 subset. Each explicitly listed author is required citation coverage. Missing works and evidence are reported; use Repair citations to update existing prose. Citation-only brief changes preserve prose.


### Text and web-page inspiration

Inspiration imports accept **DOCX, RTF, TXT, HTML (.html or .htm), and PDF** through the macOS file picker, CLI import menu, `koala ingest`, and the brief’s `inspiration_files`. TXT, RTF, and HTML files have a 32 MiB input limit and use the same 6,000-character analysis chunks and resumable checkpoints as other inspiration. TXT/MD files placed in `source_files` retain their existing short-excerpt behavior; use `inspiration_files` or Import for large TXT documents.

HTML is parsed locally into readable text. Scripts, styles, comments, metadata, tags/attributes, inline-hidden elements, navigation, forms, embedded objects, and preformatted/code blocks are omitted. Paragraph and table-cell boundaries are retained, and entities are decoded. No JavaScript executes and no linked resources are fetched. Content rendered only by JavaScript is unavailable; export it as text or PDF first. Stylesheet class rules are not evaluated, so some page furniture may remain. RTF formatting is removed with [striprtf](https://github.com/joshy/striprtf), retaining readable text and Unicode characters. UTF-8 and BOM-marked UTF-16/32 text files are supported, with Windows-1252 fallback; HTML character-set declarations are honored where supported.

Only extracted, cleaned text enters the analysis workflow. All uploaded text remains research data, not instructions to the model. Scanned PDFs still require OCR before import.
