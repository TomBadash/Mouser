import copy
import sys
import unittest

sys.platform = "linux"

from core.config import DEFAULT_CONFIG
from core.config_validation import (
    ConfigValidationError,
    assemble_full_config,
    normalize_config,
    validate_config,
)


class ConfigValidationTests(unittest.TestCase):
    def _valid_config(self):
        return copy.deepcopy(DEFAULT_CONFIG)

    def test_validate_accepts_default_config(self):
        cfg = self._valid_config()

        validate_config(cfg)

    def test_normalize_migrates_and_fills_defaults(self):
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

        normalized = normalize_config(legacy)

        self.assertEqual(normalized["profiles"]["default"]["apps"], [])
        self.assertEqual(
            normalized["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertIn("language", normalized["settings"])

    def test_normalize_unversioned_config_treats_it_as_current_schema(self):
        raw = {
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "mode_shift": "custom:super+shift+4",
                    },
                },
                "finder": {
                    "label": "Finder",
                    "apps": ["com.apple.finder"],
                    "mappings": {
                        "xbutton1": "custom:tab",
                    },
                },
            },
            "settings": {},
        }

        normalized = normalize_config(raw)

        self.assertEqual(normalized["version"], DEFAULT_CONFIG["version"])
        self.assertNotIn("mode_shift", normalized["profiles"]["finder"]["mappings"])

        assembled = assemble_full_config(normalized)

        self.assertEqual(
            assembled["profiles"]["finder"]["mappings"]["mode_shift"],
            "custom:super+shift+4",
        )

    def test_validate_rejects_unknown_top_level_key(self):
        cfg = self._valid_config()
        cfg["bogus"] = True

        with self.assertRaisesRegex(ConfigValidationError, r"Unknown key at bogus"):
            validate_config(cfg)

    def test_validate_rejects_missing_default_profile(self):
        cfg = self._valid_config()
        cfg["profiles"] = {
            "work": {
                "label": "Work",
                "apps": ["com.example.Work"],
                "mappings": {
                    "middle": "copy",
                },
            }
        }
        cfg["active_profile"] = "work"

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"Config must define a `default` profile",
        ):
            validate_config(cfg)

    def test_validate_rejects_wrong_type_via_schema(self):
        cfg = self._valid_config()
        cfg["settings"]["start_minimized"] = "yes"

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"settings.start_minimized must be a boolean",
        ):
            validate_config(cfg)

    def test_validate_rejects_unknown_mapping_key(self):
        cfg = self._valid_config()
        cfg["profiles"]["default"]["mappings"]["not_a_button"] = "none"

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"not_a_button is not a valid button mapping",
        ):
            validate_config(cfg)

    def test_validate_rejects_unknown_action_id(self):
        cfg = self._valid_config()
        cfg["profiles"]["default"]["mappings"]["middle"] = "definitely_not_real"

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"unknown action 'definitely_not_real'",
        ):
            validate_config(cfg)

    def test_validate_rejects_invalid_custom_shortcut(self):
        cfg = self._valid_config()
        cfg["profiles"]["default"]["mappings"]["middle"] = "custom:super+definitely_not_real"

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"unknown custom key",
        ):
            validate_config(cfg)

    def test_validate_rejects_unknown_layout_override(self):
        cfg = self._valid_config()
        cfg["settings"]["device_layout_overrides"] = {"mx_master_3s": "not_a_layout"}

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"unknown layout 'not_a_layout'",
        ):
            validate_config(cfg)

    def test_assemble_full_config_rejects_default_profile_with_apps(self):
        cfg = self._valid_config()
        cfg["profiles"]["default"]["apps"] = ["com.example.App"]

        with self.assertRaisesRegex(
            ConfigValidationError,
            r"Default profile must have an empty `apps` list",
        ):
            assemble_full_config(cfg)

    def test_assemble_full_config_fills_missing_profile_mappings_from_default_profile(self):
        cfg = self._valid_config()
        cfg["profiles"]["work"] = {
            "label": "Work",
            "apps": ["com.example.Work"],
            "mappings": {
                "middle": "copy",
            },
        }

        assembled = assemble_full_config(cfg)

        self.assertEqual(assembled["profiles"]["work"]["mappings"]["middle"], "copy")
        self.assertEqual(
            assembled["profiles"]["work"]["mappings"]["xbutton1"],
            cfg["profiles"]["default"]["mappings"]["xbutton1"],
        )
        self.assertEqual(
            assembled["profiles"]["work"]["mappings"]["mode_shift"],
            cfg["profiles"]["default"]["mappings"]["mode_shift"],
        )

    def test_assemble_full_config_uses_default_profile_even_when_active_profile_is_app_specific(self):
        cfg = self._valid_config()
        cfg["active_profile"] = "ghostty"
        cfg["profiles"]["default"]["mappings"]["mode_shift"] = "custom:super+shift+4"
        cfg["profiles"]["ghostty"] = {
            "label": "Ghostty",
            "apps": ["com.mitchellh.ghostty"],
            "mappings": {
                "hscroll_left": "next_tab",
            },
        }

        assembled = assemble_full_config(cfg)

        self.assertEqual(
            assembled["profiles"]["ghostty"]["mappings"]["mode_shift"],
            "custom:super+shift+4",
        )
        self.assertEqual(
            assembled["profiles"]["ghostty"]["mappings"]["xbutton1"],
            cfg["profiles"]["default"]["mappings"]["xbutton1"],
        )


if __name__ == "__main__":
    unittest.main()
