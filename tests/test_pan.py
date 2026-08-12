"""Tests for the Pan action (hold a button and slide to scroll).

Covers the platform-free PanScroller delta math, the config owner/settings
logic and migration, and the BaseMouseHook arm/sample/release flow that pan
shares with Gesture Swipe.
"""

import copy
import unittest

from core.config import (
    DEFAULT_CONFIG,
    PAN_ACTION,
    PAN_CAPABLE_BUTTONS,
    PAN_DEFAULT_SPEED,
    PAN_SPEED_PRESETS,
    _migrate,
    pan_owners,
    pan_settings,
    pan_speed_index_for,
)
from core.mouse_hook_base import BaseMouseHook
from core.pan_scroller import PanScroller


def _cfg_with(mappings=None, settings=None):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if mappings:
        cfg["profiles"]["default"]["mappings"].update(mappings)
    if settings:
        cfg["settings"].update(settings)
    return cfg


def _scroller(speed=1.0, natural=True):
    steps = []
    ps = PanScroller(emit=lambda dv, dh: steps.append((dv, dh)),
                     speed=speed, natural=natural)
    ps.steps = steps
    return ps


# ── PanScroller: delta math ──────────────────────────────────────────────────

class PanScrollerTests(unittest.TestCase):
    def test_no_output_until_begun(self):
        ps = _scroller()
        self.assertFalse(ps.sample(50, 50))
        self.assertEqual(ps.steps, [])

    def test_natural_content_follows_mouse(self):
        # Drag down/right -> content comes with the hand -> positive on both axes.
        ps = _scroller(natural=True)
        ps.begin()
        ps.sample(7, 11)
        self.assertEqual(ps.steps, [(11, 7)])

    def test_inverted_is_scrollbar_style(self):
        ps = _scroller(natural=False)
        ps.begin()
        ps.sample(7, 11)
        self.assertEqual(ps.steps, [(-11, -7)])

    def test_speed_scales_output(self):
        ps = _scroller(speed=2.0)
        ps.begin()
        ps.sample(5, 10)
        self.assertEqual(ps.steps, [(20, 10)])

    def test_subunit_motion_accumulates_instead_of_truncating(self):
        # A slow drag whose per-event delta scales below one whole unit must
        # still scroll: the remainder carries rather than being floored away.
        ps = _scroller(speed=0.5)
        ps.begin()
        self.assertFalse(ps.sample(0, 1))   # 0.5 -> nothing yet
        self.assertEqual(ps.steps, [])
        self.assertTrue(ps.sample(0, 1))    # 0.5 + 0.5 -> one whole unit
        self.assertEqual(ps.steps, [(1, 0)])

    def test_accumulator_does_not_leak_between_holds(self):
        ps = _scroller(speed=0.5)
        ps.begin()
        ps.sample(0, 1)                     # leaves 0.5 pending
        ps.end()
        ps.begin()
        self.assertFalse(ps.sample(0, 1))   # must not combine with the old 0.5
        self.assertEqual(ps.steps, [])

    def test_end_stops_further_output(self):
        ps = _scroller()
        ps.begin()
        ps.end()
        self.assertFalse(ps.sample(50, 50))
        self.assertEqual(ps.steps, [])

    def test_speed_is_clamped_to_sane_range(self):
        # Values come from a hand-editable config; 0 would silently make the
        # button inert and a huge value would make it unusable.
        self.assertEqual(_scroller(speed=0).speed, 0.1)
        self.assertEqual(_scroller(speed=-5).speed, 0.1)
        self.assertEqual(_scroller(speed=999).speed, 10.0)

    def test_configure_mid_hold_takes_effect_next_sample(self):
        ps = _scroller(speed=1.0, natural=True)
        ps.begin()
        ps.configure(natural=False)
        ps.sample(0, 4)
        self.assertEqual(ps.steps, [(-4, 0)])


# ── Config: owners, settings, migration ──────────────────────────────────────

class PanConfigTests(unittest.TestCase):
    def test_owner_requires_the_pan_sentinel(self):
        self.assertEqual(pan_owners(_cfg_with({"middle": "none"})), set())
        self.assertEqual(
            pan_owners(_cfg_with({"middle": "mouse_middle_click"})), set()
        )
        self.assertEqual(
            pan_owners(_cfg_with({"middle": PAN_ACTION})), {"middle"}
        )

    def test_pan_and_gesture_swipe_are_independent_owners(self):
        cfg = _cfg_with({"middle": PAN_ACTION, "xbutton1": "gesture_swipe"})
        self.assertEqual(pan_owners(cfg), {"middle"})

    def test_device_buttons_gate_owners(self):
        cfg = _cfg_with({"middle": PAN_ACTION, "xbutton1": PAN_ACTION})
        # Device advertises only the middle button -> back is not armed.
        self.assertEqual(pan_owners(cfg, device_buttons={"middle"}), {"middle"})
        self.assertEqual(pan_owners(cfg, device_buttons=set()), set())

    def test_pan_capable_buttons_excludes_native_hid_controls(self):
        # The native controls would double-count (rawXY + OS motion), so they
        # must not be offered until the scroller locks to one source.
        self.assertNotIn("gesture", PAN_CAPABLE_BUTTONS)
        self.assertNotIn("actions_ring", PAN_CAPABLE_BUTTONS)

    def test_pan_settings_defaults(self):
        from core.config import PAN_DEFAULT_GLIDE
        self.assertEqual(
            pan_settings(_cfg_with()),
            (PAN_DEFAULT_SPEED, True, False, PAN_DEFAULT_GLIDE, True),
        )

    def test_pan_settings_read_overrides(self):
        cfg = _cfg_with(settings={"pan_speed": 2.0, "pan_natural": False,
                                  "pan_momentum": True, "pan_glide": 0.5,
                                  "pan_glide_across_windows": False})
        self.assertEqual(pan_settings(cfg), (2.0, False, True, 0.5, False))

    def test_pan_settings_clamp_out_of_range_glide(self):
        from core.config import PAN_GLIDE_MAX
        # e.g. a value stored by an older build with a wider range.
        cfg = _cfg_with(settings={"pan_glide": 2.0})
        self.assertEqual(pan_settings(cfg)[3], PAN_GLIDE_MAX)

    def test_speed_index_round_trips_presets(self):
        for i, speed in enumerate(PAN_SPEED_PRESETS):
            self.assertEqual(pan_speed_index_for(speed), i)

    def test_migration_seeds_pan_settings(self):
        from core.config import PAN_DEFAULT_GLIDE
        old = copy.deepcopy(DEFAULT_CONFIG)
        old["version"] = 11
        for key in ("pan_speed", "pan_natural", "pan_momentum",
                    "pan_glide", "pan_glide_across_windows"):
            old["settings"].pop(key, None)
        _migrate(old)
        self.assertEqual(old["settings"]["pan_speed"], PAN_DEFAULT_SPEED)
        self.assertTrue(old["settings"]["pan_natural"])
        self.assertFalse(old["settings"]["pan_momentum"])
        self.assertEqual(old["settings"]["pan_glide"], PAN_DEFAULT_GLIDE)
        self.assertTrue(old["settings"]["pan_glide_across_windows"])
        self.assertGreaterEqual(old["version"], 12)

    def test_migration_preserves_existing_pan_settings(self):
        old = copy.deepcopy(DEFAULT_CONFIG)
        old["version"] = 11
        old["settings"]["pan_speed"] = 2.0
        old["settings"]["pan_natural"] = False
        _migrate(old)
        self.assertEqual(old["settings"]["pan_speed"], 2.0)
        self.assertFalse(old["settings"]["pan_natural"])


# ── BaseMouseHook: arm / sample / release ───────────────────────────────────

class _Hook(BaseMouseHook):
    """BaseMouseHook with the platform scroll injection captured."""

    def __init__(self):
        super().__init__()
        self.scrolls = []

    def _emit_pan_scroll(self, dv, dh):
        self.scrolls.append((dv, dh))
        return True


def _hook(pan=("middle",), swipe=(), **kw):
    h = _Hook()
    h.configure_button_gestures(
        owners=set(swipe), pan_owners=set(pan), pan_speed=1.0,
        pan_natural=True, **kw
    )
    return h


class PanHookTests(unittest.TestCase):
    def test_pan_owner_is_a_slide_owner_so_platform_dispatch_arms_it(self):
        # The platform hooks gate on is_button_gesture_owner(); pan owners must
        # satisfy it or no platform would ever arm them.
        h = _hook(pan=("middle",))
        self.assertTrue(h.is_button_gesture_owner("middle"))
        self.assertTrue(h.is_pan_owner("middle"))

    def test_hold_and_move_emits_scroll(self):
        h = _hook()
        self.assertTrue(h.arm_button_gesture("middle"))
        self.assertTrue(h.sample_button_gesture(3, 9, "os_motion"))
        self.assertEqual(h.scrolls, [(9, 3)])
        self.assertEqual(h.release_button_gesture("middle"), "pan")

    def test_motion_without_arming_emits_nothing(self):
        h = _hook()
        self.assertFalse(h.sample_button_gesture(3, 9, "os_motion"))
        self.assertEqual(h.scrolls, [])

    def test_release_after_pan_does_not_replay_a_click(self):
        # Gesture Swipe replays an unrecognized hold as a tap; pan owns the
        # button outright, so nothing is dispatched on release.
        dispatched = []
        h = _hook()
        h._dispatch = dispatched.append
        h.arm_button_gesture("middle")
        h.release_button_gesture("middle")
        self.assertEqual(dispatched, [])

    def test_release_by_a_different_owner_is_ignored(self):
        h = _hook(pan=("middle", "xbutton1"))
        h.arm_button_gesture("middle")
        self.assertIsNone(h.release_button_gesture("xbutton1"))
        self.assertEqual(h._button_gesture_active_owner, "middle")

    def test_pan_outlives_the_swipe_timeout(self):
        # A real pan lasts as long as the user holds the button; the 3s swipe
        # timeout must not cut it off.
        h = _hook(timeout_ms=3000)
        h.arm_button_gesture("middle", now=0.0)
        self.assertTrue(h.sample_button_gesture(0, 5, "os_motion", now=10.0))
        self.assertEqual(h.scrolls, [(5, 0)])

    def test_pan_still_aborts_once_wedged(self):
        h = _hook(pan_timeout_ms=30000)
        h.arm_button_gesture("middle", now=0.0)
        self.assertFalse(h.sample_button_gesture(0, 5, "os_motion", now=31.0))
        self.assertEqual(h.scrolls, [])
        self.assertIsNone(h._button_gesture_active_owner)

    def test_swipe_owner_still_uses_the_recognizer_not_the_scroller(self):
        h = _hook(pan=(), swipe=("middle",))
        h.arm_button_gesture("middle")
        h.sample_button_gesture(3, 9, "os_motion")
        self.assertEqual(h.scrolls, [])

    def test_a_button_cannot_be_both_modes(self):
        # Config is single-valued so this needs a hand-edited file; swipe wins
        # rather than both arming on one press.
        h = _hook(pan=("middle",), swipe=("middle",))
        self.assertFalse(h.is_pan_owner("middle"))
        self.assertTrue(h.is_button_gesture_owner("middle"))

    def test_only_one_owner_pans_at_a_time(self):
        h = _hook(pan=("middle", "xbutton1"))
        self.assertTrue(h.arm_button_gesture("middle"))
        self.assertFalse(h.arm_button_gesture("xbutton1"))

    def test_abort_ends_the_hold(self):
        h = _hook()
        h.arm_button_gesture("middle")
        h.abort_button_gesture("stop")
        self.assertIsNone(h._button_gesture_active_owner)
        self.assertFalse(h.sample_button_gesture(0, 5, "os_motion"))
        self.assertEqual(h.scrolls, [])

    def test_reconfiguring_with_no_owners_clears_an_active_hold(self):
        h = _hook()
        h.arm_button_gesture("middle")
        h.configure_button_gestures(owners=set(), pan_owners=set())
        self.assertIsNone(h._button_gesture_active_owner)
        self.assertFalse(h.is_pan_owner("middle"))

    def test_base_hook_pan_emit_is_inert(self):
        # A pan mapping carried from a macOS config must degrade to "does
        # nothing" on a platform with no injection, not raise in the event tap.
        h = BaseMouseHook()
        h.configure_button_gestures(owners=set(), pan_owners={"middle"})
        h.arm_button_gesture("middle")
        self.assertTrue(h.sample_button_gesture(3, 9, "os_motion"))


if __name__ == "__main__":
    unittest.main()


# ── HID++ divert path for side buttons ──────────────────────────────────────
# Some devices never report a side-button hold through the OS (MX Anywhere 3S
# over Bluetooth: ~20ms click on tap, nothing while held), so hold modes divert
# the CID and arm from the HID press -- the mode-shift hybrid.

class PanHidDivertTests(unittest.TestCase):
    def test_divert_flags_add_side_button_cids(self):
        h = _Hook()
        self.assertNotIn(0x0053, h._build_extra_diverts())
        self.assertNotIn(0x0056, h._build_extra_diverts())
        h.divert_xbutton1 = True
        h.divert_xbutton2 = True
        extras = h._build_extra_diverts()
        self.assertIn(0x0053, extras)
        self.assertIn(0x0056, extras)

    def test_hid_press_arms_pan_and_motion_scrolls(self):
        h = _hook(pan=("xbutton2",))
        h._on_hid_xbutton2_down()
        self.assertEqual(h._button_gesture_active_owner, "xbutton2")
        self.assertTrue(h.sample_button_gesture(3, 9, "os_motion"))
        self.assertEqual(h.scrolls, [(9, 3)])
        h._on_hid_xbutton2_up()
        self.assertIsNone(h._button_gesture_active_owner)

    def test_hid_press_dispatches_normal_event_when_not_owner(self):
        # Divert active (another profile maps a hold mode) but the current
        # profile maps a plain action: the press must flow through as the
        # ordinary button event so that mapping still fires.
        dispatched = []
        h = _hook(pan=())
        h._dispatch = lambda e: dispatched.append(e.event_type)
        h._on_hid_xbutton1_down()
        h._on_hid_xbutton1_up()
        self.assertEqual(dispatched, ["xbutton1_down", "xbutton1_up"])

    def test_release_falls_through_when_hold_armed_by_other_owner(self):
        h = _hook(pan=("middle", "xbutton2"))
        h.arm_button_gesture("middle")
        dispatched = []
        h._dispatch = lambda e: dispatched.append(e.event_type)
        h._on_hid_xbutton2_up()
        self.assertEqual(dispatched, ["xbutton2_up"])
        self.assertEqual(h._button_gesture_active_owner, "middle")

    def test_refresh_pushes_current_flag_set_to_listener(self):
        class _Listener:
            def __init__(self):
                self.pushed = None
            def update_extra_diverts(self, d):
                self.pushed = d
        h = _Hook()
        h._hid_gesture = _Listener()
        h.divert_xbutton2 = True
        h.refresh_extra_diverts()
        self.assertIn(0x0056, h._hid_gesture.pushed)
        self.assertNotIn(0x0053, h._hid_gesture.pushed)

    def test_refresh_without_listener_is_a_noop(self):
        h = _Hook()
        h._hid_gesture = None
        h.refresh_extra_diverts()  # must not raise


class ListenerUpdateExtraDivertsTests(unittest.TestCase):
    def _listener(self):
        from core import hid_gesture
        lst = hid_gesture.HidGestureListener()
        lst._feat_idx = 0x0A
        lst.reported = []
        lst._set_cid_reporting = lambda cid, flags: (
            lst.reported.append((cid, flags)) or (0, 0, 0, 0, [])
        )
        lst.undiverted = []
        lst._tx = lambda *a: lst.undiverted.append(a)
        return lst

    def test_add_diverts_new_cid(self):
        lst = self._listener()
        lst.update_extra_diverts({0x0056: {"on_down": None, "on_up": None}})
        lst._apply_pending_extra_diverts()
        self.assertIn(0x0056, lst._extra_diverts)
        self.assertIn(0x0056, lst._extra_divert_acks)
        self.assertEqual(lst.reported, [(0x0056, 0x03)])

    def test_remove_undiverts_and_drops_cid(self):
        lst = self._listener()
        lst.update_extra_diverts({0x0056: {"on_down": None, "on_up": None}})
        lst._apply_pending_extra_diverts()
        lst.update_extra_diverts({})
        lst._apply_pending_extra_diverts()
        self.assertNotIn(0x0056, lst._extra_diverts)
        self.assertNotIn(0x0056, lst._extra_divert_acks)
        self.assertEqual(len(lst.undiverted), 1)

    def test_reapply_same_set_makes_no_hid_traffic(self):
        lst = self._listener()
        diverts = {0x0056: {"on_down": None, "on_up": None}}
        lst.update_extra_diverts(diverts)
        lst._apply_pending_extra_diverts()
        lst.reported.clear()
        lst.update_extra_diverts(diverts)
        lst._apply_pending_extra_diverts()
        self.assertEqual(lst.reported, [])

    def test_held_state_survives_callback_refresh(self):
        lst = self._listener()
        lst.update_extra_diverts({0x0056: {"on_down": None, "on_up": None}})
        lst._apply_pending_extra_diverts()
        lst._extra_diverts[0x0056]["held"] = True
        lst.update_extra_diverts({0x0056: {"on_down": None, "on_up": None}})
        lst._apply_pending_extra_diverts()
        self.assertTrue(lst._extra_diverts[0x0056]["held"])

    def test_thumb_extra_is_never_removed(self):
        lst = self._listener()
        lst._thumb_button_cid = 0x00C3
        lst._extra_diverts[0x00C3] = {"on_down": None, "on_up": None,
                                      "held": False}
        lst._static_extra_diverts[0x00C3] = {"on_down": None, "on_up": None}
        lst.update_extra_diverts({})
        lst._apply_pending_extra_diverts()
        self.assertIn(0x00C3, lst._extra_diverts)


# ── Momentum ("throw" and glide) ─────────────────────────────────────────────

def _flick(ps, n=8, dy=12, dt=0.008, t0=100.0):
    """Feed a fast, steady downward drag ending at a known timestamp."""
    t = t0
    for _ in range(n):
        t += dt
        ps.sample(0, dy, now=t)
    return t


class PanMomentumScrollerTests(unittest.TestCase):
    def test_momentum_off_returns_no_coast(self):
        ps = _scroller()
        ps.begin()
        t = _flick(ps)
        self.assertIsNone(ps.end(now=t))

    def test_flick_release_returns_a_coast(self):
        ps = _scroller()
        ps.configure(momentum=True)
        ps.begin()
        t = _flick(ps)
        self.assertIsNotNone(ps.end(now=t))

    def test_pause_before_release_does_not_throw(self):
        # Drag, stop, THEN release = placement, not a throw.
        ps = _scroller()
        ps.configure(momentum=True)
        ps.begin()
        t = _flick(ps)
        self.assertIsNone(ps.end(now=t + 0.5))

    def test_slow_drag_does_not_throw(self):
        ps = _scroller()
        ps.configure(momentum=True)
        ps.begin()
        t = 100.0
        for _ in range(8):
            t += 0.05
            ps.sample(0, 1, now=t)   # ~20 units/s, well under the threshold
        self.assertIsNone(ps.end(now=t))

    def test_coast_decays_to_a_stop(self):
        from core.pan_scroller import PanCoast
        coast = PanCoast(1000.0, 0.0, glide_tau=0.3)
        total, steps = 0, 0
        while True:
            step = coast.step(1 / 90)
            if step is None:
                break
            total += step[0]
            steps += 1
            self.assertLess(steps, 2000, "coast never terminated")
        self.assertGreater(total, 0)

    def test_longer_glide_travels_farther(self):
        from core.pan_scroller import PanCoast

        def travel(tau):
            coast = PanCoast(1000.0, 0.0, glide_tau=tau)
            total = 0
            while (step := coast.step(1 / 90)) is not None:
                total += step[0]
            return total

        self.assertGreater(travel(1.5), travel(0.25))

    def test_coast_direction_follows_velocity_sign(self):
        from core.pan_scroller import PanCoast
        coast = PanCoast(-1000.0, 0.0, glide_tau=0.3)
        total = 0
        while (step := coast.step(1 / 90)) is not None:
            total += step[0]
        self.assertLess(total, 0)


class PanMomentumHookTests(unittest.TestCase):
    def _momentum_hook(self):
        h = _Hook()
        h.configure_button_gestures(
            owners=set(), pan_owners={"middle"}, pan_speed=1.0,
            pan_natural=True, pan_momentum=True, pan_glide=0.3,
        )
        return h

    def _flick_hold(self, h):
        h.arm_button_gesture("middle", now=100.0)
        t = 100.0
        for _ in range(8):
            t += 0.008
            h.sample_button_gesture(0, 12, "os_motion", now=t)
        h.release_button_gesture("middle", now=t)

    def test_flick_release_starts_a_coast_that_scrolls(self):
        import time as _time
        h = self._momentum_hook()
        self._flick_hold(h)
        thread = h._pan_coast_thread
        self.assertIsNotNone(thread)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertGreater(sum(dv for dv, _ in h.scrolls), 8 * 12)

    def test_regrab_cancels_the_coast(self):
        h = self._momentum_hook()
        self._flick_hold(h)
        h.arm_button_gesture("middle")   # catch the glide
        h._pan_coast_thread.join(timeout=2)
        self.assertFalse(h._pan_coast_thread.is_alive())

    def test_momentum_off_never_starts_a_thread(self):
        h = _hook()   # default: momentum off
        h.arm_button_gesture("middle", now=100.0)
        t = 100.0
        for _ in range(8):
            t += 0.008
            h.sample_button_gesture(0, 12, "os_motion", now=t)
        h.release_button_gesture("middle")
        self.assertIsNone(h._pan_coast_thread)

    def test_disabling_momentum_cancels_a_running_coast(self):
        h = self._momentum_hook()
        self._flick_hold(h)
        h.configure_button_gestures(
            owners=set(), pan_owners={"middle"}, pan_momentum=False,
        )
        h._pan_coast_thread.join(timeout=2)
        self.assertFalse(h._pan_coast_thread.is_alive())


class PanGlideClampTests(unittest.TestCase):
    def test_clamp_pan_glide(self):
        from core.config import (
            clamp_pan_glide, PAN_GLIDE_MIN, PAN_GLIDE_MAX, PAN_DEFAULT_GLIDE,
        )
        self.assertEqual(clamp_pan_glide(0.4), 0.4)
        self.assertEqual(clamp_pan_glide(0.0), PAN_GLIDE_MIN)
        self.assertEqual(clamp_pan_glide(99), PAN_GLIDE_MAX)
        # Hand-edited garbage degrades to the default, not a crash.
        self.assertEqual(clamp_pan_glide("fast"), PAN_DEFAULT_GLIDE)
        self.assertEqual(clamp_pan_glide(None), PAN_DEFAULT_GLIDE)


class PanCoastPersistenceTests(unittest.TestCase):
    def test_reapplying_config_mid_coast_does_not_stop_the_glide(self):
        # A profile switch re-runs configure_button_gestures with the same
        # settings; a glide in flight must survive it. Only an explicit
        # momentum-off, unmap, or re-grab stops the coast.
        h = PanMomentumHookTests()._momentum_hook()
        PanMomentumHookTests._flick_hold(PanMomentumHookTests(), h)
        self.assertTrue(h._pan_coast_thread.is_alive())
        h.configure_button_gestures(
            owners=set(), pan_owners={"middle"}, pan_speed=1.0,
            pan_natural=True, pan_momentum=True, pan_glide=0.3,
        )
        self.assertTrue(h._pan_coast_thread.is_alive())
        h._pan_coast_thread.join(timeout=5)   # then it ends on its own
        self.assertFalse(h._pan_coast_thread.is_alive())


class PanCoastWindowPolicyTests(unittest.TestCase):
    def _hook_with_windows(self, across, windows):
        """Hook whose window-under-pointer lookup pops from ``windows``."""
        h = _Hook()
        h.configure_button_gestures(
            owners=set(), pan_owners={"middle"}, pan_speed=1.0,
            pan_natural=True, pan_momentum=True, pan_glide=0.3,
            pan_glide_across_windows=across,
        )
        seq = list(windows)
        h._current_window_under_pointer = lambda: (
            seq.pop(0) if len(seq) > 1 else seq[0]
        )
        return h

    def _throw(self, h):
        h.arm_button_gesture("middle", now=100.0)
        t = 100.0
        for _ in range(8):
            t += 0.008
            h.sample_button_gesture(0, 12, "os_motion", now=t)
        h.release_button_gesture("middle", now=t)

    def test_pinned_glide_stops_when_pointer_changes_window(self):
        # Window 1 at throw time, then the pointer moves over window 2.
        h = self._hook_with_windows(across=False, windows=[1, 2])
        self._throw(h)
        h._pan_coast_thread.join(timeout=5)
        stopped_early = sum(dv for dv, _ in h.scrolls)

        h2 = self._hook_with_windows(across=False, windows=[1, 1])
        self._throw(h2)
        h2._pan_coast_thread.join(timeout=5)
        full_glide = sum(dv for dv, _ in h2.scrolls)

        self.assertLess(stopped_early, full_glide)

    def test_across_windows_ignores_window_changes(self):
        h = self._hook_with_windows(across=True, windows=[1, 2])
        self._throw(h)
        h._pan_coast_thread.join(timeout=5)

        h2 = self._hook_with_windows(across=True, windows=[1, 1])
        self._throw(h2)
        h2._pan_coast_thread.join(timeout=5)

        total_a = sum(dv for dv, _ in h.scrolls)
        total_b = sum(dv for dv, _ in h2.scrolls)
        # Same flick, same glide -- a window change must make no difference.
        self.assertAlmostEqual(total_a, total_b, delta=max(total_a, total_b) * 0.2)

    def test_base_hook_lookup_is_none_so_pinned_mode_never_breaks(self):
        # Platforms without a window lookup return None; None == None keeps
        # the glide alive, i.e. pinned mode degrades to across-windows.
        h = _Hook()
        h.configure_button_gestures(
            owners=set(), pan_owners={"middle"}, pan_speed=1.0,
            pan_natural=True, pan_momentum=True, pan_glide=0.3,
            pan_glide_across_windows=False,
        )
        self._throw = PanCoastWindowPolicyTests._throw
        self._throw(self, h)
        h._pan_coast_thread.join(timeout=5)
        self.assertGreater(sum(dv for dv, _ in h.scrolls), 0)
