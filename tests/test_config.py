import json
import ntpath
import os
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

        self.assertEqual(migrated["version"], 8)
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
        self.assertFalse(migrated["settings"]["hi_res_scroll"])
        self.assertFalse(migrated["settings"]["start_at_login"])
        self.assertNotIn("start_with_windows", migrated["settings"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"], "none"
        )
        for key in config.GESTURE_DIRECTION_BUTTONS:
            self.assertEqual(
                migrated["profiles"]["default"]["mappings"][key], "none"
            )
        # v7→v8 migration promotes the physical SmartShift button from "none" to
        # "switch_scroll_mode" (ratchet ↔ free-spin, matching Logi Options+ default).
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
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

        self.assertEqual(migrated["version"], 8)
        self.assertEqual(
            migrated["profiles"]["media"]["apps"],
            ["Microsoft.Media.Player.exe", "VLC.exe"],
        )
        self.assertEqual(migrated["settings"]["appearance_mode"], "system")
        self.assertFalse(migrated["settings"]["debug_mode"])
        self.assertEqual(migrated["settings"]["device_layout_overrides"], {})
        self.assertFalse(migrated["settings"]["start_at_login"])
        self.assertNotIn("start_with_windows", migrated["settings"])

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

        self.assertEqual(loaded["version"], 8)
        self.assertEqual(loaded["settings"]["dpi"], 800)
        self.assertFalse(loaded["settings"]["start_at_login"])
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

    def test_migrate_renames_start_with_windows_to_start_at_login(self):
        legacy = {
            "version": 4,
            "profiles": {"default": {"apps": [], "mappings": {}}},
            "settings": {"start_with_windows": True},
        }

        migrated = config._migrate(legacy)

        self.assertEqual(migrated["version"], 8)
        self.assertTrue(migrated["settings"]["start_at_login"])
        self.assertFalse(migrated["settings"]["hi_res_scroll"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
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

    def test_get_profile_for_app_matches_linux_desktop_id_from_runtime_path(self):
        cfg = {
            "profiles": {
                "default": {"apps": []},
                "firefox": {"apps": ["firefox.desktop"]},
            }
        }

        with patch.object(
            config,
            "resolve_app_for_config",
            return_value={
                "id": "firefox.desktop",
                "aliases": [
                    "firefox.desktop",
                    "/usr/bin/firefox",
                    "/usr/lib64/firefox/firefox",
                    "firefox",
                ],
            },
        ):
            self.assertEqual(
                config.get_profile_for_app(cfg, "/usr/lib64/firefox/firefox"),
                "firefox",
            )

    def test_get_profile_for_app_matches_linux_legacy_launcher_path(self):
        cfg = {
            "profiles": {
                "default": {"apps": []},
                "firefox": {"apps": ["/usr/bin/firefox"]},
            }
        }

        with patch.object(
            config,
            "resolve_app_for_config",
            return_value={
                "id": "firefox.desktop",
                "aliases": [
                    "firefox.desktop",
                    "/usr/bin/firefox",
                    "/usr/lib64/firefox/firefox",
                    "firefox",
                ],
            },
        ):
            self.assertEqual(
                config.get_profile_for_app(cfg, "/usr/lib64/firefox/firefox"),
                "firefox",
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
        self.assertTrue(
            resolved["path"].replace("/", os.sep).endswith(
                os.path.join("Applications", "Google Chrome.app")
            )
        )
        self.assertIn("Google Chrome", resolved["aliases"])

    def test_resolve_app_spec_for_windows_exe_path_uses_curated_label(self):
        app_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        with (
            patch.object(app_catalog.sys, "platform", "win32"),
            patch.object(app_catalog.os.path, "exists", return_value=False),
            patch("core.app_catalog.os.path.isabs", ntpath.isabs),
            patch("core.app_catalog.os.path.basename", ntpath.basename),
            patch("core.app_catalog.os.path.abspath", lambda p: p),
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

    def test_linux_desktop_discovery_resolves_exec_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_dir = Path(temp_dir) / "applications"
            bin_dir = Path(temp_dir) / "bin"
            apps_dir.mkdir()
            bin_dir.mkdir()

            exec_path = bin_dir / "code"
            exec_path.write_text("#!/bin/sh\n", encoding="utf-8")
            exec_path.chmod(0o755)

            desktop_path = apps_dir / "code.desktop"
            desktop_path.write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        "Name=Visual Studio Code",
                        "StartupWMClass=code-oss",
                        f"Exec=env BAMF_DESKTOP_FILE_HINT=/usr/share/applications/code.desktop {exec_path} --new-window %F",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(app_catalog.sys, "platform", "linux"),
                patch.object(app_catalog, "_linux_app_dirs", return_value=[str(apps_dir)]),
            ):
                entries = app_catalog._discover_linux_apps()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["label"], "Visual Studio Code")
        self.assertEqual(entries[0]["path"], str(exec_path.resolve()))
        self.assertIn("code.desktop", entries[0]["aliases"])
        self.assertIn("code-oss", entries[0]["aliases"])

    def test_resolve_app_spec_realpaths_linux_binary_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            real_exec = Path(temp_dir) / "real-code"
            linked_exec = Path(temp_dir) / "code"
            real_exec.write_text("#!/bin/sh\n", encoding="utf-8")
            real_exec.chmod(0o755)
            linked_exec.symlink_to(real_exec)

            with patch.object(app_catalog.sys, "platform", "linux"):
                resolved = app_catalog.resolve_app_spec(str(linked_exec))

        self.assertEqual(resolved["path"], str(real_exec.resolve()))
        self.assertIn("real-code", resolved["aliases"])

    def test_resolve_app_spec_for_linux_runtime_path_prefers_catalog_entry(self):
        fake_catalog = [
            {
                "id": "firefox.desktop",
                "label": "Firefox",
                "path": "/usr/bin/firefox",
                "aliases": [
                    "firefox.desktop",
                    "/usr/bin/firefox",
                    "firefox",
                    "Navigator",
                ],
                "legacy_icon": "",
            }
        ]

        with (
            patch.object(app_catalog.sys, "platform", "linux"),
            patch.object(app_catalog, "get_app_catalog", return_value=fake_catalog),
            patch.object(app_catalog.os.path, "exists", return_value=True),
            patch.object(
                app_catalog.os.path,
                "realpath",
                side_effect=lambda value: {
                    "/usr/bin/firefox": "/opt/firefox/firefox",
                    "/usr/lib64/firefox/firefox": "/usr/lib64/firefox/firefox",
                }.get(value, value),
            ),
        ):
            resolved = app_catalog.resolve_app_spec("/usr/lib64/firefox/firefox")

        self.assertEqual(resolved["id"], "firefox.desktop")
        self.assertEqual(resolved["label"], "Firefox")
        self.assertEqual(resolved["path"], "/opt/firefox/firefox")
        self.assertIn("/usr/lib64/firefox/firefox", resolved["aliases"])


if __name__ == "__main__":
    unittest.main()
