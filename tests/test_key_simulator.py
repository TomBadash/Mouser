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


if __name__ == "__main__":
    unittest.main()
