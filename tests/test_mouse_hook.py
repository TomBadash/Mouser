import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import mouse_hook


class LinuxMouseHookReconnectTests(unittest.TestCase):
    def _reload_for_linux(self):
        with patch.object(sys, "platform", "linux"):
            importlib.reload(mouse_hook)
        self.addCleanup(importlib.reload, mouse_hook)
        return mouse_hook

    def test_hid_reconnect_requests_rescan_for_fallback_evdev_device(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=0x1234))

        hook._on_hid_connect()

        self.assertTrue(hook.device_connected)
        self.assertEqual(hook.connected_device, {"name": "MX Master 3S"})
        self.assertTrue(hook._rescan_requested.is_set())

    def test_hid_reconnect_does_not_rescan_when_evdev_already_grabs_logitech(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(
            info=SimpleNamespace(vendor=module._LOGI_VENDOR)
        )

        hook._on_hid_connect()

        self.assertTrue(hook.device_connected)
        self.assertFalse(hook._rescan_requested.is_set())

    def test_find_mouse_device_prefers_known_logitech_model_over_legacy_logitech(self):
        module = self._reload_for_linux()

        class FakeDevice:
            def __init__(self, path, name, vendor, product):
                self.path = path
                self.name = name
                self.info = SimpleNamespace(vendor=vendor, product=product)
                self.closed = False

            def capabilities(self, absinfo=False):
                return {
                    module._ecodes.EV_REL: [
                        module._ecodes.REL_X,
                        module._ecodes.REL_Y,
                    ],
                    module._ecodes.EV_KEY: [
                        module._ecodes.BTN_LEFT,
                        module._ecodes.BTN_RIGHT,
                        module._ecodes.BTN_MIDDLE,
                        module._ecodes.BTN_SIDE,
                        module._ecodes.BTN_EXTRA,
                    ],
                }

            def close(self):
                self.closed = True

        legacy = FakeDevice("/dev/input/event11", "Logitech Performance MX", module._LOGI_VENDOR, 0x101A)
        modern = FakeDevice("/dev/input/event22", "Logitech MX Master 3S", module._LOGI_VENDOR, 0xB034)
        devices = {
            legacy.path: legacy,
            modern.path: modern,
        }
        hook = module.MouseHook()

        with (
            patch.object(module._evdev_mod, "list_devices", return_value=list(devices)),
            patch.object(module, "_InputDevice", side_effect=lambda path: devices[path]),
        ):
            chosen = hook._find_mouse_device()

        self.assertIs(chosen, modern)
        self.assertTrue(legacy.closed)
        self.assertFalse(modern.closed)


if __name__ == "__main__":
    unittest.main()
