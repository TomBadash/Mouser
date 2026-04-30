"""Shared helpers for build-time packaging logic."""

from __future__ import annotations

import os


LINUX_QT_KEEP = {
    "Qt6Core",
    "Qt6Gui",
    "Qt6Widgets",
    "Qt6Network",
    "Qt6OpenGL",
    "Qt6DBus",
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
    "Qt6XcbQpa",
    "icudata",
    "icui18n",
    "icuuc",
    "pyside6",
    "pyside6qml",
    "shiboken6",
}

LINUX_KEEP_PLUGIN_DIRS = {
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

LINUX_KEEP_QML_TOP = {"QtCore", "QtQml", "QtQuick", "QtNetwork"}
LINUX_KEEP_QTQUICK = {"Controls", "Layouts", "Templates", "Window"}


def normalized_qt_library_stem(path: str) -> str:
    """Normalize PySide/Qt shared-library filenames for whitelist matching."""

    base = os.path.basename(path)
    if ".so" in base:
        stem = base.split(".so", 1)[0]
    else:
        stem = os.path.splitext(base)[0]
    stem = stem.removeprefix("lib")
    if stem.endswith(".abi3"):
        stem = stem[:-5]
    return stem


def should_keep_linux_qt_asset(path: str) -> bool:
    normalized = path.replace("\\", "/")
    lower = normalized.lower()

    if "PySide6" not in normalized and "pyside6" not in lower:
        return True

    stem = normalized_qt_library_stem(normalized)
    if stem in LINUX_QT_KEEP:
        return True

    base = os.path.basename(normalized)
    if ".abi3.so" in base:
        return True

    plugin_marker = "/plugins/"
    plugin_index = lower.find(plugin_marker)
    if plugin_index != -1:
        plugin_path = normalized[plugin_index + len(plugin_marker) :]
        plugin_dir = plugin_path.split("/", 1)[0]
        return plugin_dir in LINUX_KEEP_PLUGIN_DIRS and base != "libqpdf.so"

    qml_marker = "/qml/"
    qml_index = lower.find(qml_marker)
    if qml_index != -1:
        qml_path = normalized[qml_index + len(qml_marker) :]
        parts = [part for part in qml_path.split("/") if part]
        if not parts:
            return True
        if parts[0] not in LINUX_KEEP_QML_TOP:
            return False
        if parts[0] == "QtQuick" and len(parts) > 1 and parts[1] not in LINUX_KEEP_QTQUICK:
            return False
        style_parts = {part.lower() for part in parts}
        if style_parts & {"fusion", "imagine", "universal", "fluentwinui3", "ios", "macos"}:
            return False
        return True

    return False
