#!/bin/sh
# Koobs launcher for Linux and macOS.
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/app/koobs.py" "$@"
