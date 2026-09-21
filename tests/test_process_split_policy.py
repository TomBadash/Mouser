from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProcessSplitPolicyTests(unittest.TestCase):
    def test_resident_launcher_has_no_qt_import(self):
        source = (ROOT / "mouser_daemon_launcher.py").read_text(encoding="utf-8")
        self.assertIn("from core.macos_daemon import main", source)
        self.assertNotIn("main_qml", source)
        self.assertNotIn("PySide6", source)

    def test_lightweight_daemon_has_no_qt_or_backend_imports(self):
        source = (ROOT / "core" / "macos_daemon.py").read_text(encoding="utf-8")
        self.assertNotIn("from PySide6", source)
        self.assertNotIn("import PySide6", source)
        self.assertNotIn("from ui.backend", source)

    def test_daemon_path_does_not_import_qt_quick(self):
        source = (ROOT / "main_qml.py").read_text(encoding="utf-8")
        conditional = source.index('if _SETTINGS_PROCESS:')
        qml_import = source.index('from PySide6.QtQml import QQmlApplicationEngine')
        daemon_branch = source.index('else:', qml_import)
        self.assertLess(conditional, qml_import)
        self.assertLess(qml_import, daemon_branch)

    def test_settings_child_is_launched_with_ui_helper(self):
        source = (ROOT / "core" / "macos_daemon.py").read_text(encoding="utf-8")
        self.assertIn('process_command("--settings-process")', source)
        helper_source = (ROOT / "core" / "on_demand_ui.py").read_text(encoding="utf-8")
        self.assertIn('"Helpers",', helper_source)
        self.assertIn('"MouserUI.app",', helper_source)
        settings_source = (ROOT / "main_qml.py").read_text(encoding="utf-8")
        self.assertIn('RemoteEngine.from_environment()', settings_source)
        self.assertIn('bridge = DaemonBridgeServer(', source)

    def test_bundle_uses_separate_daemon_and_ui_analyses(self):
        source = (ROOT / "Mouser-mac.spec").read_text(encoding="utf-8")
        self.assertIn('["mouser_daemon_launcher.py"]', source)
        self.assertIn('["mouser_ui_launcher.py"]', source)
        self.assertIn('excludes=[\n        "PySide6",', source)
        self.assertIn('"Contents", "Helpers", "MouserUI.app"', source)

    def test_qt_tools_are_on_demand_workers(self):
        source = (ROOT / "core" / "on_demand_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("PySide6", source)
        self.assertIn('process_command("--ring-process")', source)
        self.assertIn('process_command("--screenshot-process", action_id)', source)

    def test_settings_window_quits_instead_of_hiding(self):
        source = (ROOT / "ui" / "qml" / "Main.qml").read_text(encoding="utf-8")
        self.assertIn('if (standaloneSettingsProcess)', source)
        self.assertIn('Qt.quit()', source)

    def test_inactive_secondary_pages_are_unloaded(self):
        source = (ROOT / "ui" / "qml" / "Main.qml").read_text(encoding="utf-8")
        self.assertNotIn('|| item', source)


if __name__ == "__main__":
    unittest.main()
