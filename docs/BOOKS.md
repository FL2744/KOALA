# Scholarly books with KOALA

Book projects use the same research brief, DOCX/PDF inspiration, provider selection, abstract, citation ledger, and five export formats as articles. Book mode adds a chapter plan, long-form drafting, and manuscript-level audits.

## Start a book

```sh
cd ~/VIBES/KOALA
source .venv/bin/activate
koala init book.json --type book --words 65000 --chapters 6 --interactive
# Edit book.json as needed, then:
koala abstract --brief book.json --out output/book
koala generate --out output/book --resume
```

Alternatively, create everything in one run:

```sh
koala generate --type book --words 65000 --chapters 6 --out output/book
```

Use `--provider arc` and `--model MODEL_ID` exactly as for articles. The OpenAI default remains GPT-5.6-luna. Configure your provider API key before inference.

## Length, structure, and citations

- Book body targets must be **40,000–100,000 words**; the default is **65,000**.
- Choose **5–8 main chapters**; the default is **6**, plus an introduction.
- An afterword is optional. Appendices are optional; supply up to eight titles.
- Citation targets must be **200–800 distinct cited works**. Citation occurrences are counted separately.
- The default citation target scales linearly: 200 at 40,000 words, 450 at 65,000, and 800 at 100,000. Use `--citations 350` for an explicit target.
- Book briefs created by `init` store `"citation_target": null` for automatic scaling. Changing `target_words` before starting a run recalculates the target. A running checkpoint stores the resolved numeric target for reproducibility.

Optional divisions:

```sh
koala init book.json --type book --words 80000 --chapters 8 \
  --afterword --appendix "Source catalogue" --appendix "Methodological notes"
```

Equivalent fields in the JSON brief are `project_type`, `target_words`, `chapter_count`, `citation_target`, `include_afterword`, and `appendices`. Use `target_publishers` for scholarly presses or series and `similar_books` for comparable works; journal/article inputs remain available too. All other existing brief fields work with books. See `examples/book-brief.json`.

The body word budget includes the introduction, chapters, afterword, and appendices. It excludes the abstract, headings, contents list, reference list, and structured citation markers. The introduction initially receives 8% of the budget; the afterword receives 3% if enabled, and appendices share 5% if present. Main chapters share the remainder. The saved chapter plan records these allocations.

## DOCX/PDF inspiration

```sh
koala ingest "research-notes.docx" --type book --out output/book
koala abstract --out output/book --resume
koala generate --out output/book --resume
```

You can also use `--document`, `inspiration_files`, and `.docx`/`.pdf` entries in `source_files`. Add another DOCX or PDF at any later stage with `koala ingest new-notes.docx --out output/book`. The previous manuscript, exports, and research-selection state are archived before replanning. Existing source IDs and human source notes are retained. Subsequent generation rebuilds the abstract and all chapters to incorporate the new direction; archived prose is not silently deleted.

## How long manuscripts are drafted

KOALA first generates a book outline, then a 250–300-word guiding abstract. Each chapter is divided into sections initially budgeted at no more than 1,200 words. A detailed chapter outline is generated just before its sections are drafted. The remaining word budget is adjusted using actual completed prose lengths.

Completed sections are saved immediately, followed by short continuity summaries. Completed chapters also receive summaries. Later sections receive the chapter structure, summaries, a recent passage, relevant excerpt windows, document inspiration, and up to 40 selected source records. They do not receive the entire growing book. Long source abstracts/notes are excerpted in generation prompts; complete source records remain in the ledger.

Automatic source discovery scales up for books. Candidate relevance is assessed in batches of 40, with saved selection progress. A curated `sources_file` remains useful for books or archival projects that Crossref cannot adequately cover. Discovered records and document-derived citation candidates do not prove relevance or claim support. KOALA reports source shortfalls rather than forcing irrelevant citations.

A book requires substantially more inference calls than an article: ordinarily one drafting call and one continuity-summary call per section, chapter planning/summary calls, and any research-selection or document-analysis calls. No fixed completion time or cost is assumed.

## Resume and review

```sh
koala generate --out output/book --resume
koala audit output/book/article.json
```

The checkpoint is still named **`article.json`** for compatibility; its `brief.project_type` identifies a book. It contains chapters, section budgets, generated prose, summaries, the source ledger, and the audit. A summary failure does not discard the preceding drafted section. Retry with `--resume`. Do not run two commands against the same output directory concurrently.

Start a new output directory if changing project type, word target, chapter count, optional divisions, or other brief settings. Resume refuses conflicting settings. For manuscript revisions beyond document ingestion, work on a copy of the checkpoint. If you edit prose, clear its `continuity_summary` and the corresponding chapter summary so they can be regenerated. If you clear all `sections` to redraft, also remove chapter `continuity_summary` fields; keep the structural `plan.sections` budget slots intact.

Book section drafts must pass citation-marker and word-length checks before being saved as complete. Individual sections allow ±25% around the current word target, while the remaining budget adjusts to actual prose lengths. Unambiguous grouped S-ID citations are expanded to individual markers; unavailable IDs remain rejected. Up to three attempts receive specific correction feedback. Every attempt, including rejected prose, is retained under `draft-attempts/section-NNNN/<run-id>/` with counts, allowed IDs, and validation issues. Earlier completed sections remain available. The audit checks the absolute 40,000–100,000-word range, deviation from the chosen target (±10%), chapter structure and order, abstract length, citation validity, and citation shortfalls. It reports words and distinct cited works for each chapter. `--strict` blocks export when audit issues remain. Actual scholarly quality and source support still need editorial review; automated counts do not establish publication readiness.

## Exports

```sh
koala export output/book/article.json --formats docx html txt rtf pdf
koala export output/book/article.json --strict
```

The files are **`manuscript.docx`**, **`manuscript.html`**, **`manuscript.txt`**, **`manuscript.rtf`**, and **`manuscript.pdf`**. They include a contents list, numbered chapters, subordinate section headings, optional divisions, and one consolidated bibliography. DOCX/PDF/RTF start major divisions on new pages; DOCX/PDF include page numbers. The contents list names divisions but does not include automatically calculated page references. HTML applies chapter breaks when printing.

All manuscript and abstract exports include:

> This book manuscript was generated with the assistance of artificial intelligence.

The abstract-only command retains the `abstract.*` filenames. Existing article export names and workflows remain supported.

### Continuity-summary recovery

Each completed section is saved before its continuity summary is requested. Oversized summaries are shortened locally. If the summary is missing, blank, wrongly typed, or invalid JSON, KOALA uses bounded excerpts from the saved prose for continuity instead. This adds no summary retries and does not regenerate the section. The same recovery applies to chapter summaries. Network/authentication failures still surface with saved progress intact. Resume with the project menu's **Manuscript — generate or resume** option.
