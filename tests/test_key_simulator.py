import sys
import unittest

from core.key_simulator import ACTIONS


class KeySimulatorActionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform in ("darwin", "win32"), "desktop switching actions are platform-specific")
    def test_desktop_switch_actions_exist(self):
        self.assertIn("space_left", ACTIONS)
        self.assertIn("space_right", ACTIONS)
        self.assertEqual(ACTIONS["space_left"]["label"], "Previous Desktop")
        self.assertEqual(ACTIONS["space_right"]["label"], "Next Desktop")


if __name__ == "__main__":
    unittest.main()
