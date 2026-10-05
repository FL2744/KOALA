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
the release ZIP. The current machine has no suitable signing identity, so this
step has not been performed. Do not label the ZIP notarized or universal.

Do not distribute the development app made by `build_app.py` as a standalone
installer: that build intentionally depends on the local source checkout.
