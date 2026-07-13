"""Tests for core.gesture_recognizer.GestureRecognizer."""

import unittest

from core.gesture_recognizer import GestureRecognizer, LEFT, RIGHT, UP, DOWN


def make(enabled=True, threshold=50, commit_window_ms=400,
         settle_ms=90, cross_ratio=0.5):
    swipes = []
    rec = GestureRecognizer(on_swipe=swipes.append)
    rec.configure(
        enabled=enabled,
        threshold=threshold,
        commit_window_ms=commit_window_ms,
        settle_ms=settle_ms,
        cross_ratio=cross_ratio,
    )
    rec.swipes = swipes
    return rec


def feed(rec, deltas, t, step=0.012, gap=None, source="hid_rawxy"):
    for i, (dx, dy) in enumerate(deltas):
        t += (gap if (gap is not None and i == 0) else step)
        rec.sample(dx, dy, source, now=t)
    return t


FLICK_LEFT = [(-10, 0)] * 7
FLICK_RIGHT = [(10, 0)] * 7
FLICK_UP = [(0, -10)] * 7
FLICK_DOWN = [(0, 10)] * 7
RETURN_RIGHT = [(10, 0)] * 7
RETURN_LEFT = [(-10, 0)] * 7


class BasicRecognitionTests(unittest.TestCase):
    def test_single_left_swipe_fires_once(self):
        rec = make()
        rec.begin()
        feed(rec, FLICK_LEFT, t=0.0)
        self.assertFalse(rec.end())
        self.assertEqual(rec.swipes, [LEFT])

    def test_each_direction_is_recognised(self):
        for flick, expected in (
            (FLICK_LEFT, LEFT),
            (FLICK_RIGHT, RIGHT),
            (FLICK_UP, UP),
            (FLICK_DOWN, DOWN),
        ):
            rec = make()
            rec.begin()
            feed(rec, flick, t=0.0)
            rec.end()
            self.assertEqual(rec.swipes, [expected])

    def test_one_long_continuous_motion_fires_only_once(self):
        rec = make()
        rec.begin()
        feed(rec, [(-10, 0)] * 40, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])


class FalsePositiveRejectionTests(unittest.TestCase):
    def test_slow_drift_does_not_fire(self):
        rec = make()
        rec.begin()
        feed(rec, [(-1, 0)] * 70, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [])

    def test_small_movement_below_threshold_does_not_fire(self):
        rec = make()
        rec.begin()
        feed(rec, [(-6, 0)] * 5, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [])

    def test_steep_diagonal_is_rejected(self):
        rec = make()
        rec.begin()
        feed(rec, [(-9, -9)] * 8, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [])

    def test_mild_diagonal_still_resolves_to_dominant_axis(self):
        rec = make()
        rec.begin()
        feed(rec, [(-10, -3)] * 7, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])


class RepeatFlickTests(unittest.TestCase):
    def test_repeated_left_flicks_in_one_hold_each_fire(self):
        rec = make()
        rec.begin()
        t = 0.0
        t = feed(rec, FLICK_LEFT, t)
        t = feed(rec, RETURN_RIGHT, t)
        t = feed(rec, FLICK_LEFT, t)
        t = feed(rec, RETURN_RIGHT, t)
        t = feed(rec, FLICK_LEFT, t)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT, LEFT, LEFT])

    def test_return_stroke_alone_never_fires_opposite(self):
        rec = make()
        rec.begin()
        t = feed(rec, FLICK_LEFT, t=0.0)
        feed(rec, [(12, 0)] * 9, t)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])

    def test_repeated_flicks_across_separate_holds(self):
        rec = make()
        t = 0.0
        for _ in range(4):
            rec.begin()
            t = feed(rec, FLICK_LEFT, t)
            self.assertFalse(rec.end())
            t += 0.03
        self.assertEqual(rec.swipes, [LEFT, LEFT, LEFT, LEFT])

    def test_direction_change_after_a_pause(self):
        rec = make()
        rec.begin()
        t = feed(rec, FLICK_LEFT, t=0.0)
        feed(rec, FLICK_RIGHT, t, gap=0.20)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT, RIGHT])

    def test_opposite_flick_within_a_locked_hold_is_absorbed(self):
        rec = make()
        rec.begin()
        t = feed(rec, FLICK_LEFT, t=0.0)
        feed(rec, FLICK_RIGHT, t)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])


class ClickVsSwipeTests(unittest.TestCase):
    def test_press_release_without_motion_is_a_click(self):
        rec = make()
        rec.begin()
        self.assertTrue(rec.end())

    def test_press_release_with_tiny_motion_is_a_click(self):
        rec = make()
        rec.begin()
        feed(rec, [(-3, 0)] * 3, t=0.0)
        self.assertTrue(rec.end())

    def test_hold_with_a_swipe_is_not_a_click(self):
        rec = make()
        rec.begin()
        feed(rec, FLICK_LEFT, t=0.0)
        self.assertFalse(rec.end())


class EnableAndSourceTests(unittest.TestCase):
    def test_disabled_recognizer_emits_nothing(self):
        rec = make(enabled=False)
        rec.begin()
        feed(rec, FLICK_LEFT, t=0.0)
        self.assertTrue(rec.end())
        self.assertEqual(rec.swipes, [])

    def test_raw_xy_supersedes_event_tap_source(self):
        rec = make()
        rec.begin()
        t = feed(rec, [(-10, 0)] * 4, t=0.0, source="event_tap")
        t = feed(rec, FLICK_LEFT, t, source="hid_rawxy")
        feed(rec, [(-40, 0)], t, source="event_tap")
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])


class ClickJoltRejectionTests(unittest.TestCase):
    def test_two_report_jolt_does_not_fire(self):
        rec = make()
        rec.begin()
        feed(rec, [(-34, 0), (-34, 0)], t=0.0)
        self.assertTrue(rec.end())
        self.assertEqual(rec.swipes, [])

    def test_single_giant_report_does_not_fire(self):
        rec = make()
        rec.begin()
        feed(rec, [(-95, 5)], t=0.0)
        self.assertTrue(rec.end())
        self.assertEqual(rec.swipes, [])

    def test_quick_flick_with_enough_reports_still_fires(self):
        rec = make()
        rec.begin()
        feed(rec, [(-14, 0)] * 5, t=0.0)
        rec.end()
        self.assertEqual(rec.swipes, [LEFT])


class SummaryTests(unittest.TestCase):
    def test_summary_reports_hold_stats(self):
        rec = make()
        rec.begin()
        feed(rec, FLICK_LEFT, t=0.0)
        rec.end()
        s = rec.summary()
        self.assertEqual(s["fired"], [LEFT])
        self.assertEqual(s["samples"], len(FLICK_LEFT))
        self.assertLess(s["net_x"], 0)
        self.assertEqual(s["source"], "hid_rawxy")


if __name__ == "__main__":
    unittest.main()
