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


class _FakeQuartz:
    kCGEventMouseMoved = 1
    kCGEventOtherMouseDragged = 2
    kCGEventOtherMouseDown = 3
    kCGEventOtherMouseUp = 4
    kCGEventScrollWheel = 5
    kCGMouseEventButtonNumber = 10
    kCGMouseEventDeltaX = 11
    kCGMouseEventDeltaY = 12
    kCGEventSourceUserData = 13
    kCGScrollWheelEventFixedPtDeltaAxis1 = 14
    kCGScrollWheelEventFixedPtDeltaAxis2 = 15

    @staticmethod
    def CGEventGetIntegerValueField(event, field):
        return event.get(field, 0)


class MacMouseHookGestureButtonTests(unittest.TestCase):
    def _reload_for_darwin(self):
        fake_quartz = _FakeQuartz()
        with (
            patch.object(sys, "platform", "darwin"),
            patch.dict(sys.modules, {"Quartz": fake_quartz}),
        ):
            importlib.reload(mouse_hook)
        self.addCleanup(importlib.reload, mouse_hook)
        return mouse_hook, fake_quartz

    def test_gesture_button_is_blocked_and_dispatches_click(self):
        module, quartz = self._reload_for_darwin()
        hook = module.MouseHook()
        dispatched = []
        hook.register(
            module.MouseEvent.GESTURE_CLICK,
            lambda event: dispatched.append(event.event_type),
        )

        down_event = {quartz.kCGMouseEventButtonNumber: module._BTN_GESTURE}
        up_event = {quartz.kCGMouseEventButtonNumber: module._BTN_GESTURE}

        self.assertIsNone(
            hook._event_tap_callback(None, quartz.kCGEventOtherMouseDown, down_event, None)
        )
        self.assertTrue(hook._gesture_active)

        self.assertIsNone(
            hook._event_tap_callback(None, quartz.kCGEventOtherMouseUp, up_event, None)
        )
        self.assertFalse(hook._gesture_active)
        self.assertEqual(dispatched, [module.MouseEvent.GESTURE_CLICK])

    def test_non_gesture_button_still_passes_through(self):
        module, quartz = self._reload_for_darwin()
        hook = module.MouseHook()
        event = {quartz.kCGMouseEventButtonNumber: 99}

        self.assertIs(
            hook._event_tap_callback(None, quartz.kCGEventOtherMouseDown, event, None),
            event,
        )
        self.assertFalse(hook._gesture_active)


if __name__ == "__main__":
    unittest.main()
