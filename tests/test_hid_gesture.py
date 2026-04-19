import unittest
from unittest.mock import patch

from core import hid_gesture


class HidBackendPreferenceTests(unittest.TestCase):
    def test_default_backend_uses_iokit_on_macos(self):
        self.assertEqual(hid_gesture._default_backend_preference("darwin"), "iokit")

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


class LinuxHidDiscoveryTests(unittest.TestCase):
    def test_vendor_hid_infos_prefers_known_bluetooth_hidraw_device(self):
        receiver_info = {
            "path": b"3-9:1.2",
            "vendor_id": 0x046D,
            "product_id": 0xC52B,
            "usage_page": 0,
            "usage": 0,
            "product_string": "",
            "transport": "",
        }
        mx_master_info = {
            "path": b"/dev/hidraw8",
            "vendor_id": 0x046D,
            "product_id": 0xB034,
            "usage_page": 0,
            "usage": 0,
            "product_string": "Logitech MX Master 3S",
            "transport": "Bluetooth Low Energy",
            "source": "linux-hidraw-enumerate",
        }

        with (
            patch.object(hid_gesture.sys, "platform", "linux"),
            patch.object(hid_gesture, "HIDAPI_OK", True),
            patch.object(hid_gesture._hid, "enumerate", return_value=[receiver_info]),
            patch.object(
                hid_gesture.HidGestureListener,
                "_linux_hidraw_infos",
                return_value=[mx_master_info],
            ),
        ):
            infos = hid_gesture.HidGestureListener._vendor_hid_infos()

        self.assertEqual(infos[0]["product_id"], 0xB034)
        self.assertEqual(infos[1]["product_id"], 0xC52B)

    def test_open_linux_hidraw_uses_raw_device_wrapper(self):
        info = {"path": b"/dev/hidraw8"}

        with patch.object(hid_gesture, "_LinuxHidrawDevice") as raw_dev:
            device = raw_dev.return_value
            result = hid_gesture.HidGestureListener._open_linux_hidraw(info)

        raw_dev.assert_called_once_with("/dev/hidraw8")
        device.open.assert_called_once_with()
        device.set_nonblocking.assert_called_once_with(False)
        self.assertIs(result, device)


if __name__ == "__main__":
    unittest.main()
