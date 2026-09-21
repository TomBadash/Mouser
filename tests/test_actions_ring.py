import math
import time
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.actions_ring import ActionsRingController, angle_to_sector, DEAD_ZONE_RADIUS


# ---------------------------------------------------------------------------
# T-1: Sector Geometry (angle_to_sector)
# ---------------------------------------------------------------------------

class SectorGeometryTests(unittest.TestCase):
    """Tests for the pure-geometry angle_to_sector function."""

    # -- Dead zone --------------------------------------------------------

    def test_dead_zone_origin(self):
        """T-1.1: dx=0, dy=0 is inside the dead zone."""
        self.assertEqual(angle_to_sector(0, 0, 6), -1)

    def test_dead_zone_edge_inside(self):
        """T-1.2: 29 px from origin is still inside the dead zone."""
        self.assertEqual(angle_to_sector(0, -29, 6), -1)

    def test_dead_zone_edge_outside(self):
        """T-1.3: 31 px from origin is outside the dead zone."""
        self.assertNotEqual(angle_to_sector(0, -31, 6), -1)

    def test_dead_zone_diagonal_inside(self):
        """Diagonal displacement still inside the dead zone radius."""
        # 20*sqrt(2) ~ 28.3, inside DEAD_ZONE_RADIUS=30
        self.assertEqual(angle_to_sector(20, 20, 4), -1)

    def test_dead_zone_exactly_at_boundary(self):
        """Exactly at DEAD_ZONE_RADIUS (30 px) is outside (strict < comparison)."""
        # dist = 30.0 exactly, which is NOT < DEAD_ZONE_RADIUS, so a valid sector
        self.assertNotEqual(angle_to_sector(0, -DEAD_ZONE_RADIUS, 4), -1)

    # -- 4-sector layout --------------------------------------------------

    def test_4_sectors_12_oclock(self):
        """T-1.4: Sector 0 at 12 o'clock (straight up)."""
        self.assertEqual(angle_to_sector(0, -100, 4), 0)

    def test_4_sectors_3_oclock(self):
        """T-1.5: Sector 1 at 3 o'clock (right)."""
        self.assertEqual(angle_to_sector(100, 0, 4), 1)

    def test_4_sectors_6_oclock(self):
        """T-1.6: Sector 2 at 6 o'clock (straight down)."""
        self.assertEqual(angle_to_sector(0, 100, 4), 2)

    def test_4_sectors_9_oclock(self):
        """T-1.7: Sector 3 at 9 o'clock (left)."""
        self.assertEqual(angle_to_sector(-100, 0, 4), 3)

    def test_4_sectors_boundary_ne(self):
        """T-1.8: 45-degree boundary between sectors 0 and 1."""
        result = angle_to_sector(100, -100, 4)
        self.assertIn(result, (0, 1))

    # -- 6-sector layout --------------------------------------------------

    def test_6_sectors_all_positions(self):
        """T-1.9: All six sectors in a 6-sector layout at 60-degree intervals."""
        r = 100
        # Sectors at visual angles 0, 60, 120, 180, 240, 300 degrees clockwise
        # from 12 o'clock. Convert to (dx, dy):
        #   visual_angle -> math angle: atan2(dx, -dy)
        #   dx = r * sin(visual_angle), dy = -r * cos(visual_angle)
        expected = {}
        for sector_idx in range(6):
            angle_deg = sector_idx * 60
            angle_rad = math.radians(angle_deg)
            dx = r * math.sin(angle_rad)
            dy = -r * math.cos(angle_rad)
            expected[sector_idx] = (dx, dy)

        for sector_idx, (dx, dy) in expected.items():
            with self.subTest(sector=sector_idx, dx=dx, dy=dy):
                self.assertEqual(angle_to_sector(dx, dy, 6), sector_idx)

    # -- 2-sector layout --------------------------------------------------

    def test_2_sectors_up(self):
        """T-1.11a: Minimum 2 sectors, up = sector 0."""
        self.assertEqual(angle_to_sector(0, -100, 2), 0)

    def test_2_sectors_down(self):
        """T-1.11b: Minimum 2 sectors, down = sector 1."""
        self.assertEqual(angle_to_sector(0, 100, 2), 1)

    def test_2_sectors_left_is_sector_0(self):
        """2 sectors: left (270 deg) wraps around to sector 0."""
        self.assertEqual(angle_to_sector(-100, 0, 2), 0)

    def test_2_sectors_right_is_sector_1(self):
        """2 sectors: right (90 deg) maps to sector 1."""
        self.assertEqual(angle_to_sector(100, 0, 2), 1)

    # -- 8-sector layout --------------------------------------------------

    def test_8_sectors_all_directions(self):
        """T-1.10: 8 sectors at all cardinal and ordinal directions."""
        r = 100
        # Sector 0 = N (up), 1 = NE, 2 = E, 3 = SE, 4 = S, 5 = SW, 6 = W, 7 = NW
        directions = [
            (0, -r),    # N  -> sector 0
            (r, -r),    # NE -> sector 1
            (r, 0),     # E  -> sector 2
            (r, r),     # SE -> sector 3
            (0, r),     # S  -> sector 4
            (-r, r),    # SW -> sector 5
            (-r, 0),    # W  -> sector 6
            (-r, -r),   # NW -> sector 7
        ]
        for expected_sector, (dx, dy) in enumerate(directions):
            with self.subTest(sector=expected_sector, dx=dx, dy=dy):
                result = angle_to_sector(dx, dy, 8)
                self.assertEqual(result, expected_sector)


# ---------------------------------------------------------------------------
# T-2: Controller State Machine
# ---------------------------------------------------------------------------

class ControllerStateMachineTests(unittest.TestCase):
    """Tests for ActionsRingController lifecycle and state transitions."""

    HOLD_MS = 200  # Short hold threshold for fast tests

    def _make_controller(self, slots=None, hold_ms=None):
        if slots is None:
            slots = ["action_0", "action_1", "action_2", "action_3"]
        if hold_ms is None:
            hold_ms = self.HOLD_MS

        self.execute_cb = Mock()
        self.play_haptic_cb = Mock()
        self.show_ring_cb = Mock()
        self.hide_ring_cb = Mock()
        self.get_cursor_pos_cb = Mock(return_value=(500, 500))

        return ActionsRingController(
            slots=slots,
            hold_ms=hold_ms,
            execute_cb=self.execute_cb,
            play_haptic_cb=self.play_haptic_cb,
            show_ring_cb=self.show_ring_cb,
            hide_ring_cb=self.hide_ring_cb,
            get_cursor_pos_cb=self.get_cursor_pos_cb,
        )

    # -- Cancelling a hold whose release was lost --------------------------

    def test_cancel_during_the_hold_delay_does_not_open_the_ring(self):
        # The event tap can be disabled by the system mid-press, losing the
        # release. Routed through on_button_up this reads as a quick tap and
        # leaves a ring on screen the user never asked for.
        ctrl = self._make_controller()
        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.WAITING)

        ctrl.cancel()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.show_ring_cb.assert_not_called()
        self.execute_cb.assert_not_called()

        # The hold timer went with it, so nothing opens a moment later either.
        time.sleep(self.HOLD_MS / 1000.0 * 2)
        self.show_ring_cb.assert_not_called()

    def test_cancel_with_the_ring_held_selects_nothing(self):
        ctrl = self._make_controller()
        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 * 1.5)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        ctrl.cancel()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called()
        self.execute_cb.assert_not_called()

    def test_a_cancel_racing_the_hold_timer_still_hides_the_ring(self):
        # The hold timer sets SHOWING_HELD under the lock and then shows the
        # ring outside it. A cancel landing in that gap used to hide a ring
        # that had not been shown yet, and the show then ran anyway -- leaving
        # it on screen with the controller IDLE, so nothing would ever take it
        # down. The tap can be disabled at any instant, so the two really can
        # coincide.
        ctrl = self._make_controller()
        calls = []
        show_started = threading.Event()
        release_show = threading.Event()

        def blocking_show(slots, interactive):
            show_started.set()
            release_show.wait(2.0)
            calls.append("show")

        ctrl._show_ring_cb = blocking_show
        ctrl._hide_ring_cb = lambda: calls.append("hide")

        timer_thread = threading.Thread(target=ctrl._on_hold_triggered)
        ctrl._state = ActionsRingController.WAITING
        timer_thread.start()
        self.assertTrue(show_started.wait(2.0), "show callback never ran")

        # Let the show finish while the cancel is in flight, so the test fails
        # rather than hangs if the two are not serialised.
        threading.Timer(0.05, release_show.set).start()
        ctrl.cancel()
        timer_thread.join(2.0)

        self.assertEqual(calls, ["show", "hide"])
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)

    def test_a_slow_action_does_not_block_the_next_press(self):
        # The selected action runs outside the ordering lock on purpose: it is
        # the user's own binding and can take as long as it likes. Run it
        # inside, and the press that follows waits for Mission Control to
        # finish animating before the ring will even arm.
        ctrl = self._make_controller()
        executing = threading.Event()
        release = threading.Event()
        self.execute_cb.side_effect = lambda _a: (
            executing.set(), release.wait(2.0)
        )

        ctrl._state = ActionsRingController.SHOWING_HELD
        ctrl._current_sector = 1
        selecting = threading.Thread(target=ctrl.on_button_up)
        selecting.start()
        try:
            self.assertTrue(executing.wait(2.0), "action never started")
            next_press = threading.Thread(target=ctrl.on_button_down)
            next_press.start()
            next_press.join(1.0)
            self.assertFalse(
                next_press.is_alive(),
                "the next press blocked behind the running action",
            )
            self.assertEqual(ctrl.state, ActionsRingController.WAITING)
        finally:
            release.set()
            selecting.join(2.0)
            ctrl.shutdown()

    # -- T-2.1: Initial state ---------------------------------------------

    def test_initial_state_is_idle(self):
        """T-2.1: A freshly created controller starts in IDLE state."""
        ctrl = self._make_controller()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)

    # -- Quick tap shows ring in toggle mode -------------------------------

    def test_quick_tap_shows_toggle_ring(self):
        """Quick tap (press then release before hold timer) shows ring in toggle mode."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.WAITING)

        time.sleep(0.050)
        ctrl.on_button_up()

        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)
        self.show_ring_cb.assert_called_once()
        args = self.show_ring_cb.call_args
        self.assertTrue(args[0][1])  # interactive=True
        self.play_haptic_cb.assert_called_once_with(0)
        self.execute_cb.assert_not_called()

    # -- Hold triggers ring in held mode -----------------------------------

    def test_hold_transitions_to_showing_held(self):
        """Holding past hold_ms transitions to SHOWING_HELD and shows ring."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)

        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)
        self.show_ring_cb.assert_called_once()
        args = self.show_ring_cb.call_args
        self.assertFalse(args[0][1])  # interactive=False
        self.play_haptic_cb.assert_called_once_with(0)

    # -- Release in dead zone cancels (held mode) --------------------------

    def test_release_in_dead_zone_cancels(self):
        """Releasing while SHOWING_HELD with sector=-1 cancels without execute."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        ctrl.on_button_up()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_not_called()
        self.play_haptic_cb.assert_called_once_with(0)

    # -- Release on valid sector executes (held mode) ----------------------

    def test_release_on_valid_sector_executes(self):
        """Releasing on a valid sector in held mode executes the slot's action."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        ctrl.set_current_sector(2)
        ctrl.on_button_up()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_called_once_with("action_2")
        self.assertEqual(self.play_haptic_cb.call_count, 2)
        self.play_haptic_cb.assert_any_call(0)
        self.play_haptic_cb.assert_any_call(7)

    # -- sector_override parameter -----------------------------------------

    def test_release_with_sector_override(self):
        """on_button_up(sector_override=N) uses the override instead of current_sector."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)

        ctrl.set_current_sector(0)
        ctrl.on_button_up(sector_override=3)

        self.execute_cb.assert_called_once_with("action_3")

    # -- set_current_sector ------------------------------------------------

    def test_set_current_sector_updates_sector(self):
        """set_current_sector() updates the sector used on release."""
        ctrl = self._make_controller()

        self.assertEqual(ctrl.current_sector, -1)
        ctrl.set_current_sector(2)
        self.assertEqual(ctrl.current_sector, 2)
        ctrl.set_current_sector(-1)
        self.assertEqual(ctrl.current_sector, -1)

    # -- Toggle mode: second tap dismisses ---------------------------------

    def test_toggle_second_tap_dismisses(self):
        """Pressing trigger button again in SHOWING_TOGGLE dismisses ring."""
        ctrl = self._make_controller()

        # Quick tap to show ring in toggle mode
        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        # Second press dismisses
        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_not_called()

    # -- Toggle mode: button_up is no-op -----------------------------------

    def test_button_up_in_toggle_mode_is_noop(self):
        """on_button_up() while SHOWING_TOGGLE does nothing (ring stays open)."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        # Release from the dismiss press — no-op since state is now IDLE
        # (The dismiss press already moved to IDLE, so this tests a fresh up)
        ctrl2 = self._make_controller()
        ctrl2.on_button_down()
        time.sleep(0.050)
        ctrl2.on_button_up()
        self.assertEqual(ctrl2.state, ActionsRingController.SHOWING_TOGGLE)

        # Another up while still in SHOWING_TOGGLE
        ctrl2.on_button_up()
        self.assertEqual(ctrl2.state, ActionsRingController.SHOWING_TOGGLE)
        self.hide_ring_cb.assert_not_called()

    # -- Toggle select executes and hides ----------------------------------

    def test_on_toggle_select_executes_and_hides(self):
        """on_toggle_select() executes the action for the sector and hides ring."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        ctrl.on_toggle_select(1)

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_called_once_with("action_1")
        self.play_haptic_cb.assert_any_call(7)

    # -- Toggle select with invalid sector hides without executing ---------

    def test_on_toggle_select_invalid_sector_hides_only(self):
        """on_toggle_select() with out-of-range sector hides without executing."""
        ctrl = self._make_controller(slots=["a", "b"])

        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()

        ctrl.on_toggle_select(5)

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_not_called()

    # -- Toggle dismiss hides without executing ----------------------------

    def test_on_toggle_dismiss_hides_without_action(self):
        """on_toggle_dismiss() hides ring without executing any action."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        ctrl.on_toggle_dismiss()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_not_called()

    # -- Toggle select/dismiss while not toggle is no-op -------------------

    def test_on_toggle_select_while_idle_is_noop(self):
        """on_toggle_select() while IDLE does nothing."""
        ctrl = self._make_controller()
        ctrl.on_toggle_select(0)
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.execute_cb.assert_not_called()

    def test_on_toggle_dismiss_while_idle_is_noop(self):
        """on_toggle_dismiss() while IDLE does nothing."""
        ctrl = self._make_controller()
        ctrl.on_toggle_dismiss()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_not_called()

    # -- on_click (single-fire buttons) ------------------------------------

    def test_on_click_shows_toggle_ring(self):
        """on_click() from IDLE shows ring in toggle mode."""
        ctrl = self._make_controller()

        ctrl.on_click()

        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)
        self.show_ring_cb.assert_called_once()
        args = self.show_ring_cb.call_args
        self.assertTrue(args[0][1])  # interactive=True
        self.play_haptic_cb.assert_called_once_with(0)

    def test_on_click_toggles_off(self):
        """on_click() while SHOWING_TOGGLE dismisses ring."""
        ctrl = self._make_controller()

        ctrl.on_click()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        ctrl.on_click()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()

    # -- Button up while IDLE is a no-op -----------------------------------

    def test_button_up_while_idle_is_noop(self):
        """on_button_up() while IDLE does nothing and does not crash."""
        ctrl = self._make_controller()

        ctrl.on_button_up()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.execute_cb.assert_not_called()
        self.show_ring_cb.assert_not_called()
        self.hide_ring_cb.assert_not_called()
        self.play_haptic_cb.assert_not_called()

    # -- Shutdown ----------------------------------------------------------

    def test_shutdown_cancels_timer_resets_idle(self):
        """shutdown() while WAITING cancels the timer and resets to IDLE."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.WAITING)

        ctrl.shutdown()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)
        self.show_ring_cb.assert_not_called()
        self.play_haptic_cb.assert_not_called()

    def test_shutdown_while_showing_held_hides_ring(self):
        """Shutdown while SHOWING_HELD calls hide_ring_cb and resets to IDLE."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        ctrl.shutdown()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()

    def test_shutdown_while_showing_toggle_hides_ring(self):
        """Shutdown while SHOWING_TOGGLE calls hide_ring_cb and resets to IDLE."""
        ctrl = self._make_controller()

        ctrl.on_click()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)

        ctrl.shutdown()

        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.hide_ring_cb.assert_called_once()

    # -- Release on out-of-range sector does not execute -------------------

    def test_release_on_out_of_range_sector_does_not_execute(self):
        """Releasing with a sector >= len(slots) does not execute."""
        ctrl = self._make_controller(slots=["a", "b"])

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)

        ctrl.set_current_sector(5)  # out of range
        ctrl.on_button_up()

        self.hide_ring_cb.assert_called_once()
        self.execute_cb.assert_not_called()

    # -- resolve_sector delegates to angle_to_sector -----------------------

    def test_resolve_sector_computes_from_anchor(self):
        """resolve_sector() converts cursor position relative to anchor."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        time.sleep(self.HOLD_MS / 1000.0 + 0.100)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        anchor = ctrl.anchor_pos
        self.assertIsNotNone(anchor)

        # Cursor directly above anchor -> sector 0
        sector = ctrl.resolve_sector(anchor[0], anchor[1] - 100)
        self.assertEqual(sector, 0)
        self.assertEqual(ctrl.current_sector, 0)

    def test_resolve_sector_without_anchor_returns_neg1(self):
        """resolve_sector() returns -1 when no anchor is set."""
        ctrl = self._make_controller()
        sector = ctrl.resolve_sector(100, 100)
        self.assertEqual(sector, -1)

    # -- Double button_down is ignored while not IDLE ----------------------

    def test_double_button_down_ignored(self):
        """A second on_button_down() while WAITING is a no-op."""
        ctrl = self._make_controller()

        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.WAITING)

        ctrl.on_button_down()  # should be ignored
        self.assertEqual(ctrl.state, ActionsRingController.WAITING)

        ctrl.shutdown()

    # -- Full cycle: tap → toggle → re-tap cycle --------------------------

    def test_full_toggle_cycle(self):
        """Full cycle: tap shows ring, second tap dismisses, third tap shows again."""
        ctrl = self._make_controller()

        # Tap 1: show ring
        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)
        self.assertEqual(self.show_ring_cb.call_count, 1)

        # Tap 2: dismiss ring
        ctrl.on_button_down()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        self.assertEqual(self.hide_ring_cb.call_count, 1)
        ctrl.on_button_up()  # no-op since IDLE

        # Tap 3: show ring again
        ctrl.on_button_down()
        time.sleep(0.050)
        ctrl.on_button_up()
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_TOGGLE)
        self.assertEqual(self.show_ring_cb.call_count, 2)


# ---------------------------------------------------------------------------
# T-3: Controller Threading
# ---------------------------------------------------------------------------

class ControllerThreadingTests(unittest.TestCase):
    """Stress tests for thread safety of ActionsRingController."""

    def test_rapid_toggle_stress(self):
        """T-3.1: 50 rapid down/up cycles from a thread pool, no crashes."""
        execute_cb = Mock()
        play_haptic_cb = Mock()
        show_ring_cb = Mock()
        hide_ring_cb = Mock()

        ctrl = ActionsRingController(
            slots=["a", "b", "c", "d"],
            hold_ms=200,
            execute_cb=execute_cb,
            play_haptic_cb=play_haptic_cb,
            show_ring_cb=show_ring_cb,
            hide_ring_cb=hide_ring_cb,
        )

        errors = []

        def press_release():
            try:
                ctrl.on_button_down()
                time.sleep(0.005)
                ctrl.on_button_up()
            except Exception as exc:
                errors.append(exc)

        threads = []
        for _ in range(50):
            t = threading.Thread(target=press_release)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [])
        ctrl.shutdown()
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)

    def test_shutdown_during_showing_held_from_different_thread(self):
        """T-3.3: Shutdown from a different thread while ring is SHOWING_HELD."""
        execute_cb = Mock()
        play_haptic_cb = Mock()
        show_ring_cb = Mock()
        hide_ring_cb = Mock()

        ctrl = ActionsRingController(
            slots=["a", "b", "c", "d"],
            hold_ms=100,
            execute_cb=execute_cb,
            play_haptic_cb=play_haptic_cb,
            show_ring_cb=show_ring_cb,
            hide_ring_cb=hide_ring_cb,
        )

        ctrl.on_button_down()
        time.sleep(0.200)
        self.assertEqual(ctrl.state, ActionsRingController.SHOWING_HELD)

        shutdown_errors = []

        def shutdown_from_thread():
            try:
                ctrl.shutdown()
            except Exception as exc:
                shutdown_errors.append(exc)

        t = threading.Thread(target=shutdown_from_thread)
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(shutdown_errors, [])
        self.assertEqual(ctrl.state, ActionsRingController.IDLE)
        hide_ring_cb.assert_called()


# ---------------------------------------------------------------------------
# Engine routing of a cancelled release
# ---------------------------------------------------------------------------

class EngineCancelledReleaseTests(unittest.TestCase):
    """The hook synthesises a button-up when it loses the real one to a
    disabled event tap. The engine has to tell that apart from a release the
    user made, or a system hiccup selects a sector or opens the ring."""

    def _route(self, raw_data):
        """Run `_on_ring_button_up` unbound; a whole Engine is not needed."""
        from core.engine import Engine

        ring = Mock()
        engine = SimpleNamespace(
            _ring=ring, _ring_sector_cb=Mock(return_value=2)
        )
        event = SimpleNamespace(raw_data=raw_data)
        Engine._on_ring_button_up(engine, ring, event)
        return ring

    def test_a_cancelled_release_selects_nothing(self):
        ring = self._route({"cancelled": True})

        ring.cancel.assert_called_once()
        ring.on_button_up.assert_not_called()

    def test_a_real_release_still_selects_the_overlay_sector(self):
        ring = self._route(None)

        ring.on_button_up.assert_called_once_with(sector_override=2)
        ring.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# Overlay steering source (rawXY vs cursor)
# ---------------------------------------------------------------------------

class OverlaySteeringSourceTests(unittest.TestCase):
    """A held ring steers on HID++ rawXY, which only arrives while the
    control's divert is in force. When the divert has lapsed and the press is
    being served from the event tap instead, no delta ever arrives -- the
    offset stays at its (0, 0) seed, every sector resolves to the dead zone,
    and the ring opens and closes having selected nothing. It has to fall back
    to the cursor, which follows the same physical motion."""

    def _steer(self, offset, seen, cursor_sector=3):
        """Run `_steer_sector` against a stand-in for the overlay.

        Called unbound, because a real ActionsRingOverlay needs a
        QApplication and a window and neither takes any part in choosing the
        motion source. Returns (sector, stub) so a test can check which source
        was consulted.
        """
        from ui import actions_ring_overlay

        stub = SimpleNamespace(
            _rawxy_offset=offset,
            _rawxy_seen=seen,
            _slot_labels=["a", "b", "c", "d"],
            _cursor_to_sector=Mock(return_value=cursor_sector),
        )
        with patch.object(actions_ring_overlay, "QCursor") as cursor:
            cursor.pos.return_value = object()
            sector = actions_ring_overlay.ActionsRingOverlay._steer_sector(stub)
        return sector, stub

    def test_rawxy_steers_once_a_delta_has_arrived(self):
        sector, stub = self._steer(offset=(0, -200), seen=True)

        # Straight up, four slots -> sector 0, and the cursor is not consulted.
        self.assertEqual(sector, 0)
        stub._cursor_to_sector.assert_not_called()

    def test_cursor_steers_while_the_divert_is_down(self):
        # The regression: seeded offset, no rawXY, so the accumulated value is
        # a meaningless (0, 0) that would resolve to the dead zone forever.
        sector, stub = self._steer(offset=(0, 0), seen=False)

        self.assertEqual(sector, 3)
        stub._cursor_to_sector.assert_called_once()

    def test_interactive_mode_still_steers_on_the_cursor(self):
        sector, stub = self._steer(offset=None, seen=False)

        self.assertEqual(sector, 3)
        stub._cursor_to_sector.assert_called_once()


# ---------------------------------------------------------------------------
# Overlay steering lifecycle (wiring and the per-ring reset)
# ---------------------------------------------------------------------------

class OverlaySteeringLifecycleTests(unittest.TestCase):
    """`_steer_sector` only matters if the tick actually asks it, and if the
    flag it keys on is cleared per ring. A flag left set from a ring that did
    receive rawXY would send the next one back to steering on a stale offset,
    which is the dead-zone bug again with an extra step."""

    def _stub(self, cursor_sector=3, **overrides):
        """A stand-in with just the attributes the tick and show path touch.

        The real methods are called unbound against it: a live overlay needs a
        QApplication and a window, and neither takes any part in choosing the
        motion source or in resetting the flag.
        """
        stub = SimpleNamespace(
            _rawxy_offset=(0, 0),
            _rawxy_seen=False,
            _slot_labels=["a", "b", "c", "d"],
            _cursor_to_sector=Mock(return_value=cursor_sector),
            _tick_count=0,
            _target_sector=-1,
            _highlighted_sector=-1,
            _interactive=False,
            _appear_progress=1.0,
            _sector_reveal=[1.0] * 4,
            _sector_alphas=[0.0] * 4,
            _pulse_phase=0.0,
            _dismiss_progress=-1.0,
            _dismiss_step=0,
            _ring_diameter=220,
            _center=None,
            _tick_timer=Mock(),
            sector_changed=Mock(),
            update=Mock(),
            hide=Mock(),
            show=Mock(),
            raise_=Mock(),
            setFixedSize=Mock(),
            move=Mock(),
        )
        stub._steer_sector = lambda: self._overlay._steer_sector(stub)
        for k, v in overrides.items():
            setattr(stub, k, v)
        return stub

    @property
    def _overlay(self):
        from ui.actions_ring_overlay import ActionsRingOverlay

        return ActionsRingOverlay

    def _tick(self, stub):
        from ui import actions_ring_overlay

        with patch.object(actions_ring_overlay, "QCursor") as cursor:
            cursor.pos.return_value = object()
            actions_ring_overlay.ActionsRingOverlay._on_tick(stub)

    def _show(self, stub, interactive=False):
        from ui import actions_ring_overlay

        # No screen, so the clamp falls through to the unclamped position --
        # geometry is not what this is testing.
        with patch.object(actions_ring_overlay, "QApplication") as app, \
                patch.object(actions_ring_overlay, "QCursor"):
            app.screenAt.return_value = None
            app.screens.return_value = []
            actions_ring_overlay.ActionsRingOverlay.show_ring(
                stub, 100, 100, ["a", "b", "c", "d"], interactive=interactive
            )

    def test_the_tick_takes_its_sector_from_the_steering_source(self):
        # Straight up on rawXY is sector 0; the cursor would say 3. Catches a
        # revert to polling the cursor unconditionally.
        stub = self._stub(_rawxy_offset=(0, -200), _rawxy_seen=True)

        self._tick(stub)

        self.assertEqual(stub._target_sector, 0)
        stub.sector_changed.emit.assert_called_once_with(0)
        stub._cursor_to_sector.assert_not_called()

    def test_the_tick_falls_back_to_the_cursor_with_no_rawxy(self):
        stub = self._stub(_rawxy_offset=(0, 0), _rawxy_seen=False)

        self._tick(stub)

        self.assertEqual(stub._target_sector, 3)
        stub.sector_changed.emit.assert_called_once_with(3)

    def test_opening_a_ring_clears_a_flag_left_by_the_previous_one(self):
        # Previous ring was diverted and steered fine; this one is being
        # served from the event tap, so no delta will ever arrive.
        stub = self._stub(_rawxy_offset=(0, -200), _rawxy_seen=True)

        self._show(stub)

        self.assertEqual(stub._rawxy_offset, (0, 0))
        self.assertFalse(stub._rawxy_seen)

        self._tick(stub)
        self.assertEqual(stub._target_sector, 3)

    def test_an_interactive_ring_opens_with_no_rawxy_source_at_all(self):
        stub = self._stub(_rawxy_offset=(0, -200), _rawxy_seen=True)

        self._show(stub, interactive=True)

        self.assertIsNone(stub._rawxy_offset)
        self.assertFalse(stub._rawxy_seen)

    def test_the_flag_is_cleared_again_when_the_ring_finishes_dismissing(self):
        # Belt and braces with the reset in show_ring: hide_ring is reachable
        # on paths that never reopen through show_ring.
        from ui import actions_ring_overlay

        stub = self._stub(
            _rawxy_offset=(0, -200),
            _rawxy_seen=True,
            _dismiss_progress=0.0,
            _dismiss_step=actions_ring_overlay._DISMISS_FRAMES,
        )

        self._tick(stub)

        self.assertIsNone(stub._rawxy_offset)
        self.assertFalse(stub._rawxy_seen)
        stub.hide.assert_called_once()
        stub._tick_timer.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
