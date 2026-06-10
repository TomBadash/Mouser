import inspect
import unittest

try:
    import main_qml
except Exception:  # pragma: no cover - env without PySide6 / project deps
    main_qml = None


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class LinuxInputPolicyTests(unittest.TestCase):
    def test_main_window_lifecycle_does_not_toggle_linux_passthrough(self):
        source = inspect.getsource(main_qml.main)

        self.assertNotIn("set_ui_passthrough", source)
        self.assertNotIn("_sync_linux_ui_passthrough", source)


if __name__ == "__main__":
    unittest.main()
