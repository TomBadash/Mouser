"""Guard tests keeping the PyInstaller specs in sync with the codebase.

The three spec files are easy to forget when a commit adds a module, a data
file, or a QML import. These tests parse the specs (without executing
PyInstaller) and fail when the app's actual imports or bundled assets drift
from what the specs declare, so packaged builds cannot silently lose
functionality that works from a source checkout.
"""

import ast
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPEC_FILES = {
    "windows": "Mouser.spec",
    "macos": "Mouser-mac.spec",
    "linux": "Mouser-linux.spec",
}

# App code that ships inside the bundle. scripts/ and tools/ are build/dev-side.
APP_CODE_DIRS = ("core", "ui")
APP_ENTRY = "main_qml.py"

# Conditional / lazy imports PyInstaller's static analysis can miss on the
# platform they matter for. A new runtime dependency loaded behind a guard
# must be added both here and to the relevant spec(s).
REQUIRED_HIDDENIMPORTS = {
    "windows": {"hid", "logging.handlers", "ctypes.wintypes", "ui.locale_manager"},
    "macos": {"hid", "logging.handlers", "ui.locale_manager"},
    "linux": {"hid", "hidraw", "evdev", "logging.handlers", "ui.locale_manager"},
}

# Qt libraries each QML import pulls in at runtime. An unmapped QML import
# fails the test on purpose: whoever adds it must extend this mapping AND the
# keep-lists in the specs/build_support so the packaged builds ship the
# libraries the new QML page needs.
QML_IMPORT_TO_QT_LIBS = {
    "QtQml": {"Qt6Qml"},
    "QtQuick": {"Qt6Quick"},
    "QtQuick.Window": set(),
    "QtQuick.Layouts": {"Qt6QuickLayouts"},
    "QtQuick.Effects": {"Qt6QuickEffects"},
    "QtQuick.Shapes": {"Qt6QuickShapes"},
    "QtQuick.Controls": {"Qt6QuickControls2", "Qt6QuickTemplates2"},
    "QtQuick.Controls.Material": {
        "Qt6QuickControls2Material",
        "Qt6QuickControls2MaterialStyleImpl",
    },
}

# QML plugin directories (under PySide6/qml/) needed per import.
QML_IMPORT_TO_QML_DIRS = {
    "QtQml": ("QtQml", None),
    "QtQuick": ("QtQuick", None),
    "QtQuick.Window": ("QtQuick", "Window"),
    "QtQuick.Layouts": ("QtQuick", "Layouts"),
    "QtQuick.Effects": ("QtQuick", "Effects"),
    "QtQuick.Shapes": ("QtQuick", "Shapes"),
    "QtQuick.Controls": ("QtQuick", "Controls"),
    "QtQuick.Controls.Material": ("QtQuick", "Controls"),
}

# Excludes that clash with an import that only executes on another platform.
# Each entry must say why trimming is safe for that spec's target OS; anything
# not listed here fails the excludes test and needs a conscious decision.
PLATFORM_GUARDED_EXCLUDES = {
    # ui/linux_screenshot.py imports QtDBus (behind try/except) for the Linux
    # portal screenshot backend only; the Windows bundle trims it safely.
    ("windows", "PySide6.QtDBus"),
}

# Assets referenced by path from Python code (not covered by a whole-dir
# bundle on every platform, or load-bearing enough to pin explicitly).
REQUIRED_ASSETS = (
    os.path.join("images", "logo.ico"),          # Windows EXE icon
    os.path.join("images", "AppIcon.icns"),      # macOS bundle icon
    os.path.join("images", "logo_icon.png"),     # tray/autostart icon
    os.path.join("images", "icons", "mouse-simple.svg"),
    os.path.join("ui", "qml", "Theme.js"),
)


def _read(path):
    with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as fh:
        return fh.read()


def _spec_tree(platform_key):
    return ast.parse(_read(SPEC_FILES[platform_key]))


def _find_analysis_call(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        ):
            return node
    return None


def _keyword(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _string_list(node):
    values = []
    if node is None:
        return values
    for elt in getattr(node, "elts", []):
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            values.append(elt.value)
    return values


def _join_call_to_relpath(node):
    """Turn os.path.join(ROOT, "a", "b") / os.path.join("a", "b") into a/b."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    parts = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            parts.append(arg.value)
        elif isinstance(arg, ast.Name):
            continue  # ROOT-style prefix
        else:
            return None
    return "/".join(parts) if parts else None


def _datas_sources(call):
    """Repo-relative source paths of every datas entry, plus bare names."""
    sources = []
    datas = _keyword(call, "datas")
    for elt in getattr(datas, "elts", []):
        if not isinstance(elt, ast.Tuple) or not elt.elts:
            continue
        src = elt.elts[0]
        if isinstance(src, ast.Name):
            sources.append(src.id)
        elif isinstance(src, ast.Constant) and isinstance(src.value, str):
            sources.append(src.value.replace(os.sep, "/"))
        else:
            rel = _join_call_to_relpath(src)
            if rel:
                sources.append(rel)
    return sources


def _module_level_set(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                return set(_string_list(node.value))
    return set()


def _app_imports():
    """Every dotted module name imported anywhere in the bundled app code."""
    imported = set()
    files = [os.path.join(REPO_ROOT, APP_ENTRY)]
    for dirname in APP_CODE_DIRS:
        for root, _dirs, names in os.walk(os.path.join(REPO_ROOT, dirname)):
            if "__pycache__" in root:
                continue
            files.extend(
                os.path.join(root, n) for n in names if n.endswith(".py")
            )
    for path in files:
        with open(path, encoding="utf-8") as fh:
            try:
                tree = ast.parse(fh.read())
            except SyntaxError:  # pragma: no cover - would fail elsewhere
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module)
    return imported


def _qml_imports():
    imports = set()
    qml_dir = os.path.join(REPO_ROOT, "ui", "qml")
    pattern = re.compile(r"^import\s+(Qt[\w.]*)", re.MULTILINE)
    for name in os.listdir(qml_dir):
        if not name.endswith(".qml"):
            continue
        with open(os.path.join(qml_dir, name), encoding="utf-8") as fh:
            imports.update(pattern.findall(fh.read()))
    return imports


class SpecStructureTests(unittest.TestCase):
    """Every platform spec exists, analyzes the entry point, bundles the app data."""

    def test_specs_exist_and_analyze_entry_point(self):
        for platform_key, filename in SPEC_FILES.items():
            with self.subTest(platform=platform_key):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT, filename)), filename
                )
                call = _find_analysis_call(_spec_tree(platform_key))
                self.assertIsNotNone(call, f"{filename}: no Analysis(...) call")
                entries = _string_list(call.args[0] if call.args else None)
                self.assertIn(APP_ENTRY, entries, filename)

    def test_all_specs_bundle_qml_images_and_build_info(self):
        for platform_key, filename in SPEC_FILES.items():
            with self.subTest(platform=platform_key):
                call = _find_analysis_call(_spec_tree(platform_key))
                sources = _datas_sources(call)
                self.assertIn("ui/qml", sources, filename)
                self.assertIn("images", sources, filename)
                self.assertIn(
                    "BUILD_INFO_DATA",
                    sources,
                    f"{filename}: mouser_build_info.json (core/version.py "
                    f"reads it from the bundle root) is not in datas",
                )

    def test_linux_spec_bundles_every_packaging_file(self):
        call = _find_analysis_call(_spec_tree("linux"))
        sources = set(_datas_sources(call))
        packaging_dir = os.path.join(REPO_ROOT, "packaging", "linux")
        for name in sorted(os.listdir(packaging_dir)):
            rel = f"packaging/linux/{name}"
            covered = rel in sources or any(
                rel.startswith(src + "/") for src in sources
            )
            with self.subTest(file=rel):
                self.assertTrue(
                    covered,
                    f"{rel} exists but Mouser-linux.spec does not bundle it "
                    f"(startup.py resolves packaging assets from the bundle)",
                )


class HiddenImportTests(unittest.TestCase):
    """Conditional imports each platform needs are declared."""

    def test_required_hiddenimports_present(self):
        for platform_key, required in REQUIRED_HIDDENIMPORTS.items():
            with self.subTest(platform=platform_key):
                call = _find_analysis_call(_spec_tree(platform_key))
                declared = set(_string_list(_keyword(call, "hiddenimports")))
                missing = required - declared
                self.assertFalse(
                    missing,
                    f"{SPEC_FILES[platform_key]} hiddenimports missing: "
                    f"{sorted(missing)}",
                )


class ExcludesConsistencyTests(unittest.TestCase):
    """No spec excludes a module the app code actually imports."""

    def test_no_excluded_module_is_imported(self):
        imported = _app_imports()
        for platform_key, filename in SPEC_FILES.items():
            call = _find_analysis_call(_spec_tree(platform_key))
            excludes = _string_list(_keyword(call, "excludes"))
            for excluded in excludes:
                if (platform_key, excluded) in PLATFORM_GUARDED_EXCLUDES:
                    continue
                clashes = sorted(
                    name
                    for name in imported
                    if name == excluded or name.startswith(excluded + ".")
                )
                with self.subTest(platform=platform_key, exclude=excluded):
                    self.assertFalse(
                        clashes,
                        f"{filename} excludes {excluded!r} but the app "
                        f"imports {clashes} — the packaged build would "
                        f"crash at that import",
                    )


class QmlCoverageTests(unittest.TestCase):
    """QML imports map to Qt libraries and qml dirs every spec keeps."""

    def setUp(self):
        self.qml_imports = _qml_imports()

    def test_every_qml_import_is_mapped(self):
        unmapped = sorted(self.qml_imports - set(QML_IMPORT_TO_QT_LIBS))
        self.assertFalse(
            unmapped,
            f"New QML import(s) {unmapped} are not in the coverage mapping. "
            f"Add them to QML_IMPORT_TO_QT_LIBS / QML_IMPORT_TO_QML_DIRS "
            f"here AND to the keep-lists in Mouser.spec and "
            f"build_support.py so packaged builds ship them.",
        )

    def _required_libs(self):
        required = set()
        for qml_import in self.qml_imports:
            required.update(QML_IMPORT_TO_QT_LIBS.get(qml_import, set()))
        return required

    def test_windows_spec_keeps_required_qt_libs_and_qml_dirs(self):
        tree = _spec_tree("windows")
        qt_keep = _module_level_set(tree, "_qt_keep")
        keep_qml = _module_level_set(tree, "_keep_qml")
        keep_qtquick = _module_level_set(tree, "_keep_qtquick")

        missing = self._required_libs() - qt_keep
        self.assertFalse(
            missing, f"Mouser.spec _qt_keep missing: {sorted(missing)}"
        )
        for qml_import in self.qml_imports:
            top, sub = QML_IMPORT_TO_QML_DIRS.get(qml_import, (None, None))
            if top:
                self.assertIn(top, keep_qml, f"{qml_import}: qml/{top}")
            if sub:
                self.assertIn(
                    sub, keep_qtquick, f"{qml_import}: qml/QtQuick/{sub}"
                )

    def test_linux_keep_lists_cover_required_qt_libs_and_qml_dirs(self):
        import build_support

        missing = self._required_libs() - set(build_support.LINUX_QT_KEEP)
        self.assertFalse(
            missing,
            f"build_support.LINUX_QT_KEEP missing: {sorted(missing)}",
        )
        for qml_import in self.qml_imports:
            top, sub = QML_IMPORT_TO_QML_DIRS.get(qml_import, (None, None))
            if top:
                self.assertIn(top, build_support.LINUX_KEEP_QML_TOP, qml_import)
            if sub:
                self.assertIn(sub, build_support.LINUX_KEEP_QTQUICK, qml_import)

    def test_macos_spec_does_not_filter_required_qt_libs(self):
        tree = _spec_tree("macos")
        patterns = [
            p.lower()
            for name in ("UNWANTED_PATTERNS", "UNUSED_QUICK_CONTROLS_PATTERNS")
            for p in _module_level_set(tree, name)
        ]
        for lib in sorted(self._required_libs()):
            clashing = [p for p in patterns if p in lib.lower()]
            with self.subTest(lib=lib):
                self.assertFalse(
                    clashing,
                    f"Mouser-mac.spec filter pattern(s) {clashing} would "
                    f"drop required library {lib}",
                )


class RequiredAssetTests(unittest.TestCase):
    """Assets referenced from code/specs by exact path exist in the repo."""

    def test_referenced_assets_exist(self):
        for rel in REQUIRED_ASSETS:
            with self.subTest(asset=rel):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT, rel)), rel
                )


if __name__ == "__main__":
    unittest.main()
