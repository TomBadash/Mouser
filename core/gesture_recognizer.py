"""
core/gesture_recognizer.py — stroke-aware swipe recognizer for the gesture button.

Replaces the previous fixed-pixel-threshold accumulator. That design summed
every movement delta into one running total and fired a swipe whenever the
total crossed a threshold, then blocked all input for a fixed "cooldown".
It produced three problems this module is built to eliminate:

  * Missed inputs — the cooldown swallowed the start of the next swipe, so
    repeated swipes had to be performed slowly and deliberately.
  * False positives — slow drift while merely holding the button summed up
    past the threshold; and the motion that returns the mouse between two
    swipes ("return stroke") triggered a swipe in the opposite direction.
  * No real repeats — you could not hold the button and flick the same way
    several times in a row to page through views.

Approach
--------
The recognizer never integrates position into one global sum. It segments
the motion into *strokes* and judges each stroke on its own:

  begin()                 — gesture button pressed; start a fresh hold.
  sample(dx, dy)          — one movement report captured while held.
  end() -> bool           — button released; True == it was a plain click.

A stroke ends when the pointer pauses (`settle_ms` of no movement) or
sharply reverses. A stroke *commits* a swipe when it travels
`commit_distance` along one axis, quickly enough (within `commit_window_ms`
— this rejects slow drift), straight enough (off-axis travel within
`cross_ratio`), and across enough movement reports that the brief jolt of
clicking the button cannot be mistaken for a swipe.

The first swipe of a hold locks the hold to that axis and direction. After
that the recognizer runs a peak detector on the locked axis: every fresh
flick in the locked direction fires again, while the return strokes between
flicks only re-arm it — they can never fire, not even the opposite swipe.
A pause (`settle_ms`) clears the lock so a different direction can be used.

The class has no Qt / HID / platform imports so it is unit-tested directly
and shared unchanged by the macOS, Windows and Linux hooks.
"""

import math
import threading
import time

__all__ = ["GestureRecognizer", "LEFT", "RIGHT", "UP", "DOWN"]

LEFT = "left"
RIGHT = "right"
UP = "up"
DOWN = "down"

# Off-axis travel always tolerated on top of the cross_ratio allowance, so a
# short swipe is not rejected over a few stray pixels of hand wobble.
_CROSS_FLOOR = 14.0

# Minimum spacing between two emitted swipes — debounce only. Real repeats
# (return stroke + fresh flick) are always far slower than this.
_REFRACTORY_S = 0.09

# A turnaround only counts once the motion has reversed by this much; smaller
# jitter does not move the tracked extreme, so a noisy sensor cannot restart
# a flick mid-stroke.
_TURN_HYST = 4.0

# A stroke must span at least this many movement reports before it can commit
# a swipe. Pressing/releasing the gesture button jolts the mouse as a brief
# 1-2 report impulse; a real swipe is a sustained stream of reports. This
# (together with reversal detection) keeps a plain click from firing a swipe.
_MIN_SAMPLES = 4


def _axis_of(direction):
    return "x" if direction in (LEFT, RIGHT) else "y"


def _sign_of(direction):
    # Screen coordinates: left / up are negative, right / down are positive.
    return -1 if direction in (LEFT, UP) else 1


class GestureRecognizer:
    """Turns a stream of held-button movement deltas into swipe events.

    Feed ``begin()`` on button-down, ``sample(dx, dy)`` for every movement
    report while the button is held, and ``end()`` on button-up. Recognized
    swipes are delivered through the ``on_swipe(direction)`` callback, where
    direction is one of ``LEFT`` / ``RIGHT`` / ``UP`` / ``DOWN``.

    All public methods are thread-safe; callbacks are invoked *outside* the
    internal lock so they may safely call back into the owning hook.
    """

    # Detection phases.
    _IDLE = "idle"      # no swipe committed yet this hold — free detection.
    _LOCKED = "locked"  # a swipe fired — repeats locked to that axis + dir.

    def __init__(self, on_swipe=None, on_debug=None):
        self._on_swipe = on_swipe
        self._on_debug = on_debug
        self._lock = threading.Lock()

        # Configuration — see configure().
        self._enabled = False
        self._commit_distance = 50.0
        self._commit_window = 0.40
        self._settle = 0.09
        self._cross_ratio = 0.5
        self._dir_eps = 7.5            # derived: motion needed to start a leg
        self._min_return = 22.5        # derived: return needed to arm a repeat

        self._reset_hold()

    # ── configuration ────────────────────────────────────────────────

    def configure(self, *, enabled, threshold, commit_window_ms,
                  settle_ms, cross_ratio):
        """Apply user-tunable gesture settings.

        threshold         — px of travel along the dominant axis to fire.
        commit_window_ms  — that travel must complete this fast (drift gate).
        settle_ms         — no-movement gap that ends a stroke / clears lock.
        cross_ratio       — off-axis travel tolerated, as a fraction of the
                            dominant-axis travel.
        """
        with self._lock:
            self._enabled = bool(enabled)
            self._commit_distance = max(8.0, float(threshold))
            self._commit_window = max(0.05, float(commit_window_ms) / 1000.0)
            self._settle = max(0.02, float(settle_ms) / 1000.0)
            self._cross_ratio = min(2.0, max(0.05, float(cross_ratio)))
            # Derived thresholds scale with the commit distance.
            self._dir_eps = max(5.0, self._commit_distance * 0.15)
            self._min_return = max(14.0, self._commit_distance * 0.45)

    # ── per-hold lifecycle ───────────────────────────────────────────

    def begin(self):
        """Gesture button pressed — discard any prior state, start fresh."""
        with self._lock:
            self._reset_hold()
            self._active = True

    def end(self):
        """Gesture button released.

        Returns True when the hold produced no swipe and should therefore be
        treated as a plain gesture-button click.
        """
        with self._lock:
            was_click = self._active and not self._fired_any
            self._active = False
            self._phase = self._IDLE
        return was_click

    def sample(self, dx, dy, source="hid_rawxy", now=None):
        """Feed one movement delta captured while the button is held."""
        if now is None:
            now = time.monotonic()
        fires = []
        debugs = []
        with self._lock:
            if not (self._active and self._enabled):
                return
            if dx == 0 and dy == 0:
                return
            if not self._accept_source(source):
                return
            self._step(float(dx), float(dy), now, fires, debugs)
        # Callbacks run outside the lock.
        for event in debugs:
            self._emit_debug(event)
        for direction in fires:
            self._emit_swipe(direction)

    @property
    def fired(self):
        """True once a swipe has fired during the current / last hold."""
        with self._lock:
            return self._fired_any

    def summary(self):
        """Diagnostics for the current / most-recently-ended hold.

        Returned as a dict so the hook can print a one-line ``[Gesture]``
        trace on button-up — the quickest way to tune swipe-vs-click feel
        against real hardware.
        """
        with self._lock:
            duration_ms = 0.0
            if self._hold_first_t is not None and self._last_t is not None:
                duration_ms = (self._last_t - self._hold_first_t) * 1000.0
            return {
                "samples": self._hold_samples,
                "duration_ms": duration_ms,
                "net_x": self._cx,
                "net_y": self._cy,
                "peak_speed": self._hold_peak_speed,
                "source": self._source,
                "fired": list(self._hold_fired),
            }

    # ── internal: state management ───────────────────────────────────

    def _reset_hold(self):
        """Clear all per-hold state. Caller holds the lock."""
        self._phase = self._IDLE
        self._active = False
        self._fired_any = False
        self._source = None
        self._last_t = None
        self._last_fire_t = -1.0
        # Cumulative pointer position since begin().
        self._cx = 0.0
        self._cy = 0.0
        # Per-hold diagnostics, surfaced by summary().
        self._hold_samples = 0
        self._hold_first_t = None
        self._hold_peak_speed = 0.0
        self._hold_fired = []
        self._reset_leg(0.0, 0.0)
        # LOCKED-phase peak-detector state.
        self._lock_axis = None
        self._lock_sign = 0
        self._latch_anchor = 0.0       # locked-axis position where it fired
        self._latch_extreme = 0.0      # furthest point of the return stroke
        self._latch_off_at_turn = 0.0  # off-axis position at that turnaround
        self._latch_turn_t = 0.0       # time of that turnaround
        self._latch_return_seen = False

    def _reset_leg(self, at_x, at_y):
        """Re-base the free-detection leg at the given position."""
        self._pivot_x = at_x
        self._pivot_y = at_y
        self._pivot_t = None           # set when motion actually starts
        self._leg_peak = 0.0
        self._leg_samples = 0          # movement reports in the current leg

    def _accept_source(self, source):
        """Source arbitration: lock to the first source; a real raw-XY
        stream supersedes a coarse fallback (event-tap / evdev)."""
        if self._source == source:
            return True
        if self._source is None:
            self._source = source
            return True
        if source == "hid_rawxy":
            # Promote: discard whatever the fallback source accumulated.
            self._source = source
            self._phase = self._IDLE
            self._lock_axis = None
            self._lock_sign = 0
            self._reset_leg(self._cx, self._cy)
            return True
        return False

    # ── internal: the recognizer ─────────────────────────────────────

    def _step(self, dx, dy, now, fires, debugs):
        # Per-hold diagnostics (surfaced by summary()).
        self._hold_samples += 1
        if self._hold_first_t is None:
            self._hold_first_t = now
        if self._last_t is not None:
            dt = now - self._last_t
            if dt > 0:
                speed = math.hypot(dx, dy) / dt
                if speed > self._hold_peak_speed:
                    self._hold_peak_speed = speed

        # A long-enough gap with no movement ends the current stroke and
        # clears the hold's axis lock — the next stroke is judged afresh.
        if self._last_t is not None and (now - self._last_t) > self._settle:
            self._phase = self._IDLE
            self._lock_axis = None
            self._lock_sign = 0
            self._reset_leg(self._cx, self._cy)
        self._last_t = now

        self._cx += dx
        self._cy += dy

        if self._phase == self._LOCKED:
            self._step_locked(now, fires, debugs)
        else:
            self._step_free(now, fires, debugs)

    def _step_free(self, now, fires, debugs):
        """Pre-lock detection: watch one free stroke for the first swipe."""
        leg_x = self._cx - self._pivot_x
        leg_y = self._cy - self._pivot_y
        leg_len = math.hypot(leg_x, leg_y)

        # Wait for the leg to actually start moving before timing it.
        if self._pivot_t is None:
            if leg_len < self._dir_eps:
                return
            self._pivot_t = now
            self._leg_peak = leg_len
            self._leg_samples = 1
            debugs.append({"type": "tracking_started", "source": self._source})
        else:
            self._leg_samples += 1

        # A leg that shrinks back toward its pivot means the motion reversed
        # or stalled — re-base so the new direction gets a clean stroke.
        if leg_len < self._leg_peak - self._dir_eps:
            self._reset_leg(self._cx, self._cy)
            return
        self._leg_peak = max(self._leg_peak, leg_len)

        debugs.append({"type": "segment", "source": self._source,
                       "dx": leg_x, "dy": leg_y})

        # A leg that takes too long to reach commit distance is drift, not a
        # swipe — re-base and keep watching.
        if (now - self._pivot_t) > self._commit_window:
            self._reset_leg(self._cx, self._cy)
            return

        direction = self._evaluate_leg(leg_x, leg_y)
        if direction is None:
            return
        if self._leg_samples < _MIN_SAMPLES:
            # Far and fast enough to look like a swipe, but carried by too
            # few movement reports — this is the jolt of clicking the
            # button, not a sustained stroke. Hold off; if the motion is
            # real the next reports will commit it.
            return
        if not self._fire(direction, now, leg_x, leg_y, fires, debugs):
            return

        # First swipe of the hold — lock to this axis + direction. From now
        # on only this direction repeats; return strokes cannot fire.
        self._phase = self._LOCKED
        self._lock_axis = _axis_of(direction)
        self._lock_sign = _sign_of(direction)
        pos = self._cx if self._lock_axis == "x" else self._cy
        off = self._cy if self._lock_axis == "x" else self._cx
        self._latch_anchor = pos
        self._latch_extreme = pos
        self._latch_off_at_turn = off
        self._latch_turn_t = now
        self._latch_return_seen = False

    def _step_locked(self, now, fires, debugs):
        """Post-lock detection: a peak detector on the locked axis.

        Travel in the locked direction is a fresh flick; travel the other way
        is a return stroke that only re-arms the detector. The opposite swipe
        can never fire while the hold is locked.
        """
        axis = self._lock_axis
        sign = self._lock_sign
        pos = self._cx if axis == "x" else self._cy
        off = self._cy if axis == "x" else self._cx

        # Track the turnaround: the point furthest along the return stroke.
        # The committed swipe's own decelerating tail moves further in the
        # locked direction and is deliberately ignored here.
        if sign * pos < sign * self._latch_extreme - _TURN_HYST:
            self._latch_extreme = pos
            self._latch_off_at_turn = off
            self._latch_turn_t = now

        # The return must travel far enough to count as a genuine turnaround
        # before the next flick is allowed to fire.
        return_amount = sign * (self._latch_anchor - self._latch_extreme)
        if return_amount >= self._min_return:
            self._latch_return_seen = True

        # Flick = travel in the locked direction measured from the turnaround.
        flick = sign * (pos - self._latch_extreme)
        off_flick = off - self._latch_off_at_turn

        debugs.append({
            "type": "segment", "source": self._source,
            "dx": (pos - self._latch_extreme) if axis == "x" else off_flick,
            "dy": (pos - self._latch_extreme) if axis == "y" else off_flick,
        })

        if not self._latch_return_seen:
            return
        if flick < self._commit_distance:
            return
        if (now - self._latch_turn_t) > self._commit_window:
            # The flick was too slow to be deliberate — re-arm from here.
            self._latch_anchor = pos
            self._latch_extreme = pos
            self._latch_off_at_turn = off
            self._latch_turn_t = now
            self._latch_return_seen = False
            return
        if abs(off_flick) > self._cross_ratio * flick + _CROSS_FLOOR:
            return

        direction = self._locked_direction()
        seg_x = (pos - self._latch_extreme) if axis == "x" else off_flick
        seg_y = (pos - self._latch_extreme) if axis == "y" else off_flick
        if not self._fire(direction, now, seg_x, seg_y, fires, debugs):
            return
        # Re-arm for the next repeat from the current point.
        self._latch_anchor = pos
        self._latch_extreme = pos
        self._latch_off_at_turn = off
        self._latch_turn_t = now
        self._latch_return_seen = False

    def _evaluate_leg(self, leg_x, leg_y):
        """Return a swipe direction if (leg_x, leg_y) commits, else None.

        The caller has already enforced the speed (commit_window) gate.
        """
        abs_x = abs(leg_x)
        abs_y = abs(leg_y)
        if abs_x >= abs_y:
            dominant, cross = abs_x, abs_y
            direction = RIGHT if leg_x > 0 else LEFT
        else:
            dominant, cross = abs_y, abs_x
            direction = DOWN if leg_y > 0 else UP
        if dominant < self._commit_distance:
            return None                            # not far enough yet
        if cross > self._cross_ratio * dominant + _CROSS_FLOOR:
            return None                            # too diagonal to be sure
        return direction

    def _locked_direction(self):
        if self._lock_axis == "x":
            return RIGHT if self._lock_sign > 0 else LEFT
        return DOWN if self._lock_sign > 0 else UP

    def _fire(self, direction, now, seg_x, seg_y, fires, debugs):
        """Record a recognized swipe. Returns False if debounced away."""
        if (now - self._last_fire_t) < _REFRACTORY_S:
            return False
        self._last_fire_t = now
        self._fired_any = True
        self._hold_fired.append(direction)
        fires.append(direction)
        debugs.append({
            "type": "detected",
            "event_name": "gesture_swipe_" + direction,
            "source": self._source,
            "dx": seg_x,
            "dy": seg_y,
        })
        return True

    # ── internal: callbacks ──────────────────────────────────────────

    def _emit_swipe(self, direction):
        if self._on_swipe is None:
            return
        try:
            self._on_swipe(direction)
        except Exception as exc:                   # pragma: no cover
            print(f"[GestureRecognizer] swipe callback error: {exc}")

    def _emit_debug(self, event):
        if self._on_debug is None:
            return
        try:
            self._on_debug(event)
        except Exception:                          # pragma: no cover
            pass
