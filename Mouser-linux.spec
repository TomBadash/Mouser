# -*- mode: python ; coding: utf-8 -*-

import os
import json
import subprocess
import sysconfig
import shutil
from PySide6 import QtCore

ROOT = os.path.abspath(".")
DIST_DIR = os.path.join(ROOT, "dist", "Mouser")
BUILD_INFO_PATH = os.path.join(ROOT, "build", "mouser_build_info.json")


# =========================
# BUILD INFO
# =========================

def _load_app_version():
    version_path = os.path.join(ROOT, "core", "version.py")
    ns = {"__file__": version_path}
    with open(version_path, encoding="utf-8") as f:
        exec(f.read(), ns)
    return ns["APP_VERSION"]


def _write_build_info(v):
    os.makedirs(os.path.dirname(BUILD_INFO_PATH), exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": v}, f)
    return BUILD_INFO_PATH


APP_VERSION = _load_app_version()
BUILD_INFO_DATA = _write_build_info(APP_VERSION)


# =========================
# PYTHON LIB
# =========================

libpython_path = os.path.join(
    sysconfig.get_config_var("LIBDIR"),
    sysconfig.get_config_var("INSTSONAME"),
)


# =========================
# QT PATHS
# =========================

qt_lib_path = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibrariesPath)
qt_plugin_path = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.PluginsPath)


# =========================
# ICU DETECTION (DYNAMIC)
# =========================

def find_icu_lib(name):
    for f in os.listdir(qt_lib_path):
        if f.startswith(name):
            return os.path.join(qt_lib_path, f)
    raise RuntimeError(f"Missing ICU lib: {name}")


icu_libs = [
    (find_icu_lib("libicudata"), "."),
    (find_icu_lib("libicuuc"), "."),
    (find_icu_lib("libicui18n"), "."),
]


# =========================
# MINIMAL QT LIBS
# =========================

qt_binaries = [
    (os.path.join(qt_lib_path, "libQt6Core.so.6"), "."),
    (os.path.join(qt_lib_path, "libQt6Gui.so.6"), "."),
    (os.path.join(qt_lib_path, "libQt6Qml.so.6"), "."),
    (os.path.join(qt_lib_path, "libQt6Quick.so.6"), "."),
    (os.path.join(qt_lib_path, "libQt6Network.so.6"), "."),

    *icu_libs,

    (libpython_path, "."),
]


# =========================
# MINIMAL QT PLUGINS
# =========================

qt_plugins = [
    (os.path.join(qt_plugin_path, "platforms"), "platforms"),
    (os.path.join(qt_plugin_path, "imageformats"), "imageformats"),
]


# =========================
# ANALYSIS (NO QT AUTO EXPANSION)
# =========================

a = Analysis(
    ["main_qml.py"],
    pathex=[ROOT],

    binaries=qt_binaries + qt_plugins,

    datas=[
        (os.path.join(ROOT, "ui/qml"), "ui/qml"),
        (os.path.join(ROOT, "images"), "images"),
        (BUILD_INFO_DATA, "."),
    ],

    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtNetwork",
        "PySide6.QtQuickControls2",
    ],

    # disable PySide6 auto collection
    hooksconfig={
        "PySide6": {
            "exclude_qml": True,
            "exclude_plugins": True,
        }
    },

    excludes=[
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick3D",
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
    ],

    noarchive=False,
)


pyz = PYZ(a.pure)


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mouser",
    console=False,
    upx=False,
    upx_exclude=[
        # Qt shared libraries use mmap-based resource loading; compressing
        # them with UPX can break resource access at runtime.
        "libQt6*.so*",
        # ICU and Python shared libs — large and sensitive to UPX rewriting.
        "libicu*.so*",
        "libpython*.so*",
    ],
)


coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="Mouser",
    upx=False,
    upx_exclude=[
        "libQt6*.so*",
        "libicu*.so*",
        "libpython*.so*",
    ],
)


# =========================
# PRUNE UNUSED FILES
# =========================

def prune():
    if not os.path.exists(DIST_DIR):
        return

    print("==> Pruning build...")

    for root, dirs, files in os.walk(DIST_DIR, topdown=False):

        for f in files:
            p = os.path.join(root, f)
            lower = f.lower()

            # remove Qt junk
            if any(x in lower for x in [
                "webengine", "pdf", "multimedia",
                "3d", "charts"
            ]):
                os.remove(p)
                continue

        for d in dirs:
            dp = os.path.join(root, d)

            if any(x in d.lower() for x in [
                "webengine",
                "translations",
                "examples",
            ]):
                shutil.rmtree(dp, ignore_errors=True)


prune()


# =========================
# DEBUG: BIG FILES
# =========================

def print_big_files():
    if not os.path.exists(DIST_DIR):
        return

    files = []
    for r, _, f in os.walk(DIST_DIR):
        for x in f:
            p = os.path.join(r, x)
            try:
                files.append((os.path.getsize(p), p))
            except:
                pass

    files.sort(reverse=True)

    print("\n== TOP 30 FILES ==")
    for s, p in files[:30]:
        print(f"{s/1024/1024:.2f} MB  {p}")


print_big_files()