import importlib
import os
import sys
import unittest
from unittest.mock import patch

from core import key_simulator


class KeySimulatorActionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform in ("darwin", "win32"), "desktop switching actions are platform-specific")
    def test_desktop_switch_actions_exist(self):
        self.assertIn("space_left", key_simulator.ACTIONS)
        self.assertIn("space_right", key_simulator.ACTIONS)
        self.assertEqual(key_simulator.ACTIONS["space_left"]["label"], "Previous Desktop")
        self.assertEqual(key_simulator.ACTIONS["space_right"]["label"], "Next Desktop")

    @unittest.skipUnless(sys.platform in ("darwin", "win32"), "tab switching actions are platform-specific")
    def test_tab_switch_actions_exist(self):
        self.assertIn("next_tab", key_simulator.ACTIONS)
        self.assertIn("prev_tab", key_simulator.ACTIONS)
        self.assertEqual(key_simulator.ACTIONS["next_tab"]["category"], "Browser")
        self.assertEqual(key_simulator.ACTIONS["prev_tab"]["category"], "Browser")
        self.assertTrue(len(key_simulator.ACTIONS["next_tab"]["keys"]) > 0)
        self.assertTrue(len(key_simulator.ACTIONS["prev_tab"]["keys"]) > 0)


class CustomShortcutParsingTests(unittest.TestCase):
    def test_build_custom_key_name_map_adds_common_aliases(self):
        key_map = key_simulator._build_custom_key_name_map({
            "ctrl": 1,
            "alt": 2,
            "super": 3,
            "enter": 4,
            "esc": 5,
        })

        self.assertEqual(key_map["control"], 1)
        self.assertEqual(key_map["option"], 2)
        self.assertEqual(key_map["opt"], 2)
        self.assertEqual(key_map["cmd"], 3)
        self.assertEqual(key_map["command"], 3)
        self.assertEqual(key_map["meta"], 3)
        self.assertEqual(key_map["win"], 3)
        self.assertEqual(key_map["windows"], 3)
        self.assertEqual(key_map["return"], 4)
        self.assertEqual(key_map["escape"], 5)

    def test_parse_custom_combo_accepts_digit_keys(self):
        keys = key_simulator._parse_custom_combo(
            "custom:ctrl+4",
            {"ctrl": 17, "4": 52},
        )
        self.assertEqual(keys, [17, 52])


class LinuxDesktopShortcutTests(unittest.TestCase):
    def _reload_for_linux(self, desktop: str):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": desktop}, clear=False),
        ):
            importlib.reload(key_simulator)
        self.addCleanup(importlib.reload, key_simulator)
        return key_simulator

    def test_gnome_uses_super_page_keys_for_workspace_switching(self):
        module = self._reload_for_linux("GNOME")

        self.assertEqual(
            module.ACTIONS["space_left"]["keys"],
            [module.KEY_LEFTMETA, module.KEY_PAGEUP],
        )
        self.assertEqual(
            module.ACTIONS["space_right"]["keys"],
            [module.KEY_LEFTMETA, module.KEY_PAGEDOWN],
        )

    def test_kde_uses_ctrl_super_arrow_for_workspace_switching(self):
        module = self._reload_for_linux("KDE")

        self.assertEqual(
            module.ACTIONS["space_left"]["keys"],
            [module.KEY_LEFTCTRL, module.KEY_LEFTMETA, module.KEY_LEFT],
        )
        self.assertEqual(
            module.ACTIONS["space_right"]["keys"],
            [module.KEY_LEFTCTRL, module.KEY_LEFTMETA, module.KEY_RIGHT],
        )

    def test_linux_custom_shortcuts_include_digit_keys_and_aliases(self):
        module = self._reload_for_linux("GNOME")

        self.assertEqual(module._KEY_NAME_TO_CODE["4"], module.KEY_4)
        self.assertIn(module.KEY_4, module._ALL_KEY_CODES)
        self.assertEqual(module._KEY_NAME_TO_CODE["control"], module.KEY_LEFTCTRL)
        self.assertEqual(module._KEY_NAME_TO_CODE["cmd"], module.KEY_LEFTMETA)

class CustomShortcutCaptureTests(unittest.TestCase):
    def test_custom_action_label_uses_super_as_canonical_name(self):
        self.assertEqual(
            key_simulator.custom_action_label("custom:cmd+w"),
            "Super + W",
        )
        self.assertEqual(
            key_simulator.custom_action_label("custom:super+w"),
            "Super + W",
        )

    def test_macos_swaps_qt_control_and_meta_semantics(self):
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["ctrl"],
                "w",
                platform_name="darwin",
            ),
            "super+w",
        )
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["super"],
                "w",
                platform_name="darwin",
            ),
            "ctrl+w",
        )
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["ctrl"],
                "ctrl",
                platform_name="darwin",
            ),
            "super",
        )
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["super"],
                "super",
                platform_name="darwin",
            ),
            "ctrl",
        )

    def test_non_macos_keeps_qt_control_and_meta_semantics(self):
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["ctrl"],
                "w",
                platform_name="linux",
            ),
            "ctrl+w",
        )
        self.assertEqual(
            key_simulator.normalize_captured_shortcut_parts(
                ["super"],
                "w",
                platform_name="linux",
            ),
            "super+w",
        )


class MouseButtonActionTests(unittest.TestCase):
    """Tests for the mouse-button-to-mouse-button remapping feature."""

    _MOUSE_ACTIONS = [
        "mouse_left_click",
        "mouse_right_click",
        "mouse_middle_click",
        "mouse_back_click",
        "mouse_forward_click",
    ]

    def test_mouse_button_actions_exist_in_actions_dict(self):
        for action_id in self._MOUSE_ACTIONS:
            self.assertIn(action_id, key_simulator.ACTIONS, f"{action_id} missing from ACTIONS")
            self.assertEqual(key_simulator.ACTIONS[action_id]["category"], "Mouse")
            self.assertEqual(key_simulator.ACTIONS[action_id]["keys"], [])

    def test_is_mouse_button_action_returns_true_for_mouse_actions(self):
        for action_id in self._MOUSE_ACTIONS:
            self.assertTrue(
                key_simulator.is_mouse_button_action(action_id),
                f"is_mouse_button_action({action_id!r}) should be True",
            )

    def test_is_mouse_button_action_returns_false_for_non_mouse_actions(self):
        self.assertFalse(key_simulator.is_mouse_button_action("alt_tab"))
        self.assertFalse(key_simulator.is_mouse_button_action("none"))
        self.assertFalse(key_simulator.is_mouse_button_action("custom:ctrl+c"))

    def test_mouse_button_labels_are_non_empty_strings(self):
        for action_id in self._MOUSE_ACTIONS:
            label = key_simulator.ACTIONS[action_id]["label"]
            self.assertIsInstance(label, str)
            self.assertTrue(len(label) > 0)


@unittest.skipUnless(sys.platform == "darwin", "macOS key ordering is platform-specific")
class MacKeyComboTests(unittest.TestCase):
    def test_split_modifier_keys_preserves_modifier_first_order(self):
        modifiers, normals = key_simulator._split_modifier_keys([
            key_simulator.kVK_Command,
            key_simulator.kVK_ANSI_C,
            key_simulator.kVK_Shift,
            key_simulator.kVK_ANSI_W,
        ])

        self.assertEqual(
            modifiers,
            [key_simulator.kVK_Command, key_simulator.kVK_Shift],
        )
        self.assertEqual(
            normals,
            [key_simulator.kVK_ANSI_C, key_simulator.kVK_ANSI_W],
        )


if __name__ == "__main__":
    unittest.main()
