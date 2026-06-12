"""Tests for core.gesture_recognizer.GestureRecognizer.

These exercise the behaviour the recognizer exists to guarantee:

  * a clean swipe fires exactly once;
  * back-to-back flicks in one hold each register;
  * the return stroke between flicks never fires the opposite swipe;
  * slow drift while holding the button is ignored;
  * there is no dead window swallowing the start of the next swipe.
"""

from core.gesture_recognizer import GestureRecognizer, LEFT, RIGHT, UP, DOWN


# ── helpers ──────────────────────────────────────────────────────────

def make(enabled=True, threshold=50, commit_window_ms=400,
         settle_ms=90, cross_ratio=0.5):
    """Build a recognizer that records every swipe it emits in ``.swipes``."""
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
    """Sample each (dx, dy) in turn.

    The first sample lands ``gap`` (default ``step``) seconds after ``t``;
    every following sample is ``step`` seconds later. ``step`` (12 ms) is far
    below the 90 ms settle window, so a single feed() is one continuous
    stroke. Returns the final timestamp.
    """
    for i, (dx, dy) in enumerate(deltas):
        t += (gap if (gap is not None and i == 0) else step)
        rec.sample(dx, dy, source, now=t)
    return t


# A flick is a fast, continuous run of deltas covering well past the
# 50 px commit distance; a return is the same run reversed.
FLICK_LEFT = [(-10, 0)] * 7
FLICK_RIGHT = [(10, 0)] * 7
FLICK_UP = [(0, -10)] * 7
FLICK_DOWN = [(0, 10)] * 7
RETURN_RIGHT = [(10, 0)] * 7
RETURN_LEFT = [(-10, 0)] * 7


# ── basic recognition ────────────────────────────────────────────────

def test_single_left_swipe_fires_once():
    rec = make()
    rec.begin()
    feed(rec, FLICK_LEFT, t=0.0)
    assert rec.end() is False               # a swipe happened, not a click
    assert rec.swipes == [LEFT]


def test_each_direction_is_recognised():
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
        assert rec.swipes == [expected]


def test_one_long_continuous_motion_fires_only_once():
    """Holding a single sweep across the desk is one swipe, not many."""
    rec = make()
    rec.begin()
    feed(rec, [(-10, 0)] * 40, t=0.0)       # 400 px in one continuous push
    rec.end()
    assert rec.swipes == [LEFT]


# ── false-positive rejection ─────────────────────────────────────────

def test_slow_drift_does_not_fire():
    """Creeping the mouse while merely holding the button is not a swipe."""
    rec = make()
    rec.begin()
    # 70 px over 840 ms (~83 px/s) — well under the commit-speed gate.
    feed(rec, [(-1, 0)] * 70, t=0.0)
    rec.end()
    assert rec.swipes == []


def test_small_movement_below_threshold_does_not_fire():
    rec = make()
    rec.begin()
    feed(rec, [(-6, 0)] * 5, t=0.0)         # 30 px total, never reaches 50
    rec.end()
    assert rec.swipes == []


def test_steep_diagonal_is_rejected():
    rec = make()
    rec.begin()
    feed(rec, [(-9, -9)] * 8, t=0.0)        # 45 degrees — too ambiguous
    rec.end()
    assert rec.swipes == []


def test_mild_diagonal_still_resolves_to_dominant_axis():
    rec = make()
    rec.begin()
    feed(rec, [(-10, -3)] * 7, t=0.0)       # mostly left, slight up
    rec.end()
    assert rec.swipes == [LEFT]


# ── back-to-back repeats (the headline scenario) ─────────────────────

def test_repeated_left_flicks_in_one_hold_each_fire():
    """Hold the button and flick left, return, flick left, return, flick
    left — all in one continuous motion. Every flick must register and no
    return stroke may fire a right swipe."""
    rec = make()
    rec.begin()
    t = 0.0
    t = feed(rec, FLICK_LEFT, t)            # flick 1
    t = feed(rec, RETURN_RIGHT, t)          # return (must not fire RIGHT)
    t = feed(rec, FLICK_LEFT, t)            # flick 2
    t = feed(rec, RETURN_RIGHT, t)          # return (must not fire RIGHT)
    t = feed(rec, FLICK_LEFT, t)            # flick 3
    rec.end()
    assert rec.swipes == [LEFT, LEFT, LEFT]


def test_return_stroke_alone_never_fires_opposite():
    """A single flick followed only by a big, fast return to home position
    yields exactly one swipe."""
    rec = make()
    rec.begin()
    t = feed(rec, FLICK_LEFT, t=0.0)
    feed(rec, [(12, 0)] * 9, t)             # 108 px fast return right
    rec.end()
    assert rec.swipes == [LEFT]


def test_repeated_flicks_across_separate_holds():
    """Press / flick / release, repeated quickly, fires every time — there
    is no cooldown bleeding across button presses."""
    rec = make()
    t = 0.0
    for _ in range(4):
        rec.begin()
        t = feed(rec, FLICK_LEFT, t)
        assert rec.end() is False
        t += 0.03                           # tiny pause between presses
    assert rec.swipes == [LEFT, LEFT, LEFT, LEFT]


def test_direction_change_after_a_pause():
    """Once the motion settles, the hold unlocks and a new direction may
    be swiped."""
    rec = make()
    rec.begin()
    t = feed(rec, FLICK_LEFT, t=0.0)
    # Pause longer than the 90 ms settle window, then flick the other way.
    feed(rec, FLICK_RIGHT, t, gap=0.20)
    rec.end()
    assert rec.swipes == [LEFT, RIGHT]


def test_opposite_flick_within_a_locked_hold_is_absorbed():
    """Without a pause, the hold stays locked to the first direction, so a
    reversed flick is treated as a return stroke rather than a swipe."""
    rec = make()
    rec.begin()
    t = feed(rec, FLICK_LEFT, t=0.0)
    feed(rec, FLICK_RIGHT, t)               # continuous — no settle pause
    rec.end()
    assert rec.swipes == [LEFT]


# ── click vs swipe ───────────────────────────────────────────────────

def test_press_release_without_motion_is_a_click():
    rec = make()
    rec.begin()
    assert rec.end() is True


def test_press_release_with_tiny_motion_is_a_click():
    rec = make()
    rec.begin()
    feed(rec, [(-3, 0)] * 3, t=0.0)
    assert rec.end() is True


def test_hold_with_a_swipe_is_not_a_click():
    rec = make()
    rec.begin()
    feed(rec, FLICK_LEFT, t=0.0)
    assert rec.end() is False


# ── enable / source handling ─────────────────────────────────────────

def test_disabled_recognizer_emits_nothing():
    rec = make(enabled=False)
    rec.begin()
    feed(rec, FLICK_LEFT, t=0.0)
    assert rec.end() is True                # still a click candidate
    assert rec.swipes == []


def test_raw_xy_supersedes_event_tap_source():
    """An event-tap leg is discarded once a real raw-XY stream arrives, and
    later event-tap samples are ignored."""
    rec = make()
    rec.begin()
    t = feed(rec, [(-10, 0)] * 4, t=0.0, source="event_tap")   # partial
    t = feed(rec, FLICK_LEFT, t, source="hid_rawxy")           # the real one
    feed(rec, [(-40, 0)], t, source="event_tap")               # ignored
    rec.end()
    assert rec.swipes == [LEFT]


# ── click-jolt rejection (clicking the button jostles the mouse) ─────

def test_two_report_jolt_does_not_fire():
    """The button click jolts the mouse as a brief 1-2 report impulse.
    Even past the commit distance, that must stay a click, not a swipe."""
    rec = make()
    rec.begin()
    feed(rec, [(-34, 0), (-34, 0)], t=0.0)   # 68 px, only 2 reports
    assert rec.end() is True
    assert rec.swipes == []


def test_single_giant_report_does_not_fire():
    rec = make()
    rec.begin()
    feed(rec, [(-95, 5)], t=0.0)             # one big spike, one report
    assert rec.end() is True
    assert rec.swipes == []


def test_quick_flick_with_enough_reports_still_fires():
    """A genuine quick flick — short, but a sustained stream of reports —
    must still register."""
    rec = make()
    rec.begin()
    feed(rec, [(-14, 0)] * 5, t=0.0)         # 70 px over 5 reports
    rec.end()
    assert rec.swipes == [LEFT]


def test_summary_reports_hold_stats():
    rec = make()
    rec.begin()
    feed(rec, FLICK_LEFT, t=0.0)
    rec.end()
    s = rec.summary()
    assert s["fired"] == [LEFT]
    assert s["samples"] == len(FLICK_LEFT)
    assert s["net_x"] < 0
    assert s["source"] == "hid_rawxy"
