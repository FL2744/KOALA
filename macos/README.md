# KOALA for macOS

KOALA has a native SwiftUI/AppKit graphical interface. It launches as a regular macOS application with a Dock icon, menus, resizable window, sidebar, and native file pickers. It does not open Terminal or run a local web server.

## Run

Open `~/Applications/KOALA.app` in Finder or Spotlight. The current local installation uses `~/VIBES/KOALA/.venv/bin/python` and the source in that project's `src` directory.

Click **Open** and choose an existing project folder, or **New** to create an article or book. The application reads the same briefs, checkpoints, analysis caches, and exports as the CLI. Your existing projects do not need conversion.

### Workspace

- **Overview:** project progress and the suggested next step.
- **Brief:** subject, audience, journal/publisher guidance, source candidates, up to 999 authors, word counts, chapters, and style. Save edits explicitly.
- **Inspiration:** native DOCX/PDF file selection, local reuse of completed analysis, and extracted ideas/evidence.
- **Abstract:** create, read, edit, and save the guiding abstract.
- **Manuscript:** generate/resume and read sections, outline, sources, and citation/length audit.
- **Export:** select DOCX, PDF, HTML, TXT, and RTF, then open the generated files or reveal them in Finder.
- **Settings:** provider, model, live model discovery/filtering, optional endpoint, session API key, and Python-project location.

The activity panel reports progress and validation messages. **Stop**, or **Project → Stop Operation**, interrupts the Python task. Completed checkpoints are retained. Resume through the same generation button. Quitting while edits or a task are pending prompts before discarding/stopping them.

Keys are held in memory for the current app session and supplied to the child Python process through its environment. They are not saved in preferences or project files. Recent project paths are saved in macOS preferences. Use either the CLI or app to write a given project at a time; native app writes use a project lock.

## Build

Requirements: macOS 13+, Xcode command-line tools, Python 3.10+, and an installed KOALA Python environment.

From the repository root:

```sh
python3 macos/build_app.py --output "$HOME/Applications/KOALA.app"
```

The build refuses to overwrite an existing app. For an update, build to a new path, quit the old application, then replace it with the new build. The script compiles for the current Mac's architecture, converts `koala-logo.png` into the app icon, writes bundle metadata, and applies an ad-hoc local signature.

This is a local application build, not a standalone distribution: Python and dependencies remain in the project virtual environment. If the project moves, choose **Settings → Locate KOALA folder**. Public distribution would additionally require packaging a Python runtime and release signing/notarization.

## Implementation

- `KOALA.swift`: native UI, background process lifecycle, streamed activity, secure input, file pickers, and project state.
- `../src/koala/desktop.py`: one-request stdin JSON / stdout JSON-lines bridge. It shares existing brief validation, draft/revision logic, inference providers, and exporters.
- `build_app.py`: reproducible local bundle build.

The bridge emits `progress`, `result`, and `error` events. It never invokes a shell. Existing model availability, source-grounding, AI disclosure, and checkpoint rules apply unchanged.

## Verification

- SwiftUI source compiled successfully for Apple Silicon with a macOS 13 deployment target.
- Bundle signature and Info.plist validation passed.
- The installed app launched successfully; its welcome layout and native Open dialog were visually inspected. An existing project loaded in the native interface.
- A read-only bridge check opened the existing book checkpoint and verified its file hash was unchanged.
- All 149 Python tests pass, including mocked full article generation/export through the bridge, book setup, author lists, inspiration reuse, settings, file locking, error events, and cancellation.
- No live inference or API-key entry was performed by the assistant during these checks.

## Citation update (0.10.0)

Brief now offers MLA and Chicago author–date. Repair → Start citation repair archives and repairs existing prose, with required-author coverage under Audit and an evidence count under Sources. See [the citation guide](../docs/CITATIONS.md). Citation-only brief changes preserve prose; changing the citation style only requires re-export.

## Outline import (0.11.0)

In a book project, choose **Outline → Import outline…**. DOCX, PDF, TXT, and Markdown are supported. Review the editable text and Save brief. Explicit numbered chapter titles determine the count and order, up to 30 chapters; notes guide planning and section development. Import is local and does not call an LLM. Saving a changed outline archives an existing draft and restarts planning.

## Dedicated workspaces (0.12.0)

The sidebar now includes **Outline** and **Repair**. Outline provides the import/preview/editor workflow with explicit saving. Repair shows citation and author coverage, search and missing-author filters, source-ledger access, and resumable repair progress. Overview routes citation-repair tasks to this page for review before starting inference. No existing manuscript is rewritten by this interface update.
