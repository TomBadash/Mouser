# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building a native macOS app bundle.

Run from Apple Silicon Python on macOS:
    python3 -m PyInstaller Mouser-mac.spec --noconfirm
"""

import os

ROOT = os.path.abspath(".")
MAC_ICON = os.path.join(ROOT, "build", "macos", "Mouser.icns")
ICON_PATH = MAC_ICON if os.path.exists(MAC_ICON) else None
BUNDLE_ID = "io.github.tombadash.mouser"

a = Analysis(
    ["main_qml.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "ui", "qml"), os.path.join("ui", "qml")),
        (os.path.join(ROOT, "images"), "images"),
    ],
    hiddenimports=[
        "hid",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQml",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mouser",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON_PATH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mouser",
)

app = BUNDLE(
    coll,
    name="Mouser.app",
    icon=ICON_PATH,
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleDisplayName": "Mouser",
        "CFBundleName": "Mouser",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
