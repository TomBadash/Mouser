#!/usr/bin/env bash
# build_deb.sh — Build a Debian (.deb) package from the PyInstaller dist output.
#
# Usage:
#   ./build_deb.sh [--version VERSION] [--arch ARCH]
#
# Prerequisites:
#   • PyInstaller dist already built at dist/Mouser/ (run build with
#     `python -m PyInstaller Mouser-linux.spec --noconfirm` first)
#   • dpkg-deb available (from the `dpkg-dev` or `dpkg` package)
#
# Output: dist/Mouser-Linux.deb

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Parameters ────────────────────────────────────────────────────────────────
VERSION="${MOUSER_VERSION:-}"
ARCH="${MOUSER_ARCH:-amd64}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="$2"; shift 2 ;;
        --arch)    ARCH="$2";    shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Read version from core/version.py if not set externally
if [[ -z "$VERSION" ]]; then
    VERSION=$(python3 -c "
import sys, os
sys.path.insert(0, '.')
# Avoid importing the full module (needs PySide6); just parse the string.
with open('core/version.py') as f:
    for line in f:
        if line.strip().startswith('_DEFAULT_APP_VERSION'):
            VERSION = line.split('=')[1].strip().strip('\"').strip(\"'\")
            print(VERSION)
            break
")
fi

if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not determine application version."
    exit 1
fi

APP_NAME="mouser"
APP_DISPLAY="Mouser"
DIST_DIR="$SCRIPT_DIR/dist/Mouser"
DEB_STAGE="$SCRIPT_DIR/build/deb_stage"
DEB_OUT="$SCRIPT_DIR/dist/Mouser-Linux.deb"
INSTALL_PREFIX="/opt/mouser"
DESKTOP_DIR="/usr/share/applications"
ICONS_DIR="/usr/share/icons/hicolor"

echo "==> Building .deb for Mouser v${VERSION} (${ARCH})"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ ! -d "$DIST_DIR" ]]; then
    echo "ERROR: dist/Mouser/ not found. Run the PyInstaller build first:"
    echo "  python3 -m PyInstaller Mouser-linux.spec --noconfirm"
    exit 1
fi

if ! command -v dpkg-deb &>/dev/null; then
    echo "ERROR: dpkg-deb not found. Install it with: sudo apt install dpkg-dev"
    exit 1
fi

# ── Stage directory ───────────────────────────────────────────────────────────
rm -rf "$DEB_STAGE"
mkdir -p "$DEB_STAGE/DEBIAN"
mkdir -p "$DEB_STAGE${INSTALL_PREFIX}"
mkdir -p "$DEB_STAGE${DESKTOP_DIR}"

# ── Copy application files ────────────────────────────────────────────────────
echo "    Copying application files…"
cp -a "$DIST_DIR/." "$DEB_STAGE${INSTALL_PREFIX}/"

# Remove files that are provided by system packages or unnecessary in the deb.
# These are typically found in the host OS and add megabytes without benefit.
STRIP_PATTERNS=(
    "libz.so*"
    "libbz2.so*"
    "libexpat.so*"
    "libffi.so*"
    "libm.so*"
    "libpthread.so*"
    "libdl.so*"
    "libutil.so*"
    "librt.so*"
    "libgcc_s.so*"
    "libstdc++.so*"
)
for pat in "${STRIP_PATTERNS[@]}"; do
    find "$DEB_STAGE${INSTALL_PREFIX}" -name "$pat" -delete 2>/dev/null || true
done

# ── Launcher symlink ─────────────────────────────────────────────────────────
mkdir -p "$DEB_STAGE/usr/local/bin"
ln -sf "${INSTALL_PREFIX}/Mouser" "$DEB_STAGE/usr/local/bin/mouser"

# ── Icons ─────────────────────────────────────────────────────────────────────
SRC_ICON="$SCRIPT_DIR/images/logo_icon.png"
if [[ -f "$SRC_ICON" ]]; then
    echo "    Installing icons…"
    for SIZE in 16 32 48 64 128 256 512; do
        ICON_DEST="$DEB_STAGE${ICONS_DIR}/${SIZE}x${SIZE}/apps"
        mkdir -p "$ICON_DEST"
        if command -v convert &>/dev/null; then
            convert -resize "${SIZE}x${SIZE}" "$SRC_ICON" "$ICON_DEST/${APP_NAME}.png" 2>/dev/null \
                || cp "$SRC_ICON" "$ICON_DEST/${APP_NAME}.png"
        else
            cp "$SRC_ICON" "$ICON_DEST/${APP_NAME}.png"
        fi
    done
fi

# ── Desktop entry ─────────────────────────────────────────────────────────────
echo "    Creating desktop entry…"
cat > "$DEB_STAGE${DESKTOP_DIR}/${APP_NAME}.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_DISPLAY}
Comment=Logitech mouse button remapper
Exec=${INSTALL_PREFIX}/Mouser %U
Icon=${APP_NAME}
Terminal=false
Categories=Utility;Settings;
Keywords=mouse;logitech;remap;
StartupNotify=false
EOF

# ── Calculate installed size ──────────────────────────────────────────────────
INSTALLED_SIZE_KB=$(du -sk "$DEB_STAGE${INSTALL_PREFIX}" | awk '{print $1}')

# ── DEBIAN/control ────────────────────────────────────────────────────────────
echo "    Writing DEBIAN/control…"
cat > "$DEB_STAGE/DEBIAN/control" << EOF
Package: ${APP_NAME}
Version: ${VERSION}
Architecture: ${ARCH}
Section: utils
Priority: optional
Installed-Size: ${INSTALLED_SIZE_KB}
Maintainer: Mouser Contributors <noreply@github.com>
Homepage: https://github.com/TomBadash/Mouser
Description: Logitech mouse button remapper
 Mouser lets you remap the buttons of your Logitech mouse on Linux,
 macOS and Windows. It supports per-application profiles, DPI control,
 SmartShift scroll wheel management, and gesture buttons.
Depends: libxcb1, libxcb-cursor0, libegl1
Recommends: libinput-tools
EOF

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
cat > "$DEB_STAGE/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e
# Update icon cache if gtk-update-icon-cache is available
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
# Update desktop database
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
EOF
chmod 755 "$DEB_STAGE/DEBIAN/postinst"

# ── DEBIAN/postrm ─────────────────────────────────────────────────────────────
cat > "$DEB_STAGE/DEBIAN/postrm" << 'EOF'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
EOF
chmod 755 "$DEB_STAGE/DEBIAN/postrm"

# ── Build the .deb ────────────────────────────────────────────────────────────
echo "    Building .deb package…"
mkdir -p "$(dirname "$DEB_OUT")"
dpkg-deb --build --root-owner-group "$DEB_STAGE" "$DEB_OUT"

DEB_SIZE=$(du -sh "$DEB_OUT" | awk '{print $1}')
echo ""
echo "==> Package built successfully!"
echo "    Output:  $DEB_OUT"
echo "    Size:    ${DEB_SIZE}"
echo ""
echo "    Install with:"
echo "      sudo dpkg -i $DEB_OUT"
echo "    Or:"
echo "      sudo apt install $DEB_OUT"
