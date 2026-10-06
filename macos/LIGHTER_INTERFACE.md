# Lighter macOS interface

This branch starts from `v0.22.0-macos15` (`03f7cae`) and changes only the native
interface styling in `macos/KOALA.swift`.

The workspace uses a near-white background, a pale teal sidebar, white cards and
editor surfaces, and softer borders. Grouped panels share a consistent card
style. Existing teal accents and semantic system text colors remain, with native
dark-mode surfaces selected through adaptive colors. No Python engine, project
format, or inference behavior is changed.

## Resume on the release Mac

1. Fetch and check out `ui/lighter-macos15`.
2. Build using the macOS 15 environment described in `STANDALONE.md`, keeping the
   normal KOALA bundle identifier and release metadata.
3. Inspect the interface in light and dark modes, including the Brief editors,
   grouped panels, welcome cards, sidebar, and sheets.
4. Apply the existing Developer ID signing and notarization workflow, staple the
   accepted ticket, then package and verify the release archive.

The laptop preview used a separate bundle identifier and an ad-hoc signature.
Those preview-only packaging changes are **not** part of this source branch.
The original release's notarization does not cover a rebuilt application.

## Validation completed on the laptop

- SwiftUI source compiled for Apple Silicon with a macOS 15.0 deployment target.
- `git diff --check` passed.
- The preview bundle passed strict code-signature verification.
- All 32 bundled Mach-O binaries passed the macOS 15 deployment-target and
  external-library audit; the original release's engine and dependencies were
  reused unchanged.

Visual inspection by the assistant and runtime testing on macOS 15 remain
pending. No new notarized release was produced or published from the laptop.
