#!/usr/bin/env bash

set -euo pipefail

APP_NAME="Mouser"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${MOUSER_INSTALL_ROOT:-$HOME/.local/share/Mouser}"
BIN_DIR="${MOUSER_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_ROOT/venv"
DIST_DIR="$INSTALL_ROOT/dist"
LAUNCHER="$BIN_DIR/mouser"
VALIDATION_LOG="$(mktemp "${TMPDIR:-/tmp}/mouser-install.XXXXXX.log")"

cleanup() {
  rm -f "$VALIDATION_LOG"
  rm -rf "$REPO_ROOT/build" "$REPO_ROOT/dist"
}

trap cleanup EXIT

if [[ -z "${PYTHON:-}" ]]; then
  PYTHON_BIN="python3"
else
  PYTHON_BIN="$PYTHON"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN is not available on PATH" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin|Linux) ;;
  *)
    echo "error: supported on macOS and Linux only" >&2
    exit 1
    ;;
esac

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

cd "$REPO_ROOT"
"$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"

export PYINSTALLER_CONFIG_DIR="$INSTALL_ROOT/pyinstaller"

case "$(uname -s)" in
  Darwin)
    "$VENV_PYTHON" -m PyInstaller "$REPO_ROOT/Mouser-mac.spec" --noconfirm
    APP_BIN="$REPO_ROOT/dist/Mouser.app/Contents/MacOS/Mouser"
    ;;
  Linux)
    "$VENV_PYTHON" -m PyInstaller "$REPO_ROOT/Mouser-linux.spec" --noconfirm
    APP_BIN="$REPO_ROOT/dist/Mouser/Mouser"
    ;;
esac

if [[ ! -x "$APP_BIN" ]]; then
  echo "error: expected build output was not created: $APP_BIN" >&2
  exit 1
fi

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

if [[ "$(uname -s)" == "Darwin" ]]; then
  cp -R "$REPO_ROOT/dist/Mouser.app" "$DIST_DIR/"
  APP_BIN="$DIST_DIR/Mouser.app/Contents/MacOS/Mouser"
else
  cp -R "$REPO_ROOT/dist/Mouser" "$DIST_DIR/"
  APP_BIN="$DIST_DIR/Mouser/Mouser"
fi

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$APP_BIN" "\$@"
EOF
chmod +x "$LAUNCHER"

if ! "$LAUNCHER" --hid-backend=bogus >"$VALIDATION_LOG" 2>&1; then
  if ! grep -q "Invalid --hid-backend setting" "$VALIDATION_LOG"; then
    echo "error: installed command did not validate as expected" >&2
    cat "$VALIDATION_LOG" >&2
    exit 1
  fi
else
  echo "error: expected validation command to fail" >&2
  exit 1
fi

echo "Installed $APP_NAME to: $DIST_DIR"
echo "Launcher: $LAUNCHER"
echo "Validation: passed"
