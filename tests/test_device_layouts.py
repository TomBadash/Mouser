import unittest
from pathlib import Path

from core.device_layouts import _FAMILY_FALLBACKS, get_device_layout, get_manual_layout_choices
from core.logi_device_catalog import LOGI_DEVICE_LAYOUTS
from core.logi_devices import KNOWN_LOGI_DEVICES


class DeviceLayoutTests(unittest.TestCase):
    def test_known_devices_have_layouts_and_assets(self):
        image_root = Path(__file__).resolve().parents[1] / "images"
        for device in KNOWN_LOGI_DEVICES:
            with self.subTest(device=device.key, ui_layout=device.ui_layout):
                layout = get_device_layout(device.ui_layout)

                # Layouts with hotspot art must be interactive; placeholder
                # layouts (device cataloged before artwork is contributed,
                # per CONTRIBUTING_DEVICES.md step 3b) must not be.
                if layout["hotspots"]:
                    self.assertTrue(layout["interactive"])
                else:
                    self.assertFalse(layout["interactive"])
                self.assertEqual(layout["key"], device.ui_layout)
                self.assertTrue((image_root / layout["image_asset"]).is_file())

    def test_known_device_hotspots_are_supported_buttons(self):
        for device in KNOWN_LOGI_DEVICES:
            layout = get_device_layout(device.ui_layout)
            supported_buttons = set(device.supported_buttons)
            for hotspot in layout["hotspots"]:
                with self.subTest(device=device.key, button=hotspot["buttonKey"]):
                    self.assertIn(hotspot["buttonKey"], supported_buttons)

    def test_catalog_same_side_label_anchors_do_not_overlap(self):
        min_label_separation_px = 35
        for layout_key, layout in LOGI_DEVICE_LAYOUTS.items():
            labels_by_side = {}
            for hotspot in layout["hotspots"]:
                side = hotspot.get("labelSide", "right")
                label_y = (
                    layout["image_height"] * hotspot["normY"]
                    + hotspot.get("labelOffY", 0)
                )
                labels_by_side.setdefault(side, []).append(
                    (label_y, hotspot["buttonKey"])
                )

            for side, labels in labels_by_side.items():
                labels.sort()
                for (a_y, a_key), (b_y, b_key) in zip(labels, labels[1:]):
                    gap = b_y - a_y
                    with self.subTest(
                        layout=layout_key,
                        side=side,
                        first=a_key,
                        second=b_key,
                    ):
                        self.assertGreaterEqual(
                            gap,
                            min_label_separation_px,
                            f"{layout_key}: {a_key} (Y={a_y:.1f}) and "
                            f"{b_key} (Y={b_y:.1f}) on {side} side are "
                            f"{gap:.1f}px apart",
                        )

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

    def test_manual_choices_include_gaming_family_layouts(self):
        # G502 has no MX-style family fallback, so its layout must be
        # manually selectable for owners whose device connects with an
        # unrecognized PID/name.
        choices = get_manual_layout_choices()

        self.assertIn({"key": "g502", "label": "G502 family"}, choices)

    def test_manual_choices_do_not_duplicate_layout_keys(self):
        keys = [choice["key"] for choice in get_manual_layout_choices() if choice["key"]]

        self.assertEqual(len(keys), len(set(keys)))

    def test_mx_anywhere_layout_is_interactive(self):
        layout = get_device_layout("mx_anywhere")

        self.assertTrue(layout["interactive"])
        self.assertEqual(layout["image_asset"], "mouse_mx_anywhere_3s.png")
        self.assertGreater(len(layout["hotspots"]), 0)

    def test_mx_anywhere_device_specific_keys_use_catalog_layout(self):
        for layout_key in ("mx_anywhere_3s", "mx_anywhere_3"):
            with self.subTest(layout_key=layout_key):
                layout = get_device_layout(layout_key)

                self.assertEqual(layout["key"], layout_key)
                self.assertTrue(layout["interactive"])
                self.assertEqual(
                    layout["image_asset"],
                    f"logitech-mice/{layout_key}/mouse.png",
                )
                self.assertGreater(len(layout["hotspots"]), 0)

    def test_mx_anywhere_2s_layout_identity_and_wheel_tilt_hotspots(self):
        layout = get_device_layout("mx_anywhere_2s")

        self.assertEqual(layout["key"], "mx_anywhere_2s")
        self.assertEqual(layout["label"], "MX Anywhere 2S")
        self.assertEqual(
            layout["image_asset"],
            "logitech-mice/mx_anywhere_2s/mouse.png",
        )
        self.assertEqual(
            [hotspot["buttonKey"] for hotspot in layout["hotspots"]],
            ["middle", "xbutton1", "xbutton2", "hscroll_left"],
        )
        hotspots = {hotspot["buttonKey"]: hotspot for hotspot in layout["hotspots"]}
        self.assertNotIn("gesture_up", hotspots)
        self.assertNotIn("gesture_down", hotspots)

        self.assertEqual(hotspots["middle"]["label"], "Middle button")
        self.assertEqual(hotspots["xbutton1"]["label"], "Back button")
        self.assertEqual(hotspots["xbutton2"]["label"], "Forward button")

        left = hotspots["hscroll_left"]
        self.assertEqual(left["label"], "Horizontal scroll")
        self.assertEqual(left["summaryType"], "hscroll")
        self.assertTrue(left["isHScroll"])
        self.assertNotIn("hscroll_right", hotspots)

    def test_mx_anywhere_2s_has_no_self_fallback(self):
        self.assertEqual(_FAMILY_FALLBACKS.get("mx_anywhere_2s"), "mx_anywhere")

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
