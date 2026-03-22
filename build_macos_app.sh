#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/macos"
ICONSET_DIR="$BUILD_DIR/Mouser.iconset"
COMMITTED_ICON="$ROOT_DIR/images/AppIcon.icns"
GENERATED_ICON="$BUILD_DIR/Mouser.icns"
SOURCE_ICON="$ROOT_DIR/images/logo_icon.png"
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

python3 -m PyInstaller "$ROOT_DIR/Mouser-mac.spec" --noconfirm

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$ROOT_DIR/dist/Mouser.app"
fi

echo "Build complete: $ROOT_DIR/dist/Mouser.app"
