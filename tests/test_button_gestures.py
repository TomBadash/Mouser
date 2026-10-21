"""Tests for per-button slide gestures (back/forward/middle, all platforms).

Covers the config owner/binding logic, the shared BaseMouseHook arm/sample/
release flow (platform-agnostic), config migration seeding, and the engine
wiring that arms owners at the hook and routes swipe events to actions.
"""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import config as cfg_mod
from core.config import (
    DEFAULT_CONFIG,
    BUTTON_GESTURE_OWNERS,
    BUTTON_GESTURE_DIRECTION_KEYS,
    BUTTON_GESTURE_TAP_KEYS,
    button_gesture_owners,
    button_gesture_bindings_for,
    button_gesture_tap_action,
    _migrate,
)
from core.mouse_hook_base import BaseMouseHook


def _cfg_with(middle=None, mappings=None):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    m = cfg["profiles"]["default"]["mappings"]
    if mappings:
        m.update(mappings)
    return cfg


# ── Config: owner detection + bindings ──────────────────────────────────────

class ButtonGestureConfigTests(unittest.TestCase):
    def test_owner_is_gesture_swipe_sentinel(self):
        # normal action -> not an owner
        cfg = _cfg_with(mappings={"middle": "none"})
        self.assertEqual(button_gesture_owners(cfg), set())
        cfg = _cfg_with(mappings={"middle": "mouse_middle_click"})
        self.assertEqual(button_gesture_owners(cfg), set())
        # sentinel action -> owner (directions optional)
        cfg = _cfg_with(mappings={"middle": "gesture_swipe"})
        self.assertEqual(button_gesture_owners(cfg), {"middle"})

    def test_owner_gated_by_device_buttons(self):
        cfg = _cfg_with(mappings={
            "middle": "gesture_swipe", "xbutton1": "gesture_swipe",
        })
        self.assertEqual(button_gesture_owners(cfg), {"middle", "xbutton1"})
        # device only exposes middle -> xbutton1 dropped
        self.assertEqual(
            button_gesture_owners(cfg, device_buttons=("middle",)), {"middle"}
        )
        # device exposes neither -> empty
        self.assertEqual(
            button_gesture_owners(cfg, device_buttons=("left", "right")), set()
        )

    def test_two_buttons_independent(self):
        cfg = _cfg_with(mappings={
            "middle": "gesture_swipe", "middle_left": "next_tab",
            "xbutton2": "gesture_swipe", "xbutton2_right": "prev_tab",
        })
        self.assertEqual(button_gesture_owners(cfg), {"middle", "xbutton2"})
        self.assertEqual(
            button_gesture_bindings_for(cfg, "middle")["left"], "next_tab"
        )
        self.assertEqual(
            button_gesture_bindings_for(cfg, "xbutton2")["right"], "prev_tab"
        )

    def test_tap_action_helper(self):
        cfg = _cfg_with(mappings={
            "middle": "gesture_swipe", "middle_tap": "mouse_middle_click",
        })
        self.assertEqual(button_gesture_tap_action(cfg, "middle"),
                         "mouse_middle_click")
        self.assertEqual(button_gesture_tap_action(cfg, "xbutton1"), "none")

    def test_default_config_has_all_gesture_keys(self):
        m = DEFAULT_CONFIG["profiles"]["default"]["mappings"]
        for key in BUTTON_GESTURE_DIRECTION_KEYS + BUTTON_GESTURE_TAP_KEYS:
            self.assertIn(key, m)
            self.assertEqual(m[key], "none")

    def test_migration_seeds_gesture_keys(self):
        # An old config missing the keys gets them seeded to "none".
        old = {
            "version": 1,
            "active_profile": "default",
            "profiles": {"default": {"apps": [], "mappings": {"middle": "none"}}},
            "settings": {},
        }
        migrated = _migrate(old)
        m = migrated["profiles"]["default"]["mappings"]
        for key in BUTTON_GESTURE_DIRECTION_KEYS + BUTTON_GESTURE_TAP_KEYS:
            self.assertIn(key, m)

    def test_migration_preserves_existing_direction_binding(self):
        old = {
            "version": 1,
            "active_profile": "default",
            "profiles": {"default": {"apps": [],
                                     "mappings": {"middle_left": "next_tab"}}},
            "settings": {},
        }
        migrated = _migrate(old)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["middle_left"], "next_tab"
        )


# ── Shared base hook: arm / sample / release ────────────────────────────────

class BaseHookButtonGestureTests(unittest.TestCase):
    def _hook(self, owners=("middle", "xbutton1"), threshold=30):
        hook = BaseMouseHook()
        self.emitted = []
        hook._dispatch = lambda ev: self.emitted.append(ev)
        hook.configure_button_gestures(
            owners=set(owners), threshold=threshold,
            commit_window_ms=400, settle_ms=90, cross_ratio=0.5, timeout_ms=3000,
        )
        return hook

    def _slide(self, hook, owner, dx, dy, steps=12, t0=0.0):
        self.assertTrue(hook.arm_button_gesture(owner, now=t0))
        for i in range(steps):
            hook.sample_button_gesture(dx, dy, "os_motion", now=t0 + 0.01 * (i + 1))
        return hook.release_button_gesture(owner)

    def test_is_owner(self):
        hook = self._hook()
        self.assertTrue(hook.is_button_gesture_owner("middle"))
        self.assertFalse(hook.is_button_gesture_owner("xbutton2"))

    def test_slide_right_fires_tagged_event(self):
        hook = self._hook()
        result = self._slide(hook, "middle", 20, 0)
        self.assertEqual(result, "gesture")
        self.assertEqual(len(self.emitted), 1)
        self.assertEqual(self.emitted[0].event_type, "button_swipe_right")
        self.assertEqual(self.emitted[0].raw_data["gesture_owner"], "middle")

    def test_slide_up_fires_up(self):
        hook = self._hook()
        self._slide(hook, "xbutton1", 0, -20)
        self.assertEqual(self.emitted[0].event_type, "button_swipe_up")
        self.assertEqual(self.emitted[0].raw_data["gesture_owner"], "xbutton1")

    def test_tap_without_motion_emits_button_tap(self):
        hook = self._hook()
        self.assertTrue(hook.arm_button_gesture("middle", now=0.0))
        result = hook.release_button_gesture("middle")
        self.assertEqual(result, "click")
        # A tap emits a BUTTON_TAP event tagged with the owner (engine decides
        # whether an action is bound).
        self.assertEqual(len(self.emitted), 1)
        self.assertEqual(self.emitted[0].event_type, "button_tap")
        self.assertEqual(self.emitted[0].raw_data["gesture_owner"], "middle")

    def test_first_wins_arming(self):
        hook = self._hook()
        self.assertTrue(hook.arm_button_gesture("middle", now=0.0))
        self.assertFalse(hook.arm_button_gesture("xbutton1", now=0.0))
        self.assertEqual(hook._button_gesture_active_owner, "middle")

    def test_non_owner_cannot_arm(self):
        hook = self._hook(owners=("middle",))
        self.assertFalse(hook.arm_button_gesture("xbutton2", now=0.0))
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_release_wrong_owner_is_noop(self):
        hook = self._hook()
        hook.arm_button_gesture("middle", now=0.0)
        self.assertIsNone(hook.release_button_gesture("xbutton1"))
        self.assertEqual(hook._button_gesture_active_owner, "middle")

    def test_sample_when_idle_is_ignored(self):
        hook = self._hook()
        self.assertFalse(hook.sample_button_gesture(50, 0, "os_motion", now=0.0))

    def test_timeout_aborts_stuck_hold(self):
        hook = self._hook()
        hook.arm_button_gesture("middle", now=0.0)
        # A sample far past the timeout window aborts and stops consuming.
        consumed = hook.sample_button_gesture(20, 0, "os_motion", now=10.0)
        self.assertFalse(consumed)
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_abort_clears_state(self):
        hook = self._hook()
        hook.arm_button_gesture("middle", now=0.0)
        hook.abort_button_gesture("test")
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_configure_empty_disables_and_clears(self):
        hook = self._hook()
        hook.arm_button_gesture("middle", now=0.0)
        hook.configure_button_gestures(owners=set())
        self.assertFalse(hook._button_gesture_enabled)
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_mode_shift_hid_press_arms_gesture(self):
        # Mode shift is HID++ diverted: its press/release arm/release the gesture
        # via _on_hid_mode_shift_down/up (not an OS button), and the normal
        # MODE_SHIFT_DOWN event must NOT be dispatched while armed.
        hook = self._hook(owners=("mode_shift",))
        dispatched = []
        hook._dispatch = lambda ev: dispatched.append(ev.event_type)
        hook._on_hid_mode_shift_down()
        self.assertEqual(hook._button_gesture_active_owner, "mode_shift")
        self.assertEqual(dispatched, [])  # no MODE_SHIFT_DOWN
        hook._on_hid_mode_shift_up()
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_mode_shift_hid_press_normal_when_not_owner(self):
        # When mode shift is a normal button, presses dispatch MODE_SHIFT_DOWN/UP.
        hook = self._hook(owners=("middle",))
        dispatched = []
        hook._dispatch = lambda ev: dispatched.append(ev.event_type)
        hook._on_hid_mode_shift_down()
        hook._on_hid_mode_shift_up()
        self.assertEqual(dispatched, ["mode_shift_down", "mode_shift_up"])


# ── Engine: arms owners at the hook + routes swipe events ───────────────────

class _RecordingHook:
    """Minimal hook that records configure_button_gestures + registrations."""

    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False
        self._hid_gesture = None
        self.wheel_native_invert_active = False
        self.wheel_divert_active = False
        self.button_gesture_config = None
        self.registered = {}
        self.blocked = set()

    def set_debug_callback(self, cb): self._debug_callback = cb
    def set_gesture_callback(self, cb): self._gesture_callback = cb
    def set_status_callback(self, cb): self._status_callback = cb
    def set_connection_change_callback(self, cb): self._connection_change_callback = cb
    def set_battery_notify_callback(self, cb): self._battery_notify_callback = cb
    def configure_gestures(self, **kw): self._gesture_config = kw
    def configure_thumb_gestures(self, **kw): pass
    def configure_wheel_multipliers(self, v, h): return None
    def set_gesture_os_passthrough(self, *a, **kw): pass
    def set_thumb_os_passthrough(self, *a, **kw): pass

    def configure_button_gestures(self, **kw):
        self.button_gesture_config = kw

    def block(self, event_type): self.blocked.add(event_type)
    def register(self, event_type, cb): self.registered[event_type] = cb
    def reset_bindings(self):
        self.registered.clear()
        self.blocked.clear()
    def start(self): pass
    def stop(self): pass


class _FakeAppDetector:
    def __init__(self, callback): self.callback = callback
    def start(self): pass
    def stop(self): pass
    def set_profiles(self, *a, **kw): pass


class EngineButtonGestureWiringTests(unittest.TestCase):
    def _engine(self, mappings, supported_buttons):
        from core.engine import Engine
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"].update(mappings)
        with (
            patch("core.engine.MouseHook", _RecordingHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            engine = Engine()
        engine.hook.connected_device = SimpleNamespace(
            supported_buttons=supported_buttons
        )
        engine.hook.reset_bindings()
        engine._setup_hooks()
        return engine

    def test_owner_armed_and_handlers_registered(self):
        engine = self._engine(
            {"middle": "gesture_swipe", "middle_left": "next_tab"},
            supported_buttons=("middle", "xbutton1", "xbutton2"),
        )
        cfg = engine.hook.button_gesture_config
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["owners"], {"middle"})
        self.assertIn("button_swipe_left", engine.hook.registered)
        self.assertIn("button_tap", engine.hook.registered)

    def test_no_owner_when_device_lacks_button(self):
        engine = self._engine(
            {"middle": "gesture_swipe", "middle_left": "next_tab"},
            supported_buttons=("left", "right"),  # no middle
        )
        self.assertEqual(engine.hook.button_gesture_config["owners"], set())

    def test_swipe_event_routes_to_bound_action(self):
        engine = self._engine(
            {"middle": "gesture_swipe", "middle_left": "next_tab"},
            supported_buttons=("middle",),
        )
        handler = engine.hook.registered["button_swipe_left"]
        engine._enabled = True
        with patch.object(engine, "_dispatch_action") as dispatch:
            handler(SimpleNamespace(
                event_type="button_swipe_left",
                raw_data={"gesture_owner": "middle", "direction": "left"},
                timestamp=1.0,
            ))
        dispatch.assert_called_once_with("next_tab", "middle")

    def test_tap_event_routes_to_tap_action(self):
        engine = self._engine(
            {"middle": "gesture_swipe", "middle_tap": "mouse_middle_click"},
            supported_buttons=("middle",),
        )
        handler = engine.hook.registered["button_tap"]
        engine._enabled = True
        with patch.object(engine, "_dispatch_action") as dispatch:
            handler(SimpleNamespace(
                event_type="button_tap",
                raw_data={"gesture_owner": "middle"},
                timestamp=1.0,
            ))
        dispatch.assert_called_once_with("mouse_middle_click", "middle")

    def test_swipe_event_for_unbound_direction_does_nothing(self):
        engine = self._engine(
            {"middle": "gesture_swipe", "middle_left": "next_tab"},
            supported_buttons=("middle",),
        )
        handler = engine.hook.registered["button_swipe_up"]  # up is unbound
        engine._enabled = True
        with patch.object(engine, "_dispatch_action") as dispatch:
            handler(SimpleNamespace(
                event_type="button_swipe_up",
                raw_data={"gesture_owner": "middle", "direction": "up"},
                timestamp=1.0,
            ))
        dispatch.assert_not_called()

    def test_sentinel_button_gets_no_normal_handler(self):
        engine = self._engine(
            {"middle": "gesture_swipe"},
            supported_buttons=("middle",),
        )
        # The middle_down/up events must not be wired to a normal handler; the
        # hook owns them via arming.
        self.assertNotIn("middle_down", engine.hook.registered)


class EngineGestureSwipeHapticTests(unittest.TestCase):
    """The dedicated 'Gesture Swipe Feedback' pulse fires the moment a swipe
    direction is recognized, for any direction (bound or not), when the toggle
    is on — independent of the per-action / per-button haptic allowlists."""

    def _engine(self, mappings, *, via_sense=False,
                supported_buttons=("gesture",)):
        from core.engine import Engine
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["profiles"]["default"]["mappings"].update(mappings)
        with (
            patch("core.engine.MouseHook", _RecordingHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            engine = Engine()
        engine.hook.connected_device = SimpleNamespace(
            supported_buttons=supported_buttons,
            gesture_via_sense_panel=via_sense,
        )
        engine.hook.reset_bindings()
        engine._setup_hooks()
        return engine, cfg

    def test_observer_registered_on_all_directions_in_swipe_mode(self):
        engine, _ = self._engine({"gesture": "gesture_swipe"})
        for d in ("left", "right", "up", "down"):
            self.assertIn(f"gesture_swipe_{d}", engine.hook.registered)

    def test_thumb_swipe_observer_on_sense_panel_device(self):
        # MX Master 4: primary control is the Sense Panel; the thumb Gesture
        # button emits the gesture_swipe_* family.
        engine, _ = self._engine(
            {"gesture": "gesture_swipe"}, via_sense=True,
            supported_buttons=("gesture", "actions_ring"),
        )
        for d in ("left", "right", "up", "down"):
            self.assertIn(f"gesture_swipe_{d}", engine.hook.registered)

    def test_recognition_fires_pulse_when_enabled_even_if_unbound(self):
        engine, _ = self._engine({"gesture": "gesture_swipe"})  # up is unbound
        engine._enabled = True
        handler = engine.hook.registered["gesture_swipe_up"]
        with patch.object(engine, "_play_haptic_async") as ph:
            handler(SimpleNamespace(
                event_type="gesture_swipe_up", raw_data={}, timestamp=1.0))
        ph.assert_called_once_with(7)

    def test_no_pulse_when_toggle_off(self):
        engine, cfg = self._engine({"gesture": "gesture_swipe"})
        cfg["settings"]["gesture_swipe_haptic"] = False
        engine.cfg = cfg
        engine._enabled = True
        handler = engine.hook.registered["gesture_swipe_up"]
        with patch.object(engine, "_play_haptic_async") as ph:
            handler(SimpleNamespace(
                event_type="gesture_swipe_up", raw_data={}, timestamp=1.0))
        ph.assert_not_called()

    def test_no_pulse_when_engine_disabled(self):
        engine, _ = self._engine({"gesture": "gesture_swipe"})
        engine._enabled = False
        handler = engine.hook.registered["gesture_swipe_up"]
        with patch.object(engine, "_play_haptic_async") as ph:
            handler(SimpleNamespace(
                event_type="gesture_swipe_up", raw_data={}, timestamp=1.0))
        ph.assert_not_called()

    def test_no_observer_when_gesture_not_in_swipe_mode(self):
        engine, _ = self._engine({"gesture": "middle_click"})
        for d in ("left", "right", "up", "down"):
            self.assertNotIn(f"gesture_swipe_{d}", engine.hook.registered)


if __name__ == "__main__":
    unittest.main()
