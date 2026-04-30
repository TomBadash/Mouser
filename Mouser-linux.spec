# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building a portable Linux distribution.

Run:
    python3 -m PyInstaller Mouser-linux.spec --noconfirm

Output: dist/Mouser/  (directory with Mouser executable + dependencies)
"""

import os
import json
import subprocess
import sys

ROOT = os.path.abspath(".")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from build_support import should_keep_linux_qt_asset

BUILD_INFO_PATH = os.path.join(ROOT, "build", "mouser_build_info.json")


def _load_app_version() -> str:
    version_path = os.path.join(ROOT, "core", "version.py")
    namespace = {"__file__": version_path}
    with open(version_path, encoding="utf-8") as version_file:
        exec(version_file.read(), namespace)
    return namespace["APP_VERSION"]


def _run_git(args):
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_dirty():
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _write_build_info(version: str) -> str:
    commit = os.environ.get("MOUSER_GIT_COMMIT", "").strip() or _run_git(["rev-parse", "HEAD"])
    dirty_env = os.environ.get("MOUSER_GIT_DIRTY")
    if dirty_env:
        dirty = dirty_env.strip().lower() in {"1", "true", "yes", "on"}
    else:
        dirty = _git_dirty()

    os.makedirs(os.path.dirname(BUILD_INFO_PATH), exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as build_info_file:
        json.dump(
            {
                "version": version,
                "commit": commit,
                "dirty": dirty,
            },
            build_info_file,
        )
    return BUILD_INFO_PATH


APP_VERSION = _load_app_version()
BUILD_INFO_DATA = _write_build_info(APP_VERSION)

a = Analysis(
    ["main_qml.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "ui", "qml"), os.path.join("ui", "qml")),
        (os.path.join(ROOT, "images"), "images"),
        (
            os.path.join(ROOT, "packaging", "linux", "69-mouser-logitech.rules"),
            os.path.join("linux", "69-mouser-logitech.rules"),
        ),
        (
            os.path.join(ROOT, "packaging", "linux", "install-linux-permissions.sh"),
            os.path.join("linux", "install-linux-permissions.sh"),
        ),
        (BUILD_INFO_DATA, "."),
    ],
    hiddenimports=[
        "hid",
        "hidraw",
        "logging.handlers",
        "evdev",
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
        # Trim PySide6 modules the app does not import at runtime.
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
        # Designer / tooling modules are not needed in the packaged app.
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtUiTools",
        "PySide6.QtXml",
        "PySide6.QtConcurrent",
        "PySide6.QtStateMachine",
        "PySide6.QtHttpServer",
        "PySide6.QtSpatialAudio",
        # Trim large unused stdlib bundles.
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

a.binaries = [b for b in a.binaries if should_keep_linux_qt_asset(b[0])]
a.datas = [d for d in a.datas if should_keep_linux_qt_asset(d[0])]

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
