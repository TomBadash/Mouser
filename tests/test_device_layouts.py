import unittest

from core.device_layouts import get_device_layout, get_manual_layout_choices


class DeviceLayoutTests(unittest.TestCase):
    def test_master_layout_is_interactive(self):
        layout = get_device_layout("mx_master")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mouse.png")
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_unknown_layout_falls_back_to_generic(self):
        layout = get_device_layout("does_not_exist")

        self.assertFalse(layout["interactive"])
        self.assertEqual(layout["key"], "generic_mouse")
        self.assertEqual(layout["image_asset"], "icons/mouse-simple.svg")

    def test_manual_choices_include_auto_and_interactive_layouts(self):
        choices = get_manual_layout_choices()

        self.assertEqual(choices[0], {"key": "", "label": "Auto-detect"})
        self.assertIn({"key": "mx_master", "label": "MX Master family"}, choices)
        self.assertNotIn({"key": "mx_anywhere", "label": "MX Anywhere family"}, choices)


if __name__ == "__main__":
    unittest.main()
