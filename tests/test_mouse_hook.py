import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, call

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


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSEventTapDisabledTests(unittest.TestCase):
    """Verify CGEventTap is re-enabled when macOS disables it."""

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _make_hook(self):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        return hook

    def test_reenable_on_timeout(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")

        hook._event_tap_callback(
            None, mouse_hook._kCGEventTapDisabledByTimeout, dummy, None)

        self.mock_quartz.CGEventTapEnable.assert_called_once_with(
            hook._tap, True)

    def test_reenable_on_user_input(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")

        hook._event_tap_callback(
            None, mouse_hook._kCGEventTapDisabledByUserInput, dummy, None)

        self.mock_quartz.CGEventTapEnable.assert_called_once_with(
            hook._tap, True)

    def test_normal_event_does_not_reenable(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.return_value = 0

        hook._event_tap_callback(None, 1, dummy, None)  # kCGEventLeftMouseDown

        self.mock_quartz.CGEventTapEnable.assert_not_called()


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSTrackpadScrollFilterTests(unittest.TestCase):
    """Verify CGEventTap callback passes through trackpad events untouched."""

    _kCGScrollWheelEventIsContinuous = 88
    _kCGEventScrollWheel = 22  # Quartz.kCGEventScrollWheel

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        self.mock_quartz.kCGEventScrollWheel = self._kCGEventScrollWheel
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _make_hook(self):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.block(mouse_hook.MouseEvent.HSCROLL_LEFT)
        hook.block(mouse_hook.MouseEvent.HSCROLL_RIGHT)
        return hook

    def _mock_get_field(self, is_continuous, source_user_data=0):
        """side_effect: returns is_continuous for field 88, source_user_data
        for kCGEventSourceUserData, and 0 for everything else."""
        def _get(event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return is_continuous
            if field == self.mock_quartz.kCGEventSourceUserData:
                return source_user_data
            return 0
        return _get

    def test_trackpad_scroll_passes_through_callback(self):
        """Trackpad continuous scroll should be returned as-is, not blocked."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._mock_get_field(is_continuous=1)

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)
        # Verify no HSCROLL events were dispatched
        self.assertTrue(hook._dispatch_queue.empty())

    def test_trackpad_hscroll_not_blocked(self):
        """Trackpad horizontal scroll must NOT trigger hscroll action."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return 1  # trackpad
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 5 * 65536  # non-zero horizontal delta
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)  # passed through, not blocked
        self.assertTrue(hook._dispatch_queue.empty())

    def test_mouse_wheel_hscroll_dispatched_and_blocked(self):
        """Discrete mouse wheel horizontal scroll SHOULD dispatch and block."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return 0  # mouse wheel
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 3 * 65536  # positive = HSCROLL_RIGHT
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result)  # blocked
        self.assertFalse(hook._dispatch_queue.empty())
        event = hook._dispatch_queue.get_nowait()
        self.assertEqual(event.event_type, mouse_hook.MouseEvent.HSCROLL_RIGHT)


if __name__ == "__main__":
    unittest.main()
