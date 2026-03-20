import unittest

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    build_connected_device_info,
    clamp_dpi,
    resolve_device,
)


class LogiDeviceRegistryTests(unittest.TestCase):
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
        self.assertEqual(info.ui_layout, "mx_master")

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


if __name__ == "__main__":
    unittest.main()
