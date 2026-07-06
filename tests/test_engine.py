import copy
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

def _ensure_core_engine_importable():
    """Make `core.engine` importable in this sandbox (no PyObjC/objc).

    core.engine does `from core.mouse_hook import ...` (platform dispatch)
    and `from core.app_detector import AppDetector`, both of which pull in
    the native macOS hook at module load. Every test in this file patches
    both classes out anyway (_FakeMouseHook / _FakeAppDetector), so stub
    the two modules just long enough to import core.engine once — it's
    then cached for the rest of the session — and remove the stubs again
    immediately after, so any *other* test file that imports
    core.mouse_hook / core.app_detector directly still sees the real
    (missing-PyObjC) failure, unaffected by this workaround.
    """
    try:
        import core.engine  # noqa: F401
        return
    except ImportError:
        pass

    from core.mouse_hook_types import MouseEvent as _MouseEvent

    stubbed = []
    for name, attr, extra in (
        ("core.mouse_hook", "MouseHook", {"MouseEvent": _MouseEvent}),
        ("core.app_detector", "AppDetector", {}),
    ):
        if name in sys.modules:
            continue
        stub = types.ModuleType(name)
        setattr(stub, attr, object)
        for key, value in extra.items():
            setattr(stub, key, value)
        sys.modules[name] = stub
        stubbed.append(name)

    try:
        import core.engine  # noqa: F401
    finally:
        for name in stubbed:
            del sys.modules[name]


_ensure_core_engine_importable()

from core.config import DEFAULT_CONFIG, GESTURE_HOLD_FLOOR_MS_DEFAULT
# core.mouse_hook_types (not core.mouse_hook — see _ensure_core_engine_importable
# above) so this import is objc-free regardless of whether the sandbox stub ran.
from core.mouse_hook_types import HidRuntimeState, MouseEvent


class _FakeMouseHook:
    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False
        self._hid_gesture = None
        self.start_called = False
        self.stop_called = False
        self.registered = {}

    def set_debug_callback(self, cb):
        self._debug_callback = cb

    def set_gesture_callback(self, cb):
        self._gesture_callback = cb

    def set_status_callback(self, cb):
        self._status_callback = cb

    def set_connection_change_callback(self, cb):
        self._connection_change_callback = cb

    def configure_gestures(self, **kwargs):
        self._gesture_config = kwargs

    def block(self, event_type):
        pass

    def register(self, event_type, callback):
        self.registered.setdefault(event_type, []).append(callback)

    def reset_bindings(self):
        self.registered = {}

    def start(self):
        self.start_called = True

    def stop(self):
        self.stop_called = True


class _FakeAppDetector:
    def __init__(self, callback):
        self.callback = callback
        self.start_called = False
        self.stop_called = False

    def start(self):
        self.start_called = True

    def stop(self):
        self.stop_called = True


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


class _RecordedThread:
    def __init__(self, target=None, args=(), kwargs=None, name=None, **_):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.name = name
        self.start_called = False
        self.join = Mock()

    def start(self):
        self.start_called = True

    def run_target(self):
        if self._target:
            return self._target(*self._args, **self._kwargs)
        return None


class EngineHorizontalScrollTests(unittest.TestCase):
    def _make_engine(self):
        from core.engine import Engine

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["hscroll_threshold"] = 1

        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_hscroll_desktop_action_uses_cooldown(self):
        engine = self._make_engine()
        handler = engine._make_hscroll_handler("space_left")

        with patch("core.engine.execute_action") as execute_action_mock:
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.00,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.05,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.45,
            ))

        self.assertEqual(execute_action_mock.call_count, 2)

    def test_hscroll_accumulates_fractional_mac_deltas(self):
        engine = self._make_engine()
        handler = engine._make_hscroll_handler("space_right")

        with patch("core.engine.execute_action") as execute_action_mock:
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.35,
                timestamp=2.00,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.40,
                timestamp=2.02,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.30,
                timestamp=2.04,
            ))

        self.assertEqual(execute_action_mock.call_count, 1)

    def test_connection_callback_receives_current_state_immediately(self):
        engine = self._make_engine()
        engine.hook.device_connected = True

        seen = []
        engine.set_connection_change_callback(seen.append)

        self.assertEqual(seen, [True])

    def test_connection_callback_prefers_device_connected_flag_over_stale_identity(self):
        engine = self._make_engine()
        engine.hook.device_connected = False
        engine.hook.connected_device = SimpleNamespace(name="MX Master 3S")

        seen = []
        engine.set_connection_change_callback(seen.append)

        self.assertEqual(seen, [False])

    def test_hid_features_ready_requires_hid_identity(self):
        engine = self._make_engine()

        self.assertFalse(engine.hid_features_ready)

        engine.hook._hid_gesture = SimpleNamespace(connected_device=None)
        self.assertFalse(engine.hid_features_ready)

        engine.hook._hid_gesture = SimpleNamespace(
            connected_device=SimpleNamespace(name="MX Master 3S")
        )
        self.assertTrue(engine.hid_features_ready)

    def test_engine_projection_prefers_hid_runtime_state(self):
        engine = self._make_engine()
        device = SimpleNamespace(name="MX Master 3S")
        engine.hook.device_connected = False
        engine.hook.connected_device = SimpleNamespace(name="stale fallback")
        engine.hook._hid_gesture = None
        engine.hook.hid_runtime_state = HidRuntimeState(
            input_ready=True,
            hid_ready=True,
            connected_device=device,
        )

        seen = []
        engine.set_connection_change_callback(seen.append)

        self.assertTrue(engine.device_connected)
        self.assertIs(engine.connected_device, device)
        self.assertTrue(engine.hid_features_ready)
        self.assertEqual(seen, [True])

    def test_duplicate_connected_refresh_does_not_restart_battery_poller(self):
        engine = self._make_engine()
        seen = []
        engine.set_connection_change_callback(seen.append)
        engine.hook._hid_gesture = SimpleNamespace(connected_device=None)
        thread_instances = []

        def fake_thread(*args, **kwargs):
            thread = _RecordedThread(*args, **kwargs)
            thread_instances.append(thread)
            return thread

        with patch("core.engine.threading.Thread", side_effect=fake_thread):
            engine._on_connection_change(True)
            battery_threads = [
                thread for thread in thread_instances if thread.name == "BatteryPoll"
            ]
            self.assertEqual(len(battery_threads), 1)
            first_thread = battery_threads[0]

            engine.hook._hid_gesture = SimpleNamespace(
                connected_device=SimpleNamespace(name="MX Master 3S")
            )
            engine._on_connection_change(True)

        self.assertEqual(seen, [False, True, True])
        battery_threads = [
            thread for thread in thread_instances if thread.name == "BatteryPoll"
        ]
        self.assertEqual(len(battery_threads), 1)
        first_thread.join.assert_not_called()
        self.assertIs(engine._battery_poll_thread, first_thread)

    def test_start_applies_saved_dpi_without_reading_device_dpi(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = SimpleNamespace(
            connected_device=SimpleNamespace(name="MX Master 3S"),
            set_dpi=Mock(return_value=True),
            read_dpi=Mock(),
            smart_shift_supported=False,
        )
        seen = []
        engine.set_dpi_read_callback(seen.append)

        with (
            patch("core.engine.threading.Thread", _ImmediateThread),
            patch("time.sleep", return_value=None),
        ):
            engine.start()

        expected = engine.cfg["settings"]["dpi"]
        engine.hook._hid_gesture.set_dpi.assert_called_once_with(expected)
        engine.hook._hid_gesture.read_dpi.assert_not_called()
        self.assertEqual(seen, [expected])
        self.assertTrue(engine.hook.start_called)
        self.assertTrue(engine._app_detector.start_called)


class EngineReplayPhaseOneTests(unittest.TestCase):
    def _make_engine(self):
        from core.engine import Engine

        cfg = copy.deepcopy(DEFAULT_CONFIG)

        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    @staticmethod
    def _thread_factory(instances):
        def factory(*args, **kwargs):
            thread = _RecordedThread(*args, **kwargs)
            instances.append(thread)
            return thread

        return factory

    @staticmethod
    def _non_battery_threads(instances):
        return [thread for thread in instances if thread.name != "BatteryPoll"]

    def _make_hid(self, *, connected_device=None, dpi_result=True, smart_shift_result=True):
        return SimpleNamespace(
            connected_device=connected_device,
            read_battery=Mock(return_value=None),
            set_dpi=Mock(return_value=dpi_result),
            set_smart_shift=Mock(return_value=smart_shift_result),
            smart_shift_supported=True,
        )

    def test_hid_ready_transition_requests_replay_worker(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = self._make_hid(connected_device=None)
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)
            self.assertEqual(len(threads), 1)
            self.assertEqual(self._non_battery_threads(threads), [])
            engine.hook._hid_gesture.set_dpi.assert_not_called()
            engine.hook._hid_gesture.set_smart_shift.assert_not_called()

            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)

        expected_dpi = engine.cfg["settings"]["dpi"]
        expected_ss_mode = engine.cfg["settings"]["smart_shift_mode"]
        expected_ss_enabled = engine.cfg["settings"]["smart_shift_enabled"]
        expected_ss_threshold = engine.cfg["settings"]["smart_shift_threshold"]
        replay_threads = self._non_battery_threads(threads)
        self.assertEqual(len(replay_threads), 1)
        replay_threads[0].run_target()
        engine.hook._hid_gesture.set_dpi.assert_called_once_with(expected_dpi)
        self.assertEqual(engine.hook._hid_gesture.set_smart_shift.call_count, 2)
        engine.hook._hid_gesture.set_smart_shift.assert_called_with(
            expected_ss_mode, expected_ss_enabled, expected_ss_threshold
        )

    def test_live_reconnect_replay_restores_saved_values_through_worker(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = self._make_hid(connected_device=None)
        threads = []
        seen_dpi = []
        seen_smart_shift = []
        engine.set_dpi_read_callback(seen_dpi.append)
        engine.set_smart_shift_read_callback(seen_smart_shift.append)

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)
            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)

        replay_threads = self._non_battery_threads(threads)
        self.assertEqual(len(replay_threads), 1)
        replay_threads[0].run_target()

        self.assertEqual(seen_dpi, [engine.cfg["settings"]["dpi"]])
        self.assertGreaterEqual(len(seen_smart_shift), 2)
        self.assertEqual(
            seen_smart_shift[-1],
            {
                "mode": engine.cfg["settings"]["smart_shift_mode"],
                "enabled": engine.cfg["settings"]["smart_shift_enabled"],
                "threshold": engine.cfg["settings"]["smart_shift_threshold"],
            },
        )

    def test_evdev_only_connected_true_does_not_request_replay_worker(self):
        engine = self._make_engine()
        engine.hook.connected_device = SimpleNamespace(name="MX Master 3S", source="evdev")
        engine.hook._hid_gesture = self._make_hid(connected_device=None)
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)
            engine._on_connection_change(True)

        self.assertEqual(len(threads), 1)
        self.assertEqual(self._non_battery_threads(threads), [])
        engine.hook._hid_gesture.set_dpi.assert_not_called()
        engine.hook._hid_gesture.set_smart_shift.assert_not_called()

    def test_duplicate_same_value_refresh_does_not_create_duplicate_replay_workers(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = self._make_hid(connected_device=None)
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)

            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)
            first_replay_threads = list(self._non_battery_threads(threads))

            engine._on_connection_change(True)

        self.assertEqual(len(first_replay_threads), 1)
        self.assertEqual(self._non_battery_threads(threads), first_replay_threads)

    def test_hid_disconnect_while_evdev_connected_allows_next_hid_replay(self):
        engine = self._make_engine()
        engine.hook.connected_device = SimpleNamespace(name="MX Master 3S", source="evdev")
        engine.hook._hid_gesture = self._make_hid(
            connected_device=SimpleNamespace(name="MX Master 3S")
        )
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)
            self.assertEqual(len(self._non_battery_threads(threads)), 1)
            self._non_battery_threads(threads)[0].run_target()

            engine.hook._hid_gesture.connected_device = None
            engine._on_connection_change(True)
            self.assertEqual(len(self._non_battery_threads(threads)), 1)

            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)

        self.assertEqual(len(self._non_battery_threads(threads)), 2)

    def test_hid_disconnect_updates_last_hid_ready_without_connection_edge(self):
        engine = self._make_engine()
        engine.hook.connected_device = SimpleNamespace(name="MX Master 3S", source="evdev")
        engine.hook._hid_gesture = self._make_hid(
            connected_device=SimpleNamespace(name="MX Master 3S")
        )

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory([])):
            engine._on_connection_change(True)
        self.assertTrue(engine._last_hid_features_ready)

        engine.hook._hid_gesture.connected_device = None
        engine._on_connection_change(True)

        self.assertFalse(engine._last_hid_features_ready)

    def test_startup_fallback_does_not_queue_replay_after_hid_ready_replay_requested(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = self._make_hid(connected_device=None)
        threads = []

        with (
            patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)),
            patch("core.engine.time.sleep", return_value=None),
        ):
            engine.start()
            startup_threads = list(self._non_battery_threads(threads))
            self.assertEqual(len(startup_threads), 1)

            engine._on_connection_change(True)
            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)

        non_battery_before_fallback = list(self._non_battery_threads(threads))
        self.assertEqual(len(non_battery_before_fallback), 2)
        replay_threads = [
            thread for thread in non_battery_before_fallback
            if thread not in startup_threads
        ]
        self.assertEqual(len(replay_threads), 1)
        replay_threads[0].run_target()

        self.assertEqual(engine.hook._hid_gesture.set_dpi.call_count, 1)
        self.assertEqual(engine.hook._hid_gesture.set_smart_shift.call_count, 2)

        startup_threads[0].run_target()

        expected_dpi = engine.cfg["settings"]["dpi"]
        expected_ss_mode = engine.cfg["settings"]["smart_shift_mode"]
        expected_ss_enabled = engine.cfg["settings"]["smart_shift_enabled"]
        expected_ss_threshold = engine.cfg["settings"]["smart_shift_threshold"]
        engine.hook._hid_gesture.set_dpi.assert_called_once_with(expected_dpi)
        self.assertEqual(engine.hook._hid_gesture.set_smart_shift.call_count, 2)
        engine.hook._hid_gesture.set_smart_shift.assert_called_with(
            expected_ss_mode, expected_ss_enabled, expected_ss_threshold
        )

    def test_replay_failure_emits_engine_status_callback(self):
        engine = self._make_engine()
        status_messages = []
        engine.set_status_callback(status_messages.append)
        engine.hook._hid_gesture = self._make_hid(
            connected_device=None,
            dpi_result=False,
            smart_shift_result=True,
        )
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            engine._on_connection_change(True)
            engine.hook._hid_gesture.connected_device = SimpleNamespace(name="MX Master 3S")
            engine._on_connection_change(True)

        replay_threads = self._non_battery_threads(threads)
        self.assertEqual(len(replay_threads), 1)
        replay_threads[0].run_target()

        self.assertTrue(status_messages)
        self.assertTrue(
            any(
                "could not be restored" in message.lower()
                for message in status_messages
            ),
            status_messages,
        )

    def test_battery_poll_skips_smart_shift_reads_while_replay_is_inflight(self):
        engine = self._make_engine()
        stop_event = Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True
        engine._replay_inflight = True
        engine.hook._hid_gesture = SimpleNamespace(
            connected_device=SimpleNamespace(name="MX Master 3S"),
            smart_shift_supported=True,
            read_battery=Mock(return_value=None),
            read_smart_shift=Mock(return_value={"mode": "ratchet", "enabled": False, "threshold": 25}),
        )

        engine._battery_poll_loop(stop_event)

        engine.hook._hid_gesture.read_battery.assert_called_once_with()
        engine.hook._hid_gesture.read_smart_shift.assert_not_called()


_ALL_GESTURE_OWNERS = ("back", "forward", "middle")
_ALL_GESTURE_DIRECTIONS = ("left", "right", "up", "down")


def _fully_eligible_device():
    """A device whose supported_buttons cover every owner's 4 directions --
    used as the default device for tests that exercise ROUTING, not the
    finding #1 enable/eligibility gate itself (covered separately below)."""
    return SimpleNamespace(
        supported_buttons=tuple(
            f"gesture_{owner}_{direction}"
            for owner in _ALL_GESTURE_OWNERS
            for direction in _ALL_GESTURE_DIRECTIONS
        )
    )


def _connected_mouse_hook_cls(device):
    """A _FakeMouseHook subclass pre-wired with a connected device, so
    Engine.__init__'s synchronous _setup_hooks() call sees it (there is no
    window to inject the device after construction)."""
    class _ConnectedFakeMouseHook(_FakeMouseHook):
        def __init__(self):
            super().__init__()
            self.connected_device = device
            self.device_connected = device is not None
    return _ConnectedFakeMouseHook


def _fully_eligible_device_with_button_and_tilt():
    """Device eligible for BOTH button owners and tilt owners -- mirrors the
    real mx_anywhere_2s spec (supports_event_tap_gestures AND
    supports_tilt_gestures both True). Used to regression-test that the two
    owner kinds route into separate configure_gestures() params, never mixed."""
    return SimpleNamespace(
        supported_buttons=(
            *_fully_eligible_device().supported_buttons,
            *(
                f"gesture_{owner}_{direction}"
                for owner in ("tilt_left", "tilt_right")
                for direction in _ALL_GESTURE_DIRECTIONS
            ),
        )
    )


class EngineGestureDispatchTests(unittest.TestCase):
    """Issue 004: configure_gestures wiring + per-owner direction dispatch.

    These tests are about ROUTING, not the arming gate (finding #1, covered
    by EngineGestureArmingGateTests below) -- so every owner is enabled and
    the fake device is eligible for all of them by default.
    """

    _DEFAULT_DEVICE = object()  # sentinel: distinguish "use the default eligible device" from device=None

    def _make_engine(self, cfg, device=_DEFAULT_DEVICE):
        from core.engine import Engine

        if device is self._DEFAULT_DEVICE:
            device = _fully_eligible_device()
        hook_cls = _connected_mouse_hook_cls(device) if device is not None else _FakeMouseHook
        with (
            patch("core.engine.MouseHook", hook_cls),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def _cfg(self, **mapping_overrides):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"].update(mapping_overrides)
        cfg["settings"]["gesture_owner_enabled"] = {owner: True for owner in _ALL_GESTURE_OWNERS}
        return cfg

    def _owner_event(self, owner, dx=0, dy=-80):
        return SimpleNamespace(
            event_type=MouseEvent.GESTURE_SWIPE_UP,
            raw_data={"delta_x": dx, "delta_y": dy, "source": "event_tap", "gesture_owner": owner},
        )

    def test_configure_gestures_receives_owner_set_and_default_hold_floor(self):
        cfg = self._cfg(gesture_forward_up="mission_control")
        engine = self._make_engine(cfg)

        gesture_cfg = engine.hook._gesture_config
        self.assertEqual(gesture_cfg["owners"], {"forward"})
        self.assertEqual(gesture_cfg["hold_floor_ms"], GESTURE_HOLD_FLOOR_MS_DEFAULT)
        self.assertIs(gesture_cfg["enabled"], True)

    def test_configure_gestures_threads_custom_hold_floor(self):
        cfg = self._cfg(gesture_forward_up="mission_control")
        cfg["settings"]["gesture_hold_floor_ms"] = 150
        engine = self._make_engine(cfg)

        self.assertEqual(engine.hook._gesture_config["hold_floor_ms"], 150)

    def test_zero_owners_disables_gestures_with_empty_owner_set(self):
        engine = self._make_engine(self._cfg())

        gesture_cfg = engine.hook._gesture_config
        self.assertEqual(gesture_cfg["owners"], set())
        self.assertIs(gesture_cfg["enabled"], False)

    def test_hid_direction_only_still_enables_gestures_with_empty_owners(self):
        engine = self._make_engine(self._cfg(gesture_up="mission_control"))

        gesture_cfg = engine.hook._gesture_config
        self.assertEqual(gesture_cfg["owners"], set())
        self.assertIs(gesture_cfg["enabled"], True)

    def test_owner_gesture_dispatches_to_namespaced_action(self):
        engine = self._make_engine(self._cfg(gesture_forward_up="mission_control"))
        handlers = engine.hook.registered["gesture_swipe_up"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(self._owner_event("forward"))

        execute_action_mock.assert_called_once_with("mission_control")

    def test_two_owners_same_direction_fire_their_own_actions(self):
        engine = self._make_engine(self._cfg(
            gesture_forward_up="mission_control",
            gesture_back_up="app_expose",
        ))
        handlers = engine.hook.registered["gesture_swipe_up"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(self._owner_event("forward"))
            for handler in handlers:
                handler(self._owner_event("back"))

        execute_action_mock.assert_has_calls(
            [unittest.mock.call("mission_control"), unittest.mock.call("app_expose")]
        )
        self.assertEqual(execute_action_mock.call_count, 2)

    def test_owner_direction_without_binding_does_not_fire(self):
        # forward only binds "up" — a "down" swipe from forward has no action.
        engine = self._make_engine(self._cfg(gesture_forward_up="mission_control"))
        handlers = engine.hook.registered["gesture_swipe_down"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(SimpleNamespace(
                    event_type=MouseEvent.GESTURE_SWIPE_DOWN,
                    raw_data={"delta_x": 0, "delta_y": 80, "source": "event_tap", "gesture_owner": "forward"},
                ))

        execute_action_mock.assert_not_called()

    def test_hid_gesture_button_still_routes_when_owners_configured(self):
        """Regression guard: MX Master HID gesture path still fires from its
        own (non-owner-tagged) events once per-owner routing is also wired."""
        engine = self._make_engine(self._cfg(
            gesture_up="app_expose",
            gesture_forward_up="mission_control",
        ))
        handlers = engine.hook.registered["gesture_swipe_up"]
        self.assertEqual(len(handlers), 2)

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(SimpleNamespace(
                    event_type=MouseEvent.GESTURE_SWIPE_UP,
                    raw_data={"delta_x": 0, "delta_y": -80, "source": "hid_rawxy"},
                ))

        execute_action_mock.assert_called_once_with("app_expose")

    def test_owner_tagged_event_does_not_also_fire_hid_direction_action(self):
        """The generic gesture_up binding must not double-fire on an
        owner-tagged (event-tap) swipe — only the owner routing should."""
        engine = self._make_engine(self._cfg(
            gesture_up="app_expose",
            gesture_forward_up="mission_control",
        ))
        handlers = engine.hook.registered["gesture_swipe_up"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(self._owner_event("forward"))

        execute_action_mock.assert_called_once_with("mission_control")

    def test_no_owner_routing_registered_when_owners_empty(self):
        engine = self._make_engine(self._cfg(gesture_up="app_expose"))

        self.assertNotIn("gesture_swipe_down", engine.hook.registered)
        self.assertNotIn("gesture_swipe_left", engine.hook.registered)
        self.assertNotIn("gesture_swipe_right", engine.hook.registered)
        # gesture_swipe_up IS registered here, but only by the HID-direction path.
        self.assertEqual(len(engine.hook.registered["gesture_swipe_up"]), 1)


class EngineGestureArmingGateTests(unittest.TestCase):
    """Finding #1 (adversarial review, 2026-07-03): arming a per-button
    event-tap gesture must be gated by settings.gesture_owner_enabled AND
    device eligibility, not just by config bindings -- else the OFF switch
    has no runtime effect and a per-button gesture leaks onto a device that
    can't host it (e.g. config carried over to an MX Master)."""

    _MX_ANYWHERE_2S = SimpleNamespace(
        supported_buttons=(
            "middle", "xbutton1", "xbutton2",
            "gesture_forward_left", "gesture_forward_right",
            "gesture_forward_up", "gesture_forward_down",
        )
    )
    _MX_MASTER_3S = SimpleNamespace(supported_buttons=("middle", "xbutton1", "xbutton2"))

    def _cfg(self, enabled=None, **mapping_overrides):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"].update(mapping_overrides)
        if enabled is not None:
            cfg["settings"]["gesture_owner_enabled"] = dict(enabled)
        return cfg

    def _make_engine(self, cfg, device=None):
        from core.engine import Engine

        hook_cls = _connected_mouse_hook_cls(device) if device is not None else _FakeMouseHook
        with (
            patch("core.engine.MouseHook", hook_cls),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_bound_owner_stays_off_when_enable_toggle_is_off(self):
        cfg = self._cfg(enabled={"forward": False}, gesture_forward_up="mission_control")
        engine = self._make_engine(cfg, device=self._MX_ANYWHERE_2S)

        self.assertEqual(engine.hook._gesture_config["owners"], set())
        self.assertNotIn("gesture_swipe_up", engine.hook.registered)

    def test_bound_owner_stays_off_when_enable_flag_absent(self):
        # No settings.gesture_owner_enabled key at all -- default is off
        # (matches ui.backend "gesture mode off by default").
        cfg = self._cfg(gesture_forward_up="mission_control")
        engine = self._make_engine(cfg, device=self._MX_ANYWHERE_2S)

        self.assertEqual(engine.hook._gesture_config["owners"], set())

    def test_bound_and_enabled_owner_stays_off_with_no_device_connected(self):
        cfg = self._cfg(enabled={"forward": True}, gesture_forward_up="mission_control")
        engine = self._make_engine(cfg, device=None)

        self.assertEqual(engine.hook._gesture_config["owners"], set())

    def test_bound_and_enabled_owner_does_not_leak_onto_ineligible_device(self):
        # Regression: MX Master 3S has no per-button event-tap gesture support --
        # config carried over from another device must not arm it here.
        cfg = self._cfg(enabled={"forward": True}, gesture_forward_up="mission_control")
        engine = self._make_engine(cfg, device=self._MX_MASTER_3S)

        self.assertEqual(engine.hook._gesture_config["owners"], set())
        self.assertNotIn("gesture_swipe_up", engine.hook.registered)

    def test_bound_enabled_and_eligible_owner_arms(self):
        cfg = self._cfg(enabled={"forward": True}, gesture_forward_up="mission_control")
        engine = self._make_engine(cfg, device=self._MX_ANYWHERE_2S)

        self.assertEqual(engine.hook._gesture_config["owners"], {"forward"})
        self.assertIn("gesture_swipe_up", engine.hook.registered)

    def test_second_owner_off_does_not_block_first_owner_that_is_on(self):
        cfg = self._cfg(
            enabled={"forward": True, "back": False},
            gesture_forward_up="mission_control",
            gesture_back_up="app_expose",
        )
        engine = self._make_engine(cfg, device=_fully_eligible_device())

        self.assertEqual(engine.hook._gesture_config["owners"], {"forward"})


class EngineGestureRearmOnConnectTests(unittest.TestCase):
    """Hardware bugs A/B (fixed live, 2026-07): __init__'s _setup_hooks() runs
    before the device is connected, so _active_gesture_owners computes empty
    and nothing ever arms. _on_connection_change recomputes on the
    hid-features-ready rising edge -- and must reset_bindings() first so a
    second connect cycle doesn't stack a duplicate handler (the owner action
    firing 2-3x)."""

    _DEVICE = SimpleNamespace(
        supported_buttons=(
            "middle", "xbutton1", "xbutton2",
            "gesture_forward_left", "gesture_forward_right",
            "gesture_forward_up", "gesture_forward_down",
        )
    )

    def _cfg(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"]["gesture_forward_up"] = "mission_control"
        cfg["settings"]["gesture_owner_enabled"] = {"forward": True}
        return cfg

    def _make_engine(self):
        from core.engine import Engine

        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=self._cfg()),
        ):
            return Engine()

    def _connect_device(self, engine):
        engine.hook.connected_device = self._DEVICE
        engine.hook.device_connected = True
        engine.hook._hid_gesture = SimpleNamespace(connected_device=self._DEVICE)

    def _disconnect_device(self, engine):
        engine.hook.connected_device = None
        engine.hook.device_connected = False
        engine.hook._hid_gesture = SimpleNamespace(connected_device=None)

    @staticmethod
    def _thread_factory(instances):
        def factory(*args, **kwargs):
            thread = _RecordedThread(*args, **kwargs)
            instances.append(thread)
            return thread
        return factory

    def test_owner_arms_once_device_becomes_ready_after_construction(self):
        """Bug A: constructed with no device connected, the owner stays
        unarmed until a hid-features-ready connection-change recomputes it."""
        engine = self._make_engine()
        self.assertEqual(engine.hook._gesture_config["owners"], set())
        self.assertNotIn("gesture_swipe_up", engine.hook.registered)

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory([])):
            self._connect_device(engine)
            engine._on_connection_change(True)

        self.assertEqual(engine.hook._gesture_config["owners"], {"forward"})
        self.assertIn("gesture_swipe_up", engine.hook.registered)

    def test_reconnect_cycle_does_not_stack_duplicate_handlers(self):
        """Bug B: a disconnect/reconnect cycle must reset_bindings() before
        re-registering, so the owner action fires exactly once, not 2-3x."""
        engine = self._make_engine()
        threads = []

        with patch("core.engine.threading.Thread", side_effect=self._thread_factory(threads)):
            self._connect_device(engine)
            engine._on_connection_change(True)
            self._disconnect_device(engine)
            engine._on_connection_change(False)
            self._connect_device(engine)
            engine._on_connection_change(True)

        handlers = engine.hook.registered["gesture_swipe_up"]
        self.assertEqual(len(handlers), 1)

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(SimpleNamespace(
                    event_type=MouseEvent.GESTURE_SWIPE_UP,
                    raw_data={"delta_x": 0, "delta_y": -80, "source": "event_tap", "gesture_owner": "forward"},
                ))

        execute_action_mock.assert_called_once_with("mission_control")


class EngineTiltGestureTests(unittest.TestCase):
    """Tilt (horizontal-scroll) slide gestures: the engine feeds
    _active_tilt_owners to configure_gestures(tilt_owners=, tilt_release_ms=),
    gated the same way as button owners (bound direction + settings.
    gesture_owner_enabled + device eligibility, here on supports_tilt_gestures
    rather than supports_event_tap_gestures), and routes a gesture_swipe_<dir>
    event tagged gesture_owner="tilt_left"/"tilt_right" through the same
    owner_bindings dict as button owners. A tilt TAP arrives as a plain
    HSCROLL_LEFT/RIGHT event, already covered by EngineHorizontalScrollTests."""

    _TILT_ONLY_DEVICE = SimpleNamespace(
        supported_buttons=(
            "middle", "xbutton1", "xbutton2",
            "hscroll_left", "hscroll_right",
            "gesture_tilt_left_left", "gesture_tilt_left_right",
            "gesture_tilt_left_up", "gesture_tilt_left_down",
            "gesture_tilt_right_left", "gesture_tilt_right_right",
            "gesture_tilt_right_up", "gesture_tilt_right_down",
        )
    )
    # Per-button-event-tap eligible, but NOT tilt-eligible (no
    # supports_tilt_gestures) -- e.g. config carried over from an MX Anywhere 2S.
    _NO_TILT_DEVICE = SimpleNamespace(
        supported_buttons=(
            "middle", "xbutton1", "xbutton2",
            "gesture_forward_left", "gesture_forward_right",
            "gesture_forward_up", "gesture_forward_down",
        )
    )

    def _cfg(self, enabled=None, **mapping_overrides):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"].update(mapping_overrides)
        if enabled is not None:
            cfg["settings"]["gesture_owner_enabled"] = dict(enabled)
        return cfg

    def _make_engine(self, cfg, device=None):
        from core.engine import Engine

        hook_cls = _connected_mouse_hook_cls(device) if device is not None else _FakeMouseHook
        with (
            patch("core.engine.MouseHook", hook_cls),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_bound_enabled_and_eligible_tilt_owner_arms(self):
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)

        gesture_cfg = engine.hook._gesture_config
        self.assertEqual(gesture_cfg["tilt_owners"], {"tilt_left"})
        self.assertEqual(gesture_cfg["owners"], set())
        self.assertIs(gesture_cfg["enabled"], True)
        self.assertIn("gesture_swipe_up", engine.hook.registered)

    def test_tilt_owner_stays_off_when_enable_toggle_is_off(self):
        cfg = self._cfg(enabled={"tilt_left": False}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)

        self.assertEqual(engine.hook._gesture_config["tilt_owners"], set())
        self.assertNotIn("gesture_swipe_up", engine.hook.registered)

    def test_tilt_owner_stays_off_when_enable_flag_absent(self):
        # No settings.gesture_owner_enabled key at all -- default is off.
        cfg = self._cfg(gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)

        self.assertEqual(engine.hook._gesture_config["tilt_owners"], set())

    def test_tilt_owner_stays_off_with_no_device_connected(self):
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=None)

        self.assertEqual(engine.hook._gesture_config["tilt_owners"], set())

    def test_tilt_owner_does_not_leak_onto_non_tilt_eligible_device(self):
        # Regression: a device with per-button event-tap support but no
        # supports_tilt_gestures must not arm a tilt owner even if bound+enabled.
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._NO_TILT_DEVICE)

        self.assertEqual(engine.hook._gesture_config["tilt_owners"], set())
        self.assertNotIn("gesture_swipe_up", engine.hook.registered)

    def test_tilt_release_ms_threads_through_to_configure_gestures(self):
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        cfg["settings"]["tilt_gesture_release_ms"] = 250
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)

        self.assertEqual(engine.hook._gesture_config["tilt_release_ms"], 250)

    def test_tilt_release_ms_defaults_when_unset(self):
        from core.config import TILT_GESTURE_RELEASE_MS_DEFAULT

        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)

        self.assertEqual(
            engine.hook._gesture_config["tilt_release_ms"], TILT_GESTURE_RELEASE_MS_DEFAULT
        )

    def test_button_and_tilt_owners_do_not_cross_leak(self):
        """Regression: gesture_owners() returns the button+tilt union, so a
        device eligible for BOTH kinds with one owner of each bound+enabled
        must route each into its OWN configure_gestures() param, never mixed
        into the other's set."""
        cfg = self._cfg(
            enabled={"forward": True, "tilt_left": True},
            gesture_forward_up="mission_control",
            gesture_tilt_left_down="app_expose",
        )
        engine = self._make_engine(cfg, device=_fully_eligible_device_with_button_and_tilt())

        gesture_cfg = engine.hook._gesture_config
        self.assertEqual(gesture_cfg["owners"], {"forward"})
        self.assertEqual(gesture_cfg["tilt_owners"], {"tilt_left"})

    def test_tilt_swipe_tagged_event_routes_to_bound_action(self):
        """The tilt kernel fires gesture_swipe_<dir> tagged
        gesture_owner="tilt_left"/"tilt_right" on a slide -- routed by the
        same _make_owner_gesture_handler as button owners, keyed on
        gesture_tilt_left_up's bound action."""
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)
        handlers = engine.hook.registered["gesture_swipe_up"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(SimpleNamespace(
                    event_type=MouseEvent.GESTURE_SWIPE_UP,
                    raw_data={"delta_x": 80, "delta_y": 0, "source": "tilt", "gesture_owner": "tilt_left"},
                ))

        execute_action_mock.assert_called_once_with("mission_control")

    def test_tilt_owner_without_binding_for_direction_does_not_fire(self):
        # tilt_left only binds "up" -- a "down" swipe tagged tilt_left has no action.
        cfg = self._cfg(enabled={"tilt_left": True}, gesture_tilt_left_up="mission_control")
        engine = self._make_engine(cfg, device=self._TILT_ONLY_DEVICE)
        handlers = engine.hook.registered["gesture_swipe_down"]

        with patch("core.engine.execute_action") as execute_action_mock:
            for handler in handlers:
                handler(SimpleNamespace(
                    event_type=MouseEvent.GESTURE_SWIPE_DOWN,
                    raw_data={"delta_x": 0, "delta_y": 80, "source": "tilt", "gesture_owner": "tilt_left"},
                ))

        execute_action_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
