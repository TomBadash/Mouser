#!/bin/zsh
#
# install_macos_app.sh — build Mouser.app and install it into /Applications.
#
# Thin wrapper around build_macos_app.sh: it runs the PyInstaller build
# (producing dist/Mouser.app), then replaces any existing install in
# /Applications with the fresh bundle and launches it.
#
# It honors the same environment variables as build_macos_app.sh
# (MOUSER_PYTHON, MOUSER_SIGN_IDENTITY, PYINSTALLER_TARGET_ARCH) since
# those are simply inherited by the child process.
#
# The build always runs on local disk: the repo may sit on a network volume,
# and codesign rejects the resource-fork metadata SMB/AFP shares attach to
# files (see build_macos_app.sh). The finished bundle is then copied into the
# Applications folder, which is on the Mac's internal drive.
#
# Usage:
#   ./install_macos_app.sh                          # build + install + launch
#   MOUSER_INSTALL_DIR="$HOME/Applications" ./install_macos_app.sh
#   MOUSER_BUILD_DIR="$HOME/mouser-build" ./install_macos_app.sh
#   MOUSER_NO_LAUNCH=1 ./install_macos_app.sh       # install without launching
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Mouser.app"
# Build artifacts go to local disk; tell build_macos_app.sh to use the same
# location so we know exactly where the finished bundle lands.
BUILD_OUTPUT_DIR="${MOUSER_BUILD_DIR:-$HOME/Library/Caches/Mouser/macos-build}"
export MOUSER_BUILD_DIR="$BUILD_OUTPUT_DIR"
BUILT_APP="$BUILD_OUTPUT_DIR/dist/$APP_NAME"
DEST_DIR="${MOUSER_INSTALL_DIR:-/Applications}"
DEST_APP="$DEST_DIR/$APP_NAME"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: this installer must be run on macOS." >&2
  exit 1
fi

# ── 1. Build ────────────────────────────────────────────────────────
echo "==> Building $APP_NAME"
"$ROOT_DIR/build_macos_app.sh"

if [[ ! -d "$BUILT_APP" ]]; then
  echo "ERROR: build did not produce $BUILT_APP" >&2
  exit 1
fi

# ── 2. Quit any running copy so the bundle can be replaced cleanly ──
if pgrep -x Mouser >/dev/null 2>&1; then
  echo "==> Quitting running Mouser"
  osascript -e 'quit app "Mouser"' >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6; do
    pgrep -x Mouser >/dev/null 2>&1 || break
    sleep 0.5
  done
  pkill -x Mouser >/dev/null 2>&1 || true
fi

# ── 3. Install into the Applications folder ─────────────────────────
if [[ ! -d "$DEST_DIR" ]]; then
  echo "ERROR: install directory does not exist: $DEST_DIR" >&2
  exit 1
fi
if [[ ! -w "$DEST_DIR" ]]; then
  echo "ERROR: $DEST_DIR is not writable by this user." >&2
  echo "       Install to a user-owned folder instead, e.g.:" >&2
  echo "         MOUSER_INSTALL_DIR=\"\$HOME/Applications\" $0" >&2
  exit 1
fi

echo "==> Installing to $DEST_APP"
rm -rf "$DEST_APP"
# ditto preserves bundle symlinks, extended attributes and the code signature.
ditto "$BUILT_APP" "$DEST_APP"

echo "==> Installed: $DEST_APP"

# ── 4. Launch (unless opted out) ────────────────────────────────────
if [[ -z "${MOUSER_NO_LAUNCH:-}" ]]; then
  echo "==> Launching Mouser"
  open "$DEST_APP"
fi

cat <<'EOF'

Done. This is an ad-hoc-signed local build, so the first launch of a new
build may require re-granting Accessibility permission:
  System Settings -> Privacy & Security -> Accessibility
If a stale "Mouser" entry is already listed there, remove it (the - button)
and re-add the new bundle, otherwise macOS may keep using the old permission
record and remapping will appear dead.
EOF
