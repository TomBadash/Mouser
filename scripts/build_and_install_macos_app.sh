#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This wrapper must be run on macOS. Use scripts/build_and_install.py instead." >&2
  exit 1
fi

exec python3 "$ROOT_DIR/scripts/build_and_install.py"
