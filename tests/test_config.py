import json
import ntpath
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import app_catalog
from core import config


class ConfigMigrationTests(unittest.TestCase):
    def test_migrate_v1_config_adds_profile_apps_and_gesture_defaults(self):
        legacy = {
            "version": 1,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "mappings": {
                        "middle": "none",
                        "xbutton1": "browser_back",
                    },
                }
            },
            "settings": {
                "start_minimized": False,
            },
        }

        migrated = config._migrate(legacy)

        self.assertEqual(migrated["version"], 4)
        self.assertEqual(migrated["profiles"]["default"]["apps"], [])
        self.assertFalse(migrated["settings"]["invert_hscroll"])
        self.assertFalse(migrated["settings"]["invert_vscroll"])
        self.assertEqual(migrated["settings"]["dpi"], 1000)
        self.assertEqual(migrated["settings"]["gesture_threshold"], 50)
        self.assertEqual(migrated["settings"]["gesture_deadzone"], 40)
        self.assertEqual(migrated["settings"]["gesture_timeout_ms"], 3000)
        self.assertEqual(migrated["settings"]["gesture_cooldown_ms"], 500)
        self.assertEqual(migrated["settings"]["appearance_mode"], "system")
        self.assertFalse(migrated["settings"]["debug_mode"])
        self.assertEqual(migrated["settings"]["device_layout_overrides"], {})
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"], "none"
        )
        for key in config.GESTURE_DIRECTION_BUTTONS:
            self.assertEqual(
                migrated["profiles"]["default"]["mappings"][key], "none"
            )

    def test_migrate_updates_media_player_profile_apps(self):
        cfg = {
            "version": 3,
            "profiles": {
                "media": {
                    "apps": ["wmplayer.exe", "VLC.exe"],
                    "mappings": {},
                }
            },
            "settings": {},
        }

        migrated = config._migrate(cfg)

        self.assertEqual(
            migrated["profiles"]["media"]["apps"],
            ["Microsoft.Media.Player.exe", "VLC.exe"],
        )
        self.assertEqual(migrated["settings"]["appearance_mode"], "system")
        self.assertFalse(migrated["settings"]["debug_mode"])
        self.assertEqual(migrated["settings"]["device_layout_overrides"], {})

    def test_load_config_merges_missing_defaults_from_disk(self):
        partial = {
            "version": 3,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "copy",
                    },
                }
            },
            "settings": {
                "dpi": 800,
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(json.dumps(partial), encoding="utf-8")

            with (
                patch.object(config, "CONFIG_DIR", temp_dir),
                patch.object(config, "CONFIG_FILE", str(config_file)),
            ):
                loaded = config.load_config()

        self.assertEqual(loaded["settings"]["dpi"], 800)
        self.assertEqual(loaded["settings"]["gesture_threshold"], 50)
        self.assertEqual(loaded["settings"]["appearance_mode"], "system")
        self.assertFalse(loaded["settings"]["debug_mode"])
        self.assertEqual(loaded["settings"]["device_layout_overrides"], {})
        self.assertEqual(loaded["profiles"]["default"]["mappings"]["middle"], "copy")
        self.assertEqual(
            loaded["profiles"]["default"]["mappings"]["xbutton1"], "alt_tab"
        )
        self.assertEqual(
            loaded["profiles"]["default"]["mappings"]["gesture_left"], "none"
        )

    def test_get_profile_for_app_matches_aliases(self):
        cfg = {
            "app_overrides": {},
            "profiles": {
                "default": {"apps": []},
                "chrome": {"apps": ["Google Chrome"]},
            }
        }

        with patch.object(
            config,
            "resolve_app_for_config",
            return_value={
                "id": "com.google.Chrome",
                "aliases": ["com.google.Chrome", "Google Chrome", "Google Chrome.app"],
            },
        ):
            self.assertEqual(
                config.get_profile_for_app(cfg, "com.google.Chrome"),
                "chrome",
            )


class AppCatalogTests(unittest.TestCase):
    def test_resolve_app_spec_uses_catalog_alias(self):
        fake_catalog = [
            {
                "id": "com.google.Chrome",
                "label": "Google Chrome",
                "path": "/Applications/Google Chrome.app",
                "aliases": ["Google Chrome", "Google Chrome.app"],
                "legacy_icon": "chrom.png",
            }
        ]

        with patch.object(app_catalog, "get_app_catalog", return_value=fake_catalog):
            resolved = app_catalog.resolve_app_spec("Google Chrome")

        self.assertEqual(resolved["id"], "com.google.Chrome")
        self.assertEqual(resolved["label"], "Google Chrome")

    def test_resolve_app_spec_for_mac_app_path_prefers_bundle_identifier(self):
        app_path = "/Applications/Google Chrome.app"
        plist = {
            "CFBundleIdentifier": "com.google.Chrome",
            "CFBundleDisplayName": "Google Chrome",
            "CFBundleExecutable": "Google Chrome",
        }

        with (
            patch.object(app_catalog.sys, "platform", "darwin"),
            patch.object(app_catalog.os.path, "exists", return_value=True),
            patch.object(app_catalog, "_read_mac_bundle_info", return_value=plist),
        ):
            resolved = app_catalog.resolve_app_spec(app_path)

        self.assertEqual(resolved["id"], "com.google.Chrome")
        self.assertEqual(resolved["label"], "Google Chrome")
        self.assertEqual(resolved["path"], app_path)
        self.assertIn("Google Chrome", resolved["aliases"])

    def test_resolve_app_spec_for_windows_exe_path_uses_curated_label(self):
        app_path = "/Program Files/Google/Chrome/Application/chrome.exe"

        with (
            patch.object(app_catalog.sys, "platform", "win32"),
            patch.object(app_catalog.os.path, "exists", return_value=False),
        ):
            resolved = app_catalog.resolve_app_spec(app_path)

        self.assertEqual(resolved["id"], "chrome.exe")
        self.assertEqual(resolved["label"], "Google Chrome")
        self.assertEqual(resolved["path"], app_path)
        self.assertIn("chrome.exe", resolved["aliases"])

    def test_resolve_app_spec_for_windows_terminal_alias(self):
        with patch.object(app_catalog, "get_app_catalog", return_value=[]):
            resolved = app_catalog.resolve_app_spec("wt.exe")

        self.assertEqual(resolved["id"], "WindowsTerminal.exe")
        self.assertEqual(resolved["label"], "Windows Terminal")

    def test_get_profile_for_app_matches_windows_full_path(self):
        cfg = {
            "app_overrides": {},
            "profiles": {
                "default": {"apps": []},
                "terminal": {"apps": ["WindowsTerminal.exe"]},
            },
        }

        with patch.object(
            config,
            "resolve_app_for_config",
            return_value={
                "id": "WindowsTerminal.exe",
                "aliases": [
                    "WindowsTerminal.exe",
                    "wt.exe",
                    r"C:\\Users\\luca\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe",
                ],
            },
        ):
            self.assertEqual(
                config.get_profile_for_app(
                    cfg,
                    r"C:\\Users\\luca\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe",
                ),
                "terminal",
            )

    def test_windows_registry_match_rejects_edge_runtime_helper(self):
        spec = next(item for item in app_catalog.WINDOWS_APP_SPECS if item["id"] == "msedge.exe")
        entry = {
            "display_name": "Microsoft Edge WebView2 Runtime",
            "display_icon": "",
            "install_location": r"C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application",
        }

        self.assertFalse(app_catalog._windows_registry_matches(spec, entry))

    def test_windows_registry_path_prefers_exact_executable_match(self):
        spec = next(item for item in app_catalog.WINDOWS_APP_SPECS if item["id"] == "msedge.exe")
        entries = [
            {
                "display_name": "Microsoft Edge",
                "display_icon": r"C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\msedgewebview2.exe",
                "install_location": r"C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application",
            },
            {
                "display_name": "Microsoft Edge",
                "display_icon": r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                "install_location": r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application",
            },
        ]

        with (
            patch("core.app_catalog.os.path.basename", ntpath.basename),
            patch("core.app_catalog.os.path.abspath", lambda value: value),
        ):
            self.assertEqual(
                app_catalog._windows_registry_path(spec, entries),
                r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            )


if __name__ == "__main__":
    unittest.main()
