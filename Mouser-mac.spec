# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building a native macOS app bundle.

Run from Apple Silicon Python on macOS:
    python3 -m PyInstaller Mouser-mac.spec --noconfirm
"""

import os

ROOT = os.path.abspath(".")
COMMITTED_ICON = os.path.join(ROOT, "images", "AppIcon.icns")
GENERATED_ICON = os.path.join(ROOT, "build", "macos", "Mouser.icns")
if os.path.exists(COMMITTED_ICON):
    ICON_PATH = COMMITTED_ICON
elif os.path.exists(GENERATED_ICON):
    ICON_PATH = GENERATED_ICON
else:
    ICON_PATH = None
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
        "logging.handlers",
        "ui.locale_manager",
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
    excludes=[
        # ── Aggressively trim unneeded PySide6 modules ──
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtTest",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSql",
        "PySide6.QtTextToSpeech",
        "PySide6.QtQuick3D",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtGraphs",
        "PySide6.Qt5Compat",
        # ── PySide6 designer / tools (not needed at runtime) ──
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtUiTools",
        "PySide6.QtXml",
        "PySide6.QtConcurrent",
        "PySide6.QtDBus",
        "PySide6.QtStateMachine",
        "PySide6.QtHttpServer",
        "PySide6.QtSpatialAudio",
        # ── Other unused stdlib modules ──
        "unittest",
        "xmlrpc",
        "pydoc",
        "doctest",
        "tkinter",
        "test",
        "distutils",
        "setuptools",
        "ensurepip",
        "lib2to3",
        "idlelib",
        "turtledemo",
        "turtle",
        "sqlite3",
        "multiprocessing",
    ],
    noarchive=False,
)

# ── Filter collected Qt shared libs / plugins that PyInstaller hooks may have pulled in ──
UNWANTED_PATTERNS = [
    "QtWebEngine",
    "QtWebChannel",
    "QtWebSockets",
    "Qt3D",
    "QtMultimedia",
    "QtMultimediaWidgets",
    "QtBluetooth",
    "QtLocation",
    "QtPositioning",
    "QtSensors",
    "QtSerialPort",
    "QtPdf",
    "QtCharts",
    "QtDataVisualization",
    "QtRemoteObjects",
    "QtTextToSpeech",
    "QtQuick3D",
    "QtVirtualKeyboard",
    "QtGraphs",
    "Qt5Compat",
    "QtWebView",
    "QtTest",
    "QtLabsAnimation",
    "QtLabsFolderListModel",
    "QtLabsPlatform",
    "QtLabsQmlModels",
    "QtLabsSettings",
    "QtLabsSharedImage",
    "QtLabsWavefrontMesh",
    "QtQuickTest",
    "QtScxml",
    "QtScxmlQml",
    "QtSpatialAudio",
    "QtSql",
]

def is_unwanted(path_or_toc_entry):
    # entry can be a (src, dest) tuple (TOC) or a string path
    src = ""
    if isinstance(path_or_toc_entry, (list, tuple)) and len(path_or_toc_entry) >= 1:
        src = path_or_toc_entry[0] or ""
    elif isinstance(path_or_toc_entry, str):
        src = path_or_toc_entry
    src_lower = src.lower()
    for pat in UNWANTED_PATTERNS:
        if pat.lower() in src_lower:
            return True
    # also drop plugin subdirectories commonly unused (webengine, multimedia, printsupport, etc.)
    if "/plugins/" in src_lower:
        for pat in ("webengine", "multimedia", "printsupport", "qmltooling", "sensorgestures"):
            if pat in src_lower:
                return True
    return False

# Filter Analysis.toc lists (binaries and datas)
a.binaries = [b for b in a.binaries if not is_unwanted(b)]
a.datas = [d for d in a.datas if not is_unwanted(d)]

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
        "CFBundleShortVersionString": "3.5.3",
        "CFBundleVersion": "3.5.3",
        "LSMinimumSystemVersion": "12.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
