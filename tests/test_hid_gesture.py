import contextlib
import importlib
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import hid_gesture


class HidModuleImportTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(hid_gesture)

    def test_linux_prefers_hidraw_module_when_available(self):
        fake_hidraw = SimpleNamespace(device=object, enumerate=lambda *_args: [])
        fake_hid = SimpleNamespace(device=object, enumerate=lambda *_args: [])

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"hidraw": fake_hidraw, "hid": fake_hid}),
        ):
            module = importlib.reload(hid_gesture)

        self.assertTrue(module.HIDAPI_OK)
        self.assertIs(module._hid, fake_hidraw)
        self.assertEqual(module._HID_MODULE_NAME, "hidraw")

    def test_linux_falls_back_to_hid_when_hidraw_module_is_absent(self):
        fake_hid = SimpleNamespace(device=object, enumerate=lambda *_args: [])

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"hidraw": None, "hid": fake_hid}),
        ):
            module = importlib.reload(hid_gesture)

        self.assertTrue(module.HIDAPI_OK)
        self.assertIs(module._hid, fake_hid)
        self.assertEqual(module._HID_MODULE_NAME, "hid")


class HidLinuxDiagnosticsTests(unittest.TestCase):
    def test_linux_logitech_hidraw_nodes_reads_sysfs_uevent(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = os.path.join(tmp, "hidraw3", "device")
            os.makedirs(node_dir)
            with open(os.path.join(node_dir, "uevent"), "w", encoding="utf-8") as fh:
                fh.write("HID_ID=0005:0000046D:0000B034\n")
                fh.write("HID_NAME=MX Master 3S\n")

            with patch.object(sys, "platform", "linux"):
                nodes = hid_gesture._linux_logitech_hidraw_nodes(base=tmp)

        self.assertEqual(nodes, ["hidraw3 PID=0xB034 product=MX Master 3S"])

    def test_summarize_hid_infos_includes_candidate_metadata(self):
        summary = hid_gesture._summarize_hid_infos([
            {
                "product_id": 0xB034,
                "usage_page": 0x0000,
                "usage": 0x0001,
                "transport": "Bluetooth Low Energy",
                "product_string": "MX Master 3S",
            }
        ])

        self.assertIn("PID=0xB034", summary)
        self.assertIn("UP=0x0000", summary)
        self.assertIn("product=MX Master 3S", summary)

    def test_format_linux_device_access_includes_path_permissions_and_access(self):
        with tempfile.NamedTemporaryFile() as fh:
            summary = hid_gesture._format_linux_device_access(fh.name.encode())

        self.assertIn("path=", summary)
        self.assertIn("mode=", summary)
        self.assertIn("owner=", summary)
        self.assertIn("group=", summary)
        self.assertIn("access=read:", summary)


class HidBackendPreferenceTests(unittest.TestCase):
    def test_default_backend_uses_auto_on_macos(self):
        self.assertEqual(hid_gesture._default_backend_preference("darwin"), "auto")

    def test_default_backend_uses_auto_elsewhere(self):
        self.assertEqual(hid_gesture._default_backend_preference("win32"), "auto")
        self.assertEqual(hid_gesture._default_backend_preference("linux"), "auto")


class GestureCandidateSelectionTests(unittest.TestCase):
    def test_choose_gesture_candidates_prefers_known_device_cids(self):
        listener = hid_gesture.HidGestureListener()
        device_spec = hid_gesture.resolve_device(product_id=0xB023)

        candidates = listener._choose_gesture_candidates(
            [
                {"cid": 0x00D7, "flags": 0x03B0, "mapping_flags": 0x0051},
                {"cid": 0x00C3, "flags": 0x0130, "mapping_flags": 0x0011},
            ],
            device_spec=device_spec,
        )

        self.assertEqual(candidates[:2], [0x00C3, 0x00D7])

    def test_choose_gesture_candidates_uses_capability_heuristic(self):
        listener = hid_gesture.HidGestureListener()

        candidates = listener._choose_gesture_candidates(
            [
                {"cid": 0x00A0, "flags": 0x0030, "mapping_flags": 0x0001},
                {"cid": 0x00F1, "flags": 0x01B0, "mapping_flags": 0x0011},
            ],
        )

        self.assertEqual(candidates[0], 0x00F1)

    def test_choose_gesture_candidates_falls_back_to_defaults(self):
        listener = hid_gesture.HidGestureListener()

        self.assertEqual(
            listener._choose_gesture_candidates([]),
            list(hid_gesture.DEFAULT_GESTURE_CIDS),
        )


class DeviceInfoDumpTests(unittest.TestCase):
    def test_dump_device_info_includes_runtime_capability_inventory(self):
        listener = hid_gesture.HidGestureListener()
        controls = [
            {
                "index": 0,
                "cid": 0x00D0,
                "task": 0x00AD,
                "flags": 0x0171,
                "mapped_to": 0x00D0,
                "mapping_flags": 0x0000,
            },
            {
                "index": 1,
                "cid": 0x005B,
                "task": 0x003F,
                "flags": 0x0171,
                "mapped_to": 0x005B,
                "mapping_flags": 0x0000,
            },
        ]
        listener._feat_idx = 0x0B
        listener._battery_idx = 0x08
        listener._battery_feature_id = hid_gesture.FEAT_BATTERY_STATUS
        listener._gesture_candidates = [0x00D0]
        listener._connected_device_info = hid_gesture.build_connected_device_info(
            product_id=0xB015,
            product_name="M720_Triathlon",
            reprog_controls=controls,
            gesture_cids=(0x00D0,),
            active_gesture_cid=0x00D0,
            gesture_rawxy_enabled=True,
            discovered_features=listener._discovered_feature_ids(),
        )
        listener._last_controls = controls

        dump = listener.dump_device_info()

        self.assertEqual(dump["device_key"], "m720_triathlon")
        self.assertIn("capability_inventory", dump)
        self.assertEqual(
            dump["capability_inventory"]["active_gesture_cid"],
            "0x00D0",
        )
        self.assertTrue(dump["capability_inventory"]["gesture_directions"])
        self.assertEqual(dump["capability_inventory"]["hscroll_cids"], ["0x005B"])
        self.assertTrue(dump["capability_inventory"]["battery"])


class _FakeHidDevice:
    def __init__(self):
        self.open_path = Mock()
        self.set_nonblocking = Mock()
        self.close = Mock()


class HidEnumerationFallbackTests(unittest.TestCase):
    @staticmethod
    def _printed_messages(print_mock):
        return [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]

    def test_try_connect_accepts_known_device_without_usage_metadata(self):
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB034,
            "usage_page": 0x0000,
            "usage": 0x0000,
            "transport": "Bluetooth Low Energy",
            "product_string": "MX Master 3S",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x10
            return None

        with (
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(
                    enumerate=lambda vid, pid: [info],
                    device=lambda: fake_dev,
                ),
                create=True,
            ),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch("builtins.print") as print_mock,
        ):
            self.assertTrue(listener._try_connect())

        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any(
                "Accepting known Logitech device without vendor usage metadata"
                in message
                for message in messages
            )
        )
        self.assertEqual(listener.connected_device.display_name, "MX Master 3S")

    def test_vendor_hid_infos_logs_when_logitech_interfaces_are_filtered_out(self):
        info = {
            "product_id": 0x1234,
            "usage_page": 0x0000,
            "usage": 0x0000,
            "transport": "Bluetooth Low Energy",
            "product_string": "Unknown Logitech",
            "path": b"/dev/hidraw-test",
        }

        with (
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(enumerate=lambda vid, pid: [info]),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            infos = hid_gesture.HidGestureListener._vendor_hid_infos()

        self.assertEqual(infos, [])
        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any(
                "hidapi found Logitech interfaces, but none matched vendor "
                "usage metadata or known-device fallback"
                in message
                for message in messages
            )
        )


class HidDiscoveryDiagnosticsTests(unittest.TestCase):
    def _make_listener(self):
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB023,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "Bluetooth Low Energy",
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3",
            "path": b"/dev/hidraw-test",
        }
        return listener, info

    @staticmethod
    def _printed_messages(print_mock):
        return [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]

    @staticmethod
    def _is_missing_reprog_diag(message):
        return (
            "Opened candidate but REPROG_V4 was not found "
            "on tested devIdx values"
        ) in message

    def test_try_connect_logs_missing_reprog_when_open_succeeds_for_all_dev_indices(self):
        listener, info = self._make_listener()
        fake_dev = _FakeHidDevice()

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            self.assertFalse(listener._try_connect())

        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any("Opened PID=0xB023 via hidapi" in message for message in messages)
        )
        self.assertTrue(
            any(self._is_missing_reprog_diag(message) for message in messages)
        )
        fake_dev.close.assert_called_once_with()

    def test_try_connect_accepts_g502_x_without_reprog_v4(self):
        """G502 family has no REPROG_V4; OS-level connect must still succeed."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC098,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "-",
            "source": "hidapi-enumerate",
            "product_string": "G502 X LIGHTSPEED",
            "path": b"/dev/hidraw-g502x",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, timeout_ms=None):
            # No REPROG_V4. Optional DPI still advertised on G502.
            if feature_id == hid_gesture.FEAT_ADJ_DPI:
                return 0x0A
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_divert") as divert_mock,
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            self.assertTrue(listener._try_connect())

        divert_mock.assert_not_called()
        fake_dev.close.assert_not_called()
        self.assertIsNotNone(listener.connected_device)
        self.assertEqual(listener.connected_device.key, "g502_x")
        self.assertEqual(listener.connected_device.display_name, "G502 X")
        self.assertIn("middle", listener.connected_device.supported_buttons)
        self.assertEqual(listener._dpi_idx, 0x0A)
        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any(
                "OS-level connect without REPROG_V4" in message
                for message in messages
            )
        )

    def test_try_connect_g502_adds_spy_buttons_when_present(self):
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC098,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "-",
            "source": "hidapi-enumerate",
            "product_string": "G502 X LIGHTSPEED",
            "path": b"/dev/hidraw-g502x",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_ADJ_DPI:
                return 0x0A
            if feature_id == hid_gesture.FEAT_MOUSE_BUTTON_SPY:
                return 0x0C
            if feature_id == hid_gesture.FEAT_ONBOARD_PROFILES:
                return 0x09
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            if feat == 0x0C and func == 0:
                return (0x11, 0x0C, 0x0, 0xA, [0x0B])
            if feat == 0x0C and func == 3:
                return (0x11, 0x0C, 0x3, 0xA, list(range(1, 17)))
            if feat == 0x0C and func in (1, 2, 4):
                return (0x11, 0x0C, func, 0xA, [0x00])
            if feat == 0x09 and func == 2:
                return (0x11, 0x09, 0x2, 0xA, [hid_gesture.ONBOARD_MODE_ONBOARD])
            if feat == 0x09 and func == 0:
                return (
                    0x11,
                    0x09,
                    0x0,
                    0xA,
                    [0x01, 0x02, 0x00, 0x05, 0x00, 0x0B, 0x05, 0x00, 0x10, 0x00],
                )
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch.object(listener, "_divert"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        buttons = listener.connected_device.supported_buttons
        self.assertIn("sniper", buttons)
        self.assertIn("dpi_switch", buttons)
        self.assertIn("dpi_up", buttons)
        self.assertIn("dpi_down", buttons)
        self.assertIn("middle", buttons)
        dump = listener.dump_device_info()
        self.assertTrue(dump["mouse_button_spy"]["supported"])
        self.assertEqual(dump["mouse_button_spy"]["button_count"], 11)
        self.assertFalse(dump["onboard_profiles"]["writes_enabled"])

    def test_apply_pending_dpi_rediscovers_feature_index(self):
        """G502 OS-level connect may miss DPI; set_dpi must rediscover it."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._dpi_idx = None
        listener._onboard_profiles_idx = None
        listener._connected_device_info = hid_gesture.build_connected_device_info(
            product_id=0xC098,
            product_name="G502 X LIGHTSPEED",
        )
        listener._pending_dpi = 1600
        listener._feat_idx = None

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_ADJ_DPI:
                return 0x07
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            if feat == 0x07 and func == 3:
                return (0x11, 0x07, 0x3, 0xA, [0x00, 0x06, 0x40])
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            listener._apply_pending_dpi()

        self.assertEqual(listener._dpi_idx, 0x07)
        self.assertTrue(listener._dpi_result)

    def test_apply_pending_dpi_is_set_sensor_dpi_only(self):
        """DPI write must not touch onboard Host mode (resets LEDs / link)."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._dpi_idx = 0x07
        listener._onboard_profiles_idx = 0x09
        listener._feat_idx = None
        listener._connected_device_info = hid_gesture.build_connected_device_info(
            product_id=0xC098,
            product_name="G502 X LIGHTSPEED",
        )
        listener._pending_dpi = 2400
        calls = []

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params)))
            if feat == 0x07 and func == 3:
                return (0x11, 0x07, 0x3, 0xA, [0x00, 0x09, 0x60])
            return None

        with (
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            listener._apply_pending_dpi()

        self.assertTrue(listener._dpi_result)
        self.assertEqual(calls, [(0x07, 3, [0x00, 0x09, 0x60])])

    def test_spy_notification_emits_sniper_and_dpi_switch(self):
        """G502 X Lightspeed: sniper=4, dpi_switch=8, dpi_down=9, dpi_up=10."""
        events = []
        listener = hid_gesture.HidGestureListener(
            on_spy_button=lambda key, down: events.append((key, down))
        )
        listener._mouse_button_spy_idx = 0x0C
        listener._feat_idx = None

        # Bits 4+8+9+10: 0x0010|0x0100|0x0200|0x0400 = 0x0710
        listener._handle_spy_notification([0x07, 0x10])
        listener._handle_spy_notification([0x00, 0x00])

        self.assertEqual(
            events,
            [
                ("sniper", True),
                ("dpi_switch", True),
                ("dpi_down", True),
                ("dpi_up", True),
                ("sniper", False),
                ("dpi_switch", False),
                ("dpi_down", False),
                ("dpi_up", False),
            ],
        )

    def test_reapply_spy_after_receiver_link(self):
        """0x41 link-up rewrites patched remapping + Start (nibble)."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._mouse_button_spy_idx = 0x0C
        listener._spy_started = True
        listener._spy_remap_original = [i + 1 for i in range(16)]
        listener._spy_remap_patched = list(listener._spy_remap_original)
        listener._spy_remap_patched[4] = 0
        listener._spy_remap_patched[8] = 0
        calls = []

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params)))
            return (0x11, feat, func, 0xA, [0x00])

        with (
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            # Receiver link notification: feat=0x41, params[0] bit6 clear = up.
            raw = bytes([0x10, 0x01, 0x41, 0x00, 0x00] + [0x00] * 2)
            listener._on_report(raw)
            self.assertTrue(listener._pending_spy_reapply)
            listener._apply_pending_spy_reapply()

        set_calls = [c for c in calls if c[0] == 0x0C and c[1] == 4]
        start_calls = [c for c in calls if c[0] == 0x0C and c[1] == 1]
        self.assertEqual(len(set_calls), 1)
        self.assertEqual(set_calls[0][2][4], 0)
        self.assertEqual(set_calls[0][2][8], 0)
        self.assertEqual(set_calls[0][2][0], 1)
        self.assertEqual(len(start_calls), 1)
        # Must not replace original with the already-patched device table.
        self.assertEqual(listener._spy_remap_original[4], 5)
        self.assertFalse(listener._pending_spy_reapply)

    def test_on_report_routes_spy_without_reprog(self):
        events = []
        listener = hid_gesture.HidGestureListener(
            on_spy_button=lambda key, down: events.append((key, down))
        )
        listener._mouse_button_spy_idx = 0x0C
        listener._feat_idx = None
        listener._battery_idx = None

        # Long report: params 0x01 0x10 = dpi bit8 + sniper bit4
        # (measured on G502 X Lightspeed guided spy).
        raw = bytes([0x11, 0xFF, 0x0C, 0x00, 0x01, 0x10] + [0x00] * 14)
        with patch("builtins.print"):
            listener._on_report(raw)

        self.assertIn(("sniper", True), events)
        self.assertIn(("dpi_switch", True), events)

    def test_probe_mouse_button_spy_read_only(self):
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_MOUSE_BUTTON_SPY:
                return 0x0C
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            if feat == 0x0C and func == 0:
                return (0x11, 0x0C, 0x0, 0xA, [0x0B])
            if feat == 0x0C and func == 3:
                return (0x11, 0x0C, 0x3, 0xA, list(range(1, 17)))
            if feat == 0x0C and func in (1, 2, 4):
                return (0x11, 0x0C, func, 0xA, [0x00])
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            self.assertEqual(listener._probe_mouse_button_spy(), 0x0C)

        self.assertEqual(listener._spy_button_count, 11)
        self.assertTrue(listener.mouse_button_spy_supported)
        self.assertTrue(listener._spy_started)

    def test_probe_onboard_profiles_readonly_no_writes(self):
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        calls = []

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_ONBOARD_PROFILES:
                return 0x09
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params)))
            if feat == 0x09 and func == 2:
                return (0x11, 0x09, 0x2, 0xA, [hid_gesture.ONBOARD_MODE_ONBOARD])
            if feat == 0x09 and func == 0:
                return (
                    0x11,
                    0x09,
                    0x0,
                    0xA,
                    [0x01, 0x02, 0x00, 0x05, 0x00, 0x0B, 0x05, 0x00, 0x10, 0x00],
                )
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            self.assertEqual(listener._probe_onboard_profiles_readonly(), 0x09)

        self.assertEqual(listener._onboard_mode, hid_gesture.ONBOARD_MODE_ONBOARD)
        self.assertEqual(listener._onboard_desc["buttons"], 11)
        # Only read fns 0 and 2 — never sector write 0x60/0x70/0x80.
        self.assertEqual(sorted(func for _f, func, _p in calls), [0, 2])

    def test_win_hidpp_group_key_strips_collection(self):
        """Windows splits short/long HID++ into &col01 / &col02 paths."""
        path = (
            r"\\?\hid#vid_046d&pid_c547&mi_02&col01#"
            r"{4d1e55b2-f16f-11cf-88cb-001111000030}"
        )
        key = hid_gesture._win_hidpp_group_key(path)
        self.assertTrue(key.endswith("&mi_02"))
        self.assertNotIn("&col", key)

    def test_win_hidpp_siblings_same_receiver(self):
        short = {
            "product_id": 0xC547,
            "usage_page": 0xFF00,
            "usage": 1,
            "path": b"\\\\?\\hid#vid_046d&pid_c547&mi_02&col01#a",
        }
        long = {
            "product_id": 0xC547,
            "usage_page": 0xFF00,
            "usage": 2,
            "path": b"\\\\?\\hid#vid_046d&pid_c547&mi_02&col02#b",
        }
        other = {
            "product_id": 0xC547,
            "usage_page": 0xFF00,
            "usage": 1,
            "path": b"\\\\?\\hid#vid_046d&pid_c547&mi_00&col01#c",
        }
        siblings = hid_gesture._win_hidpp_siblings(short, [short, long, other])
        usages = sorted(int(i["usage"]) for i in siblings)
        self.assertEqual(usages, [1, 2])

    def test_candidate_priority_prefers_long_collection(self):
        short = {
            "product_id": 0xC547,
            "usage_page": 0xFF00,
            "usage": 1,
            "product_string": "USB Receiver",
        }
        long = {
            "product_id": 0xC547,
            "usage_page": 0xFF00,
            "usage": 2,
            "product_string": "USB Receiver",
        }
        self.assertLess(
            hid_gesture._candidate_probe_priority(long),
            hid_gesture._candidate_probe_priority(short),
        )

    def test_win_hidpp_bundle_reads_secondary_collection(self):
        """Spy bitmaps arrive on the long collection; short-only open misses them."""

        class _QueuedDev:
            def __init__(self, reports):
                self._reports = list(reports)
                self.closed = False

            def write(self, data):
                return len(data)

            def read(self, size, timeout_ms=0):
                if self._reports:
                    return self._reports.pop(0)
                time.sleep(min(0.02, max(timeout_ms, 1) / 1000.0))
                return None

            def set_nonblocking(self, enabled):
                return None

            def close(self):
                self.closed = True

        # Long-collection Input: sniper bit 4 (0x0010)
        long_report = [0x11, 0x01, 0x0C, 0x00, 0x00, 0x10] + [0] * 14
        short_dev = _QueuedDev([])
        long_dev = _QueuedDev([long_report])
        bundle = hid_gesture._WinHidppBundle(
            write_dev=long_dev,
            read_devs=(short_dev, long_dev),
        )
        try:
            raw = bundle.read(64, timeout_ms=500)
        finally:
            bundle.close()

        self.assertIsNotNone(raw)
        self.assertEqual(list(raw)[:6], long_report[:6])

    def test_probe_mouse_button_spy_enables_notifications(self):
        """Nibble protocol: fn3 get table, fn4 zero slots, fn1 Start."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        calls = []
        original = [i + 1 for i in range(16)]

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_MOUSE_BUTTON_SPY:
                return 0x0C
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params)))
            if feat == 0x0C and func == 0:
                return (0x11, 0x0C, 0x0, 0xA, [0x0B])
            if feat == 0x0C and func == 3:
                return (0x11, 0x0C, 0x3, 0xA, list(original))
            if feat == 0x0C and func in (1, 2, 4):
                return (0x11, 0x0C, func, 0xA, [0x00])
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            self.assertEqual(listener._probe_mouse_button_spy(), 0x0C)

        self.assertTrue(listener._spy_started)
        self.assertEqual(listener._spy_remap_original, original)
        self.assertEqual(listener._spy_remap_patched[4], 0)
        self.assertEqual(listener._spy_remap_patched[8], 0)
        self.assertEqual(listener._spy_remap_patched[9], 0)
        self.assertEqual(listener._spy_remap_patched[10], 0)
        set_calls = [c for c in calls if c[0] == 0x0C and c[1] == 4]
        self.assertEqual(len(set_calls), 1)
        patched = set_calls[0][2]
        self.assertEqual(patched[4], 0)  # sniper (G502 X bit 4)
        self.assertEqual(patched[8], 0)  # dpi_switch
        self.assertEqual(patched[9], 0)  # dpi_down
        self.assertEqual(patched[10], 0)  # dpi_up
        self.assertEqual(patched[0], 1)  # left untouched
        self.assertEqual(patched[5], 6)  # forward slot not zeroed
        self.assertTrue(any(c[1] == 1 and c[2] == [] for c in calls))

    def test_report_rate_probe_lists_supported_hz(self):
        """0x8060 fn0 bitfield → Hz list; fn1 current interval."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPORT_RATE:
                return 0x0D
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            if feat == 0x0D and func == 0:
                # bits 0,1,3,7 → 1/2/4/8 ms → 1000/500/250/125 Hz
                return (0x11, 0x0D, 0x0, 0xA, [0x8B])
            if feat == 0x0D and func == 1:
                return (0x11, 0x0D, 0x1, 0xA, [0x01])  # 1 ms = 1000 Hz
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            self.assertEqual(listener._probe_report_rate(), 0x0D)

        self.assertTrue(listener.report_rate_supported)
        self.assertEqual(listener._report_rate_hz_list, [1000, 500, 250, 125])
        self.assertEqual(listener._report_rate_hz, 1000)

    def test_report_rate_set_requires_host_opt_in(self):
        """Refuse 0x8060 writes unless Host opt-in is already enabled."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._report_rate_idx = 0x0D
        listener._report_rate_hz_list = [1000, 500, 250, 125]
        listener.set_prefer_host_mode(False)
        calls = []

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params)))
            return (0x11, feat, func, 0xA, [0x00])

        with (
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            listener._pending_report_rate = 500
            listener._apply_pending_report_rate()

        self.assertFalse(listener._report_rate_result)
        self.assertEqual(calls, [])

        listener.set_prefer_host_mode(True)
        listener._host_mode_applied = True
        with (
            patch.object(listener, "_request", side_effect=fake_request),
            patch.object(listener, "_apply_host_mode_once", return_value=True),
            patch("builtins.print"),
        ):
            listener._pending_report_rate = 500
            listener._apply_pending_report_rate()

        self.assertTrue(listener._report_rate_result)
        self.assertEqual(calls, [(0x0D, 2, [0x02])])  # 2 ms = 500 Hz
        self.assertEqual(listener._report_rate_hz, 500)

    def test_onboard_active_profile_dpi_readonly(self):
        """Parse active profile DPI stages from memoryRead (Solaar layout)."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._onboard_profiles_idx = 0x09
        listener._onboard_desc = {
            "memory": 1,
            "profile": 5,
            "count": 5,
            "buttons": 11,
            "sectors": 16,
            "size": 255,
        }

        # Sector bytes: rate=1ms, default=1, shift=0,
        # DPI 800,1200,1600,2400,3200 little-endian.
        sector = bytearray(16)
        sector[0] = 0x01
        sector[1] = 0x01
        sector[2] = 0x00
        for i, dpi in enumerate((800, 1200, 1600, 2400, 3200)):
            sector[3 + i * 2] = dpi & 0xFF
            sector[4 + i * 2] = (dpi >> 8) & 0xFF

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            if feat == 0x09 and func == 4:
                # getCurrentProfile → sector 0x0001
                return (0x11, 0x09, 0x4, 0xA, [0x00, 0x01])
            if feat == 0x09 and func == 5:
                return (0x11, 0x09, 0x5, 0xA, list(sector))
            return None

        with (
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            info = listener._read_active_profile_dpi(timeout_ms=400)

        self.assertEqual(
            info,
            {
                "sector": 1,
                "report_rate_ms": 1,
                "default_index": 1,
                "shift_index": 0,
                "resolutions": [800, 1200, 1600, 2400, 3200],
            },
        )
        self.assertEqual(listener._onboard_active_dpi, info)

    def test_host_mode_switch_once_when_prefer_enabled(self):
        """Opt-in Host mode uses 0x8100 once; never via setSensorDpi."""
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener._dev_idx = 0x01
        listener._feat_idx = None
        listener._dpi_idx = 0x07
        listener.set_prefer_host_mode(True)
        calls = []

        def fake_find_feature(feature_id, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_ONBOARD_PROFILES:
                return 0x09
            return None

        def fake_request(feat, func, params, timeout_ms=2000, count_timeout=True):
            calls.append((feat, func, list(params), count_timeout))
            if feat == 0x09 and func == 2:
                return (0x11, 0x09, 0x2, 0xA, [hid_gesture.ONBOARD_MODE_ONBOARD])
            if feat == 0x09 and func == 1:
                return (0x11, 0x09, 0x1, 0xA, [hid_gesture.ONBOARD_MODE_HOST])
            return None

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_request", side_effect=fake_request),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._apply_host_mode_once())
            self.assertTrue(listener._apply_host_mode_once())

        host_sets = [
            c for c in calls
            if c[0] == 0x09 and c[1] == 1
        ]
        self.assertEqual(len(host_sets), 1)
        self.assertEqual(host_sets[0][2], [hid_gesture.ONBOARD_MODE_HOST])
        self.assertFalse(host_sets[0][3])

    def test_host_mode_skipped_when_prefer_disabled(self):
        listener = hid_gesture.HidGestureListener()
        listener._dev = _FakeHidDevice()
        listener.set_prefer_host_mode(False)

        with (
            patch.object(listener, "_find_feature") as find_mock,
            patch.object(listener, "_request") as request_mock,
            patch("builtins.print"),
        ):
            self.assertTrue(listener._apply_host_mode_once())

        find_mock.assert_not_called()
        request_mock.assert_not_called()

    def test_vendor_hid_infos_skips_windows_vhf_wpid_stub(self):
        """User dump: PID 0x4099 / HID VHF Driver / UP 0x59 is not HID++."""
        infos = [
            {
                "product_id": 0x4099,
                "usage_page": 0x0059,
                "usage": 0x0001,
                "transport": "-",
                "product_string": "HID VHF Driver",
                "path": (
                    b"\\\\?\\HID#HID_DEVICE_SYSTEM_VHF#b&30aba98b&0&0000#"
                    b"{4d1e55b2-f16f-11cf-88cb-001111000030}"
                ),
            },
            {
                "product_id": hid_gesture.LIGHTSPEED_RECEIVER_PID,
                "usage_page": 0xFF00,
                "usage": 0x0001,
                "transport": "-",
                "product_string": "LIGHTSPEED Receiver",
                "path": b"\\\\?\\HID#VID_046D&PID_C547#...",
            },
        ]

        with (
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(enumerate=lambda vid, pid: infos),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            found = hid_gesture.HidGestureListener._vendor_hid_infos()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["product_id"], hid_gesture.LIGHTSPEED_RECEIVER_PID)
        messages = self._printed_messages(print_mock)
        self.assertTrue(any("Skipping non-HID++ interface" in m for m in messages))

    def test_try_connect_rejects_g502_without_adjustable_dpi(self):
        """Catalog match alone must not claim connected with empty features."""
        status_messages = []
        listener = hid_gesture.HidGestureListener(on_status=status_messages.append)
        info = {
            "product_id": 0xC098,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "-",
            "source": "hidapi-enumerate",
            "product_string": "G502 X LIGHTSPEED",
            "path": b"/dev/hidraw-g502x",
        }
        fake_dev = _FakeHidDevice()

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", return_value=None),
            patch.object(listener, "_query_device_name", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            self.assertFalse(listener._try_connect())

        self.assertIsNone(listener.connected_device)
        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any("ADJUSTABLE_DPI not found" in message for message in messages)
        )
        # Phase A Q5: surface a clear UI status, not console-only.
        self.assertTrue(
            any("Lightspeed HID++" in message for message in status_messages),
            status_messages,
        )

    def test_missing_hidpp_status_is_rate_limited(self):
        """Reconnect loops must not spam the same missing-HID++ toast."""
        status_messages = []
        listener = hid_gesture.HidGestureListener(on_status=status_messages.append)
        info = {
            "product_id": 0xC098,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "-",
            "source": "hidapi-enumerate",
            "product_string": "G502 X LIGHTSPEED",
            "path": b"/dev/hidraw-g502x",
        }
        fake_dev = _FakeHidDevice()

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", return_value=None),
            patch.object(listener, "_query_device_name", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertFalse(listener._try_connect())
            self.assertFalse(listener._try_connect())

        self.assertEqual(
            sum(1 for m in status_messages if "Lightspeed HID++" in m),
            1,
            status_messages,
        )

    def test_try_connect_g502_retries_dpi_after_short_probe_miss(self):
        """Short connect probes often time out; final DPI pass must succeed."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC098,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "-",
            "source": "hidapi-enumerate",
            "product_string": "G502 X LIGHTSPEED",
            "path": b"/dev/hidraw-g502x",
        }
        fake_dev = _FakeHidDevice()
        calls = []

        def fake_find_feature(feature_id, timeout_ms=None):
            calls.append((feature_id, timeout_ms))
            if feature_id != hid_gesture.FEAT_ADJ_DPI:
                return None
            # Only the longer final probe finds DPI.
            if timeout_ms is not None and timeout_ms >= 1500:
                return 0x07
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_query_device_name", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertEqual(listener._dpi_idx, 0x07)
        self.assertTrue(
            any(
                feature_id == hid_gesture.FEAT_ADJ_DPI
                and timeout_ms is not None
                and timeout_ms >= 1500
                for feature_id, timeout_ms in calls
            )
        )

    def test_try_connect_logs_linux_hid_path_access_before_open(self):
        listener, info = self._make_listener()
        fake_dev = _FakeHidDevice()
        fake_dev.open_path.side_effect = OSError("open failed")

        with tempfile.NamedTemporaryFile() as fh:
            info = dict(info, path=fh.name.encode())
            with (
                patch.object(sys, "platform", "linux"),
                patch.object(listener, "_vendor_hid_infos", return_value=[info]),
                patch.object(hid_gesture, "HIDAPI_OK", True),
                patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
                patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
                patch.object(
                    hid_gesture,
                    "_hid",
                    SimpleNamespace(device=lambda: fake_dev),
                    create=True,
                ),
                patch("builtins.print") as print_mock,
            ):
                hid_gesture._LOG_ONCE_KEYS.clear()
                self.assertFalse(listener._try_connect())

        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any("HID path access before open:" in message for message in messages)
        )
        self.assertTrue(any("access=read:" in message for message in messages))

    def test_try_connect_success_path_keeps_existing_reprog_discovery_diagnostics(self):
        listener, info = self._make_listener()
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x10
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            self.assertTrue(listener._try_connect())

        messages = self._printed_messages(print_mock)
        self.assertTrue(
            any("Opened PID=0xB023 via hidapi" in message for message in messages)
        )
        self.assertTrue(
            any("Found REPROG_V4 @0x10" in message for message in messages)
        )
        self.assertFalse(
            any(self._is_missing_reprog_diag(message) for message in messages)
        )
        fake_dev.close.assert_not_called()

    def test_try_connect_rearms_extra_diverts_on_reconnect(self):
        listener = hid_gesture.HidGestureListener(
            extra_diverts={
                0x00C4: {"on_down": Mock(), "on_up": Mock()},
            }
        )
        info = {
            "product_id": 0xB023,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "Bluetooth Low Energy",
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3",
            "path": b"/dev/hidraw-test",
        }
        fake_devs = [_FakeHidDevice(), _FakeHidDevice()]

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x10
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras") as divert_extras_mock,
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_devs.pop(0)),
                create=True,
            ),
        ):
            self.assertTrue(listener._try_connect())
            listener._dev = None
            self.assertTrue(listener._try_connect())

        self.assertEqual(divert_extras_mock.call_count, 2)
        self.assertIn(0x00C4, listener._extra_diverts)
        self.assertFalse(listener._extra_diverts[0x00C4]["held"])


class HidRequestTransportFailureTests(unittest.TestCase):
    def test_request_raises_ioerror_on_tx_failure_during_active_session(self):
        listener = hid_gesture.HidGestureListener()
        listener._connected = True

        with patch.object(listener, "_tx", side_effect=OSError("tx boom")):
            with self.assertRaises(IOError):
                listener._request(0x0E, 0, [])

    def test_request_raises_ioerror_on_rx_failure_during_active_session(self):
        listener = hid_gesture.HidGestureListener()
        listener._connected = True

        with (
            patch.object(listener, "_tx"),
            patch.object(listener, "_rx", side_effect=OSError("rx boom")),
        ):
            with self.assertRaises(IOError):
                listener._request(0x0E, 0, [])

    def test_request_returns_none_on_tx_failure_during_discovery(self):
        listener = hid_gesture.HidGestureListener()

        with patch.object(listener, "_tx", side_effect=OSError("tx boom")):
            self.assertIsNone(listener._request(0x0E, 0, []))

    def test_request_returns_none_on_rx_failure_during_discovery(self):
        listener = hid_gesture.HidGestureListener()

        with (
            patch.object(listener, "_tx"),
            patch.object(listener, "_rx", side_effect=OSError("rx boom")),
        ):
            self.assertIsNone(listener._request(0x0E, 0, []))

    def test_request_timeout_still_increments_timeout_counter(self):
        listener = hid_gesture.HidGestureListener()

        with (
            patch.object(listener, "_tx"),
            patch.object(listener, "_rx", return_value=None),
        ):
            self.assertIsNone(listener._request(0x0E, 0, [], timeout_ms=0))

        self.assertEqual(listener._consecutive_request_timeouts, 1)


class HidBoltReceiverTests(unittest.TestCase):
    """Tests for Logi Bolt receiver support."""

    def test_divert_failure_continues_to_next_receiver_slot(self):
        """When divert fails on one slot (e.g. keyboard), the loop
        continues and connects to the mouse on a later slot."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC548,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "USB Receiver",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()
        divert_call_count = [0]

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        def fake_divert():
            divert_call_count[0] += 1
            # First call fails (keyboard), second succeeds (mouse)
            return divert_call_count[0] >= 2

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", side_effect=fake_divert),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())
            self.assertEqual(divert_call_count[0], 2)

    def test_candidates_sorted_direct_devices_before_receivers(self):
        """Bluetooth devices should be tried before USB receivers."""
        listener = hid_gesture.HidGestureListener()
        infos = [
            {"product_string": "USB Receiver", "product_id": 0xC548,
             "usage_page": 0xFF00, "usage": 1, "source": "hidapi"},
            {"product_string": "MX Master 3S", "product_id": 0xB034,
             "usage_page": 0xFF43, "usage": 1, "source": "hidapi"},
            {"product_string": "USB Receiver", "product_id": 0xC548,
             "usage_page": 0xFF00, "usage": 2, "source": "hidapi"},
        ]

        with patch.object(listener, "_vendor_hid_infos", return_value=infos):
            # _try_connect sorts infos in place before iterating
            with (
                patch.object(listener, "_find_feature", return_value=None),
                patch("builtins.print"),
                patch(
                    "core.hid_gesture._load_last_device_cache",
                    return_value=None,
                ),
            ):
                listener._try_connect()

        # After sorting, direct device should be first
        self.assertEqual(infos[0]["product_string"], "MX Master 3S")

    def test_transport_label_bluetooth_for_direct_connection(self):
        """devIdx 0xFF should produce 'Bluetooth' transport."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB034,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3S",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        # devIdx 0xFF (first tried) = Bluetooth
        self.assertEqual(listener.connected_device.transport, "Bluetooth")

    def test_try_connect_applies_runtime_supported_buttons(self):
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB034,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3S",
            "path": b"/dev/hidraw-test",
        }
        controls = [
            {"cid": 0x0052, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x0053, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x0056, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x00C3, "flags": 0x0130, "mapping_flags": 0x0011},
        ]
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=controls),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertIn("gesture", listener.connected_device.supported_buttons)
        self.assertNotIn("gesture_up", listener.connected_device.supported_buttons)
        self.assertNotIn("mode_shift", listener.connected_device.supported_buttons)

    def test_try_connect_marks_thumb_button_cid_button_only_for_mx_master_4(self):
        """MX Master 4 must mark its thumb_button CID (the small HID++
        button at 0x00C3) as button-only so the rawXY-enabled divert is
        skipped if it ever ends up as the active gesture CID. Without
        that the firmware suppresses OS mouse motion while the user
        holds the button, freezing the cursor for nothing -- its rawXY
        data is irrelevant when gestures are routed through the haptic
        panel."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB042,  # MX Master 4
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 4",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(listener, "_install_thumb_button_extra"),
            patch.object(listener, "_query_device_name", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertIn(
            0x00C3, listener._button_only_cids,
            "MX Master 4's small HID++ button (thumb_button_cid) must be "
            "added to _button_only_cids so the rawXY divert is skipped -- "
            "rawXY would freeze the cursor while held.",
        )

    def test_try_connect_leaves_button_only_cids_empty_for_mx_master_3s(self):
        """Older MX Masters have no thumb_button_cid, so no CID needs to be
        forced into button-only mode. The default rawXY-enabled divert on
        the gesture CID is what drives directional swipes on those mice."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB034,  # MX Master 3S
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3S",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(listener, "_install_thumb_button_extra"),
            patch.object(listener, "_query_device_name", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertEqual(listener._button_only_cids, set())

    def test_divert_skips_rawxy_attempt_for_cids_in_button_only_set(self):
        """`_divert` must request 0x03 (button-only) directly for any CID
        flagged in `_button_only_cids`, rather than first trying 0x33
        (rawXY-enabled) and falling back. This is the per-CID equivalent
        of the old global button-only flag."""
        listener = hid_gesture.HidGestureListener()
        listener._feat_idx = 0x09
        listener._gesture_candidates = [0x00C3]
        listener._button_only_cids = {0x00C3}

        recorded = []

        def fake_set_cid_reporting(cid, flags):
            recorded.append((cid, flags))
            return True

        with (
            patch.object(listener, "_set_cid_reporting", side_effect=fake_set_cid_reporting),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._divert())

        self.assertEqual(recorded, [(0x00C3, 0x03)])
        self.assertFalse(listener._rawxy_enabled)

    def test_divert_tries_rawxy_first_for_cids_not_in_button_only_set(self):
        """Default behavior -- including for the new haptic CID 0x01A0 on
        MX Master 4 -- is to request rawXY-enabled divert (0x33) so the
        firmware delivers swipe motion over the vendor channel and pins
        the cursor on its own."""
        listener = hid_gesture.HidGestureListener()
        listener._feat_idx = 0x09
        listener._gesture_candidates = [0x01A0]
        listener._button_only_cids = {0x00C3}  # only small button is button-only

        recorded = []

        def fake_set_cid_reporting(cid, flags):
            recorded.append((cid, flags))
            return True

        with (
            patch.object(listener, "_set_cid_reporting", side_effect=fake_set_cid_reporting),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._divert())

        self.assertEqual(recorded, [(0x01A0, 0x33)])
        self.assertTrue(listener._rawxy_enabled)

    def test_install_thumb_button_extra_adds_cid_when_distinct_from_gesture(self):
        """Happy path: 0x01A0 is the active gesture CID on MX Master 4,
        so 0x00C3 (thumb_button_cid) is added as a button-only extra with
        thumb_button callbacks wired in. ``thumb_button_via_hid`` stays
        False until ``_divert_extras`` acknowledges the setCidReporting."""
        on_down = Mock()
        on_up = Mock()
        listener = hid_gesture.HidGestureListener(
            on_thumb_button_down=on_down,
            on_thumb_button_up=on_up,
        )
        listener._gesture_cid = 0x01A0
        device_spec = SimpleNamespace(thumb_button_cid=0x00C3)
        controls = [
            {"cid": 0x00C3, "flags": 0x0030, "mapping_flags": 0x0001},
        ]

        with patch("builtins.print"):
            listener._install_thumb_button_extra(device_spec, controls)

        self.assertEqual(listener._thumb_button_cid, 0x00C3)
        self.assertIn(0x00C3, listener._extra_diverts)
        # No ack yet -- divert_extras has not run.
        self.assertFalse(listener.thumb_button_via_hid)

        listener._extra_divert_acks.add(0x00C3)
        self.assertTrue(listener.thumb_button_via_hid)

        # Trigger the wired callbacks via the extras dispatch path.
        listener._extra_diverts[0x00C3]["on_down"]()
        on_down.assert_called_once()
        listener._extra_diverts[0x00C3]["on_up"]()
        on_up.assert_called_once()

    def test_install_thumb_button_extra_skipped_when_cid_absent_from_reprog(self):
        """Catalog declares a thumb_button CID, but the firmware does not
        advertise it on this connection. The helper must refuse to queue the
        divert -- queueing would hammer setCidReporting with a CID the
        firmware never exposed.
        """
        listener = hid_gesture.HidGestureListener(
            on_thumb_button_down=Mock(),
            on_thumb_button_up=Mock(),
        )
        listener._gesture_cid = 0x01A0
        device_spec = SimpleNamespace(thumb_button_cid=0x00C3)
        controls = [
            {"cid": 0x0052, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x01A0, "flags": 0x0130, "mapping_flags": 0x0011},
        ]

        with patch("builtins.print"):
            listener._install_thumb_button_extra(device_spec, controls)

        self.assertIsNone(listener._thumb_button_cid)
        self.assertNotIn(0x00C3, listener._extra_diverts)
        self.assertFalse(listener.thumb_button_via_hid)

    def test_divert_extras_clears_acks_and_drops_failed_cids(self):
        """When setCidReporting fails for a CID, the listener must drop it
        from ``_extra_diverts`` so the OS-fallback path stays in charge of
        that button. ``thumb_button_via_hid`` then resolves to False.
        """
        listener = hid_gesture.HidGestureListener()
        listener._feat_idx = 0x09
        listener._thumb_button_cid = 0x00C3
        listener._extra_diverts = {
            0x00C4: {"on_down": Mock(), "on_up": Mock(), "held": False},
            0x00C3: {"on_down": Mock(), "on_up": Mock(), "held": False},
        }
        responses = {0x00C4: True, 0x00C3: None}

        def fake_set_cid_reporting(cid, flags):
            return responses.get(cid)

        with (
            patch.object(listener, "_set_cid_reporting", side_effect=fake_set_cid_reporting),
            patch("builtins.print"),
        ):
            listener._divert_extras()

        self.assertEqual(listener._extra_divert_acks, {0x00C4})
        self.assertIn(0x00C4, listener._extra_diverts)
        self.assertNotIn(0x00C3, listener._extra_diverts)
        self.assertIsNone(listener._thumb_button_cid)
        self.assertFalse(listener.thumb_button_via_hid)

    def test_install_thumb_button_extra_skipped_when_same_as_gesture_cid(self):
        """Fallback path: 0x01A0 divert was rejected, so 0x00C3 became
        the gesture CID. The thumb_button extra must NOT be added -- that
        would re-divert the same CID and stomp on the gesture flags."""
        listener = hid_gesture.HidGestureListener(
            on_thumb_button_down=Mock(),
            on_thumb_button_up=Mock(),
        )
        listener._gesture_cid = 0x00C3
        device_spec = SimpleNamespace(thumb_button_cid=0x00C3)
        controls = [
            {"cid": 0x00C3, "flags": 0x0030, "mapping_flags": 0x0001},
        ]

        with patch("builtins.print"):
            listener._install_thumb_button_extra(device_spec, controls)

        self.assertIsNone(listener._thumb_button_cid)
        self.assertNotIn(0x00C3, listener._extra_diverts)
        self.assertFalse(listener.thumb_button_via_hid)

    def test_install_thumb_button_extra_no_op_when_cid_unset(self):
        listener = hid_gesture.HidGestureListener()
        listener._gesture_cid = 0x00C3
        device_spec = SimpleNamespace(thumb_button_cid=None)

        with patch("builtins.print"):
            listener._install_thumb_button_extra(device_spec, [])

        self.assertIsNone(listener._thumb_button_cid)
        self.assertEqual(listener._extra_diverts, {})
        self.assertFalse(listener.thumb_button_via_hid)

    def test_mx_master_4_full_connect_wires_haptic_gesture_and_thumb_button_extra(self):
        """End-to-end happy path: when MX Master 4 connects and the
        haptic CID 0x01A0 is divertable with rawXY, the listener picks
        it as the active gesture CID and ALSO installs 0x00C3 as the
        thumb_button extra. The resulting ConnectedDeviceInfo carries
        both flags so platform mouse hooks can drop their OS-level
        fallback paths and let HID++ own both buttons end-to-end."""
        on_action_down = Mock()
        on_action_up = Mock()
        listener = hid_gesture.HidGestureListener(
            on_thumb_button_down=on_action_down,
            on_thumb_button_up=on_action_up,
        )
        info = {
            "product_id": 0xB042,  # MX Master 4
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 4",
            "path": b"/dev/hidraw-test",
        }
        # Simulate the device exposing both the haptic CID (0x01A0 with
        # rawXY) and the small button (0x00C3, also rawXY-capable) plus
        # back/forward.
        controls = [
            {"cid": 0x0053, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x0056, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x00C3, "flags": 0x0130, "mapping_flags": 0x0011},
            {"cid": 0x01A0, "flags": 0x0130, "mapping_flags": 0x0011},
        ]
        fake_dev = _FakeHidDevice()
        cid_calls: list[tuple[int, int]] = []

        def fake_set_cid_reporting(cid, flags):
            cid_calls.append((cid, flags))
            return True  # firmware accepts every divert

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=controls),
            patch.object(listener, "_set_cid_reporting", side_effect=fake_set_cid_reporting),
            patch.object(listener, "_query_device_name", return_value="MX Master 4"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        # Active gesture CID should be the sense panel.
        self.assertEqual(listener._gesture_cid, 0x01A0)
        # And it should have been diverted with rawXY (0x33), not 0x03.
        self.assertIn(
            (0x01A0, 0x33), cid_calls,
            "haptic CID must be diverted with rawXY so swipe data flows "
            f"over HID++; setCidReporting calls were {cid_calls}",
        )
        # Action ring extra installed for 0x00C3, button-only.
        self.assertEqual(listener._thumb_button_cid, 0x00C3)
        self.assertIn(0x00C3, listener._extra_diverts)
        self.assertIn(
            (0x00C3, 0x03), cid_calls,
            "thumb_button CID must be diverted button-only (no rawXY) so "
            "the firmware doesn't suppress cursor motion while the "
            f"small button is held; setCidReporting calls were {cid_calls}",
        )
        # ConnectedDeviceInfo reflects the wiring.
        self.assertEqual(
            listener.connected_device.active_gesture_cid, 0x01A0
        )
        self.assertTrue(listener.connected_device.thumb_button_via_hid)

    def test_install_thumb_button_extra_clears_stale_entry_on_reconnect(self):
        """Reconnect to a different device whose spec has no thumb_button
        CID -- the previously-installed entry must be removed so it doesn't
        leak across devices."""
        listener = hid_gesture.HidGestureListener(
            on_thumb_button_down=Mock(),
            on_thumb_button_up=Mock(),
        )
        listener._gesture_cid = 0x01A0
        first_controls = [
            {"cid": 0x00C3, "flags": 0x0030, "mapping_flags": 0x0001},
        ]
        with patch("builtins.print"):
            listener._install_thumb_button_extra(
                SimpleNamespace(thumb_button_cid=0x00C3),
                first_controls,
            )
        self.assertIn(0x00C3, listener._extra_diverts)

        listener._gesture_cid = 0x00C3  # different device
        with patch("builtins.print"):
            listener._install_thumb_button_extra(
                SimpleNamespace(thumb_button_cid=None),
                [],
            )

        self.assertNotIn(0x00C3, listener._extra_diverts)
        self.assertIsNone(listener._thumb_button_cid)

    def test_try_connect_preserves_directional_gestures_after_rawxy_divert(self):
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xB034,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "MX Master 3S",
            "path": b"/dev/hidraw-test",
        }
        controls = [
            {"cid": 0x0052, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x0053, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x0056, "flags": 0x0030, "mapping_flags": 0x0001},
            {"cid": 0x00C3, "flags": 0x0130, "mapping_flags": 0x0011},
            {"cid": 0x00C4, "flags": 0x0130, "mapping_flags": 0x0001},
        ]
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x09
            return None

        def fake_divert():
            listener._gesture_cid = 0x00C3
            listener._rawxy_enabled = True
            return True

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=controls),
            patch.object(listener, "_divert", side_effect=fake_divert),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertIn("gesture", listener.connected_device.supported_buttons)
        self.assertIn("gesture_up", listener.connected_device.supported_buttons)
        self.assertIn("mode_shift", listener.connected_device.supported_buttons)

    def test_transport_label_logi_bolt_for_bolt_receiver(self):
        """devIdx 1-6 with Bolt PID 0xC548 should produce 'Logi Bolt'."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC548,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "USB Receiver",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()
        call_count = [0]

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id != hid_gesture.FEAT_REPROG_V4:
                return None
            call_count[0] += 1
            return 0x09 if call_count[0] >= 2 else None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
            patch(
                "core.hid_gesture._load_last_device_cache",
                return_value=None,
            ),
        ):
            self.assertTrue(listener._try_connect())

        self.assertEqual(listener.connected_device.transport, "Logi Bolt")

    def test_transport_label_usb_receiver_for_non_bolt(self):
        """devIdx 1-6 with non-Bolt PID (e.g. Unifying 0xC52B) should produce
        'USB Receiver', not 'Logi Bolt'."""
        listener = hid_gesture.HidGestureListener()
        info = {
            "product_id": 0xC52B,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "USB Receiver",
            "path": b"/dev/hidraw-test",
        }
        fake_dev = _FakeHidDevice()
        call_count = [0]

        def fake_find_feature(feature_id, *, timeout_ms=None):
            if feature_id != hid_gesture.FEAT_REPROG_V4:
                return None
            call_count[0] += 1
            return 0x09 if call_count[0] >= 2 else None

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        self.assertEqual(listener.connected_device.transport, "USB Receiver")


class HidReconnectInvariantTests(unittest.TestCase):
    def test_force_release_stale_holds_clears_gesture_and_extra_buttons(self):
        gesture_up = Mock()
        extra_up = Mock()
        listener = hid_gesture.HidGestureListener(
            on_up=gesture_up,
            extra_diverts={0x00C4: {"on_up": extra_up}},
        )
        listener._held = True
        listener._extra_diverts[0x00C4]["held"] = True

        listener._force_release_stale_holds()

        self.assertFalse(listener._held)
        self.assertFalse(listener._extra_diverts[0x00C4]["held"])
        gesture_up.assert_called_once_with()
        extra_up.assert_called_once_with()


class MxMaster4ConstantTests(unittest.TestCase):
    def test_sense_panel_cid_named(self):
        self.assertIn(0x01A0, hid_gesture.KNOWN_CID_NAMES)
        self.assertEqual(hid_gesture.KNOWN_CID_NAMES[0x01A0], "Sense Panel")

    def test_haptic_feature_constant(self):
        self.assertEqual(hid_gesture.FEAT_HAPTIC, 0x19B0)

    def test_force_sensing_constant(self):
        self.assertEqual(hid_gesture.FEAT_FORCE_SENSING, 0x19C0)


class HidReconnectStormTests(unittest.TestCase):
    """Regression coverage for issue #238: the reconnect/probe throttle.

    These exercise the platform-independent connect logic (via the hidapi
    fake). The IOKit manager/port leak fix itself is macOS-only and must be
    validated on-device with `leaks`/`heap`; see the issue for that harness."""

    @staticmethod
    def _printed_messages(print_mock):
        return [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]

    @staticmethod
    def _info(pid, product, path):
        return {
            "product_id": pid,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "transport": "Bluetooth Low Energy",
            "source": "hidapi-enumerate",
            "product_string": product,
            "path": path,
        }

    @contextlib.contextmanager
    def _connecting(self, listener, infos, fake_dev, *, reprog_found=True):
        def fake_find_feature(feature_id, *, timeout_ms=None):
            if reprog_found and feature_id == hid_gesture.FEAT_REPROG_V4:
                return 0x10
            return None

        cms = (
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=lambda: fake_dev),
                create=True,
            ),
            patch.object(hid_gesture, "_load_last_device_cache", return_value=None),
            patch.object(hid_gesture, "_save_last_device_cache"),
            patch.object(listener, "_vendor_hid_infos", return_value=infos),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(listener, "_discover_reprog_controls", return_value=[]),
            patch.object(listener, "_divert", return_value=True),
            patch.object(listener, "_divert_extras"),
        )
        with contextlib.ExitStack() as stack:
            for cm in cms:
                stack.enter_context(cm)
            yield

    def test_candidate_cooldown_key_is_hashable_and_distinct(self):
        a = self._info(0xB034, "Iface A", b"/dev/hidraw-a")
        b = self._info(0xB023, "Iface B", b"/dev/hidraw-b")
        key_a = hid_gesture._candidate_cooldown_key(a)
        self.assertEqual(key_a, hid_gesture._candidate_cooldown_key(a))
        self.assertNotEqual(key_a, hid_gesture._candidate_cooldown_key(b))
        self.assertIsInstance(hash(key_a), int)

    def test_missing_reprog_records_cooldown(self):
        listener = hid_gesture.HidGestureListener()
        info = self._info(0xB034, "MX Master 3S", b"/dev/hidraw-x")
        fake_dev = _FakeHidDevice()
        with self._connecting(listener, [info], fake_dev, reprog_found=False):
            self.assertFalse(listener._try_connect())
        self.assertIn(
            hid_gesture._candidate_cooldown_key(info),
            listener._reprog_absent_until,
        )

    def test_cooled_interface_is_skipped_when_another_candidate_exists(self):
        listener = hid_gesture.HidGestureListener()
        # Name sorts the cooled interface first so the skip branch runs before
        # the good interface connects.
        cooled = self._info(0xB025, "AAA Cooled Iface", b"/dev/hidraw-cooled")
        good = self._info(0xB034, "MX Master 3S", b"/dev/hidraw-good")
        listener._reprog_absent_until[
            hid_gesture._candidate_cooldown_key(cooled)
        ] = time.monotonic() + 999
        fake_dev = _FakeHidDevice()
        with self._connecting(listener, [cooled, good], fake_dev):
            with patch("builtins.print") as print_mock:
                self.assertTrue(listener._try_connect())
        # Only the non-cooled interface was opened.
        fake_dev.open_path.assert_called_once_with(b"/dev/hidraw-good")
        self.assertTrue(
            any(
                "Skipping recently-incompatible interface" in message
                for message in self._printed_messages(print_mock)
            )
        )

    def test_sole_cooled_interface_is_still_probed(self):
        listener = hid_gesture.HidGestureListener()
        only = self._info(0xB034, "MX Master 3S", b"/dev/hidraw-only")
        listener._reprog_absent_until[
            hid_gesture._candidate_cooldown_key(only)
        ] = time.monotonic() + 999
        fake_dev = _FakeHidDevice()
        with self._connecting(listener, [only], fake_dev):
            # A lone candidate is never skipped, even while cooling down, so a
            # just-woken device reconnects without waiting out the cooldown.
            self.assertTrue(listener._try_connect())
        fake_dev.open_path.assert_called_once_with(b"/dev/hidraw-only")

    def test_interruptible_sleep_returns_immediately_when_stopped(self):
        listener = hid_gesture.HidGestureListener()
        listener._running = False
        start = time.monotonic()
        listener._interruptible_sleep(5)
        self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
