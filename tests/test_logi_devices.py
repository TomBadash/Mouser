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

    def test_resolve_m650_by_bluetooth_pid(self):
        device = resolve_device(product_id=0xB02A)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "m650")
        self.assertEqual(device.ui_layout, "m650")

    def test_resolve_m650_by_common_name_variants(self):
        for product_name in (
            "Signature M650",
            "Logi M650",
            "Logitech Signature M650",
        ):
            with self.subTest(product_name=product_name):
                device = resolve_device(product_name=product_name)

                self.assertIsNotNone(device)
                self.assertEqual(device.key, "m650")
                self.assertEqual(device.ui_layout, "m650")

    def test_build_m650_connected_device_info_uses_catalog_layout_and_buttons(self):
        info = build_connected_device_info(
            product_id=0xB02A,
            product_name="Signature M650",
            reprog_controls=[
                {"cid": 0x0052},
                {"cid": 0x0053},
                {"cid": 0x0056},
                {"cid": 0x00D7},
            ],
            gesture_cids=(0x00D7,),
        )

        self.assertEqual(info.key, "m650")
        self.assertEqual(info.display_name, "M650 Signature")
        self.assertEqual(info.ui_layout, "m650")
        self.assertEqual(info.image_asset, "icons/mouse-simple.svg")
        self.assertEqual(info.supported_buttons, ("middle", "xbutton1", "xbutton2"))
        self.assertEqual(info.dpi_min, 200)
        self.assertEqual(info.dpi_max, 4000)

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

    def test_resolve_g502_hero_by_product_id(self):
        device = resolve_device(product_id=0xC08B)

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "g502_hero")
        self.assertEqual(device.ui_layout, "g502")

    def test_resolve_g502_lightspeed_by_receiver_wpid(self):
        for product_id in (0xC08D, 0x407F):
            with self.subTest(product_id=f"0x{product_id:04X}"):
                device = resolve_device(product_id=product_id)

                self.assertIsNotNone(device)
                self.assertEqual(device.key, "g502_lightspeed")

    def test_resolve_g502_x_plus_by_alias(self):
        device = resolve_device(product_name="G502 X PLUS")

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "g502_x")

    def test_resolve_g502_x_plus_by_product_id(self):
        for product_id in (0xC095, 0x4099):
            with self.subTest(product_id=f"0x{product_id:04X}"):
                device = resolve_device(product_id=product_id)

                self.assertIsNotNone(device)
                self.assertEqual(device.key, "g502_x")

    def test_resolve_g502_proteus_by_reported_name(self):
        device = resolve_device(product_name="Tunable FPS Gaming Mouse G502")

        self.assertIsNotNone(device)
        self.assertEqual(device.key, "g502")

    def test_g502_buttons_are_os_level_only(self):
        buttons = get_buttons_for_layout("g502")

        self.assertIn("middle", buttons)
        self.assertIn("xbutton1", buttons)
        self.assertIn("xbutton2", buttons)
        self.assertIn("hscroll_left", buttons)
        self.assertIn("hscroll_right", buttons)
        # No REPROG_CONTROLS_V4 on G-series onboard-profile mice, so no
        # HID++-gated buttons may be offered.
        self.assertNotIn("gesture", buttons)
        self.assertNotIn("mode_shift", buttons)
        self.assertNotIn("dpi_switch", buttons)

    def test_g502_layout_is_placeholder_not_generic(self):
        layout = get_device_layout("g502")

        self.assertEqual(layout["key"], "g502")
        self.assertFalse(layout["interactive"])
        self.assertEqual(layout["hotspots"], [])

    def test_build_g502_hero_connected_info(self):
        info = build_connected_device_info(
            product_id=0xC08B,
            product_name="G502 HERO Gaming Mouse",
            transport="usb",
        )

        self.assertEqual(info.key, "g502_hero")
        self.assertEqual(info.display_name, "G502 HERO")
        self.assertEqual(info.ui_layout, "g502")
        self.assertEqual(clamp_dpi(50000, info), 25600)
        self.assertEqual(clamp_dpi(50, info), 100)

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

    def test_mx_anywhere_2s_spec_supports_event_tap_gestures(self):
        device = resolve_device(product_id=0xB01A)

        self.assertIsNotNone(device)
        self.assertTrue(device.supports_event_tap_gestures)
        for owner in ("back", "forward", "middle"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, device.supported_buttons)

    def test_other_known_devices_do_not_support_event_tap_gestures(self):
        # supports_event_tap_gestures is opt-in; only the 2S has it in issue #005.
        for device in KNOWN_LOGI_DEVICES:
            if device.key == "mx_anywhere_2s":
                continue
            with self.subTest(device=device.key):
                self.assertFalse(device.supports_event_tap_gestures)

    def test_mx_anywhere_2s_spec_supports_tilt_gestures(self):
        device = resolve_device(product_id=0xB01A)

        self.assertIsNotNone(device)
        self.assertTrue(device.supports_tilt_gestures)
        for owner in ("tilt_left", "tilt_right"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, device.supported_buttons)

    def test_only_2s_supports_tilt_gestures_and_no_tilt_keys_elsewhere(self):
        # Opt-in like the event-tap flag; MX Master entries untouched.
        for device in KNOWN_LOGI_DEVICES:
            if device.key == "mx_anywhere_2s":
                continue
            with self.subTest(device=device.key):
                self.assertFalse(device.supports_tilt_gestures)
                self.assertNotIn("gesture_tilt_left_left", device.supported_buttons)


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
            [{"cid": "0x01A0", "name": "haptic"}],
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

    # -- Per-button event-tap gestures (issue #002) --------------------------

    _EVENT_TAP_STATIC_BUTTONS = (
        "middle",
        "xbutton1",
        "xbutton2",
        "gesture",
        "gesture_left",
        "gesture_right",
        "gesture_up",
        "gesture_down",
        "gesture_back_left",
        "gesture_back_right",
        "gesture_forward_up",
        "gesture_forward_down",
        "gesture_middle_left",
        "gesture_middle_right",
    )

    def test_event_tap_only_device_keeps_per_button_gesture_keys_without_rawxy(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            self._EVENT_TAP_STATIC_BUTTONS,
            [self._control(0x0052, flags=0x0130), self._control(0x0053, flags=0x0130)],
            supports_event_tap_gestures=True,
        )

        self.assertIn("gesture_back_left", buttons)
        self.assertIn("gesture_forward_up", buttons)
        self.assertIn("gesture_middle_right", buttons)
        # No divertable HID gesture control present, so the legacy HID path
        # stays stripped -- the event-tap flag doesn't resurrect it.
        self.assertNotIn("gesture", buttons)
        self.assertNotIn("gesture_left", buttons)

    def test_device_with_neither_flag_still_strips_all_gesture_keys(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            self._EVENT_TAP_STATIC_BUTTONS,
            [self._control(0x0052, flags=0x0130), self._control(0x0053, flags=0x0130)],
        )

        self.assertNotIn("gesture_back_left", buttons)
        self.assertNotIn("gesture_forward_up", buttons)
        self.assertNotIn("gesture_middle_right", buttons)
        self.assertNotIn("gesture", buttons)
        self.assertNotIn("gesture_left", buttons)

    def test_real_hid_gesture_control_unaffected_by_event_tap_flag(self):
        # MX Master regression guard: a device with a real divertable RawXY
        # gesture control keeps working exactly as before, and the (absent)
        # event-tap flag does not add per-button keys it never declared.
        buttons = derive_supported_buttons_from_reprog_controls(
            self._EVENT_TAP_STATIC_BUTTONS,
            [self._control(0x00D7, flags=0x03A0)],
            gesture_cids=(0x00D7,),
            active_gesture_cid=0x00D7,
            gesture_rawxy_enabled=True,
            supports_event_tap_gestures=False,
        )

        self.assertIn("gesture", buttons)
        self.assertIn("gesture_left", buttons)
        self.assertIn("gesture_right", buttons)
        self.assertNotIn("gesture_back_left", buttons)
        self.assertNotIn("gesture_forward_up", buttons)

    def test_mx_anywhere_2s_exposes_per_button_gesture_keys_via_capability_model(self):
        info = build_connected_device_info(
            product_id=0xB01A,
            reprog_controls=[
                self._control(0x0052, flags=0x0130),
                self._control(0x0053, flags=0x0130),
                self._control(0x0056, flags=0x0130),
            ],
        )

        self.assertTrue(info.capability_inventory.supports_event_tap_gestures)
        for owner in ("back", "forward", "middle"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, info.supported_buttons)
        # No real HID gesture control on the 2S -- the legacy global path
        # stays inert (stripped), same as before this feature existed.
        self.assertNotIn("gesture", info.supported_buttons)
        self.assertNotIn("gesture_left", info.supported_buttons)

    def test_mx_master_4_haptic_control_does_not_create_supported_button(self):
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
        self.assertNotIn("action_ring", info.supported_buttons)
        self.assertNotIn("haptic", info.supported_buttons)
        self.assertEqual(
            info.capability_inventory.to_dict()["known_unsupported_controls"],
            [{"cid": "0x01A0", "name": "haptic"}],
        )

    # -- Tilt slide gestures (supports_tilt_gestures capability) --------------

    _TILT_STATIC_BUTTONS = (
        "middle",
        "xbutton1",
        "xbutton2",
        "hscroll_left",
        "hscroll_right",
        "gesture_tilt_left_left",
        "gesture_tilt_left_up",
        "gesture_tilt_right_right",
        "gesture_tilt_right_down",
    )

    def test_tilt_flag_keeps_tilt_keys(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            self._TILT_STATIC_BUTTONS,
            [self._control(0x0052, flags=0x0130), self._control(0x0053, flags=0x0130)],
            supports_tilt_gestures=True,
        )
        self.assertIn("gesture_tilt_left_left", buttons)
        self.assertIn("gesture_tilt_right_down", buttons)
        self.assertIn("hscroll_left", buttons)

    def test_no_tilt_flag_strips_tilt_keys(self):
        buttons = derive_supported_buttons_from_reprog_controls(
            self._TILT_STATIC_BUTTONS,
            [self._control(0x0052, flags=0x0130), self._control(0x0053, flags=0x0130)],
        )
        self.assertNotIn("gesture_tilt_left_left", buttons)
        self.assertNotIn("gesture_tilt_right_down", buttons)
        # OS-level hscroll (the tilt tap target) is unaffected.
        self.assertIn("hscroll_left", buttons)

    def test_mx_anywhere_2s_exposes_tilt_keys_via_capability_model(self):
        info = build_connected_device_info(
            product_id=0xB01A,
            reprog_controls=[
                self._control(0x0052, flags=0x0130),
                self._control(0x0053, flags=0x0130),
                self._control(0x0056, flags=0x0130),
            ],
        )

        self.assertTrue(info.capability_inventory.supports_tilt_gestures)
        self.assertTrue(info.capability_inventory.to_dict()["supports_tilt_gestures"])
        for owner in ("tilt_left", "tilt_right"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, info.supported_buttons)


if __name__ == "__main__":
    unittest.main()
