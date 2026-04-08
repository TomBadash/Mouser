import unittest

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    MX_MASTER_BUTTONS,
    MX_MASTER_4_BUTTONS,
    build_connected_device_info,
    clamp_dpi,
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

    def test_resolve_device_by_product_id(self):
        device = resolve_device(product_id=0xB034)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3s")
        self.assertEqual(device.display_name, "MX Master 3S")

    def test_resolve_device_by_alias(self):
        device = resolve_device(product_name="MX Master 3 for Mac")

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_master_3")
        self.assertIn(0xB023, device.product_ids)

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
        self.assertEqual(info.ui_layout, "generic_mouse")

    def test_clamp_dpi_uses_known_device_bounds(self):
        info = build_connected_device_info(product_id=0xB019)

        self.assertEqual(clamp_dpi(8000, info), 4000)
        self.assertEqual(clamp_dpi(100, info), 200)

    def test_clamp_dpi_defaults_without_device(self):
        self.assertEqual(clamp_dpi(100, None), 200)
        self.assertEqual(clamp_dpi(9000, None), 8000)

    # ── MX Master 4 specific tests ─────────────────────────────

    def test_mx_master_4_has_actions_ring_button(self):
        device = resolve_device(product_id=0xB042)
        self.assertIn("actions_ring", device.supported_buttons)

    def test_mx_master_4_uses_mxm4_image(self):
        device = resolve_device(product_id=0xB042)
        self.assertEqual(device.image_asset, "mxm4.png")

    def test_mx_master_4_buttons_superset_of_mx_master(self):
        self.assertTrue(
            set(MX_MASTER_BUTTONS).issubset(set(MX_MASTER_4_BUTTONS)),
            "MX Master 4 buttons must include all MX Master buttons",
        )

    def test_mx_master_3s_lacks_actions_ring(self):
        device = resolve_device(product_id=0xB034)
        self.assertNotIn("actions_ring", device.supported_buttons)

    def test_mx_master_4_build_info_has_actions_ring(self):
        info = build_connected_device_info(
            product_id=0xB042,
            product_name="MX Master 4",
            transport="Bluetooth Low Energy",
            source="hidapi-enumerate",
        )
        self.assertIn("actions_ring", info.supported_buttons)
        self.assertEqual(info.image_asset, "mxm4.png")
        self.assertEqual(info.ui_layout, "mx_master_4")


if __name__ == "__main__":
    unittest.main()
