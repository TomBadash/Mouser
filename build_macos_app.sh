#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/macos"
ICONSET_DIR="$BUILD_DIR/Mouser.iconset"
COMMITTED_ICON="$ROOT_DIR/images/AppIcon.icns"
GENERATED_ICON="$BUILD_DIR/Mouser.icns"
SOURCE_ICON="$ROOT_DIR/images/logo_icon.png"
ENTITLEMENTS="$ROOT_DIR/build_resources/Mouser.entitlements"
TARGET_ARCH="${PYINSTALLER_TARGET_ARCH:-}"
SIGN_IDENTITY="${MOUSER_SIGN_IDENTITY:-}"
export PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must be run on macOS."
  exit 1
fi

mkdir -p "$BUILD_DIR"
if [[ -f "$COMMITTED_ICON" ]]; then
  echo "Using committed macOS app icon: $COMMITTED_ICON"
else
  rm -rf "$ICONSET_DIR"
  mkdir -p "$ICONSET_DIR"

  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$SOURCE_ICON" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
    double_size=$((size * 2))
    sips -z "$double_size" "$double_size" "$SOURCE_ICON" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
  done

  if ! iconutil -c icns "$ICONSET_DIR" -o "$GENERATED_ICON"; then
    echo "warning: iconutil failed, continuing without a custom .icns icon"
    rm -f "$GENERATED_ICON"
  fi
fi

if [[ -n "$TARGET_ARCH" ]]; then
  case "$TARGET_ARCH" in
    arm64|x86_64|universal2) ;;
    *)
      echo "Unsupported PYINSTALLER_TARGET_ARCH: $TARGET_ARCH"
      echo "Expected one of: arm64, x86_64, universal2"
      exit 1
      ;;
  esac
  echo "Building macOS app for target architecture: $TARGET_ARCH"
fi

# Resolve the Python interpreter used for PyInstaller. Order:
#   1. MOUSER_PYTHON      explicit override, wins over everything
#   2. $ROOT_DIR/.venv    typical "python -m venv .venv" + requirements.txt
#                         flow; preferred because it isolates the
#                         PyInstaller / Qt / PyObjC dependency set from
#                         the user's global site-packages
#   3. pyenv which python3   when MOUSER_PREFER_PYENV=1 or .venv absent;
#                            picks the interpreter pinned by
#                            .python-version after pyenv has installed
#                            PyInstaller / requirements into it
#   4. python3 on PATH     fallback
# Using the wrong interpreter silently produces a different bundle
# layout (different stdlib paths, different .so vendor IDs), which
# defeats the cdhash stability the rest of this script enforces.
if [[ -n "${MOUSER_PYTHON:-}" ]]; then
  PYTHON="$MOUSER_PYTHON"
elif [[ -z "${MOUSER_PREFER_PYENV:-}" && -x "$ROOT_DIR/.venv/bin/python3" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python3"
elif command -v pyenv >/dev/null 2>&1; then
  PYTHON="$(cd "$ROOT_DIR" && pyenv which python3 2>/dev/null)" || PYTHON=""
  if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
    PYTHON="python3"
  fi
else
  PYTHON="python3"
fi
if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "ERROR: PyInstaller not installed in $PYTHON" >&2
  echo "       Install it with:  $PYTHON -m pip install pyinstaller" >&2
  exit 1
fi
echo "Using Python: $PYTHON"

# PYTHONHASHSEED=0 pins set iteration so PyInstaller's base_library.zip
# layout is byte-identical across rebuilds. Without it the outer cdhash
# drifts even when the same identity and entitlements are reused.
PYTHONHASHSEED=0 "$PYTHON" -m PyInstaller "$ROOT_DIR/Mouser-mac.spec" --noconfirm

if ! command -v codesign >/dev/null 2>&1; then
  echo "warning: codesign not available, bundle is unsigned"
  echo "Build complete: $ROOT_DIR/dist/Mouser.app"
  exit 0
fi

if [[ -z "$SIGN_IDENTITY" ]]; then
  # Ad-hoc fallback: cdhash differs on every rebuild, so TCC grants reset.
  codesign --force --deep --sign - "$ROOT_DIR/dist/Mouser.app"
else
  if [[ ! -f "$ENTITLEMENTS" ]]; then
    echo "ERROR: entitlements file not found at $ENTITLEMENTS" >&2
    exit 1
  fi
  echo "Code-signing with identity: $SIGN_IDENTITY"

  # Sign nested code first; codesign --deep can't apply per-level
  # entitlements, and --options runtime must be set on every binary.
  while IFS= read -r -d '' nested; do
    codesign --force --options runtime --timestamp=none \
      --sign "$SIGN_IDENTITY" "$nested"
  done < <(find "$ROOT_DIR/dist/Mouser.app/Contents/Frameworks" \
             \( -name "*.dylib" -o -name "*.so" \) -print0 2>/dev/null)

  while IFS= read -r -d '' framework; do
    codesign --force --options runtime --timestamp=none \
      --sign "$SIGN_IDENTITY" "$framework"
  done < <(find "$ROOT_DIR/dist/Mouser.app/Contents/Frameworks" \
             -type d -name "*.framework" -print0 2>/dev/null)

  codesign --force --options runtime --timestamp=none \
    --entitlements "$ENTITLEMENTS" \
    --sign "$SIGN_IDENTITY" \
    "$ROOT_DIR/dist/Mouser.app"

  if ! codesign --verify --deep --strict --verbose=2 "$ROOT_DIR/dist/Mouser.app"; then
    echo "ERROR: codesign --verify --deep --strict failed for the signed bundle" >&2
    exit 1
  fi
fi

echo "Build complete: $ROOT_DIR/dist/Mouser.app"
