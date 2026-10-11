#!/usr/bin/env bash
# SMSL AO300 custom firmware: the one-step installer. Creates a Python virtual environment next
# to this script, installs the dependencies into it and runs the installer wizard
# (tools/installer/ao300_installer.py). Arguments are passed on to the wizard (see --help).
#
# Do not run this with sudo: on macOS the serial port needs no elevation, and on Linux add
# yourself to the serial group instead (sudo usermod -aG dialout "$USER", then log in again).
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(id -u)" = 0 ] && [ -z "${AO300_ALLOW_ROOT:-}" ]; then
    echo "Please run this as your normal user, not with sudo (see the README)." >&2
    exit 1
fi

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        PY="$candidate"; break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.8 or newer is needed. macOS: install the Xcode command line tools (xcode-select --install)" >&2
    echo "or python.org's installer; Linux: your distribution's python3 package." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Creating the Python environment in .venv ..."
    if ! "$PY" -m venv .venv; then
        echo "Could not create a virtual environment. On Debian/Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

STAMP=.venv/.requirements.sha256
WANT="$("$PY" -c 'import hashlib,sys; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
    echo "Installing the dependencies (stcgal, pefile, pyserial) ..."
    .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
    echo "$WANT" > "$STAMP"
fi

exec .venv/bin/python tools/installer/ao300_installer.py "$@"
