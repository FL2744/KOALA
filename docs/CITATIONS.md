# Citations and required authors

KOALA now tracks **distinct cited works**, **citation occurrences**, and **required authors** separately. Repeating one work 100 times does not meet a target of 100 distinct works. The usual targets are 50–100 works for articles and 200–800 for books. Set the target in Brief. Each entry in Important authors / Required authors requires an in-text citation to a matching authored work; merely mentioning a name or citing a work about that person does not count.

## Repair an existing manuscript

1. Open the project in the macOS app. In **Brief**, import or paste the required authors and set the target. Author lists accept semicolons or newlines, up to 999 entries. A plain `.txt` filename is now read as a file rather than searched as an author's name; relative paths are resolved against the brief/project directory.
2. Choose **MLA** or **Chicago author–date**, then save. Citation-only brief changes retain the manuscript. Changing style alone requires only a new export.
3. Choose **Repair → Start citation repair**. The CLI menu offers **Review → Repair citations / required authors**. This action uses your provider/API key and may incur inference charges. It archives the original manuscript and exports, researches missing references, and revises sections with explicit citation budgets. Interrupted repairs resume at the next unfinished section.
4. Review **Manuscript → Audit** for author-by-author status and **Sources** for the evidence count. `citation-coverage.json` records the complete preflight report. A missing work, a work lacking evidence, and a supported but uncited work are separate states.
5. Supply missing source evidence, then retry Repair citations. **Sources → Open source ledger** opens `sources.json`. Add accurate abstracts, your research notes, or passages with exact locators to its records. Repair reloads this ledger, preserving existing source IDs; use a curated ledger in Brief to make a separate source file authoritative.
6. Export the revised manuscript. Draft exports remain available for review; choose strict audit mode to block exports with outstanding issues. Generation/repair does not mark a manuscript complete when citation coverage is below its target.

The command-line equivalents are:

```sh
koala repair-citations --out output/book --resume --authors-file authors.txt --citation-style chicago-author-date
koala audit output/book/article.json
koala export output/book/article.json --citation-style mla --formats docx pdf
```

Use `--no-research` with repair to use your existing/curated ledger without network discovery. Repair still uses the selected LLM to revise prose. Formatting and audits do not call an LLM.

## What changed in research and drafting

Author searches are no longer lost behind the old 30-query article limit. Author searches verify the names in the returned authorship metadata instead of accepting title mentions. Open Library edition metadata supplements authors poorly represented by Crossref. Catalog records are not treated as textual evidence. Query results and batch selections are cached; source selection preserves at least one matching candidate for each requested author. Inferred authors from inspiration documents remain research suggestions; only explicitly supplied authors are required.

Before drafting, KOALA checks whether enough works have abstracts, notes, or passages and whether each required author has a supported work. A shortfall produces a report before writing tens of thousands of words. Each section has a budget for new works and required author references; repeated citations cannot substitute for breadth. Failed attempts are saved, with specific feedback for a bounded retry. Quantitative checks do not prove the relevance or truth of a citation: scholarly review remains necessary.

Names are matched conservatively across accents, initials, and family/given ordering. Distinct given names such as Sam Harris and Tristan Harris are not merged. For pseudonyms or historical name variants that cannot be resolved automatically, supply verified `author_aliases` in the corresponding source record. Do not add an alias just to silence a coverage warning.

## MLA and Chicago

KOALA uses bundled CSL styles with Pandoc's citation processor, with no online formatting request. New projects default to **Chicago author–date (18th edition)**. **MLA (9th edition)** is also available. The previous `author-date` and `numeric` options remain for compatibility. Chicago here means the parenthetical author–date system, not footnotes/endnotes.

- MLA uses author–page citations and a **Works Cited** list.
- Chicago uses author–year citations, with locators when supplied, and a **References** list.
- Disambiguation, multi-author citations, reference sorting, and book-title italics come from the CSL styles. TXT necessarily omits italics; DOCX, HTML, RTF, and PDF retain them.
- The app's manuscript preview displays formatted citation text; exports preserve rich formatting.
- References are edition-specific. Provide accurate publisher, year, translator/editor, type, and edition information. The `csl` object can supply richer CSL metadata and structured names. Automatic metadata must still be checked, especially for classical texts, translated works, and unusual names.

These conventions follow [Purdue's MLA guide](https://owl.purdue.edu/owl/research_and_citation/mla_style/mla_formatting_and_style_guide/mla_in_text_citations_the_basics.html) and [Chicago's author–date examples](https://www.chicagomanualofstyle.org/tools_citationguide/citation-guide-2). They concern citations and references; KOALA does not impose every journal's document-layout requirements.

## Located source passages

The source ledger can hold passages such as this **synthetic schema example**:

```json
{
  "id": "S001",
  "type": "book",
  "title": "Example Book",
  "authors": ["Example Author"],
  "year": "2020",
  "publisher": "Example Press",
  "notes": "Replace with accurate research notes about the actual source.",
  "passages": [
    {"id": "P1", "text": "Replace with the exact source passage.", "locator": "42", "label": "page"}
  ]
}
```

The internal marker `[@S001#P1]` refers to that passage and its recorded locator. Generated markers cannot invent a passage ID or a page number. Ordinary `[@S001]` refers to the whole work without an invented locator. The publication's entire page range is never used as a pinpoint. Supported labels are page, chapter, section, paragraph, and line. Page numbers depend on the edition actually consulted; add them for specific quotations and passages when available. A bare author citation does not establish support for a quotation.

All exports retain the AI-assistance disclosure. Third-party CSL licenses and attribution are in [the bundled styles notice](../src/koala/styles/README.md); KOALA's own code remains MIT-licensed.
