# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building a portable Linux distribution.

Run:
    python3 -m PyInstaller Mouser-linux.spec --noconfirm

Output: dist/Mouser/  (directory with Mouser executable + dependencies)
"""

import os

ROOT = os.path.abspath(".")

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
        "logging.handlers",
        "evdev",
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
