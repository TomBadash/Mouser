import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["profiles"]["default"]["apps"], [])
        self.assertFalse(migrated["settings"]["invert_hscroll"])
        self.assertFalse(migrated["settings"]["invert_vscroll"])
        self.assertEqual(migrated["settings"]["dpi"], 1000)
        self.assertEqual(migrated["settings"]["gesture_threshold"], 50)
        self.assertEqual(migrated["settings"]["gesture_deadzone"], 40)
        self.assertEqual(migrated["settings"]["gesture_timeout_ms"], 3000)
        self.assertEqual(migrated["settings"]["gesture_cooldown_ms"], 500)
        self.assertFalse(migrated["settings"]["debug_mode"])
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
        self.assertFalse(migrated["settings"]["debug_mode"])

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
        self.assertFalse(loaded["settings"]["debug_mode"])
        self.assertEqual(loaded["profiles"]["default"]["mappings"]["middle"], "copy")
        self.assertEqual(
            loaded["profiles"]["default"]["mappings"]["xbutton1"], "alt_tab"
        )
        self.assertEqual(
            loaded["profiles"]["default"]["mappings"]["gesture_left"], "none"
        )


if __name__ == "__main__":
    unittest.main()
