import unittest

from core.device_layouts import get_device_layout
from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    GENERIC_BUTTONS,
    KNOWN_LOGI_DEVICES,
    MX_MASTER_BUTTONS,
    MX_VERTICAL_BUTTONS,
    build_device_capability_inventory,
    build_connected_device_info,
    clamp_dpi,
    derive_supported_buttons_from_reprog_controls,
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

    def test_resolve_mx_anywhere_3s_uses_layout_key(self):
        device = resolve_device(product_id=0xB037)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "mx_anywhere_3s")
        self.assertEqual(device.ui_layout, "mx_anywhere_3s")
        self.assertEqual(device.image_asset, "logitech-mice/mx_anywhere_3s/mouse.png")

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

    def test_all_device_layout_keys_resolve_to_button_sets(self):
        for device in KNOWN_LOGI_DEVICES:
            with self.subTest(device=device.key, ui_layout=device.ui_layout):
                self.assertIsNotNone(get_buttons_for_layout(device.ui_layout))

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
        self.assertIn("mode_shift", info.supported_buttons)

    def test_hid_capability_guardrail_filters_runtime_buttons(self):
        info = build_connected_device_info(
            product_id=0xB023,
            reprog_controls=[
                {"cid": 0x0052},
                {"cid": 0x0053},
                {"cid": 0x0056},
                {"cid": 0x00C3},
            ],
            gesture_cids=(0x00C3,),
        )

        self.assertIn("gesture", info.supported_buttons)
        self.assertNotIn("mode_shift", info.supported_buttons)
        self.assertIn("hscroll_left", info.supported_buttons)

    def test_build_mx_anywhere_3s_uses_exact_catalog_layout(self):
        info = build_connected_device_info(product_id=0xB037)
        layout = get_device_layout(info.ui_layout)

        self.assertEqual(info.key, "mx_anywhere_3s")
        self.assertEqual(info.ui_layout, "mx_anywhere_3s")
        self.assertEqual(info.image_asset, "logitech-mice/mx_anywhere_3s/mouse.png")
        self.assertEqual(layout["key"], "mx_anywhere_3s")
        self.assertTrue(layout["interactive"])

    def test_build_connected_device_info_falls_back_to_runtime_name(self):
        info = build_connected_device_info(
            product_id=0xB999,
            product_name="Mystery Logitech Mouse",
            reprog_controls=[
                {"cid": 0x00C3},
            ],
            gesture_cids=(0x00F1,),
        )

        self.assertEqual(info.display_name, "Mystery Logitech Mouse")
        self.assertEqual(info.key, "mystery_logitech_mouse")
        self.assertEqual(info.gesture_cids, (0x00F1,))
        self.assertEqual(info.ui_layout, "generic_mouse")
        self.assertEqual(info.image_asset, "icons/mouse-simple.svg")
        self.assertEqual(info.supported_buttons, ("middle", "xbutton1", "xbutton2"))

    def test_m720_falls_back_to_generic_layout_without_device_claim(self):
        for product_id in (0xC52B, 0xB015):
            with self.subTest(product_id=f"0x{product_id:04X}"):
                info = build_connected_device_info(
                    product_id=product_id,
                    product_name="M720 Triathlon Multi-Device Mouse",
                    reprog_controls=[
                        {"cid": 0x0050},
                        {"cid": 0x0051},
                        {"cid": 0x0052},
                        {"cid": 0x0053},
                        {"cid": 0x0056},
                        {"cid": 0x005B},
                        {"cid": 0x005D},
                        {"cid": 0x00D0},
                        {"cid": 0x00D7},
                    ],
                )

                self.assertEqual(info.key, "m720_triathlon_multi-device_mouse")
                self.assertEqual(info.display_name, "M720 Triathlon Multi-Device Mouse")
                self.assertEqual(info.ui_layout, "generic_mouse")
                self.assertEqual(info.image_asset, "icons/mouse-simple.svg")
                self.assertEqual(info.supported_buttons, ("middle", "xbutton1", "xbutton2"))

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

    def test_mx_anywhere_2s_supported_buttons_include_middle_and_hscroll(self):
        device = resolve_device(product_id=0xB01A)

        self.assertIsNotNone(device)
        self.assertIn("middle", device.supported_buttons)
        self.assertIn("hscroll_left", device.supported_buttons)
        self.assertIn("hscroll_right", device.supported_buttons)
        self.assertNotIn("mode_shift", device.supported_buttons)

    def test_get_buttons_for_mx_anywhere_2s_layout_uses_specific_tuple(self):
        device = resolve_device(product_id=0xB01A)

        self.assertIsNotNone(device)
        self.assertIs(get_buttons_for_layout("mx_anywhere_2s"), device.supported_buttons)

    def test_mx_master_4_supports_haptic_button(self):
        device = resolve_device(product_id=0xB042)
        self.assertIsNotNone(device)
        self.assertIn("haptic", device.supported_buttons)

    def test_other_mx_master_devices_do_not_expose_haptic(self):
        for pid in (0xB034, 0xB023, 0xB019, 0xB012):  # 3S, 3, 2S, original
            device = resolve_device(product_id=pid)
            self.assertIsNotNone(device, f"missing device for PID {pid:#06x}")
            self.assertNotIn(
                "haptic",
                device.supported_buttons,
                f"{device.key} should not expose haptic button",
            )

    def test_mx_master_4_layout_buttons_include_haptic(self):
        buttons = get_buttons_for_layout("mx_master_4")
        self.assertIsNotNone(buttons)
        self.assertIn("haptic", buttons)


class RuntimeSupportedButtonTests(unittest.TestCase):
    @staticmethod
    def _control(cid, flags=None, mapping_flags=None):
        control = {"cid": cid}
        if flags is not None:
            control["flags"] = flags
        if mapping_flags is not None:
            control["mapping_flags"] = mapping_flags
        return control

    def test_reprog_control_filter_keeps_static_buttons_without_controls(self):
        self.assertEqual(
            derive_supported_buttons_from_reprog_controls(
                MX_MASTER_BUTTONS,
                [],
                gesture_cids=(0x00C3,),
            ),
            MX_MASTER_BUTTONS,
        )

    def test_capability_inventory_serializes_json_safe_shape(self):
        inventory = build_device_capability_inventory(
            [
                self._control(0x00C4, flags="0x0531"),
                self._control(0x00D7, flags="0x03A0"),
                self._control(0x01A0, flags="0x0531"),
            ],
            gesture_cids=(0x00D7,),
            active_gesture_cid="0x00D7",
            gesture_rawxy_enabled=True,
            discovered_features=(
                "REPROG_V4 (0x1B04)",
                "ADJUSTABLE_DPI (0x2201)",
                "SMART_SHIFT_ENHANCED (0x2111)",
                "BATTERY (0x1004)",
            ),
        )

        self.assertTrue(inventory.has_reprog_controls)
        self.assertEqual(inventory.active_gesture_cid, 0x00D7)
        self.assertTrue(inventory.gesture_directions)
        self.assertTrue(inventory.mode_shift)
        self.assertTrue(inventory.smart_shift)
        self.assertTrue(inventory.adjustable_dpi)
        self.assertTrue(inventory.battery)
        self.assertEqual(
            inventory.to_dict()["known_unsupported_controls"],
            [],
        )

    def test_reprog_control_filter_removes_missing_gesture_group(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x0052),
                self._control(0x0053),
                self._control(0x0056),
                self._control(0x00C4),
            ],
            gesture_cids=(0x00C3,),
        )

        self.assertNotIn("gesture", buttons)
        self.assertNotIn("gesture_left", buttons)
        self.assertNotIn("gesture_right", buttons)

    def test_reprog_control_filter_keeps_selected_gesture_cid(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x00D7, flags=0x03B0),
                self._control(0x00C4, flags=0x0130),
            ],
            gesture_cids=(0x00D7,),
            active_gesture_cid=0x00D7,
            gesture_rawxy_enabled=True,
        )

        self.assertIn("gesture", buttons)
        self.assertIn("gesture_up", buttons)

    def test_reprog_control_filter_removes_directional_gestures_without_rawxy(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x00C3, flags=0x0030),
                self._control(0x00C4, flags=0x0130),
            ],
            gesture_cids=(0x00C3,),
            active_gesture_cid=0x00C3,
            gesture_rawxy_enabled=False,
        )

        self.assertIn("gesture", buttons)
        self.assertNotIn("gesture_left", buttons)
        self.assertNotIn("gesture_right", buttons)
        self.assertNotIn("gesture_up", buttons)
        self.assertNotIn("gesture_down", buttons)

    def test_reprog_control_filter_removes_missing_mode_shift(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x00C3, flags=0x0130),
                self._control(0x0052),
            ],
            gesture_cids=(0x00C3,),
            active_gesture_cid=0x00C3,
            gesture_rawxy_enabled=True,
        )

        self.assertNotIn("mode_shift", buttons)

    def test_reprog_control_filter_removes_non_divertable_mode_shift(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x00C3, flags=0x0130),
                self._control(0x00C4, flags=0x0110),
            ],
            gesture_cids=(0x00C3,),
            active_gesture_cid=0x00C3,
            gesture_rawxy_enabled=True,
        )

        self.assertNotIn("mode_shift", buttons)

    def test_reprog_control_filter_removes_missing_dpi_switch(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_VERTICAL_BUTTONS,
            [
                self._control(0x0052),
                self._control(0x0053),
                self._control(0x0056),
            ],
        )

        self.assertNotIn("dpi_switch", buttons)

    def test_reprog_control_filter_preserves_hscroll_without_hscroll_cids(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control(0x00C3, flags=0x0130),
                self._control(0x00C4, flags=0x0130),
            ],
            gesture_cids=(0x00C3,),
            active_gesture_cid=0x00C3,
            gesture_rawxy_enabled=True,
        )

        self.assertIn("hscroll_left", buttons)
        self.assertIn("hscroll_right", buttons)

    def test_reprog_control_filter_ignores_unknown_cids_and_preserves_order(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            MX_MASTER_BUTTONS,
            [
                self._control("0x01A0", flags="0x0130"),
                self._control("0x00C3", flags="0x0130"),
                self._control("0x00C4", flags="0x0130"),
            ],
            gesture_cids=(0x00C3,),
            active_gesture_cid="0x00C3",
            gesture_rawxy_enabled=True,
        )

        self.assertNotIn("0x01A0", buttons)
        self.assertEqual(buttons, tuple(button for button in MX_MASTER_BUTTONS))

    def test_mx_anywhere_2s_solaar_controls_keep_tilt_hscroll_without_mode_shift(self):
        info = build_connected_device_info(
            product_id=0xB01A,
            reprog_controls=[
                self._control(0x0052, flags=0x0130),
                self._control(0x0053, flags=0x0130),
                self._control(0x0056, flags=0x0130),
                self._control(0x005B, flags=0x0130),
                self._control(0x005D, flags=0x0130),
                self._control(0x00D7, flags=0x03A0),
            ],
            gesture_cids=(0x00D7,),
            active_gesture_cid=0x00D7,
            gesture_rawxy_enabled=True,
        )

        self.assertIn("gesture_left", info.supported_buttons)
        self.assertIn("gesture_right", info.supported_buttons)
        self.assertIn("hscroll_left", info.supported_buttons)
        self.assertIn("hscroll_right", info.supported_buttons)
        self.assertNotIn("mode_shift", info.supported_buttons)

    def test_mx_anywhere_3_issue_142_distinguishes_mode_shift_and_gesture(self):
        info = build_connected_device_info(
            product_id=0xB025,
            product_name="MX Anywhere 3",
            reprog_controls=[
                self._control(0x0052, flags=0x0531),
                self._control(0x0053, flags=0x0D31),
                self._control(0x0056, flags=0x0D31),
                self._control(0x00C4, flags=0x0531),
                self._control(0x00D7, flags=0x03A0),
            ],
            discovered_features=(
                "REPROG_V4 (0x1B04)",
                "ADJUSTABLE_DPI (0x2201)",
                "SMART_SHIFT_ENHANCED (0x2111)",
                "BATTERY (0x1004)",
            ),
        )

        self.assertEqual(info.key, "mx_anywhere_3")
        self.assertIn("mode_shift", info.supported_buttons)
        self.assertIn("gesture", info.supported_buttons)
        self.assertEqual(info.capability_inventory.active_gesture_cid, 0x00D7)
        self.assertTrue(info.capability_inventory.mode_shift)
        self.assertTrue(info.capability_inventory.smart_shift)
        self.assertTrue(info.capability_inventory.adjustable_dpi)

    def test_m720_issue_47_reports_capability_inventory_without_support_claim(self):
        info = build_connected_device_info(
            product_id=0xB015,
            product_name="M720_Triathlon",
            reprog_controls=[
                self._control(0x0052, flags=0x0171),
                self._control(0x0053, flags=0x0171),
                self._control(0x0056, flags=0x0171),
                self._control(0x005B, flags=0x0171),
                self._control(0x005D, flags=0x0171),
                self._control(0x00D0, flags=0x0171),
                self._control(0x00D7, flags=0x03A0),
            ],
            gesture_cids=(0x00D0,),
            active_gesture_cid=0x00D0,
            gesture_rawxy_enabled=True,
            discovered_features=("REPROG_V4 (0x1B04)", "BATTERY (0x1000)"),
        )

        self.assertEqual(info.key, "m720_triathlon")
        self.assertEqual(info.ui_layout, "generic_mouse")
        self.assertEqual(info.supported_buttons, GENERIC_BUTTONS)
        self.assertEqual(info.capability_inventory.active_gesture_cid, 0x00D0)
        self.assertEqual(info.capability_inventory.hscroll_cids, (0x005B, 0x005D))
        self.assertNotIn("mode_shift", info.supported_buttons)

    def test_mx_ergo_issue_22_reports_precision_mode_without_support_claim(self):
        info = build_connected_device_info(
            product_id=0xB01D,
            product_name="MX Ergo Multi-Device Trackball",
            reprog_controls=[
                self._control(0x0052, flags=0x0171),
                self._control(0x0053, flags=0x0171),
                self._control(0x0056, flags=0x0171),
                self._control(0x00ED, flags=0x0171),
                self._control(0x005B, flags=0x0171),
                self._control(0x005D, flags=0x0171),
                self._control(0x00D7, flags=0x03A0),
            ],
            discovered_features=("REPROG_V4 (0x1B04)", "BATTERY (0x1000)"),
        )

        self.assertEqual(info.key, "mx_ergo_multi-device_trackball")
        self.assertEqual(info.ui_layout, "generic_mouse")
        self.assertEqual(info.supported_buttons, GENERIC_BUTTONS)
        self.assertEqual(info.capability_inventory.hscroll_cids, (0x005B, 0x005D))
        self.assertNotIn("mode_shift", info.supported_buttons)
        self.assertEqual(
            info.capability_inventory.to_dict()["known_unsupported_controls"],
            [{"cid": "0x00ED", "name": "precision_mode"}],
        )

    def test_ergo_m575_issue_95_reports_inventory_without_support_claim(self):
        info = build_connected_device_info(
            product_id=0xC52B,
            product_name="ERGO M575 Trackball",
            reprog_controls=[
                self._control(0x0052, flags=0x0571),
                self._control(0x0056, flags=0x0571),
                self._control(0x0053, flags=0x0571),
                self._control(0x00D7, flags=0x03A0),
            ],
            discovered_features=(
                "REPROG_V4 (0x1B04)",
                "ADJUSTABLE_DPI (0x2201)",
                "BATTERY (0x1004)",
            ),
        )

        self.assertEqual(info.key, "ergo_m575_trackball")
        self.assertEqual(info.ui_layout, "generic_mouse")
        self.assertEqual(info.supported_buttons, GENERIC_BUTTONS)
        self.assertNotIn("gesture", info.supported_buttons)
        self.assertNotIn("hscroll_left", info.supported_buttons)
        self.assertTrue(info.capability_inventory.gesture_click)
        self.assertTrue(info.capability_inventory.adjustable_dpi)

    def test_mx_anywhere_3s_solaar_controls_keep_mode_shift_and_catalog_hscroll(self):
        info = build_connected_device_info(
            product_id=0xB037,
            reprog_controls=[
                self._control(0x0052, flags=0x0130),
                self._control(0x0053, flags=0x0130),
                self._control(0x0056, flags=0x0130),
                self._control(0x00C4, flags=0x0130),
                self._control(0x00D7, flags=0x03A0),
            ],
            gesture_cids=(0x00D7,),
            active_gesture_cid=0x00D7,
            gesture_rawxy_enabled=True,
        )

        self.assertIn("mode_shift", info.supported_buttons)
        self.assertIn("gesture_up", info.supported_buttons)
        self.assertIn("hscroll_left", info.supported_buttons)
        self.assertIn("hscroll_right", info.supported_buttons)

    def test_mx_master_4_haptic_control_is_supported(self):
        info = build_connected_device_info(
            product_id=0xB042,
            reprog_controls=[
                self._control(0x0052, flags=0x0130),
                self._control(0x0053, flags=0x0130),
                self._control(0x0056, flags=0x0130),
                self._control(0x00C3, flags=0x0130),
                self._control(0x00C4, flags=0x0130),
                self._control(0x01A0, flags=0x0130),
                self._control(0x00D7, flags=0x03A0),
            ],
            gesture_cids=(0x00C3, 0x00D7),
            active_gesture_cid=0x00C3,
            gesture_rawxy_enabled=True,
        )

        self.assertIn("mode_shift", info.supported_buttons)
        self.assertIn("gesture_down", info.supported_buttons)
        self.assertIn("haptic", info.supported_buttons)
        self.assertEqual(
            info.capability_inventory.to_dict()["known_unsupported_controls"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
