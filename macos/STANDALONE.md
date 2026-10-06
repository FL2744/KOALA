# Standalone macOS distribution

A standalone build includes the SwiftUI interface, frozen Python runtime, KOALA
engine, Pandoc, TLS certificate bundle, and document/citation dependencies. Users
need no Python installation or source checkout. API credentials and internet
access are still needed for inference and online research.

## Build

Build on the oldest macOS version you intend to support, with Python and binary
dependencies compatible with that version. The build architecture determines the
app architecture; this does not produce a universal Intel/Apple Silicon binary.

```bash
python3 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install -r macos/standalone-requirements.txt
python -m pip install .
python macos/build_standalone.py --output dist/KOALA.app
```

Use a fresh output path for another build. The script produces the app and an
architecture-labelled ZIP, signs the app ad hoc, and verifies its signature.
Dependency notices are in `Contents/Resources/ThirdPartyNotices`. Preserve those
notices and applicable third-party source redistribution obligations when publishing.

The initial local package was built for **Apple Silicon (arm64), macOS 26 or
later**, because its Python runtime targets macOS 26. It has been tested on the
build Mac, including a relocated copy; it has not been tested on other Macs.

## macOS 15 build (Apple Silicon)

Use a Python runtime and binary dependencies built for macOS 15 or earlier. The
Homebrew Python used for the original package requires macOS 26; changing the
app plist alone cannot make that runtime compatible with macOS 15.

The macOS 15 candidate uses CPython 3.13.16 from uv's managed Python distribution:

```bash
uv python install 3.13.16
uv venv --python 3.13.16 --managed-python .venv-build-macos15
uv pip install --python .venv-build-macos15/bin/python -r macos/standalone-requirements.txt .
.venv-build-macos15/bin/python macos/build_standalone.py --minimum-macos 15.0 --output dist/macos15/KOALA.app
```

`build_standalone.py` checks every bundled Mach-O binary's deployment target and
rejects absolute non-system library dependencies. The audit can also be run alone:

```bash
python macos/audit_bundle.py dist/macos15/KOALA.app --minimum-macos 15.0
```

These checks catch incompatible runtimes and libraries; they do not replace a
launch and workflow test on a real macOS 15 Mac. The candidate is Apple Silicon
only. The build script signs ad hoc; Developer ID signing and notarization are
separate steps for each newly built artifact.

## Test

```bash
dist/KOALA.app/Contents/Resources/engine/koala-engine --self-test
```

The self-test exercises project creation, MLA and Chicago rendering, DOCX, PDF,
HTML, TXT and RTF exports. It makes no paid inference calls. Also test the app
interactively and on a clean target Mac before a stable release.

The standalone app ignores saved development-engine paths and locates its engine
inside its own bundle. New projects default to `~/Documents/KOALA/output`.
Existing projects can be opened anywhere with appropriate read/write access.
Prompt templates remain under `~/Library/Application Support/KOALA`.

## Signing and release

Ad-hoc signing is not Apple Developer ID signing or notarization. This build is
suitable for local testing but may be blocked by Gatekeeper after download.
For a normal public download, sign embedded executable code and the final app
with a Developer ID Application identity using hardened runtime, submit the
archive with `xcrun notarytool`, and staple the accepted ticket before recreating
the release ZIP. A suitable signing identity was unavailable for the original build, so this
step was not performed for that artifact. The separate v0.22.0-macos15
prerelease has since been Developer ID signed, notarized, and stapled. Builds
produced by this script still require those release steps; do not label them
notarized or universal.

Do not distribute the development app made by `build_app.py` as a standalone
installer: that build intentionally depends on the local source checkout.
