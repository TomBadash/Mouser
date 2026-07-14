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

_CROSS_FLOOR = 14.0

_REFRACTORY_S = 0.09

_TURN_HYST = 4.0

_MIN_SAMPLES = 4


def _axis_of(direction):
    return "x" if direction in (LEFT, RIGHT) else "y"


def _sign_of(direction):
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

    _IDLE = "idle"
    _LOCKED = "locked"

    def __init__(self, on_swipe=None, on_debug=None):
        self._on_swipe = on_swipe
        self._on_debug = on_debug
        self._lock = threading.Lock()

        self._enabled = False
        self._commit_distance = 50.0
        self._commit_window = 0.40
        self._settle = 0.09
        self._cross_ratio = 0.5
        self._dir_eps = 7.5
        self._min_return = 22.5

        self._reset_hold()

    def configure(self, *, enabled, threshold, commit_window_ms,
                  settle_ms, cross_ratio):
        with self._lock:
            self._enabled = bool(enabled)
            self._commit_distance = max(8.0, float(threshold))
            self._commit_window = max(0.05, float(commit_window_ms) / 1000.0)
            self._settle = max(0.02, float(settle_ms) / 1000.0)
            self._cross_ratio = min(2.0, max(0.05, float(cross_ratio)))
            self._dir_eps = max(5.0, self._commit_distance * 0.15)
            self._min_return = max(14.0, self._commit_distance * 0.45)

    def begin(self):
        """Gesture button pressed — discard any prior state, start fresh."""
        with self._lock:
            self._reset_hold()
            self._active = True

    def end(self):
        """Gesture button released. Returns True when no swipe fired (click)."""
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

    def _reset_hold(self):
        self._phase = self._IDLE
        self._active = False
        self._fired_any = False
        self._source = None
        self._last_t = None
        self._last_fire_t = -1.0
        self._cx = 0.0
        self._cy = 0.0
        self._hold_samples = 0
        self._hold_first_t = None
        self._hold_peak_speed = 0.0
        self._hold_fired = []
        self._reset_leg(0.0, 0.0)
        self._lock_axis = None
        self._lock_sign = 0
        self._latch_anchor = 0.0
        self._latch_extreme = 0.0
        self._latch_off_at_turn = 0.0
        self._latch_turn_t = 0.0
        self._latch_return_seen = False

    def _reset_leg(self, at_x, at_y):
        self._pivot_x = at_x
        self._pivot_y = at_y
        self._pivot_t = None
        self._leg_peak = 0.0
        self._leg_samples = 0

    def _accept_source(self, source):
        if self._source == source:
            return True
        if self._source is None:
            self._source = source
            return True
        if source == "hid_rawxy":
            self._source = source
            self._phase = self._IDLE
            self._lock_axis = None
            self._lock_sign = 0
            self._reset_leg(self._cx, self._cy)
            return True
        return False

    def _step(self, dx, dy, now, fires, debugs):
        self._hold_samples += 1
        if self._hold_first_t is None:
            self._hold_first_t = now
        if self._last_t is not None:
            dt = now - self._last_t
            if dt > 0:
                speed = math.hypot(dx, dy) / dt
                if speed > self._hold_peak_speed:
                    self._hold_peak_speed = speed

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
        leg_x = self._cx - self._pivot_x
        leg_y = self._cy - self._pivot_y
        leg_len = math.hypot(leg_x, leg_y)

        if self._pivot_t is None:
            if leg_len < self._dir_eps:
                return
            self._pivot_t = now
            self._leg_peak = leg_len
            self._leg_samples = 1
            debugs.append({"type": "tracking_started", "source": self._source})
        else:
            self._leg_samples += 1

        if leg_len < self._leg_peak - self._dir_eps:
            self._reset_leg(self._cx, self._cy)
            return
        self._leg_peak = max(self._leg_peak, leg_len)

        debugs.append({"type": "segment", "source": self._source,
                       "dx": leg_x, "dy": leg_y})

        if (now - self._pivot_t) > self._commit_window:
            self._reset_leg(self._cx, self._cy)
            return

        direction = self._evaluate_leg(leg_x, leg_y)
        if direction is None:
            return
        if self._leg_samples < _MIN_SAMPLES:
            return
        if not self._fire(direction, now, leg_x, leg_y, fires, debugs):
            return

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
        axis = self._lock_axis
        sign = self._lock_sign
        pos = self._cx if axis == "x" else self._cy
        off = self._cy if axis == "x" else self._cx

        if sign * pos < sign * self._latch_extreme - _TURN_HYST:
            self._latch_extreme = pos
            self._latch_off_at_turn = off
            self._latch_turn_t = now

        return_amount = sign * (self._latch_anchor - self._latch_extreme)
        if return_amount >= self._min_return:
            self._latch_return_seen = True

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
        self._latch_anchor = pos
        self._latch_extreme = pos
        self._latch_off_at_turn = off
        self._latch_turn_t = now
        self._latch_return_seen = False

    def _evaluate_leg(self, leg_x, leg_y):
        abs_x = abs(leg_x)
        abs_y = abs(leg_y)
        if abs_x >= abs_y:
            dominant, cross = abs_x, abs_y
            direction = RIGHT if leg_x > 0 else LEFT
        else:
            dominant, cross = abs_y, abs_x
            direction = DOWN if leg_y > 0 else UP
        if dominant < self._commit_distance:
            return None
        if cross > self._cross_ratio * dominant + _CROSS_FLOOR:
            return None
        return direction

    def _locked_direction(self):
        if self._lock_axis == "x":
            return RIGHT if self._lock_sign > 0 else LEFT
        return DOWN if self._lock_sign > 0 else UP

    def _fire(self, direction, now, seg_x, seg_y, fires, debugs):
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

    def _emit_swipe(self, direction):
        if self._on_swipe is None:
            return
        try:
            self._on_swipe(direction)
        except Exception as exc:
            print(f"[GestureRecognizer] swipe callback error: {exc}")

    def _emit_debug(self, event):
        if self._on_debug is None:
            return
        try:
            self._on_debug(event)
        except Exception:
            pass
