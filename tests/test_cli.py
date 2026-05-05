import io
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("Quartz", type("QuartzStub", (), {})())
sys.modules.setdefault("yaml", type("YamlStub", (), {"safe_load": staticmethod(lambda stream: None)})())

sys.platform = "linux"
import main_cli


class CliTests(unittest.TestCase):
    def _valid_config(self):
        return {
            "version": 8,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "gesture": "none",
                        "gesture_left": "none",
                        "gesture_right": "none",
                        "gesture_up": "none",
                        "gesture_down": "none",
                        "xbutton1": "alt_tab",
                        "xbutton2": "alt_tab",
                        "hscroll_left": "browser_back",
                        "hscroll_right": "browser_forward",
                        "mode_shift": "switch_scroll_mode",
                    },
                }
            },
            "settings": {
                "start_minimized": True,
                "start_at_login": False,
                "hscroll_threshold": 1,
                "hscroll_cooldown_ms": 350,
                "invert_hscroll": False,
                "invert_vscroll": False,
                "dpi": 1000,
                "smart_shift_mode": "ratchet",
                "smart_shift_enabled": False,
                "smart_shift_threshold": 25,
                "gesture_threshold": 50,
                "gesture_deadzone": 40,
                "gesture_timeout_ms": 3000,
                "gesture_cooldown_ms": 500,
                "appearance_mode": "system",
                "debug_mode": False,
                "device_layout_overrides": {},
                "language": "en",
                "ignore_trackpad": True,
            },
        }

    def test_wait_for_headless_activity_pumps_macos_run_loop(self):
        stop_event = main_cli.threading.Event()
        calls = []

        class _QuartzStub:
            kCFRunLoopDefaultMode = "default"

            @staticmethod
            def CFRunLoopRunInMode(mode, seconds, return_after_source_handled):
                calls.append((mode, seconds, return_after_source_handled))
                stop_event.set()

        with (
            patch("main_cli.sys.platform", "darwin"),
            patch.object(main_cli, "Quartz", _QuartzStub),
        ):
            main_cli._wait_for_headless_activity(stop_event, timeout_s=0.5)

        self.assertEqual(calls, [("default", 0.1, False)])

    def test_export_prints_current_config_as_json(self):
        buf = io.StringIO()
        cfg = {"version": 8, "profiles": {}, "settings": {}}

        with patch("main_cli.load_config", return_value=cfg):
            rc = main_cli.export_config(stdout=buf)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()), cfg)

    def test_normalize_config_migrates_and_fills_defaults(self):
        legacy = {
            "version": 1,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "mappings": {"xbutton1": "browser_back"},
                }
            },
            "settings": {},
        }

        normalized = main_cli.normalize_config(legacy)

        self.assertEqual(normalized["profiles"]["default"]["apps"], [])
        self.assertEqual(
            normalized["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertIn("language", normalized["settings"])

    def test_load_persists_normalized_config_then_starts_engine(self):
        raw = {
            "version": 1,
            "active_profile": "default",
            "profiles": {"default": {"label": "Default", "mappings": {}}},
            "settings": {},
        }

        saved = {}

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "import.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            with (
                patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)),
                patch("main_cli.start_background_service", return_value=0) as start_background_service,
            ):
                rc = main_cli.load_config_and_start(
                    str(config_path),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(
            saved["cfg"]["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        start_background_service.assert_called_once_with()

    def test_load_accepts_stdin_marker(self):
        raw = self._valid_config()
        saved = {}

        with (
            patch("sys.stdin", io.StringIO(json.dumps(raw))),
            patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)),
            patch("main_cli.start_background_service", return_value=0) as start_background_service,
        ):
            rc = main_cli.load_config_and_start(
                "-",
            )

        self.assertEqual(rc, 0)
        start_background_service.assert_called_once_with()

    def test_normalize_rejects_unknown_top_level_key(self):
        raw = self._valid_config()
        raw["bogus"] = True

        with self.assertRaisesRegex(ValueError, r"Unknown key at bogus"):
            main_cli.normalize_config(raw)

    def test_normalize_rejects_missing_default_profile(self):
        raw = self._valid_config()
        raw["profiles"] = {
            "work": {
                "label": "Work",
                "apps": ["com.example.Work"],
                "mappings": {
                    "middle": "copy",
                },
            }
        }
        raw["active_profile"] = "work"

        with self.assertRaisesRegex(ValueError, r"Config must define a `default` profile"):
            main_cli.normalize_config(raw)

    def test_normalize_rejects_unknown_mapping_key(self):
        raw = self._valid_config()
        raw["profiles"]["default"]["mappings"]["not_a_button"] = "none"

        with self.assertRaisesRegex(ValueError, r"not_a_button is not a valid button mapping"):
            main_cli.normalize_config(raw)

    def test_normalize_rejects_unknown_action_id(self):
        raw = self._valid_config()
        raw["profiles"]["default"]["mappings"]["middle"] = "definitely_not_real"

        with self.assertRaisesRegex(ValueError, r"unknown action 'definitely_not_real'"):
            main_cli.normalize_config(raw)

    def test_normalize_rejects_invalid_custom_shortcut(self):
        raw = self._valid_config()
        raw["profiles"]["default"]["mappings"]["middle"] = "custom:super+definitely_not_real"

        with self.assertRaisesRegex(ValueError, r"unknown custom key"):
            main_cli.normalize_config(raw)

    def test_normalize_rejects_wrong_setting_type_instead_of_silently_resetting(self):
        raw = self._valid_config()
        raw["settings"]["start_minimized"] = "yes"

        with self.assertRaisesRegex(ValueError, r"settings.start_minimized must be a boolean"):
            main_cli.normalize_config(raw)

    def test_load_rejects_default_profile_with_nonempty_apps(self):
        raw = self._valid_config()
        raw["profiles"]["default"]["apps"] = ["com.example.App"]

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "import.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"Default profile must have an empty `apps` list"):
                main_cli.load_config_and_start(str(config_path))

    def test_main_load_invalid_config_prints_human_readable_error(self):
        raw = self._valid_config()
        raw["settings"]["start_minimized"] = "yes"

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "import.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            stderr = io.StringIO()

            with (
                patch("main_cli.sys.platform", "darwin"),
                patch("main_cli.setup_logging"),
                patch("sys.stderr", stderr),
            ):
                rc = main_cli.main(["load", str(config_path)])

        self.assertEqual(rc, 2)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("settings.start_minimized must be a boolean", stderr.getvalue())

    def test_start_writes_launch_agent_and_bootstraps_it(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plist_path = Path(tmp_dir) / main_cli.CLI_SERVICE_PLIST_NAME
            launchctl_calls = []

            def _fake_launchctl(args):
                launchctl_calls.append(args)
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with (
                patch("sys.platform", "darwin"),
                patch("main_cli._service_plist_path", return_value=str(plist_path)),
                patch("main_cli._launchctl_run", side_effect=_fake_launchctl),
            ):
                rc = main_cli.start_background_service()
            payload = plistlib.loads(plist_path.read_bytes())

        self.assertEqual(rc, 0)
        self.assertEqual(
            launchctl_calls,
            [["launchctl", "bootstrap", f"gui/{main_cli.os.getuid()}", str(plist_path)]],
        )
        self.assertEqual(payload["Label"], main_cli.CLI_SERVICE_LABEL)
        self.assertEqual(payload["ProgramArguments"], main_cli._service_program_arguments())
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])

    def test_stop_boots_out_and_removes_launch_agent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plist_path = Path(tmp_dir) / main_cli.CLI_SERVICE_PLIST_NAME
            plist_path.write_text("placeholder", encoding="utf-8")
            launchctl_calls = []

            def _fake_launchctl(args):
                launchctl_calls.append(args)
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with (
                patch("sys.platform", "darwin"),
                patch("main_cli._service_plist_path", return_value=str(plist_path)),
                patch("main_cli._launchctl_run", side_effect=_fake_launchctl),
            ):
                rc = main_cli.stop_background_service()

        self.assertEqual(rc, 0)
        self.assertEqual(
            launchctl_calls,
            [["launchctl", "bootout", f"gui/{main_cli.os.getuid()}", str(plist_path)]],
        )
        self.assertFalse(plist_path.exists())

    def test_main_start_and_stop_dispatch_to_service_helpers(self):
        with (
            patch("main_cli.sys.platform", "darwin"),
            patch("main_cli.setup_logging"),
            patch("main_cli.start_background_service", return_value=0) as start_background_service,
            patch("main_cli.stop_background_service", return_value=0) as stop_background_service,
        ):
            self.assertEqual(main_cli.main(["start"]), 0)
            self.assertEqual(main_cli.main(["stop"]), 0)

        start_background_service.assert_called_once_with()
        stop_background_service.assert_called_once_with()

    def test_main_internal_run_dispatches_to_headless_runner(self):
        with (
            patch("main_cli.sys.platform", "darwin"),
            patch("main_cli.setup_logging"),
            patch("main_cli.run_headless_instance", return_value=0) as run_headless_instance,
        ):
            self.assertEqual(main_cli.main(["run"]), 0)

        run_headless_instance.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
