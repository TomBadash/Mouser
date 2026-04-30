import unittest

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    KNOWN_LOGI_DEVICES,
    build_connected_device_info,
    clamp_dpi,
    get_buttons_for_layout,
    resolve_device,
)


class LogiDeviceRegistryTests(unittest.TestCase):
    def test_resolve_mx_master_4_by_product_id(self):
        device = resolve_device(product_id=0xB042)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_4")
        self.assertEqual(device.ui_layout, "mx_master_4")

    def test_resolve_mx_master_4_by_hid_product_string(self):
        device = resolve_device(product_name="MX_Master_4")

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_4")

    def test_resolve_mx_master_4_business_pid_to_same_layout(self):
        device = resolve_device(product_id=0xB048)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_4")
        self.assertEqual(device.ui_layout, "mx_master_4")

    def test_resolve_device_by_product_id(self):
        device = resolve_device(product_id=0xB034)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3s")
        self.assertEqual(device.display_name, "MX Master 3S")

    def test_resolve_mx_master_3s_business_pid(self):
        device = resolve_device(product_id=0xB043)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3s")

    def test_resolve_device_by_alias(self):
        device = resolve_device(product_name="MX Master 3 for Mac")

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3")
        self.assertIn(0xB023, device.product_ids)

    def test_resolve_mx_master_3_business_pid(self):
        device = resolve_device(product_id=0xB028)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3")

    def test_resolve_mx_anywhere_3_promoted_pids(self):
        for product_id in (0xB025, 0xB02D):
            with self.subTest(product_id=product_id):
                device = resolve_device(product_id=product_id)

                self.assertIsNotNone(device)
                self.assertEqual(device.key, "mx_anywhere_3")
                self.assertEqual(device.ui_layout, "mx_anywhere_3")
                self.assertEqual(
                    device.image_asset,
                    "logitech-mice/mx_anywhere_3/mouse.png",
                )

    def test_mx_anywhere_3s_uses_exact_catalog_layout(self):
        info = build_connected_device_info(product_id=0xB037)

        self.assertEqual(info.display_name, "MX Anywhere 3S")
        self.assertEqual(info.ui_layout, "mx_anywhere_3s")
        self.assertEqual(
            info.image_asset,
            "logitech-mice/mx_anywhere_3s/mouse.png",
        )

    def test_exact_mx_anywhere_button_sets_include_expected_controls(self):
        anywhere_2s = get_buttons_for_layout("mx_anywhere_2s")
        anywhere_3 = get_buttons_for_layout("mx_anywhere_3")
        anywhere_3s = get_buttons_for_layout("mx_anywhere_3s")

        for buttons in (anywhere_2s, anywhere_3, anywhere_3s):
            with self.subTest(buttons=buttons):
                self.assertIn("hscroll_left", buttons)
                self.assertIn("hscroll_right", buttons)
                self.assertIn("gesture_left", buttons)
                self.assertIn("gesture_right", buttons)

        self.assertNotIn("mode_shift", anywhere_2s)
        self.assertIn("mode_shift", anywhere_3)
        self.assertIn("mode_shift", anywhere_3s)

    def test_known_product_ids_are_unique(self):
        product_ids = {}
        for device in KNOWN_LOGI_DEVICES:
            for product_id in device.product_ids:
                with self.subTest(product_id=f"0x{product_id:04X}"):
                    self.assertNotIn(product_id, product_ids)
                    product_ids[product_id] = device.key

    def test_all_known_product_ids_resolve_to_their_device(self):
        for device in KNOWN_LOGI_DEVICES:
            for product_id in device.product_ids:
                with self.subTest(device=device.key, product_id=f"0x{product_id:04X}"):
                    self.assertEqual(resolve_device(product_id=product_id), device)

    def test_all_exact_layout_keys_resolve_to_button_sets(self):
        for device in KNOWN_LOGI_DEVICES:
            with self.subTest(device=device.key, ui_layout=device.ui_layout):
                self.assertEqual(
                    get_buttons_for_layout(device.ui_layout),
                    device.supported_buttons,
                )

    def test_build_connected_device_info_uses_registry_defaults(self):
        info = build_connected_device_info(
            product_id=0xB023,
            product_name="MX Master 3 for Mac",
            transport="Bluetooth Low Energy",
            source="iokit-enumerate",
        )

        self.assertEqual(info.display_name, "MX Master 3")
        self.assertEqual(info.product_id, 0xB023)
        self.assertEqual(info.transport, "Bluetooth Low Energy")
        self.assertEqual(info.gesture_cids, DEFAULT_GESTURE_CIDS)
        self.assertEqual(info.ui_layout, "mx_master_3")

    def test_build_connected_device_info_falls_back_to_runtime_name(self):
        info = build_connected_device_info(
            product_id=0xB999,
            product_name="Mystery Logitech Mouse",
            gesture_cids=(0x00F1,),
        )

        self.assertEqual(info.display_name, "Mystery Logitech Mouse")
        self.assertEqual(info.key, "mystery_logitech_mouse")
        self.assertEqual(info.gesture_cids, (0x00F1,))
        self.assertEqual(info.ui_layout, "mx_master_3s")
        self.assertEqual(info.image_asset, "logitech-mice/mx_master_3s/mouse.png")

    def test_clamp_dpi_uses_known_device_bounds(self):
        info = build_connected_device_info(product_id=0xB019)

        self.assertEqual(clamp_dpi(8000, info), 4000)
        self.assertEqual(clamp_dpi(100, info), 200)

    def test_clamp_dpi_defaults_without_device(self):
        self.assertEqual(clamp_dpi(100, None), 200)
        self.assertEqual(clamp_dpi(9000, None), 8000)


if __name__ == "__main__":
    unittest.main()
