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

ROOT = os.path.abspath(".")
BUILD_INFO_PATH = os.path.join(ROOT, "build", "mouser_build_info.json")


def _load_app_version() -> str:
    namespace = {}
    version_path = os.path.join(ROOT, "core", "version.py")
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
        (BUILD_INFO_DATA, "."),
    ],
    hiddenimports=[
        "hid",
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

# Keep only the Qt runtime pieces Mouser actually uses. The negative-match
# approach still let large transitive Qt payload through on Linux.
QT_KEEP = {
    "Qt6Core",
    "Qt6Gui",
    "Qt6Widgets",
    "Qt6Network",
    "Qt6OpenGL",
    "Qt6Qml",
    "Qt6QmlCore",
    "Qt6QmlMeta",
    "Qt6QmlModels",
    "Qt6QmlNetwork",
    "Qt6QmlWorkerScript",
    "Qt6Quick",
    "Qt6QuickControls2",
    "Qt6QuickControls2Impl",
    "Qt6QuickControls2Basic",
    "Qt6QuickControls2BasicStyleImpl",
    "Qt6QuickControls2Material",
    "Qt6QuickControls2MaterialStyleImpl",
    "Qt6QuickTemplates2",
    "Qt6QuickLayouts",
    "Qt6QuickEffects",
    "Qt6QuickShapes",
    "Qt6ShaderTools",
    "Qt6Svg",
    "pyside6",
    "pyside6qml",
    "shiboken6",
}

KEEP_PLUGIN_DIRS = {
    "platforms",
    "imageformats",
    "styles",
    "iconengines",
    "platforminputcontexts",
    "xcbglintegrations",
    "platformthemes",
    "tls",
    "egldeviceintegrations",
    "networkinformation",
    "generic",
    "wayland-decoration-client",
    "wayland-graphics-integration-client",
    "wayland-shell-integration",
}

KEEP_QML_TOP = {"QtCore", "QtQml", "QtQuick", "QtNetwork"}
KEEP_QTQUICK = {"Controls", "Layouts", "Templates", "Window"}


def normalized_stem(path):
    base = os.path.basename(path)
    if ".so" in base:
        return base.split(".so", 1)[0].removeprefix("lib")
    stem = os.path.splitext(base)[0]
    if stem.endswith(".abi3"):
        stem = stem[:-5]
    return stem


def should_keep(path):
    normalized = path.replace("\\", "/")
    lower = normalized.lower()

    if "PySide6" not in normalized and "pyside6" not in lower:
        return True

    stem = normalized_stem(normalized)
    if stem in QT_KEEP:
        return True

    base = os.path.basename(normalized)
    if base.endswith(".abi3.so"):
        return True

    plugin_marker = "/plugins/"
    plugin_index = lower.find(plugin_marker)
    if plugin_index != -1:
        plugin_path = normalized[plugin_index + len(plugin_marker) :]
        plugin_dir = plugin_path.split("/", 1)[0]
        return plugin_dir in KEEP_PLUGIN_DIRS and base != "libqpdf.so"

    qml_marker = "/qml/"
    qml_index = lower.find(qml_marker)
    if qml_index != -1:
        qml_path = normalized[qml_index + len(qml_marker) :]
        parts = [part for part in qml_path.split("/") if part]
        if not parts:
            return True
        if parts[0] not in KEEP_QML_TOP:
            return False
        if parts[0] == "QtQuick" and len(parts) > 1 and parts[1] not in KEEP_QTQUICK:
            return False
        style_parts = {part.lower() for part in parts}
        if style_parts & {"fusion", "imagine", "universal", "fluentwinui3", "ios", "macos"}:
            return False
        return True

    return False


a.binaries = [b for b in a.binaries if should_keep(b[0])]
a.datas = [d for d in a.datas if should_keep(d[0])]

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
