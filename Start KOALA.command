#!/bin/sh
# Double-click launcher for macOS. Uses the existing project-local installation.
cd -- "$(dirname -- "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    printf '%s\n' 'Install KOALA first using the setup instructions in README.md.'
    printf '%s' 'Press Enter to close.'
    read -r answer
    exit 1
fi
exec .venv/bin/python -m koala menu
