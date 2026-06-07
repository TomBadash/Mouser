import sys
import unittest

from core import device_hook
from core.device_hook_contract import DeviceHookLike
from core.device_hook_types import HidRuntimeState, DeviceEvent


class DeviceHookContractTests(unittest.TestCase):
    def test_core_device_hook_reexports_mousehook_and_mouseevent(self):
        self.assertIs(device_hook.DeviceEvent, DeviceEvent)
        self.assertTrue(hasattr(device_hook, "DeviceHook"))

    def test_dispatcher_selects_current_platform_module(self):
        expected = {
            "darwin": "core.device_hook_macos",
            "linux": "core.device_hook_linux",
            "win32": "core.device_hook_windows",
        }.get(sys.platform, "core.device_hook_stub")
        self.assertEqual(device_hook.DeviceHook.__module__, expected)

    def test_selected_hook_exposes_engine_contract_surface(self):
        hook = device_hook.DeviceHook()
        self.assertIsInstance(hook, DeviceHookLike)

    def test_selected_hook_exposes_hid_runtime_state(self):
        hook = device_hook.DeviceHook()

        state = hook.hid_runtime_state

        self.assertIsInstance(state, HidRuntimeState)
        self.assertFalse(state.input_ready)
        self.assertFalse(state.hid_ready)
        self.assertIsNone(state.connected_device)

    def test_dispatcher_monkeypatch_forwards_to_platform_module(self):
        platform_module = sys.modules[device_hook.DeviceHook.__module__]

        if sys.platform == "darwin":
            original = getattr(platform_module, "Quartz", None)
            sentinel = object()
            device_hook.Quartz = sentinel
            try:
                self.assertIs(platform_module.Quartz, sentinel)
                self.assertIs(device_hook.Quartz, sentinel)
            finally:
                if original is None:
                    del device_hook.Quartz
                else:
                    device_hook.Quartz = original
        elif sys.platform == "linux":
            original = getattr(platform_module, "_InputDevice", None)
            sentinel = object()
            device_hook._InputDevice = sentinel
            try:
                self.assertIs(platform_module._InputDevice, sentinel)
                self.assertIs(device_hook._InputDevice, sentinel)
            finally:
                if original is None:
                    del device_hook._InputDevice
                else:
                    device_hook._InputDevice = original
        else:
            self.skipTest("No platform-specific forwarding probe for this platform")


if __name__ == "__main__":
    unittest.main()
