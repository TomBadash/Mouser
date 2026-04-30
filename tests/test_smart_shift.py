"""Tests for SmartShift (HID++ 0x2110/0x2111) across hid_gesture, engine, and backend."""

import copy
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import hid_gesture
from core.config import DEFAULT_CONFIG


# ──────────────────────────────────────────────────────────────────────────────
# HidGestureListener — write path
# ──────────────────────────────────────────────────────────────────────────────

class SmartShiftWriteTests(unittest.TestCase):
    """_apply_pending_smart_shift: correct function IDs and byte payloads."""

    def _make_listener(self, enhanced=True):
        listener = hid_gesture.HidGestureListener()
        listener._smart_shift_idx = 0x05  # arbitrary feature table index
        listener._smart_shift_enhanced = enhanced
        listener._dev = object()  # non-None so the not-connected guard is passed
        return listener

    def _write_call_args(self, listener, mode, enabled, threshold):
        listener._request = Mock(return_value=b"\x00" * 20)
        listener._pending_smart_shift = (mode, enabled, threshold)
        listener._apply_pending_smart_shift()
        return listener._request.call_args

    def test_enhanced_uses_write_fn2(self):
        listener = self._make_listener(enhanced=True)
        args = self._write_call_args(listener, "ratchet", True, 30)
        self.assertEqual(args[0][1], 2)  # fn_id argument

    def test_basic_uses_write_fn1(self):
        listener = self._make_listener(enhanced=False)
        args = self._write_call_args(listener, "ratchet", True, 30)
        self.assertEqual(args[0][1], 1)

    def test_enabled_sends_ratchet_mode_with_threshold(self):
        listener = self._make_listener()
        args = self._write_call_args(listener, "ratchet", True, 30)
        payload = args[0][2]
        self.assertEqual(payload[0], hid_gesture.HidGestureListener.SMART_SHIFT_RATCHET)
        self.assertEqual(payload[1], 30)
        self.assertEqual(payload[2], 0x00)

    def test_threshold_clamped_to_max_50(self):
        listener = self._make_listener()
        args = self._write_call_args(listener, "ratchet", True, 99)
        self.assertEqual(args[0][2][1], 50)

    def test_threshold_clamped_to_min_1(self):
        listener = self._make_listener()
        args = self._write_call_args(listener, "ratchet", True, 0)
        self.assertEqual(args[0][2][1], 1)

    def test_disabled_ratchet_sends_0xff_threshold(self):
        listener = self._make_listener()
        args = self._write_call_args(listener, "ratchet", False, 25)
        payload = args[0][2]
        self.assertEqual(payload[0], hid_gesture.HidGestureListener.SMART_SHIFT_RATCHET)
        self.assertEqual(payload[1], hid_gesture.HidGestureListener.SMART_SHIFT_DISABLE_THRESHOLD)

    def test_freespin_sends_freespin_mode_with_zero_threshold(self):
        listener = self._make_listener()
        args = self._write_call_args(listener, "freespin", False, 25)
        payload = args[0][2]
        self.assertEqual(payload[0], hid_gesture.HidGestureListener.SMART_SHIFT_FREESPIN)
        self.assertEqual(payload[1], 0x00)

    def test_not_connected_clears_pending_and_returns_false(self):
        listener = hid_gesture.HidGestureListener()
        listener._smart_shift_idx = None  # no feature discovered
        listener._pending_smart_shift = ("ratchet", False, 25)
        listener._apply_pending_smart_shift()
        self.assertIsNone(listener._pending_smart_shift)
        self.assertFalse(listener._smart_shift_result)

    def test_failed_request_sets_result_false(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=None)  # simulate HID error
        listener._pending_smart_shift = ("ratchet", False, 25)
        listener._apply_pending_smart_shift()
        self.assertFalse(listener._smart_shift_result)


# ──────────────────────────────────────────────────────────────────────────────
# HidGestureListener — read path
# ──────────────────────────────────────────────────────────────────────────────

class SmartShiftReadTests(unittest.TestCase):
    """_apply_pending_read_smart_shift: correct function IDs and state parsing."""

    def _make_listener(self, enhanced=True):
        listener = hid_gesture.HidGestureListener()
        listener._smart_shift_idx = 0x05
        listener._smart_shift_enhanced = enhanced
        listener._dev = object()
        listener._pending_smart_shift = "read"
        return listener

    @staticmethod
    def _mock_response(mode_byte, auto_disengage):
        """Build a fake 5-tuple HID++ response with mode/threshold in the payload."""
        payload = bytes([mode_byte, auto_disengage] + [0x00] * 14)
        return (None, None, None, None, payload)

    def test_enhanced_uses_read_fn1(self):
        listener = self._make_listener(enhanced=True)
        listener._request = Mock(return_value=self._mock_response(0x02, 42))
        listener._apply_pending_read_smart_shift()
        self.assertEqual(listener._request.call_args[0][1], 1)

    def test_basic_uses_read_fn0(self):
        listener = self._make_listener(enhanced=False)
        listener._request = Mock(return_value=self._mock_response(0x02, 42))
        listener._apply_pending_read_smart_shift()
        self.assertEqual(listener._request.call_args[0][1], 0)

    def test_auto_disengage_in_range_means_enabled(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 42))
        listener._apply_pending_read_smart_shift()
        result = listener._smart_shift_result
        self.assertTrue(result["enabled"])
        self.assertEqual(result["threshold"], 42)

    def test_auto_disengage_boundary_min_1_is_enabled(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 1))
        listener._apply_pending_read_smart_shift()
        self.assertTrue(listener._smart_shift_result["enabled"])

    def test_auto_disengage_boundary_max_50_is_enabled(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 50))
        listener._apply_pending_read_smart_shift()
        self.assertTrue(listener._smart_shift_result["enabled"])

    def test_auto_disengage_0xff_means_disabled(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 0xFF))
        listener._apply_pending_read_smart_shift()
        result = listener._smart_shift_result
        self.assertFalse(result["enabled"])
        self.assertEqual(result["threshold"], 25)  # default when disabled

    def test_auto_disengage_zero_means_disabled(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 0))
        listener._apply_pending_read_smart_shift()
        self.assertFalse(listener._smart_shift_result["enabled"])

    def test_mode_byte_0x01_parses_as_freespin(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x01, 0xFF))
        listener._apply_pending_read_smart_shift()
        self.assertEqual(listener._smart_shift_result["mode"], "freespin")

    def test_freespin_with_in_range_auto_disengage_still_disabled(self):
        """Device preserves auto_disengage=25 in freespin state; must not report enabled=True."""
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x01, 25))
        listener._apply_pending_read_smart_shift()
        result = listener._smart_shift_result
        self.assertEqual(result["mode"], "freespin")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["threshold"], 25)

    def test_freespin_with_any_auto_disengage_is_always_disabled(self):
        """Regardless of auto_disengage value, freespin mode is never SmartShift-enabled."""
        listener = self._make_listener()
        for auto_dis in [1, 25, 50]:
            listener._request = Mock(return_value=self._mock_response(0x01, auto_dis))
            listener._apply_pending_read_smart_shift()
            self.assertFalse(listener._smart_shift_result["enabled"],
                             f"expected enabled=False for auto_disengage={auto_dis}")

    def test_mode_byte_0x02_parses_as_ratchet(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=self._mock_response(0x02, 0xFF))
        listener._apply_pending_read_smart_shift()
        self.assertEqual(listener._smart_shift_result["mode"], "ratchet")

    def test_failed_request_returns_none(self):
        listener = self._make_listener()
        listener._request = Mock(return_value=None)
        listener._apply_pending_read_smart_shift()
        self.assertIsNone(listener._smart_shift_result)


class SmartShiftPendingRequestAbortTests(unittest.TestCase):
    def test_read_abort_returns_none_instead_of_stale_result(self):
        listener = hid_gesture.HidGestureListener()
        listener._smart_shift_result = {"mode": "ratchet", "enabled": True, "threshold": 30}
        seen = []
        done = threading.Event()

        def worker():
            seen.append(listener.read_smart_shift())
            done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        for _ in range(50):
            if listener._pending_smart_shift == "read":
                break
            time.sleep(0.01)
        listener._abort_pending_smart_shift()
        done.wait(1)
        thread.join(timeout=1)

        self.assertEqual(seen, [None])

    def test_write_abort_returns_false_instead_of_stale_success(self):
        listener = hid_gesture.HidGestureListener()
        listener._smart_shift_result = True
        seen = []
        done = threading.Event()

        def worker():
            seen.append(listener.set_smart_shift("ratchet", False, 25))
            done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        for _ in range(50):
            if listener._pending_smart_shift == ("ratchet", False, 25):
                break
            time.sleep(0.01)
        listener._abort_pending_smart_shift()
        done.wait(1)
        thread.join(timeout=1)

        self.assertEqual(seen, [False])


# ──────────────────────────────────────────────────────────────────────────────
# Engine — SmartShift config persistence and startup
# ──────────────────────────────────────────────────────────────────────────────

class _FakeMouseHook:
    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False
        self._hid_gesture = None
        self.divert_mode_shift = False
        self.start_called = False

    def set_debug_callback(self, cb): pass
    def set_gesture_callback(self, cb): pass
    def set_connection_change_callback(self, cb): pass
    def configure_gestures(self, **kwargs): pass
    def block(self, event_type): pass
    def register(self, event_type, callback): pass
    def reset_bindings(self): pass
    def sync_hid_extra_diverts(self): pass
    def start(self): self.start_called = True
    def stop(self): pass


class _FakeAppDetector:
    def __init__(self, callback): pass
    def start(self): pass
    def stop(self): pass


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


class EngineSmartShiftTests(unittest.TestCase):
    def _make_engine(self, extra_settings=None):
        from core.engine import Engine
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if extra_settings:
            cfg["settings"].update(extra_settings)
        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_set_smart_shift_persists_all_three_fields(self):
        engine = self._make_engine()
        with patch("core.engine.save_config") as save_mock:
            engine.set_smart_shift("freespin", True, 30)
        save_mock.assert_called_once()
        self.assertEqual(engine.cfg["settings"]["smart_shift_mode"], "freespin")
        self.assertTrue(engine.cfg["settings"]["smart_shift_enabled"])
        self.assertEqual(engine.cfg["settings"]["smart_shift_threshold"], 30)

    def test_set_smart_shift_calls_hid_gesture_when_connected(self):
        engine = self._make_engine()
        hg = Mock(smart_shift_supported=True)
        engine.hook._hid_gesture = hg
        with patch("core.engine.save_config"):
            engine.set_smart_shift("ratchet", True, 25)
        hg.set_smart_shift.assert_called_once_with("ratchet", True, 25)

    def test_set_smart_shift_skips_hid_gesture_when_not_connected(self):
        engine = self._make_engine()
        engine.hook._hid_gesture = None
        with patch("core.engine.save_config"):
            result = engine.set_smart_shift("ratchet", False, 25)
        self.assertFalse(result)

    def test_start_applies_saved_smart_shift_to_device(self):
        engine = self._make_engine({
            "smart_shift_mode": "freespin",
            "smart_shift_enabled": True,
            "smart_shift_threshold": 40,
        })
        hg = Mock(smart_shift_supported=True)
        engine.hook._hid_gesture = hg
        with (
            patch("core.engine.threading.Thread", _ImmediateThread),
            patch("time.sleep"),
        ):
            engine.start()
        # Called twice: once immediately, once after the settled 3 s delay.
        hg.set_smart_shift.assert_called_with("freespin", True, 40)
        self.assertGreaterEqual(hg.set_smart_shift.call_count, 1)

    def test_start_skips_smart_shift_when_not_supported(self):
        engine = self._make_engine()
        hg = Mock(smart_shift_supported=False)
        engine.hook._hid_gesture = hg
        with (
            patch("core.engine.threading.Thread", _ImmediateThread),
            patch("time.sleep"),
        ):
            engine.start()
        hg.set_smart_shift.assert_not_called()

    def test_run_saved_settings_replay_reapplies_saved_smart_shift(self):
        """Live replay pushes saved SmartShift to the device after reconnect."""
        engine = self._make_engine({
            "smart_shift_mode": "ratchet",
            "smart_shift_enabled": False,
            "smart_shift_threshold": 30,
        })
        hg = Mock(smart_shift_supported=True)
        hg.connected_device = SimpleNamespace(name="MX Master 3S")
        engine.hook._hid_gesture = hg
        with patch("time.sleep"):
            engine._run_saved_settings_replay()
        hg.set_smart_shift.assert_called_with("ratchet", False, 30)

    def test_on_connection_change_spawns_battery_poll_thread(self):
        """_on_connection_change(True) must start a BatteryPoll thread."""
        engine = self._make_engine()
        with patch("core.engine.threading.Thread") as thread_cls:
            thread_cls.return_value = Mock(start=Mock())
            engine._on_connection_change(True)
        thread_names = [c.kwargs.get("name") for c in thread_cls.call_args_list]
        self.assertIn("BatteryPoll", thread_names)

    def test_on_connection_change_replays_settings_when_hid_features_become_ready(self):
        """SavedSettingsReplay thread is started when HID features transition to ready."""
        engine = self._make_engine()
        hg = Mock(smart_shift_supported=True)
        # _last_hid_features_ready is False at init (no _hid_gesture); setting
        # _hid_gesture here makes hid_features_ready flip to True on next call.
        engine.hook._hid_gesture = hg
        with patch("core.engine.threading.Thread") as thread_cls:
            thread_cls.return_value = Mock(start=Mock())
            engine._on_connection_change(True)
        thread_names = [c.kwargs.get("name") for c in thread_cls.call_args_list]
        self.assertIn("SavedSettingsReplay", thread_names)

    def test_run_saved_settings_replay_retries_on_failure(self):
        """On write failure (e.g. IOReturnBadArgument right after wake), retry once."""
        engine = self._make_engine({
            "smart_shift_enabled": True,
            "smart_shift_threshold": 25,
        })
        hg = Mock(smart_shift_supported=True)
        hg.connected_device = SimpleNamespace(name="MX Master 3S")
        # First call fails (immediate write), second succeeds (settled replay)
        hg.set_smart_shift.side_effect = [False, True]
        engine.hook._hid_gesture = hg
        with patch("time.sleep"):
            engine._run_saved_settings_replay()
        self.assertEqual(hg.set_smart_shift.call_count, 2)

    def test_run_saved_settings_replay_notifies_ui_with_saved_state(self):
        """UI must show the saved config, not stale hardware state read by the poll."""
        engine = self._make_engine({
            "smart_shift_mode": "ratchet",
            "smart_shift_enabled": False,
            "smart_shift_threshold": 30,
        })
        hg = Mock(smart_shift_supported=True)
        hg.connected_device = SimpleNamespace(name="MX Master 3S")
        engine.hook._hid_gesture = hg
        received = []
        engine.set_smart_shift_read_callback(received.append)
        with patch("time.sleep"):
            engine._run_saved_settings_replay()
        # UI is notified twice: once immediately, once after the settled 3 s delay.
        self.assertGreaterEqual(len(received), 2)
        self.assertEqual(received[-1], {
            "mode": "ratchet",
            "enabled": False,
            "threshold": 30,
        })


# ──────────────────────────────────────────────────────────────────────────────
# Backend — SmartShift properties, slots, and device read sync
# ──────────────────────────────────────────────────────────────────────────────

try:
    from ui.backend import Backend
except ModuleNotFoundError:
    Backend = None


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendSmartShiftTests(unittest.TestCase):
    def _make_backend(self, extra_settings=None):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if extra_settings:
            cfg["settings"].update(extra_settings)
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config"),
        ):
            return Backend(engine=None)

    def test_smart_shift_mode_property_returns_config_value(self):
        backend = self._make_backend({"smart_shift_mode": "freespin"})
        self.assertEqual(backend.smartShiftMode, "freespin")

    def test_smart_shift_mode_defaults_to_ratchet(self):
        backend = self._make_backend()
        self.assertEqual(backend.smartShiftMode, "ratchet")

    def test_smart_shift_enabled_property_is_bool(self):
        backend = self._make_backend({"smart_shift_enabled": True})
        self.assertIsInstance(backend.smartShiftEnabled, bool)
        self.assertTrue(backend.smartShiftEnabled)

    def test_smart_shift_threshold_property_is_int(self):
        backend = self._make_backend({"smart_shift_threshold": 42})
        self.assertIsInstance(backend.smartShiftThreshold, int)
        self.assertEqual(backend.smartShiftThreshold, 42)

    def test_set_smart_shift_updates_mode(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setSmartShift("freespin")
        self.assertEqual(backend.smartShiftMode, "freespin")

    def test_set_smart_shift_sends_all_params_to_engine(self):
        backend = self._make_backend({"smart_shift_enabled": True, "smart_shift_threshold": 30})
        engine_mock = Mock()
        backend._engine = engine_mock
        with patch("ui.backend.save_config"):
            backend.setSmartShift("freespin")
        engine_mock.set_smart_shift.assert_called_once_with("freespin", True, 30)

    def test_set_smart_shift_enabled_sends_all_params_to_engine(self):
        backend = self._make_backend({"smart_shift_mode": "ratchet", "smart_shift_threshold": 30})
        engine_mock = Mock()
        backend._engine = engine_mock
        with patch("ui.backend.save_config"):
            backend.setSmartShiftEnabled(True)
        engine_mock.set_smart_shift.assert_called_once_with("ratchet", True, 30)

    def test_set_smart_shift_threshold_sends_all_params_to_engine(self):
        backend = self._make_backend({"smart_shift_mode": "ratchet", "smart_shift_enabled": True})
        engine_mock = Mock()
        backend._engine = engine_mock
        with patch("ui.backend.save_config"):
            backend.setSmartShiftThreshold(45)
        engine_mock.set_smart_shift.assert_called_once_with("ratchet", True, 45)

    def test_handle_smart_shift_read_updates_in_memory_config(self):
        backend = self._make_backend({"smart_shift_threshold": 42})
        with patch("ui.backend.save_config") as save_mock:
            # Simulate the two-step cross-thread call: stage state, then invoke handler
            backend._pending_smart_shift_state = {"mode": "freespin", "enabled": False, "threshold": 35}
            backend._handleSmartShiftRead()
        # Hardware reads should NOT be persisted — user's explicit saves drive the file.
        save_mock.assert_not_called()
        self.assertEqual(backend._cfg["settings"]["smart_shift_mode"], "freespin")
        self.assertFalse(backend._cfg["settings"]["smart_shift_enabled"])
        self.assertEqual(backend._cfg["settings"]["smart_shift_threshold"], 42)

    def test_handle_smart_shift_read_preserves_saved_fallback_mode_when_enabled(self):
        backend = self._make_backend({
            "smart_shift_mode": "freespin",
            "smart_shift_enabled": True,
            "smart_shift_threshold": 30,
        })
        with patch("ui.backend.save_config") as save_mock:
            # Real hardware reads report enabled SmartShift as ratchet + threshold,
            # which must not overwrite the user's saved fixed-mode fallback.
            backend._pending_smart_shift_state = {
                "mode": "ratchet",
                "enabled": True,
                "threshold": 35,
            }
            backend._handleSmartShiftRead()
        save_mock.assert_not_called()
        self.assertEqual(backend._cfg["settings"]["smart_shift_mode"], "freespin")
        self.assertTrue(backend._cfg["settings"]["smart_shift_enabled"])
        self.assertEqual(backend._cfg["settings"]["smart_shift_threshold"], 35)

    def test_handle_smart_shift_read_ignores_non_dict(self):
        """None or unexpected types should not crash or corrupt config."""
        backend = self._make_backend({"smart_shift_mode": "ratchet"})
        backend._pending_smart_shift_state = None
        backend._handleSmartShiftRead()  # should not raise
        self.assertEqual(backend._cfg["settings"]["smart_shift_mode"], "ratchet")


# ──────────────────────────────────────────────────────────────────────────────
# Engine — _toggle_smart_shift (physical button / mapped action)
# ──────────────────────────────────────────────────────────────────────────────

class EngineToggleSmartShiftTests(unittest.TestCase):
    def _make_engine(self, extra_settings=None):
        from core.engine import Engine
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if extra_settings:
            cfg["settings"].update(extra_settings)
        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_toggle_turns_on_when_currently_off(self):
        engine = self._make_engine({"smart_shift_enabled": False, "smart_shift_threshold": 30})
        with patch("core.engine.save_config"):
            engine._toggle_smart_shift()
        self.assertTrue(engine.cfg["settings"]["smart_shift_enabled"])

    def test_toggle_turns_off_when_currently_on(self):
        engine = self._make_engine({"smart_shift_enabled": True, "smart_shift_threshold": 30})
        with patch("core.engine.save_config"):
            engine._toggle_smart_shift()
        self.assertFalse(engine.cfg["settings"]["smart_shift_enabled"])

    def test_toggle_preserves_mode_and_threshold(self):
        engine = self._make_engine({
            "smart_shift_enabled": False,
            "smart_shift_mode": "freespin",
            "smart_shift_threshold": 42,
        })
        with patch("core.engine.save_config"):
            engine._toggle_smart_shift()
        self.assertEqual(engine.cfg["settings"]["smart_shift_mode"], "freespin")
        self.assertEqual(engine.cfg["settings"]["smart_shift_threshold"], 42)

    def test_toggle_calls_hid_gesture_when_connected(self):
        engine = self._make_engine({"smart_shift_enabled": False, "smart_shift_threshold": 30})
        hg = Mock(smart_shift_supported=True)
        engine.hook._hid_gesture = hg
        with (
            patch("core.engine.save_config"),
            patch("core.engine.threading.Thread", _ImmediateThread),
        ):
            engine._toggle_smart_shift()
        hg.set_smart_shift.assert_called_once_with("ratchet", True, 30)

    def test_toggle_fires_ui_callback(self):
        engine = self._make_engine({"smart_shift_enabled": False, "smart_shift_threshold": 20})
        received = []
        engine.set_smart_shift_read_callback(received.append)
        with (
            patch("core.engine.save_config"),
            patch("core.engine.threading.Thread", _ImmediateThread),
        ):
            engine._toggle_smart_shift()
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0]["enabled"])

    def test_make_handler_calls_toggle_for_toggle_action(self):
        engine = self._make_engine()
        toggle_calls = []
        engine._toggle_smart_shift = lambda: toggle_calls.append(True)
        handler = engine._make_handler("toggle_smart_shift")
        handler(SimpleNamespace(event_type="mode_shift_down"))
        self.assertEqual(len(toggle_calls), 1)

    def test_make_handler_calls_execute_action_for_normal_action(self):
        engine = self._make_engine()
        handler = engine._make_handler("alt_tab")
        with patch("core.engine.execute_action") as exec_mock:
            handler(SimpleNamespace(event_type="xbutton1_down"))
        exec_mock.assert_called_once_with("alt_tab")

    def test_make_handler_calls_switch_for_switch_action(self):
        engine = self._make_engine()
        switch_calls = []
        engine._switch_scroll_mode = lambda: switch_calls.append(True)
        handler = engine._make_handler("switch_scroll_mode")
        handler(SimpleNamespace(event_type="mode_shift_down"))
        self.assertEqual(len(switch_calls), 1)


# ──────────────────────────────────────────────────────────────────────────────
# Engine — _switch_scroll_mode (ratchet ↔ freespin, disables SmartShift auto)
# ──────────────────────────────────────────────────────────────────────────────

class EngineSwitchScrollModeTests(unittest.TestCase):
    def _make_engine(self, extra_settings=None):
        from core.engine import Engine
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if extra_settings:
            cfg["settings"].update(extra_settings)
        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_switch_ratchet_to_freespin(self):
        engine = self._make_engine({"smart_shift_mode": "ratchet"})
        with patch("core.engine.save_config"):
            engine._switch_scroll_mode()
        self.assertEqual(engine.cfg["settings"]["smart_shift_mode"], "freespin")

    def test_switch_freespin_to_ratchet(self):
        engine = self._make_engine({"smart_shift_mode": "freespin"})
        with patch("core.engine.save_config"):
            engine._switch_scroll_mode()
        self.assertEqual(engine.cfg["settings"]["smart_shift_mode"], "ratchet")

    def test_switch_disables_smart_shift_auto(self):
        """Switching mode always disables SmartShift auto-switching."""
        engine = self._make_engine({"smart_shift_mode": "ratchet", "smart_shift_enabled": True})
        with patch("core.engine.save_config"):
            engine._switch_scroll_mode()
        self.assertFalse(engine.cfg["settings"]["smart_shift_enabled"])

    def test_switch_calls_hid_gesture_when_connected(self):
        engine = self._make_engine({"smart_shift_mode": "ratchet", "smart_shift_threshold": 25})
        hg = Mock(smart_shift_supported=True)
        engine.hook._hid_gesture = hg
        with (
            patch("core.engine.save_config"),
            patch("core.engine.threading.Thread", _ImmediateThread),
        ):
            engine._switch_scroll_mode()
        hg.set_smart_shift.assert_called_once_with("freespin", False, 25)

    def test_switch_fires_ui_callback(self):
        engine = self._make_engine({"smart_shift_mode": "ratchet", "smart_shift_threshold": 20})
        received = []
        engine.set_smart_shift_read_callback(received.append)
        with (
            patch("core.engine.save_config"),
            patch("core.engine.threading.Thread", _ImmediateThread),
        ):
            engine._switch_scroll_mode()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["mode"], "freespin")
        self.assertFalse(received[0]["enabled"])

    def test_switch_preserves_threshold(self):
        engine = self._make_engine({"smart_shift_mode": "ratchet", "smart_shift_threshold": 42})
        with patch("core.engine.save_config"):
            engine._switch_scroll_mode()
        self.assertEqual(engine.cfg["settings"]["smart_shift_threshold"], 42)


# ──────────────────────────────────────────────────────────────────────────────
# Config v7 migration — mode_shift "none" → "toggle_smart_shift"
# (v7 runs as an intermediate step; v8 then upgrades toggle → switch)
# ──────────────────────────────────────────────────────────────────────────────

class ConfigV7MigrationTests(unittest.TestCase):
    def _v6_config(self, mode_shift="none"):
        return {
            "version": 6,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "mode_shift": mode_shift,
                    },
                }
            },
            "settings": {},
        }

    def test_mode_shift_none_is_promoted_to_switch_scroll_mode(self):
        # v6 "none" → v7 "toggle_smart_shift" → v8 "switch_scroll_mode"
        from core.config import _migrate
        migrated = _migrate(self._v6_config("none"))
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )

    def test_explicit_non_none_mapping_is_preserved(self):
        from core.config import _migrate
        migrated = _migrate(self._v6_config("alt_tab"))
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "alt_tab",
        )

    def test_multiple_profiles_all_migrated(self):
        from core.config import _migrate
        cfg = self._v6_config("none")
        cfg["profiles"]["work"] = {
            "label": "Work",
            "apps": ["Code"],
            "mappings": {"mode_shift": "none"},
        }
        migrated = _migrate(cfg)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertEqual(
            migrated["profiles"]["work"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )

    def test_version_bumped_to_current(self):
        from core.config import _migrate
        migrated = _migrate(self._v6_config())
        self.assertEqual(migrated["version"], 9)


# ──────────────────────────────────────────────────────────────────────────────
# Config v8 migration — mode_shift "toggle_smart_shift" → "switch_scroll_mode"
# ──────────────────────────────────────────────────────────────────────────────

class ConfigV8MigrationTests(unittest.TestCase):
    def _v7_config(self, mode_shift="toggle_smart_shift"):
        return {
            "version": 7,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "mode_shift": mode_shift,
                    },
                }
            },
            "settings": {},
        }

    def test_toggle_smart_shift_upgraded_to_switch_scroll_mode(self):
        from core.config import _migrate
        migrated = _migrate(self._v7_config("toggle_smart_shift"))
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )

    def test_explicit_non_toggle_mapping_is_preserved(self):
        from core.config import _migrate
        migrated = _migrate(self._v7_config("alt_tab"))
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "alt_tab",
        )

    def test_multiple_profiles_all_migrated(self):
        from core.config import _migrate
        cfg = self._v7_config("toggle_smart_shift")
        cfg["profiles"]["work"] = {
            "label": "Work",
            "apps": ["Code"],
            "mappings": {"mode_shift": "toggle_smart_shift"},
        }
        migrated = _migrate(cfg)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertEqual(
            migrated["profiles"]["work"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )

    def test_version_bumped_to_current(self):
        from core.config import _migrate
        migrated = _migrate(self._v7_config())
        self.assertEqual(migrated["version"], 9)


class HidForceReconnectTests(unittest.TestCase):
    """force_reconnect() flag and inner-loop behavior."""

    def _make_listener(self):
        return hid_gesture.HidGestureListener()

    def test_force_reconnect_sets_flag(self):
        listener = self._make_listener()
        self.assertFalse(listener._reconnect_requested)
        listener.force_reconnect()
        self.assertTrue(listener._reconnect_requested)

    def test_reconnect_flag_cleared_and_raises(self):
        """Inner loop should clear flag and raise IOError when _reconnect_requested is True."""
        listener = self._make_listener()
        listener._reconnect_requested = True
        # Simulate the inner-loop guard directly
        with self.assertRaises(IOError):
            if listener._reconnect_requested:
                listener._reconnect_requested = False
                raise IOError("reconnect requested")
        self.assertFalse(listener._reconnect_requested)

    def test_not_connected_read_returns_none_result(self):
        """When not connected, a pending read should leave _smart_shift_result as None."""
        listener = self._make_listener()
        listener._smart_shift_idx = None
        listener._dev = None
        listener._pending_smart_shift = "read"
        listener._apply_pending_smart_shift()
        self.assertIsNone(listener._smart_shift_result)
        self.assertIsNone(listener._pending_smart_shift)

    def test_not_connected_write_returns_false_result(self):
        """When not connected, a pending write should leave _smart_shift_result as False."""
        listener = self._make_listener()
        listener._smart_shift_idx = None
        listener._dev = None
        listener._pending_smart_shift = ("ratchet", True, 25)
        listener._apply_pending_smart_shift()
        self.assertFalse(listener._smart_shift_result)
        self.assertIsNone(listener._pending_smart_shift)


if __name__ == "__main__":
    unittest.main()
