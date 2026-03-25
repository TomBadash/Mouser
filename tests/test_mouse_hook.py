import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from core import mouse_hook


class MacOSCGEventTapWakeTests(unittest.TestCase):
    """Tests for CGEventTap re-enable logic after macOS sleep/wake."""

    _DISABLED_BY_TIMEOUT = 0xFFFFFFFE
    _DISABLED_BY_USER_INPUT = 0xFFFFFFFD

    def _make_quartz_mock(self):
        q = MagicMock()
        q.kCGEventTapDisabledByTimeout = self._DISABLED_BY_TIMEOUT
        q.kCGEventTapDisabledByUserInput = self._DISABLED_BY_USER_INPUT
        return q

    def _reload_with_quartz(self, quartz_mock=None):
        if quartz_mock is None:
            quartz_mock = self._make_quartz_mock()
        with patch.dict(sys.modules, {"Quartz": quartz_mock}):
            with patch.object(sys, "platform", "darwin"):
                importlib.reload(mouse_hook)
        self.addCleanup(importlib.reload, mouse_hook)
        return mouse_hook, quartz_mock

    # -- _event_tap_callback: disabled events --------------------------------

    def test_callback_reenables_tap_on_timeout_disabled(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        fake_tap = object()
        hook._tap = fake_tap
        fake_event = object()

        result = hook._event_tap_callback(None, q.kCGEventTapDisabledByTimeout, fake_event, None)

        q.CGEventTapEnable.assert_called_once_with(fake_tap, True)
        self.assertIs(result, fake_event)

    def test_callback_reenables_tap_on_user_input_disabled(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        fake_tap = object()
        hook._tap = fake_tap
        fake_event = object()

        result = hook._event_tap_callback(None, q.kCGEventTapDisabledByUserInput, fake_event, None)

        q.CGEventTapEnable.assert_called_once_with(fake_tap, True)
        self.assertIs(result, fake_event)

    def test_callback_does_not_reenable_for_normal_events(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        hook._tap = object()
        # Use a plain integer that is not a disabled-event constant
        normal_event_type = 22  # kCGEventScrollWheel

        hook._event_tap_callback(None, normal_event_type, MagicMock(), None)

        q.CGEventTapEnable.assert_not_called()

    # -- _register_wake_observer / _on_wake callback -------------------------

    def _make_appkit_mock(self):
        appkit = MagicMock()
        nc = appkit.NSWorkspace.sharedWorkspace.return_value.notificationCenter.return_value
        return appkit, nc

    def _register_and_get_wake_cb(self, hook):
        appkit_mock, nc = self._make_appkit_mock()
        with patch.dict(sys.modules, {"AppKit": appkit_mock}):
            hook._register_wake_observer()
        wake_cb = nc.addObserverForName_object_queue_usingBlock_.call_args[0][3]
        return wake_cb, nc, appkit_mock

    def test_register_wake_observer_subscribes_to_did_wake(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        _, nc, _ = self._register_and_get_wake_cb(hook)

        name_arg = nc.addObserverForName_object_queue_usingBlock_.call_args[0][0]
        self.assertEqual(name_arg, "NSWorkspaceDidWakeNotification")

    def test_on_wake_reenables_tap_when_running(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        fake_tap = object()
        hook._tap = fake_tap
        hook._running = True
        wake_cb, _, _ = self._register_and_get_wake_cb(hook)

        wake_cb(None)

        q.CGEventTapEnable.assert_called_once_with(fake_tap, True)

    def test_on_wake_skips_reenable_when_not_running(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        hook._tap = object()
        hook._running = False
        wake_cb, _, _ = self._register_and_get_wake_cb(hook)

        wake_cb(None)

        q.CGEventTapEnable.assert_not_called()

    def test_on_wake_skips_reenable_when_tap_is_none(self):
        mod, q = self._reload_with_quartz()
        hook = mod.MouseHook()
        hook._tap = None
        hook._running = True
        wake_cb, _, _ = self._register_and_get_wake_cb(hook)

        wake_cb(None)

        q.CGEventTapEnable.assert_not_called()

    # -- _unregister_wake_observer -------------------------------------------

    def test_unregister_removes_observer_and_clears_field(self):
        mod, _ = self._reload_with_quartz()
        hook = mod.MouseHook()
        sentinel = object()
        hook._wake_observer = sentinel
        appkit_mock, nc = self._make_appkit_mock()

        with patch.dict(sys.modules, {"AppKit": appkit_mock}):
            hook._unregister_wake_observer()

        nc.removeObserver_.assert_called_once_with(sentinel)
        self.assertIsNone(hook._wake_observer)

    def test_unregister_is_noop_when_no_observer(self):
        mod, _ = self._reload_with_quartz()
        hook = mod.MouseHook()
        hook._wake_observer = None
        appkit_mock, nc = self._make_appkit_mock()

        with patch.dict(sys.modules, {"AppKit": appkit_mock}):
            hook._unregister_wake_observer()  # must not raise

        nc.removeObserver_.assert_not_called()

    def test_register_failure_sets_observer_to_none(self):
        mod, _ = self._reload_with_quartz()
        hook = mod.MouseHook()
        appkit_mock = MagicMock()
        appkit_mock.NSWorkspace.sharedWorkspace.side_effect = RuntimeError("no workspace")

        with patch.dict(sys.modules, {"AppKit": appkit_mock}):
            hook._register_wake_observer()  # must not raise

        self.assertIsNone(hook._wake_observer)


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


if __name__ == "__main__":
    unittest.main()
