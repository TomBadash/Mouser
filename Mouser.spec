# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mouser
Produces a single-directory portable build in  dist/Mouser/
Run:  pyinstaller Mouser.spec
"""

import os
import sys
import shutil
import PySide6

block_cipher = None
ROOT = os.path.abspath(".")
PYSIDE6_DIR = os.path.dirname(PySide6.__file__)

a = Analysis(
    ["main_qml.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # QML UI files
        (os.path.join(ROOT, "ui", "qml"), os.path.join("ui", "qml")),
        # Image assets
        (os.path.join(ROOT, "images"), "images"),
    ],
    hiddenimports=[
        # conditional / lazy imports PyInstaller may miss
        "hid",
        "logging.handlers",
        "ctypes.wintypes",
        "ui.locale_manager",
        # PySide6 QML runtime
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Filter out massive Qt DLLs and data we don't need ──────────────────
# The PySide6 hooks copy EVERYTHING (WebEngine=193MB, 3D, Charts, etc.).
# We only need: Core, Gui, Widgets, Qml, Quick, QuickControls2 (Material),
# OpenGL, Network, ShaderTools, and a few essentials.
_qt_keep = {
    # Core Qt
    "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Network", "Qt6OpenGL",
    # QML / Quick
    "Qt6Qml", "Qt6QmlCore", "Qt6QmlMeta", "Qt6QmlModels",
    "Qt6QmlNetwork", "Qt6QmlWorkerScript",
    "Qt6Quick", "Qt6QuickControls2", "Qt6QuickControls2Impl",
    "Qt6QuickControls2Basic", "Qt6QuickControls2BasicStyleImpl",
    "Qt6QuickControls2Material", "Qt6QuickControls2MaterialStyleImpl",
    "Qt6QuickTemplates2", "Qt6QuickLayouts", "Qt6QuickEffects",
    "Qt6QuickShapes",
    # Rendering
    "Qt6ShaderTools", "Qt6Svg",
    # PySide6 runtime
    "pyside6.abi3", "pyside6qml.abi3", "shiboken6.abi3",
    # VC runtime
    "MSVCP140", "MSVCP140_1", "MSVCP140_2",
    "VCRUNTIME140", "VCRUNTIME140_1",
}

def _should_keep(name):
    """Return True if this binary/data entry should be kept."""
    # Always keep non-PySide6 files
    if "PySide6" not in name and "pyside6" not in name.lower():
        return True
    # Check the filename (last component)
    base = os.path.basename(name)
    stem = os.path.splitext(base)[0]
    # Keep if it's in our whitelist
    if stem in _qt_keep:
        return True
    # Keep all .pyd files (Python extensions — small and needed)
    if base.endswith(".pyd"):
        return True
    # Keep plugin dirs we need (platforms, imageformats, styles, iconengines)
    for keep in ("platforms", "imageformats", "styles", "iconengines",
                 "platforminputcontexts"):
        if keep in name:
            return True
    # Keep QML dirs we need
    for keep_qml in ("QtCore", "QtQml", "QtQuick", "QtNetwork"):
        pat = os.path.join("qml", keep_qml)
        if pat in name.replace("/", os.sep):
            return True
    # Drop everything else (WebEngine, 3D, Charts, Multimedia, etc.)
    return False

a.binaries = [b for b in a.binaries if _should_keep(b[0])]
a.datas    = [d for d in a.datas    if _should_keep(d[0])]

exe = EXE(
    pyz,
    a.scripts,
    [],                     # not one-file (faster startup, easier debugging)
    exclude_binaries=True,
    name="Mouser",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX OFF — decompression at startup is very slow
    console=False,          # windowed app (no terminal)
    icon=os.path.join(ROOT, "images", "logo.ico"),
    uac_admin=False,        # does NOT require admin
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,              # UPX OFF — faster cold start
    upx_exclude=[],
    name="Mouser",
)

# ── Post-build cleanup: remove Qt QML/plugin dirs we don't need ──────────
# PyInstaller's hooks copy the entire PySide6 QML tree; we only need
# QtQuick/Controls + Material, QtQml, QtQuick/Layouts, QtQuick/Templates,
# QtQuick/Window.  Everything else is dead weight that slows startup.
_dist = os.path.join("dist", "Mouser", "_internal", "PySide6")

# QML dirs to KEEP (everything else under qml/ is deleted)
_keep_qml = {
    "QtCore", "QtQml", "QtQuick", "QtNetwork",
}

# Under QtQuick, keep only what the app uses
_keep_qtquick = {
    "Controls", "Layouts", "Templates", "Window",
}

# Plugin dirs to KEEP
_keep_plugins = {
    "iconengines", "imageformats", "platforms",
    "platforminputcontexts", "styles",
}

def _cleanup():
    qml_root = os.path.join(_dist, "qml")
    if os.path.isdir(qml_root):
        for d in os.listdir(qml_root):
            if d not in _keep_qml:
                p = os.path.join(qml_root, d)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"  [cleanup] removed qml/{d}")

        # Trim inside QtQuick
        qtquick = os.path.join(qml_root, "QtQuick")
        if os.path.isdir(qtquick):
            for d in os.listdir(qtquick):
                if d not in _keep_qtquick:
                    p = os.path.join(qtquick, d)
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                        print(f"  [cleanup] removed qml/QtQuick/{d}")

    plugins_root = os.path.join(_dist, "plugins")
    if os.path.isdir(plugins_root):
        for d in os.listdir(plugins_root):
            if d not in _keep_plugins:
                p = os.path.join(plugins_root, d)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"  [cleanup] removed plugins/{d}")

    # Remove translations (not needed)
    trans = os.path.join(_dist, "translations")
    if os.path.isdir(trans):
        shutil.rmtree(trans, ignore_errors=True)
        print("  [cleanup] removed translations/")

print("[Mouser] Post-build cleanup...")
_cleanup()
print("[Mouser] Cleanup done.")

# ── macOS App Bundle ───────────────────────────────────────────────────
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Mouser.app',
        icon='images/AppIcon.icns',
        bundle_identifier='com.mouser.app',
        info_plist={
            'CFBundleShortVersionString': '3.5.0',
            'CFBundleVersion': '3.5.0',
            'LSUIElement': True, # Runs in background (menu bar app)
            'NSHighResolutionCapable': True,
        },
    )
