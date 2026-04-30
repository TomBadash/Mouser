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
        self.assertIn({"key": "mx_anywhere", "label": "MX Anywhere family"}, choices)
        self.assertIn({"key": "mx_vertical", "label": "MX Vertical family"}, choices)

    def test_mx_anywhere_layout_is_interactive(self):
        layout = get_device_layout("mx_anywhere")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mouse_mx_anywhere_3s.png")
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_mx_vertical_layout_is_interactive(self):
        layout = get_device_layout("mx_vertical")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mx_vertical.png")
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_exact_mx_master_3s_layout_uses_catalog_asset(self):
        layout = get_device_layout("mx_master_3s")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["key"], "mx_master_3s")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_master_3s/mouse.png",
        )
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_exact_mx_master_4_layout_uses_catalog_asset(self):
        layout = get_device_layout("mx_master_4")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["key"], "mx_master_4")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_master_4/mouse.png",
        )
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_exact_mx_anywhere_2s_layout_uses_catalog_asset(self):
        layout = get_device_layout("mx_anywhere_2s")
        hotspot_keys = {hotspot["buttonKey"] for hotspot in layout["hotspots"]}

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["key"], "mx_anywhere_2s")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_anywhere_2s/mouse.png",
        )
        self.assertIn("hscroll_left", hotspot_keys)
        self.assertNotIn("mode_shift", hotspot_keys)

    def test_exact_mx_anywhere_3_layout_uses_catalog_asset(self):
        layout = get_device_layout("mx_anywhere_3")
        hotspot_keys = {hotspot["buttonKey"] for hotspot in layout["hotspots"]}

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["key"], "mx_anywhere_3")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_anywhere_3/mouse.png",
        )
        self.assertIn("hscroll_left", hotspot_keys)
        self.assertIn("mode_shift", hotspot_keys)

    def test_exact_mx_anywhere_3s_layout_uses_catalog_asset(self):
        layout = get_device_layout("mx_anywhere_3s")
        hotspot_keys = {hotspot["buttonKey"] for hotspot in layout["hotspots"]}

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["key"], "mx_anywhere_3s")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_anywhere_3s/mouse.png",
        )
        self.assertIn("hscroll_left", hotspot_keys)
        self.assertIn("mode_shift", hotspot_keys)


if __name__ == "__main__":
    unittest.main()
