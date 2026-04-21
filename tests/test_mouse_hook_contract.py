import sys
import unittest

from core import mouse_hook
from core.mouse_hook_contract import MouseHookLike
from core.mouse_hook_types import MouseEvent


class MouseHookContractTests(unittest.TestCase):
    def test_core_mouse_hook_reexports_mousehook_and_mouseevent(self):
        self.assertIs(mouse_hook.MouseEvent, MouseEvent)
        self.assertTrue(hasattr(mouse_hook, "MouseHook"))

    def test_dispatcher_selects_current_platform_module(self):
        expected = {
            "darwin": "core.mouse_hook_macos",
            "linux": "core.mouse_hook_linux",
            "win32": "core.mouse_hook_windows",
        }.get(sys.platform, "core.mouse_hook_stub")
        self.assertEqual(mouse_hook.MouseHook.__module__, expected)

    def test_selected_hook_exposes_engine_contract_surface(self):
        hook = mouse_hook.MouseHook()
        self.assertIsInstance(hook, MouseHookLike)

    def test_dispatcher_monkeypatch_forwards_to_platform_module(self):
        platform_module = sys.modules[mouse_hook.MouseHook.__module__]

        if sys.platform == "darwin":
            original = getattr(platform_module, "Quartz", None)
            sentinel = object()
            mouse_hook.Quartz = sentinel
            try:
                self.assertIs(platform_module.Quartz, sentinel)
                self.assertIs(mouse_hook.Quartz, sentinel)
            finally:
                if original is None:
                    del mouse_hook.Quartz
                else:
                    mouse_hook.Quartz = original
        elif sys.platform == "linux":
            original = getattr(platform_module, "_InputDevice", None)
            sentinel = object()
            mouse_hook._InputDevice = sentinel
            try:
                self.assertIs(platform_module._InputDevice, sentinel)
                self.assertIs(mouse_hook._InputDevice, sentinel)
            finally:
                if original is None:
                    del mouse_hook._InputDevice
                else:
                    mouse_hook._InputDevice = original
        else:
            self.skipTest("No platform-specific forwarding probe for this platform")


if __name__ == "__main__":
    unittest.main()
