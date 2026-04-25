import os
import stat
import unittest

from build_support import normalized_qt_library_stem, should_keep_linux_qt_asset


class LinuxQtAssetFilterTests(unittest.TestCase):
    def test_normalizes_versioned_abi3_shared_library_names(self):
        cases = {
            "/tmp/_internal/PySide6/libpyside6.abi3.so.6.11": "pyside6",
            "/tmp/_internal/PySide6/libpyside6qml.abi3.so.6.11": "pyside6qml",
            "/tmp/_internal/PySide6/libshiboken6.abi3.so.6.11": "shiboken6",
        }

        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(normalized_qt_library_stem(path), expected)

    def test_keeps_versioned_pyside6_abi3_runtime_library(self):
        runtime_paths = [
            "/tmp/_internal/PySide6/libpyside6.abi3.so.6.11",
            "/tmp/_internal/PySide6/libpyside6qml.abi3.so.6.11",
            "/tmp/_internal/PySide6/libshiboken6.abi3.so.6.11",
        ]

        for path in runtime_paths:
            with self.subTest(path=path):
                self.assertTrue(should_keep_linux_qt_asset(path))

    def test_keeps_core_qt_dependency_libraries(self):
        dependency_paths = [
            "/tmp/_internal/PySide6/Qt/lib/libQt6DBus.so.6",
            "/tmp/_internal/PySide6/Qt/lib/libQt6XcbQpa.so.6",
            "/tmp/_internal/PySide6/Qt/lib/libicui18n.so.73",
            "/tmp/_internal/PySide6/Qt/lib/libicuuc.so.73",
            "/tmp/_internal/PySide6/Qt/lib/libicudata.so.73",
        ]

        for path in dependency_paths:
            with self.subTest(path=path):
                self.assertTrue(should_keep_linux_qt_asset(path))

    def test_drops_unneeded_qt_webengine_binary(self):
        path = "/tmp/_internal/PySide6/Qt/lib/libQt6WebEngineCore.so.6"
        self.assertFalse(should_keep_linux_qt_asset(path))

    def test_drops_optional_qml_style_family(self):
        path = "/tmp/_internal/PySide6/qml/QtQuick/Controls/Fusion/Button.qml"
        self.assertFalse(should_keep_linux_qt_asset(path))


class LinuxPermissionPackagingTests(unittest.TestCase):
    def test_linux_permission_helper_files_exist(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        helper = os.path.join(
            root, "packaging", "linux", "install-linux-permissions.sh"
        )
        rules = os.path.join(
            root, "packaging", "linux", "69-mouser-logitech.rules"
        )

        self.assertTrue(os.path.isfile(helper))
        self.assertTrue(os.stat(helper).st_mode & stat.S_IXUSR)
        self.assertTrue(os.path.isfile(rules))


if __name__ == "__main__":
    unittest.main()
