import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, call, patch

from core import mouse_hook


class _FakeEvdevDevice:
    def __init__(self, *, name, path, vendor, capabilities, product=0, fd=11):
        self.name = name
        self.path = path
        self.fd = fd
        self.info = SimpleNamespace(vendor=vendor, product=product)
        self._capabilities = capabilities
        self.grab = Mock()
        self.ungrab = Mock()
        self.close = Mock()
        self.read = Mock(return_value=[])

    def capabilities(self, absinfo=False):
        return self._capabilities


class _CapturingListener:
    def __init__(self, on_down=None, on_up=None, on_move=None,
                 on_connect=None, on_disconnect=None, extra_diverts=None):
        self.on_down = on_down
        self.on_up = on_up
        self.on_move = on_move
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.extra_diverts = extra_diverts or {}
        self.connected_device = None
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class _FakeLinuxEcodes:
    EV_REL = 0x02
    EV_KEY = 0x01
    REL_X = 0x00
    REL_Y = 0x01
    BTN_LEFT = 0x110
    BTN_RIGHT = 0x111
    BTN_MIDDLE = 0x112
    BTN_SIDE = 0x113
    BTN_EXTRA = 0x114


class _FakeLinuxUInput:
    @staticmethod
    def from_device(*_args, **_kwargs):
        return Mock()


class LinuxMouseHookReconnectTests(unittest.TestCase):
    def _reload_for_linux(self):
        fake_evdev = SimpleNamespace(
            ecodes=_FakeLinuxEcodes,
            UInput=_FakeLinuxUInput,
            InputDevice=Mock(name="InputDevice"),
        )
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"evdev": fake_evdev}),
        ):
            importlib.reload(mouse_hook)
        self.addCleanup(importlib.reload, mouse_hook)
        return mouse_hook

    def _fake_caps(self, module, *, include_side=True):
        ecodes = module._ecodes
        key_codes = [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]
        if include_side:
            key_codes.extend([ecodes.BTN_SIDE, ecodes.BTN_EXTRA])
        return {
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
            ecodes.EV_KEY: key_codes,
        }

    def _patch_evdev_lookup(self, module, devices_by_path):
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: list(devices_by_path))

        def fake_input_device(path):
            return devices_by_path[path]

        return (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module, "_InputDevice", side_effect=fake_input_device),
        )

    def test_find_mouse_device_prefers_logitech_candidates(self):
        module = self._reload_for_linux()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        generic = _FakeEvdevDevice(
            name="Generic Mouse",
            path="/dev/input/event0",
            vendor=0x1234,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                generic.path: generic,
                logi.path: logi,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, logi)
        self.assertTrue(generic.close.called)
        self.assertFalse(logi.close.called)

    def test_find_mouse_device_prefers_known_supported_logitech_model(self):
        module = self._reload_for_linux()
        legacy = _FakeEvdevDevice(
            name="Logitech Performance MX",
            path="/dev/input/event11",
            vendor=module._LOGI_VENDOR,
            product=0x101A,
            capabilities=self._fake_caps(module),
        )
        modern = _FakeEvdevDevice(
            name="Logitech MX Master 3S",
            path="/dev/input/event22",
            vendor=module._LOGI_VENDOR,
            product=0xB034,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                legacy.path: legacy,
                modern.path: modern,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, modern)
        self.assertTrue(legacy.close.called)
        self.assertFalse(modern.close.called)

    def test_find_mouse_device_returns_none_when_only_non_logitech_candidates_exist(self):
        module = self._reload_for_linux()
        generic_one = _FakeEvdevDevice(
            name="Generic Mouse A",
            path="/dev/input/event0",
            vendor=0x1234,
            capabilities=self._fake_caps(module),
        )
        generic_two = _FakeEvdevDevice(
            name="Generic Mouse B",
            path="/dev/input/event1",
            vendor=0x4321,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                generic_one.path: generic_one,
                generic_two.path: generic_two,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIsNone(chosen)

    def test_find_mouse_device_logs_permission_errors_opening_evdev(self):
        module = self._reload_for_linux()
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: ["/dev/input/event0"])

        with (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module, "_InputDevice", side_effect=PermissionError("denied")),
            patch("builtins.print") as print_mock,
        ):
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIsNone(chosen)
        messages = [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]
        self.assertTrue(
            any("Permission denied opening /dev/input/event0" in msg for msg in messages)
        )

    def test_find_mouse_device_falls_back_to_glob_when_evdev_list_is_empty(self):
        module = self._reload_for_linux()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event4",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: [])

        with (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module.glob, "glob", return_value=[logi.path]),
            patch.object(module, "_InputDevice", return_value=logi),
            patch("builtins.print") as print_mock,
        ):
            module._LOG_ONCE_KEYS.clear()
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, logi)
        messages = [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]
        self.assertTrue(
            any("falling back to visible /dev/input/event* nodes" in msg for msg in messages)
        )

    def test_hid_reconnect_requests_rescan_for_fallback_evdev_device(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=0x1234))

        hook._on_hid_connect()

        self.assertFalse(hook.device_connected)
        self.assertTrue(hook.hid_ready)
        self.assertEqual(hook.connected_device, {"name": "MX Master 3S"})
        self.assertTrue(hook._rescan_requested.is_set())
        self.assertTrue(hook._evdev_wakeup.is_set())

    def test_hid_connect_wakes_evdev_scan_when_no_evdev_device_is_grabbed(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})

        hook._on_hid_connect()

        self.assertTrue(hook.hid_ready)
        self.assertTrue(hook._rescan_requested.is_set())
        self.assertTrue(hook._evdev_wakeup.is_set())

    def test_hid_reconnect_does_not_rescan_when_evdev_already_grabs_logitech(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(
            info=SimpleNamespace(vendor=module._LOGI_VENDOR)
        )
        hook._evdev_connected_device = {"name": "MX Master 3S"}
        hook._set_evdev_ready(True)

        hook._on_hid_connect()

        self.assertTrue(hook.device_connected)
        self.assertFalse(hook._rescan_requested.is_set())

    def test_hid_connect_does_not_mark_device_connected_when_evdev_is_missing(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=0x1234))

        hook._on_hid_connect()

        self.assertFalse(hook.device_connected)

    def test_hid_disconnect_keeps_evdev_driven_connected_state(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=module._LOGI_VENDOR))
        hook._evdev_connected_device = {"name": "MX Master 3S"}
        hook._set_evdev_ready(True)
        hook._hid_ready = True
        hook._connected_device = {"name": "MX Master 3S"}

        hook._on_hid_disconnect()

        self.assertTrue(hook.device_connected)
        self.assertEqual(hook.connected_device, {"name": "MX Master 3S"})

    def test_setup_evdev_marks_connected_and_populates_fallback_device_info(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )

        with (
            patch.object(hook, "_find_mouse_device", return_value=logi),
            patch.object(module._UInput, "from_device", return_value=Mock()),
        ):
            self.assertTrue(hook._setup_evdev())

        self.assertTrue(hook.device_connected)
        self.assertEqual(getattr(hook.connected_device, "display_name", None), "MX Master 3S")
        self.assertEqual(getattr(hook.connected_device, "source", None), "evdev")

    def test_listen_loop_exits_when_rescan_is_requested(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._evdev_device = SimpleNamespace(fd=11, read=Mock(return_value=[]))
        select_calls = []

        def fake_select(readable, writable, exceptional, timeout):
            select_calls.append(timeout)
            hook._rescan_requested.set()
            return ([11], [], [])

        with patch.object(module, "_select_mod", SimpleNamespace(select=fake_select)):
            hook._listen_loop()

        self.assertEqual(select_calls, [0.5])
        self.assertEqual(hook._evdev_device.read.call_count, 1)


class LinuxGestureDetectionTests(unittest.TestCase):
    def _reload_for_linux(self):
        fake_evdev = SimpleNamespace(
            ecodes=_FakeLinuxEcodes,
            UInput=_FakeLinuxUInput,
            InputDevice=Mock(name="InputDevice"),
        )
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"evdev": fake_evdev}),
        ):
            importlib.reload(mouse_hook)
        self.addCleanup(importlib.reload, mouse_hook)
        return mouse_hook

    def _make_hook(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook.configure_gestures(enabled=True, threshold=50, deadzone=40)
        return module, hook

    def test_horizontal_swipe_with_vertical_noise_resolves_horizontal(self):
        module, hook = self._make_hook()
        hook._gesture_delta_x = -72
        hook._gesture_delta_y = -20

        self.assertEqual(
            hook._detect_gesture_event(),
            module.MouseEvent.GESTURE_SWIPE_LEFT,
        )

    def test_equal_diagonal_stays_ambiguous_instead_of_becoming_vertical(self):
        module, hook = self._make_hook()
        hook._gesture_delta_x = -60
        hook._gesture_delta_y = -60

        self.assertIsNone(hook._detect_gesture_event())

    def test_repeated_left_swipes_ignore_rebound_right_within_same_hold(self):
        module, hook = self._make_hook()
        hook._gesture_cooldown_ms = 0
        seen = []
        hook.register(
            module.MouseEvent.GESTURE_SWIPE_LEFT,
            lambda event: seen.append(event.event_type),
        )
        hook.register(
            module.MouseEvent.GESTURE_SWIPE_RIGHT,
            lambda event: seen.append(event.event_type),
        )

        hook._on_hid_gesture_down()
        hook._accumulate_gesture_delta(-70, 0, "hid_rawxy")
        hook._accumulate_gesture_delta(70, 0, "hid_rawxy")
        hook._accumulate_gesture_delta(-70, 0, "hid_rawxy")
        hook._on_hid_gesture_up()

        self.assertEqual(
            seen,
            [
                module.MouseEvent.GESTURE_SWIPE_LEFT,
                module.MouseEvent.GESTURE_SWIPE_LEFT,
            ],
        )

    def test_evdev_loop_clears_rescan_and_retries_after_listen_returns(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        setup_calls = []
        seen_rescan_state = []
        cleanup_calls = []

        def fake_setup():
            setup_calls.append(len(setup_calls))
            if len(setup_calls) == 1:
                return True
            seen_rescan_state.append(hook._rescan_requested.is_set())
            hook._running = False
            return False

        def fake_listen():
            hook._rescan_requested.set()

        def fake_cleanup():
            cleanup_calls.append(True)

        with (
            patch.object(hook, "_setup_evdev", side_effect=fake_setup),
            patch.object(hook, "_listen_loop", side_effect=fake_listen),
            patch.object(hook, "_cleanup_evdev", side_effect=fake_cleanup),
            patch.object(module.time, "sleep", return_value=None),
        ):
            hook._evdev_loop()

        self.assertEqual(len(setup_calls), 2)
        self.assertEqual(seen_rescan_state, [False])
        self.assertEqual(len(cleanup_calls), 1)

    def test_gesture_click_callback_fires_again_after_reconnect(self):
        module = self._reload_for_linux()
        seen = []

        with (
            patch.object(module, "HidGestureListener", _CapturingListener),
            patch.object(module, "_EVDEV_OK", False),
        ):
            hook = module.MouseHook()
            hook.register(module.MouseEvent.GESTURE_CLICK, lambda event: seen.append(event.event_type))
            hook.start()
            listener = hook._hid_gesture

            listener.on_down()
            listener.on_up()
            hook._on_hid_disconnect()
            hook._on_hid_connect()
            listener.on_down()
            listener.on_up()

        self.assertEqual(
            seen,
            [module.MouseEvent.GESTURE_CLICK, module.MouseEvent.GESTURE_CLICK],
        )

    def test_mode_shift_callbacks_fire_again_after_reconnect(self):
        module = self._reload_for_linux()
        seen = []

        with (
            patch.object(module, "HidGestureListener", _CapturingListener),
            patch.object(module, "_EVDEV_OK", False),
        ):
            hook = module.MouseHook()
            hook.divert_mode_shift = True
            hook.register(module.MouseEvent.MODE_SHIFT_DOWN, lambda event: seen.append(event.event_type))
            hook.register(module.MouseEvent.MODE_SHIFT_UP, lambda event: seen.append(event.event_type))
            hook.start()
            listener = hook._hid_gesture

            listener.extra_diverts[0x00C4]["on_down"]()
            listener.extra_diverts[0x00C4]["on_up"]()
            hook._on_hid_disconnect()
            hook._on_hid_connect()
            listener.extra_diverts[0x00C4]["on_down"]()
            listener.extra_diverts[0x00C4]["on_up"]()

        self.assertEqual(
            seen,
            [
                module.MouseEvent.MODE_SHIFT_DOWN,
                module.MouseEvent.MODE_SHIFT_UP,
                module.MouseEvent.MODE_SHIFT_DOWN,
                module.MouseEvent.MODE_SHIFT_UP,
            ],
        )


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

    def test_trackpad_filter_can_be_disabled(self):
        """Continuous scroll should be handled when ignore_trackpad is off."""
        hook = self._make_hook()
        hook.ignore_trackpad = False
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return 1  # trackpad / Magic Mouse
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 3 * 65536  # positive = HSCROLL_RIGHT
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result)
        self.assertFalse(hook._dispatch_queue.empty())
        event = hook._dispatch_queue.get_nowait()
        self.assertEqual(event.event_type, mouse_hook.MouseEvent.HSCROLL_RIGHT)

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
