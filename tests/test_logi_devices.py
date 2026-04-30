import unittest

from core.device_layouts import get_device_layout
from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    build_connected_device_info,
    clamp_dpi,
    get_buttons_for_layout,
    iter_known_devices,
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

    def test_resolve_mx_anywhere_3s_uses_layout_key(self):
        device = resolve_device(product_id=0xB037)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_anywhere_3s")
        self.assertEqual(device.ui_layout, "mx_anywhere_3s")
        self.assertEqual(device.image_asset, "mouse_mx_anywhere_3s.png")

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

    def test_build_mx_anywhere_3s_uses_anywhere_family_layout(self):
        info = build_connected_device_info(product_id=0xB037)
        layout = get_device_layout(info.ui_layout)

        self.assertEqual(info.key, "mx_anywhere_3s")
        self.assertEqual(info.ui_layout, "mx_anywhere_3s")
        self.assertEqual(info.image_asset, "mouse_mx_anywhere_3s.png")
        self.assertEqual(layout["key"], "mx_anywhere")
        self.assertTrue(layout["interactive"])

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

    def test_known_device_layout_metadata_is_valid(self):
        for device in iter_known_devices():
            with self.subTest(device=device.key):
                self.assertFalse(device.ui_layout.lower().endswith((".png", ".svg")))
                self.assertIsNotNone(get_buttons_for_layout(device.ui_layout))

                if device.ui_layout != "generic_mouse":
                    layout = get_device_layout(device.ui_layout)
                    self.assertNotEqual(layout["key"], "generic_mouse")

    def test_clamp_dpi_uses_known_device_bounds(self):
        info = build_connected_device_info(product_id=0xB019)

        self.assertEqual(clamp_dpi(8000, info), 4000)
        self.assertEqual(clamp_dpi(100, info), 200)

    def test_clamp_dpi_defaults_without_device(self):
        self.assertEqual(clamp_dpi(100, None), 200)
        self.assertEqual(clamp_dpi(9000, None), 8000)


if __name__ == "__main__":
    unittest.main()
