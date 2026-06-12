import importlib
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import hid_gesture


_save_device_cache_patch = None


def setUpModule():
    """Stop _try_connect's success path from writing a real device_cache.json
    into the developer's config dir while the suite runs."""
    global _save_device_cache_patch
    _save_device_cache_patch = patch.object(
        hid_gesture.config, "save_device_cache"
    )
    _save_device_cache_patch.start()


def tearDownModule():
    if _save_device_cache_patch is not None:
        _save_device_cache_patch.stop()


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


class DevIndexScanOrderTests(unittest.TestCase):
    def test_receiver_pid_probes_numbered_slots_before_bluetooth(self):
        listener = hid_gesture.HidGestureListener()

        order = listener._dev_index_scan_order(
            product_id=hid_gesture.BOLT_RECEIVER_PID
        )

        self.assertEqual(order, [1, 2, 3, 4, 5, 6, hid_gesture.BT_DEV_IDX])

    def test_receiver_detected_by_product_name(self):
        listener = hid_gesture.HidGestureListener()

        order = listener._dev_index_scan_order(
            product_id=0x0000, product_name="USB Receiver"
        )

        self.assertEqual(order[0], 1)
        self.assertEqual(order[-1], hid_gesture.BT_DEV_IDX)

    def test_direct_device_probes_bluetooth_first(self):
        listener = hid_gesture.HidGestureListener()

        order = listener._dev_index_scan_order(
            product_id=0xB034, product_name="MX Master 4"
        )

        self.assertEqual(order[0], hid_gesture.BT_DEV_IDX)
        self.assertEqual(order[1:], [1, 2, 3, 4, 5, 6])

    def test_last_good_index_is_probed_first(self):
        listener = hid_gesture.HidGestureListener()
        listener._last_good_dev_idx = 3

        order = listener._dev_index_scan_order(
            product_id=hid_gesture.BOLT_RECEIVER_PID
        )

        self.assertEqual(order[0], 3)
        # Every slot is still present — the cache only reorders the scan.
        self.assertEqual(
            sorted(order), sorted([1, 2, 3, 4, 5, 6, hid_gesture.BT_DEV_IDX])
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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

        def fake_find_feature(feature_id, **_kwargs):
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


class HidDeviceCacheTests(unittest.TestCase):
    """Persistent device cache and the discovery short-circuits in
    _try_connect that keep boot and reconnects fast."""

    @staticmethod
    def _receiver_info(**overrides):
        info = {
            "product_id": 0xC548,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "product_string": "USB Receiver",
            "path": b"/dev/hidraw-test",
        }
        info.update(overrides)
        return info

    def test_unresponsive_reprog_slot_is_skipped(self):
        """A slot that advertises REPROG_V4 but will not answer the
        control-count query is abandoned, and the scan moves on."""
        listener = hid_gesture.HidGestureListener()
        info = self._receiver_info()
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, **_kwargs):
            return 0x09 if feature_id == hid_gesture.FEAT_REPROG_V4 else None

        # devIdx 1 answers the root probe but is dead; devIdx 2 is real.
        controls_by_slot = [None, []]

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=[info]),
            patch.object(listener, "_find_feature", side_effect=fake_find_feature),
            patch.object(
                listener,
                "_discover_reprog_controls",
                side_effect=lambda: controls_by_slot.pop(0),
            ),
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

        # Connected on devIdx 2 — the dead devIdx 1 was skipped.
        self.assertEqual(listener._dev_idx, 2)

    def test_cached_device_is_probed_before_other_candidates(self):
        """A cached identity is moved to the front of the candidate list."""
        listener = hid_gesture.HidGestureListener()
        listener._device_cache = {
            "product_id": 0xC548,
            "usage_page": 0xFF00,
            "usage": 0x0001,
            "source": "hidapi-enumerate",
            "dev_idx": 2,
        }
        infos = [
            self._receiver_info(product_id=0xC541),   # other receiver
            self._receiver_info(product_id=0xC548),   # cached device
        ]
        fake_dev = _FakeHidDevice()

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=infos),
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
            patch("builtins.print"),
        ):
            listener._try_connect()

        # _try_connect reorders infos in place — the cached PID now leads.
        self.assertEqual(infos[0]["product_id"], 0xC548)

    def test_dead_non_receiver_pid_is_probed_once_not_per_interface(self):
        """A webcam (non-receiver) exposing several vendor collections is
        ruled out once, then its remaining interfaces are skipped."""
        listener = hid_gesture.HidGestureListener()
        infos = [
            {
                "product_id": 0x0944,
                "usage_page": 0xFF00,
                "usage": usage,
                "source": "hidapi-enumerate",
                "product_string": "MX Brio",
                "path": b"/dev/hidraw-webcam",
            }
            for usage in (0x0001, 0x0002, 0x0003)
        ]
        open_count = [0]

        def make_dev():
            open_count[0] += 1
            return _FakeHidDevice()

        with (
            patch.object(listener, "_vendor_hid_infos", return_value=infos),
            patch.object(listener, "_find_feature", return_value=None),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture, "_BACKEND_PREFERENCE", "hidapi"),
            patch.object(hid_gesture, "_HID_API_STYLE", "hidapi"),
            patch.object(
                hid_gesture,
                "_hid",
                SimpleNamespace(device=make_dev),
                create=True,
            ),
            patch("builtins.print"),
        ):
            self.assertFalse(listener._try_connect())

        # Opened once — the 2nd and 3rd MX Brio interfaces were skipped.
        self.assertEqual(open_count[0], 1)

    def test_discovery_request_timeout_is_capped_short(self):
        """Before a session is live, _request caps the wait at the short
        discovery timeout no matter how long the caller asked for."""
        listener = hid_gesture.HidGestureListener()
        self.assertFalse(listener._connected)

        with (
            patch.object(hid_gesture, "DISCOVERY_PROBE_TIMEOUT_MS", 50),
            patch.object(listener, "_tx"),
            patch.object(listener, "_rx", return_value=None),
        ):
            started = time.monotonic()
            self.assertIsNone(
                listener._request(0x0E, 0, [], timeout_ms=10_000)
            )
            elapsed_ms = (time.monotonic() - started) * 1000

        # Capped near 50 ms — nowhere near the 10 s the caller requested.
        self.assertLess(elapsed_ms, 1000)

    def test_successful_connect_persists_device_identity(self):
        """A successful connection writes the device identity to the cache."""
        listener = hid_gesture.HidGestureListener()
        info = self._receiver_info()
        fake_dev = _FakeHidDevice()

        def fake_find_feature(feature_id, **_kwargs):
            return 0x09 if feature_id == hid_gesture.FEAT_REPROG_V4 else None

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
            patch.object(hid_gesture.config, "save_device_cache") as save_mock,
            patch("builtins.print"),
        ):
            self.assertTrue(listener._try_connect())

        save_mock.assert_called_once()
        identity = save_mock.call_args[0][0]
        self.assertEqual(identity["product_id"], 0xC548)
        self.assertEqual(identity["source"], "hidapi-enumerate")
        self.assertEqual(identity["dev_idx"], 1)


if __name__ == "__main__":
    unittest.main()
