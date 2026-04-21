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

    def test_drops_unneeded_qt_webengine_binary(self):
        path = "/tmp/_internal/PySide6/Qt/lib/libQt6WebEngineCore.so.6"
        self.assertFalse(should_keep_linux_qt_asset(path))

    def test_drops_optional_qml_style_family(self):
        path = "/tmp/_internal/PySide6/qml/QtQuick/Controls/Fusion/Button.qml"
        self.assertFalse(should_keep_linux_qt_asset(path))


if __name__ == "__main__":
    unittest.main()
