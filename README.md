<p align="center">
  <img src="koala-logo.png" alt="KOALA — a koala wearing red glasses and reading a book" width="600">
</p>

<h1 align="left">KOALA</h1>
<p align="left"><strong>Knowledge-Oriented Australian Literary Analysis</strong></p>
<p align="left">A native macOS AI writing studio for scholarly articles and books.</p>

KOALA helps develop humanities and social-science manuscripts from an initial idea through research, a guiding abstract, drafting, revision, and export. Start with a detailed brief, import documents and data, or leave optional fields open for the model to develop.

Every exported manuscript includes a plain statement that it was generated with the assistance of artificial intelligence. Outputs are scholarly drafts for human review: references, interpretations, quotations, and claims need checking before publication.

## Features

- **Articles and books:** articles of 1,000–20,000 words; books of 40,000–100,000 words. Books normally have an introduction and 5–8 chapters; imported outlines support additional chapters, with optional afterwords and appendices.
- **Brief and Ideas:** define the subject, authors, ideas, audience, and style. Use inference to generate ten title choices, research ideas, authors, a starter bibliography, a 250–300-word abstract, and a table of contents. Review suggestions before applying them.
- **Research and citations:** discover primary and secondary literature, maintain a source ledger, and track required authors and citation coverage. MLA is the default; Chicago author-date is also available. Citation targets are typically 50–100 works for articles and 200–800 for books, but are not a guarantee of verified coverage.
- **Literature reviews:** introduction prompts require cited engagement with relevant previous scholarship and an explanation of the manuscript’s contribution, using available evidence.
- **Inspiration:** import DOCX, PDF, RTF, TXT, or HTML; long documents are analyzed in chunks. HTML scripts and formatting are stripped. Reuse completed inspiration analysis across projects. Scanned PDFs require OCR first.
- **Bibliography and outlines:** import existing bibliographies and chapter outlines to guide research and structure.
- **Data:** upload CSV, TSV, flat JSON records, or TXT. Run local descriptive statistics, missing-value checks, frequencies, and group comparisons, or request model-assisted interpretation and thematic analysis. Review and explicitly include selected findings in future generation.
- **Style and prompts:** enter an author or influence, writing traits, or a custom main writing prompt. Fields are optional. Inspirations use broad craft traits, with general characteristics rather than imitation of a living author’s distinctive voice.
- **Repair and rewrite:** make targeted global repairs or create a separate substantive rewrite using revised parameters. Review before/after reports, retain backups, and resume interrupted work. Rewrites preserve the existing chapter structure and use existing evidence.
- **Exports:** DOCX, HTML, TXT, RTF, and PDF, with citation formatting and an AI-assistance disclosure.
- **Project management:** named projects, recent projects, checkpoints, and a confirmed Delete Project action that moves the project folder to macOS Trash.

## Requirements

- Python 3.10 or later.
- An OpenAI or Virginia Tech ARC API account and an available model.
- For the native app: macOS 13 or later and Xcode Command Line Tools.
- Internet access for inference and literature discovery. Local analysis and export do not require inference.

## Install

```bash
git clone https://github.com/FL2744/KOALA.git
cd KOALA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### Native macOS app

If needed, install Apple’s command-line tools:

```bash
xcode-select --install
```

Build the app, then open it:

```bash
python macos/build_app.py
open ~/Applications/KOALA.app
```

The build script refuses to overwrite an existing app. Move an older build aside before rebuilding. The app uses the Python environment and project directory from which it was built; keep that directory in place. This is a local build, not a notarized standalone installer.

Create or open a project, complete **Brief**, then use **Ideas**, **Inspiration**, **Bibliography**, **Data**, and **Style** as needed. Create the researched abstract before generating the manuscript. Enter provider credentials in **Settings**.

### Menu-driven CLI

```bash
source .venv/bin/activate
koala menu
```

On macOS, `Start KOALA.command` also starts the menu-driven CLI. Use `koala --help` for command options.

## Providers and credentials

OpenAI inference defaults to the model ID `gpt-6-luna`. Availability depends on the account; choose another model in Settings or list available models:

```bash
export OPENAI_API_KEY="your-api-key"
koala models --provider openai
```

For Virginia Tech ARC, use `ARC_API_KEY` and select the ARC provider. The default API endpoint is `https://llm-api.arc.vt.edu/api/v1`; access and model availability depend on your ARC account. The application supports endpoint overrides.

API keys entered in the application are held for the session. For shell configuration, see [.env.example](.env.example); KOALA does not automatically load `.env` files. Do not commit credentials.

## Working with existing manuscripts

**Repair** applies conservative text edits for recurring problems. **Rewrite** creates a separate candidate using revised topic, emphasis, style, or length parameters. Enter those changes on Rewrite before saving a changed Brief. Review the candidate, choose **Use rewritten manuscript**, and export again. The original remains backed up.

Style-only and title-only changes preserve existing prose. Other brief changes may restart planning after archiving the prior draft. Citation formatting changes take effect when you re-export.

Citation counts and required-author coverage are goals. If research falls short, KOALA can ask you to authorize proceeding with the available evidence. Citation-count shortfalls during drafting are review notes rather than reasons to stop generation. Unsupported sources, quotations, and page locators must not be invented.

## Data and privacy

Project files contain manuscript text, research material, imported data, and revision history. Local projects and outputs are excluded from this repository. Keep your own backups.

Model-assisted operations send relevant project context to the selected inference provider. Data interpretation uses computed summaries and up to the first 100 rows or 30,000 text characters; this is not a random sample. Local numerical analyses are descriptive, not significance tests or evidence of causality. Import limits are 20 MB per file, 100,000 rows, and 200 columns.

## Documentation and development

- [Usage guide](docs/USAGE.md)
- [Book manuscripts](docs/BOOKS.md)
- [Citations and source evidence](docs/CITATIONS.md)
- [Writing guidance](docs/WRITING_STYLE.md)
- [Example briefs](examples/)

Run the test suite:

```bash
python -m unittest discover -s tests
```

The Python engine lives in `src/koala/`; the native SwiftUI application is in `macos/KOALA.swift`. Tests use fixtures and mocked inference rather than paid model calls.

## License

KOALA is [MIT licensed](LICENSE). Bundled CSL styles retain their upstream Creative Commons Attribution–ShareAlike license, including the modified MLA style; see [style notices](src/koala/styles/README.md). Pandoc and other dependencies retain their own licenses.
