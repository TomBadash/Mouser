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

    @unittest.skipUnless(sys.platform in ("darwin", "win32"), "tab switching actions are platform-specific")
    def test_tab_switch_actions_exist(self):
        self.assertIn("next_tab", ACTIONS)
        self.assertIn("prev_tab", ACTIONS)
        self.assertEqual(ACTIONS["next_tab"]["category"], "Browser")
        self.assertEqual(ACTIONS["prev_tab"]["category"], "Browser")
        self.assertTrue(len(ACTIONS["next_tab"]["keys"]) > 0)
        self.assertTrue(len(ACTIONS["prev_tab"]["keys"]) > 0)


if __name__ == "__main__":
    unittest.main()
