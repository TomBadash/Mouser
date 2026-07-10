import copy
import json
import ntpath
import os
import plistlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from core import app_catalog
from core import config


@contextmanager
def _platform_catalog(platform):
    original_cache = app_catalog._CATALOG_CACHE
    try:
        app_catalog._CATALOG_CACHE = None
        with patch.object(app_catalog.sys, "platform", platform):
            yield
    finally:
        app_catalog._CATALOG_CACHE = original_cache


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

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(migrated["profiles"]["default"]["apps"], [])
        self.assertFalse(migrated["settings"]["invert_hscroll"])
        self.assertFalse(migrated["settings"]["invert_vscroll"])
        self.assertEqual(migrated["settings"]["dpi"], 1000)
        self.assertEqual(
            migrated["settings"]["gesture_threshold"],
            config.GESTURE_SENSITIVITY_PX[config.GESTURE_DEFAULT_SENSITIVITY_INDEX],
        )
        self.assertEqual(migrated["settings"]["gesture_commit_window_ms"], 400)
        self.assertEqual(migrated["settings"]["gesture_settle_ms"], 90)
        self.assertEqual(migrated["settings"]["gesture_cross_ratio"], 0.5)
        self.assertEqual(migrated["settings"]["appearance_mode"], "system")
        self.assertFalse(migrated["settings"]["debug_mode"])
        self.assertEqual(migrated["settings"]["device_layout_overrides"], {})
        self.assertTrue(migrated["settings"]["ignore_trackpad"])
        self.assertEqual(migrated["settings"]["screenshot_directory"], "")
        self.assertTrue(migrated["settings"]["check_for_updates"])
        self.assertEqual(migrated["settings"]["update_check_state"], {})
        self.assertFalse(migrated["settings"]["start_at_login"])
        self.assertNotIn("start_with_windows", migrated["settings"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        for key in config.GESTURE_DIRECTION_BUTTONS:
            self.assertEqual(
                migrated["profiles"]["default"]["mappings"][key], "none"
            )
        # v7→v8 migration promotes the physical SmartShift button from "none" to
        # "switch_scroll_mode" (ratchet ↔ free-spin).
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

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(
            migrated["profiles"]["media"]["apps"],
            ["Microsoft.Media.Player.exe", "VLC.exe"],
        )
        self.assertEqual(migrated["settings"]["appearance_mode"], "system")
        self.assertFalse(migrated["settings"]["debug_mode"])
        self.assertEqual(migrated["settings"]["device_layout_overrides"], {})
        self.assertTrue(migrated["settings"]["ignore_trackpad"])
        self.assertEqual(migrated["settings"]["screenshot_directory"], "")
        self.assertTrue(migrated["settings"]["check_for_updates"])
        self.assertEqual(migrated["settings"]["update_check_state"], {})
        self.assertFalse(migrated["settings"]["start_at_login"])
        self.assertNotIn("start_with_windows", migrated["settings"])

    def test_default_hscroll_threshold_supports_fractional_mac_deltas(self):
        self.assertEqual(config.DEFAULT_CONFIG["settings"]["hscroll_threshold"], 0.1)

    def test_load_config_migrates_integer_hscroll_threshold(self):
        partial = {
            "version": 9,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {},
                }
            },
            "settings": {
                "hscroll_threshold": 1,
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

        self.assertEqual(loaded["settings"]["hscroll_threshold"], 0.1)

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

        self.assertEqual(loaded["version"], 21)
        self.assertEqual(loaded["settings"]["dpi"], 800)
        self.assertEqual(loaded["settings"]["action_haptic"], [])
        self.assertTrue(loaded["settings"]["haptic_enabled"])
        self.assertFalse(loaded["settings"]["start_at_login"])
        self.assertEqual(
            loaded["settings"]["gesture_threshold"],
            config.GESTURE_SENSITIVITY_PX[config.GESTURE_DEFAULT_SENSITIVITY_INDEX],
        )
        self.assertEqual(loaded["settings"]["appearance_mode"], "system")
        self.assertFalse(loaded["settings"]["debug_mode"])
        self.assertEqual(loaded["settings"]["device_layout_overrides"], {})
        self.assertTrue(loaded["settings"]["ignore_trackpad"])
        self.assertEqual(loaded["settings"]["screenshot_directory"], "")
        self.assertTrue(loaded["settings"]["check_for_updates"])
        self.assertEqual(loaded["settings"]["update_check_state"], {})
        self.assertEqual(loaded["profiles"]["default"]["mappings"]["middle"], "copy")
        self.assertEqual(
            loaded["profiles"]["default"]["mappings"]["xbutton1"], "mouse_back_click"
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

        self.assertEqual(migrated["version"], 21)
        self.assertTrue(migrated["settings"]["start_at_login"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )

    def test_migrate_v8_to_v9_adds_actions_ring_and_haptic(self):
        v8_cfg = {
            "version": 8,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "mode_shift": "switch_scroll_mode",
                    },
                }
            },
            "settings": {"dpi": 1000},
        }

        migrated = config._migrate(v8_cfg)

        self.assertEqual(migrated["version"], 21)
        # Physical key naming keeps the Sense Panel action on actions_ring.
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "app_expose",
        )
        self.assertEqual(migrated["settings"]["haptic_level"], 2)
        self.assertEqual(migrated["profiles"]["default"]["button_haptic"], {})

    def test_migrate_v9_to_v10_adds_gesture_recognizer_params(self):
        v9_cfg = {
            "version": 9,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"middle": "none", "actions_ring": "none"},
                },
            },
            "settings": {"dpi": 1000, "haptic_level": 2},
        }

        migrated = config._migrate(v9_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(migrated["settings"]["gesture_commit_window_ms"], 400)
        self.assertEqual(migrated["settings"]["gesture_settle_ms"], 90)
        self.assertEqual(migrated["settings"]["gesture_cross_ratio"], 0.5)

    def test_migrate_v10_to_v11_adds_button_haptic(self):
        v10_cfg = {
            "version": 10,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"middle": "none", "actions_ring": "none"},
                },
                "work": {
                    "label": "Work",
                    "apps": ["Code.exe"],
                    "mappings": {"middle": "copy", "actions_ring": "none"},
                },
            },
            "settings": {"dpi": 1000, "haptic_level": 2},
        }

        migrated = config._migrate(v10_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(migrated["profiles"]["default"]["button_haptic"], {})
        self.assertEqual(migrated["profiles"]["work"]["button_haptic"], {})

    def test_migrate_v12_to_v13_adds_action_haptic_list(self):
        v12_cfg = {
            "version": 12,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"middle": "none", "actions_ring": "none"},
                }
            },
            "settings": {"dpi": 1000, "haptic_level": 2, "haptic_enabled": True},
        }

        migrated = config._migrate(v12_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(migrated["settings"]["action_haptic"], [])
        # existing haptic settings preserved
        self.assertTrue(migrated["settings"]["haptic_enabled"])
        self.assertEqual(migrated["settings"]["haptic_level"], 2)

    def test_action_haptic_enabled_returns_false_when_missing(self):
        cfg = {"settings": {"action_haptic": ["cycle_dpi"]}}
        self.assertTrue(config.action_haptic_enabled(cfg, "cycle_dpi"))
        self.assertFalse(config.action_haptic_enabled(cfg, "alt_tab"))

    def test_set_action_haptic_adds_and_removes(self):
        cfg = {"settings": {"action_haptic": []}}

        with patch.object(config, "save_config", lambda c: c):
            cfg = config.set_action_haptic(cfg, "cycle_dpi", True)
            self.assertEqual(cfg["settings"]["action_haptic"], ["cycle_dpi"])

            # Adding the same action twice is a no-op
            cfg = config.set_action_haptic(cfg, "cycle_dpi", True)
            self.assertEqual(cfg["settings"]["action_haptic"], ["cycle_dpi"])

            cfg = config.set_action_haptic(cfg, "volume_mute", True)
            self.assertEqual(
                cfg["settings"]["action_haptic"], ["cycle_dpi", "volume_mute"]
            )

            cfg = config.set_action_haptic(cfg, "cycle_dpi", False)
            self.assertEqual(cfg["settings"]["action_haptic"], ["volume_mute"])

            # Removing a non-present action is a no-op
            cfg = config.set_action_haptic(cfg, "cycle_dpi", False)
            self.assertEqual(cfg["settings"]["action_haptic"], ["volume_mute"])

    def test_migrate_v13_to_v14_adds_button_haptic_and_dedup(self):
        v13_cfg = {
            "version": 13,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"middle": "none", "actions_ring": "none"},
                }
            },
            "settings": {"dpi": 1000, "haptic_level": 2, "haptic_enabled": True,
                         "action_haptic": ["cycle_dpi"]},
        }

        migrated = config._migrate(v13_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(migrated["settings"]["button_haptic"], [])
        self.assertTrue(migrated["settings"]["haptic_dedup"])
        # existing settings preserved
        self.assertEqual(migrated["settings"]["action_haptic"], ["cycle_dpi"])
        self.assertTrue(migrated["settings"]["haptic_enabled"])

    def test_migrate_v17_to_v18_adds_actions_ring_settings_and_slots(self):
        v17_cfg = {
            "version": 17,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "actions_ring": "none",
                        "thumb_button": "none",
                    },
                },
                "work": {
                    "label": "Work",
                    "apps": ["Code.exe"],
                    "mappings": {
                        "middle": "copy",
                        "actions_ring": "none",
                    },
                },
            },
            "settings": {"dpi": 1000, "haptic_level": 2},
        }

        migrated = config._migrate(v17_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertNotIn("actions_ring_mode", migrated["settings"])
        self.assertEqual(migrated["settings"]["actions_ring_hold_ms"], 250)
        # v18→v19 converts "ring" mode to the physical actions_ring key.
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "app_expose",
        )
        self.assertEqual(
            migrated["profiles"]["work"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["work"]["mappings"]["gesture"],
            "app_expose",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring_slots"],
            ["screenshot_fullscreen", "play_pause", "show_desktop", "lock_screen"],
        )
        self.assertEqual(
            migrated["profiles"]["work"]["mappings"]["actions_ring_slots"],
            ["screenshot_fullscreen", "play_pause", "show_desktop", "lock_screen"],
        )
        # existing settings preserved
        self.assertEqual(migrated["settings"]["dpi"], 1000)
        self.assertEqual(migrated["settings"]["haptic_level"], 2)
        # new close-confirmation setting backfilled for pre-existing configs
        self.assertEqual(migrated["settings"]["close_action"], "ask")

    def test_migrate_preserves_explicit_close_action(self):
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg["settings"]["close_action"] = "quit"

        migrated = config._migrate(cfg)

        self.assertEqual(migrated["settings"]["close_action"], "quit")

    def test_migrate_v17_to_v18_preserves_existing_slots(self):
        v17_cfg = {
            "version": 17,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "actions_ring_slots": ["volume_mute", "next_track"],
                    },
                }
            },
            "settings": {"actions_ring_mode": "pie"},
        }

        migrated = config._migrate(v17_cfg)

        self.assertEqual(migrated["version"], 21)
        # setdefault must not overwrite pre-existing values
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring_slots"],
            ["volume_mute", "next_track"],
        )
        # v18→v19 pops actions_ring_mode regardless of value
        self.assertNotIn("actions_ring_mode", migrated["settings"])

    def test_migrate_v18_to_v19_ring_mode_becomes_mapping(self):
        v18_cfg = {
            "version": 18,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"actions_ring": "none"},
                }
            },
            "settings": {"actions_ring_mode": "ring"},
        }

        migrated = config._migrate(v18_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertNotIn("actions_ring_mode", migrated["settings"])
        # v18→v19 sets the physical actions_ring key to activate.
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "app_expose",
        )

    def test_migrate_v18_to_v19_disabled_mode_sets_none(self):
        v18_cfg = {
            "version": 18,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"actions_ring": "play_pause"},
                }
            },
            "settings": {"actions_ring_mode": "disabled"},
        }

        migrated = config._migrate(v18_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertNotIn("actions_ring_mode", migrated["settings"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "none",
        )

    def test_migrate_v18_to_v19_simple_mode_preserves_mapping(self):
        v18_cfg = {
            "version": 18,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"actions_ring": "play_pause"},
                }
            },
            "settings": {"actions_ring_mode": "simple"},
        }

        migrated = config._migrate(v18_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertNotIn("actions_ring_mode", migrated["settings"])
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "play_pause",
        )

    def test_migrate_v19_to_v20_keeps_actions_ring_physical_key(self):
        v19_cfg = {
            "version": 19,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "actions_ring": "activate_actions_ring",
                        "gesture": "none",
                    },
                }
            },
            "settings": {},
        }

        migrated = config._migrate(v19_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "none",
        )

    def test_migrate_v19_to_v20_skips_when_gesture_already_assigned(self):
        v19_cfg = {
            "version": 19,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "actions_ring": "activate_actions_ring",
                        "gesture": "play_pause",
                    },
                }
            },
            "settings": {},
        }

        migrated = config._migrate(v19_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "play_pause",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )

    def test_migrate_v20_to_v21_repairs_legacy_actions_ring_default(self):
        v20_cfg = {
            "version": 20,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "actions_ring": "none",
                        "gesture": "activate_actions_ring",
                    },
                },
                "custom": {
                    "label": "Custom",
                    "apps": [],
                    "mappings": {
                        "actions_ring": "volume_down",
                        "gesture": "app_expose",
                    },
                },
            },
            "settings": {},
        }

        migrated = config._migrate(v20_cfg)

        self.assertEqual(migrated["version"], 21)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["actions_ring"],
            "activate_actions_ring",
        )
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["gesture"],
            "none",
        )
        self.assertEqual(
            migrated["profiles"]["custom"]["mappings"]["actions_ring"],
            "volume_down",
        )
        self.assertEqual(
            migrated["profiles"]["custom"]["mappings"]["gesture"],
            "app_expose",
        )

    def test_button_haptic_enabled_returns_false_when_not_listed(self):
        cfg = {"settings": {"button_haptic": ["middle"]}}
        self.assertTrue(config.button_haptic_enabled(cfg, "middle"))
        self.assertFalse(config.button_haptic_enabled(cfg, "gesture"))

    def test_set_button_haptic_adds_and_removes(self):
        cfg = {"settings": {"button_haptic": []}}

        with patch.object(config, "save_config", lambda c: c):
            cfg = config.set_button_haptic(cfg, "middle", True)
            self.assertEqual(cfg["settings"]["button_haptic"], ["middle"])

            cfg = config.set_button_haptic(cfg, "middle", True)   # no-op
            self.assertEqual(cfg["settings"]["button_haptic"], ["middle"])

            cfg = config.set_button_haptic(cfg, "gesture", True)
            self.assertEqual(cfg["settings"]["button_haptic"], ["middle", "gesture"])

            cfg = config.set_button_haptic(cfg, "middle", False)
            self.assertEqual(cfg["settings"]["button_haptic"], ["gesture"])

            cfg = config.set_button_haptic(cfg, "middle", False)  # no-op
            self.assertEqual(cfg["settings"]["button_haptic"], ["gesture"])

    def test_get_profile_for_app_identity_matches_aliases(self):
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
                config.get_profile_for_app_identity(cfg, ("com.google.Chrome",)),
                "chrome",
            )

    def test_get_profile_for_app_identity_matches_linux_desktop_id_from_runtime_path(self):
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
                config.get_profile_for_app_identity(
                    cfg,
                    ("/usr/lib64/firefox/firefox",),
                ),
                "firefox",
            )

    def test_get_profile_for_app_identity_matches_linux_legacy_launcher_path(self):
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
                config.get_profile_for_app_identity(
                    cfg,
                    ("/usr/lib64/firefox/firefox",),
                ),
                "firefox",
            )


class SaveConfigTests(unittest.TestCase):
    def test_save_config_writes_atomically_to_regular_file(self):
        cfg = {"version": 9, "settings": {}, "profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            with (
                patch.object(config, "CONFIG_DIR", temp_dir),
                patch.object(config, "CONFIG_FILE", str(config_file)),
            ):
                config.save_config(cfg)

            self.assertTrue(config_file.is_file())
            self.assertFalse(config_file.is_symlink())
            self.assertEqual(
                json.loads(config_file.read_text(encoding="utf-8")), cfg
            )

    def test_save_config_preserves_symlinked_config_file(self):
        """When CONFIG_FILE is a symlink (e.g. via GNU stow), save_config must
        update the link target in place rather than replacing the link with a
        regular file."""
        cfg = {"version": 9, "settings": {}, "profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "Application Support" / "Mouser"
            config_dir.mkdir(parents=True)
            real_dir = Path(temp_dir) / "dotfiles" / "mouser"
            real_dir.mkdir(parents=True)
            real_target = real_dir / "config.json"
            real_target.write_text("{}", encoding="utf-8")

            symlink_path = config_dir / "config.json"
            symlink_path.symlink_to(real_target)

            with (
                patch.object(config, "CONFIG_DIR", str(config_dir)),
                patch.object(config, "CONFIG_FILE", str(symlink_path)),
            ):
                config.save_config(cfg)

            self.assertTrue(
                symlink_path.is_symlink(),
                "save_config replaced the symlink with a regular file",
            )
            self.assertEqual(
                os.readlink(str(symlink_path)), str(real_target)
            )
            self.assertEqual(
                json.loads(real_target.read_text(encoding="utf-8")), cfg
            )

    def test_save_config_follows_broken_symlink_target(self):
        """A dangling symlink should be repaired in place: the link survives and
        now points at a valid file with the saved contents."""
        cfg = {"version": 9, "settings": {}, "profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "cfg"
            config_dir.mkdir()
            real_dir = Path(temp_dir) / "real"
            real_dir.mkdir()
            real_target = real_dir / "config.json"  # does NOT exist yet
            symlink_path = config_dir / "config.json"
            symlink_path.symlink_to(real_target)

            with (
                patch.object(config, "CONFIG_DIR", str(config_dir)),
                patch.object(config, "CONFIG_FILE", str(symlink_path)),
            ):
                config.save_config(cfg)

            self.assertTrue(symlink_path.is_symlink())
            self.assertTrue(real_target.is_file())
            self.assertEqual(
                json.loads(real_target.read_text(encoding="utf-8")), cfg
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

    def test_mac_catalog_contains_profile_identity_targets(self):
        ids = {
            spec["id"]: spec
            for spec in app_catalog.MAC_APP_SPECS
        }

        self.assertIn("org.mozilla.firefox", ids)
        self.assertIn("org.mozilla.firefox", ids["org.mozilla.firefox"]["bundle_ids"])
        self.assertIn("firefox", ids["org.mozilla.firefox"]["executables"])

        self.assertIn("com.todesktop.230313mzl4w4u92", ids)
        self.assertIn(
            "com.todesktop.230313mzl4w4u92",
            ids["com.todesktop.230313mzl4w4u92"]["bundle_ids"],
        )

        self.assertIn("com.microsoft.VSCode", ids)
        self.assertIn(
            "com.microsoft.VSCodeInsiders",
            ids["com.microsoft.VSCode"]["bundle_ids"],
        )
        self.assertNotIn("Electron", ids["com.microsoft.VSCode"]["executables"])

    def test_resolve_app_spec_for_firefox_bundle_id_matches_alias(self):
        with _platform_catalog("darwin"):
            by_id = app_catalog.resolve_app_spec("org.mozilla.firefox")
            by_alias = app_catalog.resolve_app_spec("Firefox")
            by_executable = app_catalog.resolve_app_spec("firefox")

        self.assertEqual(by_id["id"], "org.mozilla.firefox")
        self.assertEqual(by_alias["id"], "org.mozilla.firefox")
        self.assertEqual(by_executable["id"], "org.mozilla.firefox")

    def test_resolve_app_spec_for_cursor_bundle_id_matches_alias(self):
        with _platform_catalog("darwin"):
            by_id = app_catalog.resolve_app_spec("com.todesktop.230313mzl4w4u92")
            by_alias = app_catalog.resolve_app_spec("Cursor")

        self.assertEqual(by_id["id"], "com.todesktop.230313mzl4w4u92")
        self.assertEqual(by_alias["id"], "com.todesktop.230313mzl4w4u92")

    def test_generic_electron_executable_does_not_resolve_as_visual_studio_code(self):
        fake_catalog = [
            {
                "id": "com.microsoft.VSCode",
                "label": "Visual Studio Code",
                "path": "/Applications/Visual Studio Code.app",
                "aliases": [
                    "com.microsoft.VSCode",
                    "Visual Studio Code",
                    "VS Code",
                    "Code",
                ],
                "legacy_icon": "VSCODE.png",
            },
            {
                "id": "com.example.electron",
                "label": "Example Electron",
                "path": "/Applications/Example Electron.app",
                "aliases": ["Electron"],
                "legacy_icon": "",
            },
        ]

        with (
            _platform_catalog("darwin"),
            patch.object(app_catalog, "get_app_catalog", return_value=fake_catalog),
        ):
            resolved = app_catalog.resolve_app_spec("Electron")

        self.assertEqual(resolved["id"], "com.example.electron")

    def test_get_profile_for_app_identity_matches_mac_bundle_identity(self):
        cfg = {
            "profiles": {
                "default": {"apps": []},
                "firefox": {"apps": ["Firefox"]},
                "cursor": {"apps": ["Cursor"]},
                "code": {"apps": ["Visual Studio Code"]},
            }
        }

        with _platform_catalog("darwin"):
            self.assertEqual(
                config.get_profile_for_app_identity(cfg, ("org.mozilla.firefox",)),
                "firefox",
            )
            self.assertEqual(
                config.get_profile_for_app_identity(
                    cfg,
                    ("com.todesktop.230313mzl4w4u92",),
                ),
                "cursor",
            )
            self.assertEqual(
                config.get_profile_for_app_identity(
                    cfg,
                    ("com.microsoft.VSCodeInsiders",),
                ),
                "code",
            )

    def test_get_profile_for_app_identity_matches_mac_app_path_to_runtime_bundle_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_path = os.path.join(tmp, "Windowed.app")
            contents = os.path.join(app_path, "Contents")
            os.makedirs(contents)
            with open(os.path.join(contents, "Info.plist"), "wb") as f:
                plistlib.dump({"CFBundleIdentifier": "com.example.Windowed"}, f)

            cfg = {
                "profiles": {
                    "default": {"apps": []},
                    "windowed": {"apps": [app_path]},
                }
            }

            with (
                _platform_catalog("darwin"),
                patch.object(app_catalog, "get_app_catalog", return_value=[]),
            ):
                self.assertEqual(
                    config.get_profile_for_app_identity(
                        cfg,
                        ("com.example.Windowed",),
                    ),
                    "windowed",
                )

    def test_get_profile_for_app_identity_prefers_specific_nested_identity(self):
        cfg = {
            "profiles": {
                "default": {"apps": []},
                "outer": {"apps": ["OuterHost"]},
                "inner": {"apps": ["InnerTool"]},
            }
        }

        self.assertEqual(
            config.get_profile_for_app_identity(cfg, ("InnerTool", "OuterHost")),
            "inner",
        )

    def test_get_profile_for_app_identity_falls_back_to_outer_nested_identity(self):
        cfg = {
            "profiles": {
                "default": {"apps": []},
                "outer": {"apps": ["OuterHost"]},
            }
        }

        self.assertEqual(
            config.get_profile_for_app_identity(cfg, ("InnerTool", "OuterHost")),
            "outer",
        )

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

    def test_get_profile_for_app_identity_matches_windows_full_path(self):
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
                config.get_profile_for_app_identity(
                    cfg,
                    (
                        r"C:\\Users\\luca\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe",
                    ),
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
