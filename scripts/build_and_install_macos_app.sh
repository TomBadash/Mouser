#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Mouser.app"
BUILD_OUTPUT="$ROOT_DIR/dist/$APP_NAME"
INSTALL_DIR="${MOUSER_INSTALL_DIR:-/Applications}"
INSTALL_PATH="$INSTALL_DIR/$APP_NAME"
ENV_LOCAL="$ROOT_DIR/.env.local"

if [[ -f "$ENV_LOCAL" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_LOCAL"
  set +a
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

resolve_sign_identity() {
  if [[ -n "${MOUSER_SIGN_IDENTITY:-}" ]]; then
    echo "$MOUSER_SIGN_IDENTITY"
    return
  fi

  local team_id="${MOUSER_TEAM_ID:-}"
  if [[ -z "$team_id" ]]; then
    fail "Set MOUSER_SIGN_IDENTITY or MOUSER_TEAM_ID for macOS code signing."
  fi
  local line sha1

  line="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep "(${team_id})" \
    | head -1)" || true

  if [[ -z "$line" ]]; then
    fail "No codesigning identity found for team ${team_id}. Set MOUSER_SIGN_IDENTITY or MOUSER_TEAM_ID."
  fi

  sha1="${line#*) }"
  sha1="${sha1%% *}"
  [[ "$sha1" =~ ^[A-F0-9]{40}$ ]] || fail "Could not parse codesigning identity for team ${team_id}."

  echo "$sha1"
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script must be run on macOS."
fi

SIGN_IDENTITY="$(resolve_sign_identity)"
export MOUSER_SIGN_IDENTITY="$SIGN_IDENTITY"

echo "Building signed macOS app (identity: ${SIGN_IDENTITY})"
"$ROOT_DIR/build_macos_app.sh"

[[ -d "$BUILD_OUTPUT" ]] || fail "Build output not found: $BUILD_OUTPUT"

echo "Installing to ${INSTALL_PATH}"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_PATH"
ditto "$BUILD_OUTPUT" "$INSTALL_PATH"

if command -v codesign >/dev/null 2>&1; then
  codesign --verify --deep --strict --verbose=2 "$INSTALL_PATH"
fi

echo "Installed: ${INSTALL_PATH}"
