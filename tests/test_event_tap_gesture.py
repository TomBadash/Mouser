"""Issue 003 — event-tap gesture activation kernel.

Exercises the pure, objc-free decision helpers that the macOS CGEventTap handler
calls: the click-vs-gesture release decision (`decide_gesture`) and the
first-wins arming gate (`should_arm_gesture`). The native tap wiring is verified
on real hardware (issue 007); these tests pin the logic that decides it.

Also covers the stateful hook transitions (arming / release / abort, finding #4
of the 2026-07-03 adversarial review) via a tiny fake-Quartz harness: real
core.mouse_hook_macos is imported against a minimal fake objc/Quartz so the
actual callback code runs, objc-free, in this sandbox.
"""

import importlib
import sys
import time
import types
import unittest

from core.mouse_hook_base import CLICK, GESTURE, decide_gesture, should_arm_gesture
from core.mouse_hook_types import MouseEvent

# The engine's default gesture tuning (core/config.py DEFAULT_CONFIG settings).
_THRESHOLD = 50.0
_DEADZONE = 40.0
_FLOOR_MS = 80


class DecideGestureTests(unittest.TestCase):
    def test_quick_tap_no_movement_is_a_click(self):
        decision, direction = decide_gesture(
            held_ms=200, dx=0, dy=0,
            hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
        )
        self.assertEqual(decision, CLICK)
        self.assertIsNone(direction)

    def test_sub_deadzone_micro_drift_is_a_click(self):
        # Held well past the floor, but the slide never clears the threshold.
        decision, direction = decide_gesture(
            held_ms=250, dx=12, dy=7,
            hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
        )
        self.assertEqual(decision, CLICK)
        self.assertIsNone(direction)

    def test_fast_flick_below_hold_floor_is_a_click(self):
        # A big slide, but released before the hold floor — must NOT misfire (D4).
        decision, direction = decide_gesture(
            held_ms=40, dx=0, dy=-200,
            hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
        )
        self.assertEqual(decision, CLICK)
        self.assertIsNone(direction)

    def test_clean_four_way_gestures_detect_the_direction(self):
        cases = {
            (0, -120): MouseEvent.GESTURE_SWIPE_UP,
            (0, 120): MouseEvent.GESTURE_SWIPE_DOWN,
            (-120, 0): MouseEvent.GESTURE_SWIPE_LEFT,
            (120, 0): MouseEvent.GESTURE_SWIPE_RIGHT,
        }
        for (dx, dy), expected in cases.items():
            with self.subTest(dx=dx, dy=dy):
                decision, direction = decide_gesture(
                    held_ms=150, dx=dx, dy=dy,
                    hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
                )
                self.assertEqual(decision, GESTURE)
                self.assertEqual(direction, expected)

    def test_boundary_held_exactly_at_floor_is_eligible(self):
        decision, direction = decide_gesture(
            held_ms=_FLOOR_MS, dx=120, dy=0,
            hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
        )
        self.assertEqual(decision, GESTURE)
        self.assertEqual(direction, MouseEvent.GESTURE_SWIPE_RIGHT)

    def test_ambiguous_diagonal_is_a_click_not_a_random_gesture(self):
        # Equal cross-axis motion → existing cross-axis reject → no direction.
        decision, direction = decide_gesture(
            held_ms=150, dx=120, dy=120,
            hold_floor_ms=_FLOOR_MS, threshold=_THRESHOLD, deadzone=_DEADZONE,
        )
        self.assertEqual(decision, CLICK)
        self.assertIsNone(direction)


class ShouldArmGestureTests(unittest.TestCase):
    def test_owner_button_arms_when_idle(self):
        self.assertTrue(
            should_arm_gesture(gesture_active=False, btn_owner="forward",
                               owners={"forward", "back"})
        )

    def test_non_owner_button_never_arms(self):
        self.assertFalse(
            should_arm_gesture(gesture_active=False, btn_owner="middle",
                               owners={"forward", "back"})
        )

    def test_second_owner_passes_through_while_one_is_active(self):
        # Two-owner overlap: first-held wins, the second must not arm (PRD rule).
        self.assertFalse(
            should_arm_gesture(gesture_active=True, btn_owner="back",
                               owners={"forward", "back"})
        )

    def test_no_owners_configured_means_feature_off(self):
        self.assertFalse(
            should_arm_gesture(gesture_active=False, btn_owner="forward", owners=set())
        )


# ---------------------------------------------------------------------------
# Fake-Quartz harness: exercises the real core.mouse_hook_macos callback code
# (arming, release, abort) against a minimal fake objc/Quartz so it runs
# objc-free in this sandbox. Loaded fresh per test and popped from
# sys.modules afterwards, so any OTHER test file that imports
# core.mouse_hook_macos directly still sees the real (missing-PyObjC)
# ImportError, unaffected by this workaround (mirrors tests/test_engine.py's
# _ensure_core_engine_importable hygiene).
# ---------------------------------------------------------------------------

class _FakeCGEvent:
    """Minimal CGEventRef stand-in: an integer-field store + location."""

    def __init__(self, location=(0.0, 0.0)):
        self.fields = {}
        self.location = location
        self.flags = 0


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _build_fake_quartz():
    """A fake Quartz module exposing just the surface core.mouse_hook_macos
    touches, backed by _FakeCGEvent so the real callback code runs unmodified."""
    mod = types.ModuleType("Quartz")

    const_names = [
        "kCGEventMouseMoved", "kCGEventOtherMouseDragged",
        "kCGEventOtherMouseDown", "kCGEventOtherMouseUp", "kCGEventScrollWheel",
        "kCGMouseEventDeltaX", "kCGMouseEventDeltaY", "kCGMouseEventButtonNumber",
        "kCGEventSourceUserData",
        "kCGScrollWheelEventFixedPtDeltaAxis1", "kCGScrollWheelEventFixedPtDeltaAxis2",
        "kCGScrollWheelEventPointDeltaAxis1", "kCGScrollWheelEventPointDeltaAxis2",
        "kCGScrollWheelEventDeltaAxis1", "kCGScrollWheelEventDeltaAxis2",
        "kCGScrollWheelEventScrollPhase", "kCGScrollWheelEventMomentumPhase",
        "kCGScrollEventUnitPixel", "kCGHIDEventTap",
        "kCGEventSourceStateHIDSystemState",
        "kCGSessionEventTap", "kCGHeadInsertEventTap", "kCGEventTapOptionDefault",
        "kCFRunLoopCommonModes",
    ]
    for i, cname in enumerate(const_names):
        setattr(mod, cname, i + 1)

    mod.posted_events = []
    mod.modifier_flags = 0

    mod.CGEventGetIntegerValueField = lambda event, field: event.fields.get(field, 0)
    mod.CGEventSetIntegerValueField = lambda event, field, value: event.fields.__setitem__(field, value)
    mod.CGEventGetFlags = lambda event: event.flags
    mod.CGEventSetFlags = lambda event, flags: setattr(event, "flags", flags)
    mod.CGEventGetLocation = lambda event: event.location
    mod.CGEventCreate = lambda source: _FakeCGEvent()
    mod.CGEventSourceFlagsState = lambda state_id: mod.modifier_flags
    mod.CGEventPost = lambda tap, event: mod.posted_events.append(event)
    mod.CGEventTapEnable = lambda tap, enable: None
    mod.CGEventMaskBit = lambda bit: 1 << int(bit)

    def _create_mouse_event(source, mouse_type, point, button):
        ev = _FakeCGEvent(location=point)
        ev.fields[mod.kCGMouseEventButtonNumber] = button
        return ev

    mod.CGEventCreateMouseEvent = _create_mouse_event
    return mod


def _load_mouse_hook_macos():
    """Import a FRESH core.mouse_hook_macos backed by a fake objc/Quartz and
    return (MouseHook, fake_quartz_module). Saves and restores any real objc /
    Quartz / core.mouse_hook_macos already in sys.modules, so this works whether
    or not PyObjC is installed and never corrupts other test files: on Linux/CI
    the real modules are absent; on a real Mac they ARE loaded (e.g. by
    tests/test_engine.py) and MUST be forced aside, else this imports the real
    objc-backed module and the fake-CGEvent assertions run against a live tap."""
    name = "core.mouse_hook_macos"
    quartz = _build_fake_quartz()
    fake_objc = types.ModuleType("objc")
    fake_objc.autorelease_pool = lambda: _NullContext()

    sentinel = object()
    saved = {k: sys.modules.get(k, sentinel) for k in ("objc", "Quartz", name)}
    sys.modules["objc"] = fake_objc
    sys.modules["Quartz"] = quartz
    sys.modules.pop(name, None)  # force a fresh, fake-backed import
    try:
        module = importlib.import_module(name)
        MouseHook = module.MouseHook  # capture before restoring real modules
    finally:
        for key, value in saved.items():
            if value is sentinel:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    return MouseHook, quartz


_MIDDLE_BTN = 2
_BACK_BTN = 3
_FORWARD_BTN = 4


class EventTapGestureStateTransitionTests(unittest.TestCase):
    """Finding #4: the callback's owner-state transitions (arm / release /
    abort) driven through the real macOS callback code via the fake-Quartz
    harness above."""

    def setUp(self):
        MouseHook, quartz = _load_mouse_hook_macos()
        self.quartz = quartz
        self.hook = MouseHook()
        self.hook.configure_gestures(
            enabled=True, threshold=50, deadzone=40,
            timeout_ms=3000, cooldown_ms=500, owners={"forward", "back"},
            hold_floor_ms=80,
        )

    def _down(self, btn):
        ev = _FakeCGEvent()
        ev.fields[self.quartz.kCGMouseEventButtonNumber] = btn
        return self.hook._event_tap_callback(None, self.quartz.kCGEventOtherMouseDown, ev, None)

    def _up(self, btn):
        ev = _FakeCGEvent()
        ev.fields[self.quartz.kCGMouseEventButtonNumber] = btn
        return self.hook._event_tap_callback(None, self.quartz.kCGEventOtherMouseUp, ev, None)

    def _move(self, dx, dy):
        ev = _FakeCGEvent()
        ev.fields[self.quartz.kCGMouseEventDeltaX] = dx
        ev.fields[self.quartz.kCGMouseEventDeltaY] = dy
        return self.hook._event_tap_callback(None, self.quartz.kCGEventMouseMoved, ev, None)

    def test_down_then_quick_up_resets_owner_and_dispatches_owner_click(self):
        result = self._down(_FORWARD_BTN)
        self.assertIsNone(result)  # down is swallowed/deferred
        self.assertEqual(self.hook._gesture_owner, "forward")
        self.assertTrue(self.hook._gesture_active)

        result = self._up(_FORWARD_BTN)  # released well under the 80ms floor

        self.assertIsNone(result)
        self.assertIsNone(self.hook._gesture_owner)
        self.assertFalse(self.hook._gesture_active)
        self.assertEqual(self.quartz.posted_events, [])  # no native replay (Bug C)
        fired = [self.hook._dispatch_queue.get_nowait(), self.hook._dispatch_queue.get_nowait()]
        self.assertEqual(
            [ev.event_type for ev in fired],
            [MouseEvent.XBUTTON2_DOWN, MouseEvent.XBUTTON2_UP],
        )

    def test_down_slide_up_fires_tagged_event_and_resets(self):
        self._down(_FORWARD_BTN)
        self.hook._gesture_press_at = time.monotonic() - 0.2  # outlive the hold floor
        self._move(120, 0)  # swallowed, accumulated

        result = self._up(_FORWARD_BTN)

        self.assertIsNone(result)
        self.assertIsNone(self.hook._gesture_owner)
        self.assertFalse(self.hook._gesture_active)
        fired = self.hook._dispatch_queue.get_nowait()
        self.assertEqual(fired.event_type, MouseEvent.GESTURE_SWIPE_RIGHT)
        self.assertEqual(fired.raw_data["gesture_owner"], "forward")
        self.assertEqual(len(self.quartz.posted_events), 0)  # no click replay

    def test_missed_up_then_move_does_not_stay_frozen_past_timeout(self):
        self.hook.configure_gestures(
            enabled=True, threshold=50, deadzone=40,
            timeout_ms=250, cooldown_ms=500, owners={"forward", "back"},
            hold_floor_ms=80,
        )
        self._down(_FORWARD_BTN)
        self.hook._gesture_press_at = time.monotonic() - 1.0  # older than the timeout

        result = self._move(50, 0)

        # Cursor is no longer frozen: the move is NOT swallowed.
        self.assertIsNotNone(result)
        self.assertIsNone(self.hook._gesture_owner)
        self.assertFalse(self.hook._gesture_active)

        # The shared should_arm_gesture gate is unstuck: a different owner
        # can arm right away.
        result = self._down(_BACK_BTN)
        self.assertIsNone(result)
        self.assertEqual(self.hook._gesture_owner, "back")

    def test_tap_disabled_event_aborts_a_pending_gesture(self):
        self._down(_FORWARD_BTN)

        self.hook._event_tap_callback(
            None, 0xFFFFFFFE, _FakeCGEvent(), None  # _kCGEventTapDisabledByTimeout
        )

        self.assertIsNone(self.hook._gesture_owner)
        self.assertFalse(self.hook._gesture_active)

    def test_stop_aborts_a_pending_gesture(self):
        self._down(_FORWARD_BTN)

        self.hook.stop()

        self.assertIsNone(self.hook._gesture_owner)
        self.assertFalse(self.hook._gesture_active)

    def test_tap_dispatches_owner_click_pair_not_native_replay(self):
        """Bug C: a tap of ANY armed owner button fires that button's own
        (DOWN, UP) MouseEvent pair via the dispatch queue (dual-mode) --
        never a Quartz.CGEventPost native replay (macOS ignores raw button
        4/3, so a native replay would be a dead click)."""
        self.hook.configure_gestures(
            enabled=True, threshold=50, deadzone=40,
            timeout_ms=3000, cooldown_ms=500, owners={"forward", "back", "middle"},
            hold_floor_ms=80,
        )
        cases = {
            _MIDDLE_BTN: (MouseEvent.MIDDLE_DOWN, MouseEvent.MIDDLE_UP),
            _BACK_BTN: (MouseEvent.XBUTTON1_DOWN, MouseEvent.XBUTTON1_UP),
            _FORWARD_BTN: (MouseEvent.XBUTTON2_DOWN, MouseEvent.XBUTTON2_UP),
        }
        for btn, (expected_down, expected_up) in cases.items():
            with self.subTest(btn=btn):
                self._down(btn)
                self._up(btn)  # quick tap, well under the hold floor

                fired = [
                    self.hook._dispatch_queue.get_nowait(),
                    self.hook._dispatch_queue.get_nowait(),
                ]
                self.assertEqual(
                    [ev.event_type for ev in fired], [expected_down, expected_up]
                )
                self.assertEqual(self.quartz.posted_events, [])  # no native replay


_TILT_RIGHT_PULSE = 1 * 65536  # fixed-point h_delta = +1.0 -> tilt_right
_TILT_LEFT_PULSE = -1 * 65536  # fixed-point h_delta = -1.0 -> tilt_left


class TiltGestureStateTransitionTests(unittest.TestCase):
    """Tilt (hscroll) gesture: armed off the hscroll pulse stream instead of
    a button down/up, resolved by the same decide_gesture on release. Drives
    the real macOS callback (_maybe_arm_tilt_gesture / _finish_tilt_gesture)
    via the fake-Quartz harness above."""

    def setUp(self):
        MouseHook, quartz = _load_mouse_hook_macos()
        self.quartz = quartz
        self.hook = MouseHook()
        self.hook.configure_gestures(
            enabled=True, threshold=50, deadzone=40,
            timeout_ms=3000, cooldown_ms=500, owners=set(),
            hold_floor_ms=80,
            tilt_owners={"tilt_left", "tilt_right"}, tilt_release_ms=150,
        )

    def _scroll(self, h_fixed):
        ev = _FakeCGEvent()
        ev.fields[self.quartz.kCGScrollWheelEventFixedPtDeltaAxis2] = h_fixed
        return self.hook._event_tap_callback(
            None, self.quartz.kCGEventScrollWheel, ev, None
        )

    def _move(self, dx, dy):
        ev = _FakeCGEvent()
        ev.fields[self.quartz.kCGMouseEventDeltaX] = dx
        ev.fields[self.quartz.kCGMouseEventDeltaY] = dy
        return self.hook._event_tap_callback(
            None, self.quartz.kCGEventMouseMoved, ev, None
        )

    def _fire_tilt_release(self):
        """Cancel the live threading.Timer and drive the real timeout handler
        as if release_ms had already elapsed -- avoids a real sleep."""
        timer = self.hook._tilt_release_timer
        if timer is not None:
            timer.cancel()
        self.hook._tilt_last_pulse_at = time.monotonic() - (
            self.hook._tilt_release_ms / 1000.0 + 0.05
        )
        self.hook._on_tilt_release_timeout()

    def test_single_pulse_then_silence_is_a_tap_fires_hscroll(self):
        result = self._scroll(_TILT_RIGHT_PULSE)

        self.assertIsNone(result)  # swallowed -- gesture armed
        self.assertTrue(self.hook._gesture_active)
        self.assertEqual(self.hook._gesture_owner, "tilt_right")

        self._fire_tilt_release()

        self.assertFalse(self.hook._gesture_active)
        self.assertIsNone(self.hook._gesture_owner)
        fired = self.hook._dispatch_queue.get_nowait()
        self.assertEqual(fired.event_type, MouseEvent.HSCROLL_RIGHT)
        self.assertEqual(fired.raw_data, 1.0)
        self.assertTrue(self.hook._dispatch_queue.empty())

    def test_pulse_stream_plus_slide_up_fires_tagged_gesture(self):
        self._scroll(_TILT_LEFT_PULSE)  # first pulse arms tilt_left
        self.hook._gesture_press_at = time.monotonic() - 0.2  # outlive hold floor
        self._scroll(_TILT_LEFT_PULSE)  # a second pulse -- still streaming

        result = self._move(0, -120)  # accumulated slide up
        self.assertIsNone(result)  # swallowed while gesture active

        # Fire-on-slide-cross: the gesture fires the INSTANT the slide crosses
        # the threshold (mid-hold), NOT on release -- so it's already queued and
        # _gesture_triggered is set before the release timer runs. This is what
        # keeps a fragmenting pulse stream from dropping the gesture.
        self.assertTrue(self.hook._gesture_triggered)
        fired = self.hook._dispatch_queue.get_nowait()
        self.assertEqual(fired.event_type, MouseEvent.GESTURE_SWIPE_UP)
        self.assertEqual(fired.raw_data["source"], "tilt")
        self.assertEqual(fired.raw_data["gesture_owner"], "tilt_left")

        self._fire_tilt_release()  # resolves release: gesture already fired -> no tap
        self.assertFalse(self.hook._gesture_active)
        self.assertTrue(self.hook._dispatch_queue.empty())

    def test_disabled_tilt_direction_does_not_arm(self):
        self.hook.configure_gestures(
            enabled=True, threshold=50, deadzone=40,
            timeout_ms=3000, cooldown_ms=500, owners=set(),
            hold_floor_ms=80,
            tilt_owners={"tilt_right"}, tilt_release_ms=150,  # tilt_left NOT enabled
        )

        result = self._scroll(_TILT_LEFT_PULSE)

        self.assertIsNotNone(result)  # passed through, not swallowed
        self.assertFalse(self.hook._gesture_active)
        self.assertIsNone(self.hook._gesture_owner)
        # falls through to the tilt's normal (non-gesture) hscroll action
        fired = self.hook._dispatch_queue.get_nowait()
        self.assertEqual(fired.event_type, MouseEvent.HSCROLL_LEFT)
        self.assertEqual(fired.raw_data, 1.0)
        self.assertTrue(self.hook._dispatch_queue.empty())


if __name__ == "__main__":
    unittest.main()
