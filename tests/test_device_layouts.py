import unittest

from core.device_layouts import _FAMILY_FALLBACKS, get_device_layout, get_manual_layout_choices


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

    def test_manual_choices_do_not_duplicate_layout_keys(self):
        keys = [choice["key"] for choice in get_manual_layout_choices() if choice["key"]]

        self.assertEqual(len(keys), len(set(keys)))

    def test_mx_anywhere_layout_is_interactive(self):
        layout = get_device_layout("mx_anywhere")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mouse_mx_anywhere_3s.png")
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_mx_anywhere_device_specific_keys_use_family_layout(self):
        for layout_key in ("mx_anywhere_3s", "mx_anywhere_3"):
            with self.subTest(layout_key=layout_key):
                layout = get_device_layout(layout_key)

                self.assertEqual(layout["key"], "mx_anywhere")
                self.assertTrue(layout["interactive"])
                self.assertEqual(layout["image_asset"], "mouse_mx_anywhere_3s.png")
                self.assertGreater(len(layout["hotspots"]), 0)

    def test_mx_anywhere_2s_layout_identity_and_wheel_tilt_hotspots(self):
        layout = get_device_layout("mx_anywhere_2s")

        self.assertEqual(layout["key"], "mx_anywhere_2s")
        self.assertEqual(layout["label"], "MX Anywhere 2S")
        hotspots = {hotspot["buttonKey"]: hotspot for hotspot in layout["hotspots"]}
        self.assertNotIn("gesture_up", hotspots)
        self.assertNotIn("gesture_down", hotspots)

        left = hotspots["hscroll_left"]
        self.assertEqual(left["label"], "Wheel Left")
        self.assertEqual(left["summaryType"], "hscroll")
        self.assertTrue(left["isHScroll"])
        self.assertEqual(left["normX"], 0.39)
        self.assertEqual(left["normY"], 0.57)
        self.assertEqual(left["labelSide"], "left")
        self.assertEqual(left["labelOffX"], 200)
        self.assertEqual(left["labelOffY"], 80)

        right = hotspots["hscroll_right"]
        self.assertEqual(right["label"], "Wheel Right")
        self.assertEqual(right["summaryType"], "hscroll")
        self.assertTrue(right["isHScroll"])
        self.assertEqual(right["normX"], 0.26)
        self.assertEqual(right["normY"], 0.44)
        self.assertEqual(right["labelSide"], "left")
        self.assertEqual(right["labelOffX"], -20)
        self.assertEqual(right["labelOffY"], -30)

    def test_mx_anywhere_2s_has_no_self_fallback(self):
        self.assertNotEqual(_FAMILY_FALLBACKS.get("mx_anywhere_2s"), "mx_anywhere_2s")

    def test_mx_vertical_layout_is_interactive(self):
        layout = get_device_layout("mx_vertical")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mx_vertical.png")
        self.assertGreater(len(layout["hotspots"]), 0)


if __name__ == "__main__":
    unittest.main()
