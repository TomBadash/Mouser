"""
Pointer-motion -> scroll translation for the Pan action.

Pan turns a held button into a hand tool: while the button is down the pointer
freezes and mouse movement is re-emitted as scroll, so dragging the mouse drags
the content underneath it (the "Pan" gesture in Logitech Options+).

This module is deliberately platform-free -- it owns only the delta math, and
hands whole scroll units to an ``emit`` callback that each platform hook
implements. Keeping it separate from ``GestureRecognizer`` is not incidental:
that recognizer is a *discrete* swipe machine (refractory period, minimum
sample count, axis locking, commit-window rejection of slow drift) whose whole
job is to reject the sustained slow motion that panning is made of. Feeding pan
deltas through it would silently drop most of them.

Momentum ("throw" the content and let it glide after release) follows the same
split: ``PanScroller`` tracks flick velocity and hands a ``PanCoast`` back from
``end()``; the hook owns the timing loop that steps it. All tunables and decay
math stay here where they are unit-testable with explicit timestamps.
"""

import math
import time

# Velocity EMA time constant while dragging. Short enough to follow a flick's
# final direction change, long enough to smooth per-event jitter.
_VEL_TAU_S = 0.06
# A release only throws if the last motion sample is at least this recent --
# drag, stop, THEN release must not glide.
_FLICK_MAX_GAP_S = 0.10
# Release velocity below this (scroll units/second) is a placement, not a
# throw; above the cap it is clamped so a wild flick stays controllable.
_FLICK_MIN_SPEED = 250.0
_FLICK_MAX_SPEED = 6000.0
# A coast ends once it slows below this speed.
_COAST_STOP_SPEED = 30.0


class PanCoast:
    """Decaying post-release glide, stepped by the hook's timing loop.

    ``step(dt)`` returns the ``(dv, dh)`` scroll to emit for that slice, or
    ``None`` once the glide has slowed to a stop. Velocity decays
    exponentially with time constant ``glide_tau`` -- the "feel" control:
    small tau stops like paper on felt, large tau glides like ice.
    """

    def __init__(self, vel_v, vel_h, glide_tau):
        self._vel_v = float(vel_v)
        self._vel_h = float(vel_h)
        self._tau = max(0.05, float(glide_tau))
        self._acc_v = 0.0
        self._acc_h = 0.0

    def step(self, dt):
        dt = min(max(float(dt), 0.0), 0.1)
        decay = math.exp(-dt / self._tau)
        self._vel_v *= decay
        self._vel_h *= decay
        if math.hypot(self._vel_v, self._vel_h) < _COAST_STOP_SPEED:
            return None
        self._acc_v += self._vel_v * dt
        self._acc_h += self._vel_h * dt
        step_v = int(self._acc_v)
        step_h = int(self._acc_h)
        self._acc_v -= step_v
        self._acc_h -= step_h
        return (step_v, step_h)


class PanScroller:
    """Accumulates pointer deltas and emits whole scroll units.

    ``emit(dv, dh)`` receives *integer* scroll amounts: ``dv`` vertical, ``dh``
    horizontal, both already sign-corrected and speed-scaled. Sub-unit motion is
    carried in an accumulator rather than truncated away, so a slow drag still
    scrolls smoothly instead of stalling until it crosses a whole unit.
    """

    def __init__(self, emit, speed=1.0, natural=True, momentum=False,
                 glide_tau=0.7):
        self._emit = emit
        self._speed = 1.0
        self._natural = True
        self._momentum = False
        self._glide_tau = 0.7
        self._active = False
        self._acc_v = 0.0
        self._acc_h = 0.0
        self._vel_v = 0.0
        self._vel_h = 0.0
        self._last_sample_t = None
        self.configure(speed=speed, natural=natural, momentum=momentum,
                       glide_tau=glide_tau)

    def configure(self, speed=None, natural=None, momentum=None,
                  glide_tau=None):
        """Update tuning. Safe to call mid-hold; takes effect on the next sample."""
        if speed is not None:
            # Clamp rather than reject: the value comes from a config file a user
            # may have hand-edited, and a zero/negative speed would silently make
            # the button do nothing at all.
            self._speed = min(10.0, max(0.1, float(speed)))
        if natural is not None:
            self._natural = bool(natural)
        if momentum is not None:
            self._momentum = bool(momentum)
        if glide_tau is not None:
            self._glide_tau = min(3.0, max(0.05, float(glide_tau)))

    @property
    def active(self):
        return self._active

    @property
    def speed(self):
        return self._speed

    @property
    def natural(self):
        return self._natural

    @property
    def momentum(self):
        return self._momentum

    @property
    def glide_tau(self):
        return self._glide_tau

    def begin(self):
        """Start a pan hold. Resets carried sub-unit motion from any prior hold."""
        self._active = True
        self._acc_v = 0.0
        self._acc_h = 0.0
        self._vel_v = 0.0
        self._vel_h = 0.0
        self._last_sample_t = None

    def sample(self, dx, dy, now=None):
        """Feed one pointer delta. Returns True if a scroll was emitted.

        ``dx``/``dy`` are in the platform's pointer-delta convention (y grows
        downward on every platform Mouser supports).
        """
        if not self._active:
            return False

        # "Natural" here means content-follows-mouse, the hand-tool feel: drag
        # down and the content comes down with you. That is the same sign as a
        # natural-direction trackpad swipe, so it maps to a positive scroll
        # delta on the same axis. The inverted mode is scrollbar-style, where
        # dragging down moves the viewport down and content appears to go up.
        sign = 1 if self._natural else -1
        sdv = dy * self._speed * sign
        sdh = dx * self._speed * sign
        self._acc_v += sdv
        self._acc_h += sdh

        # Flick-velocity estimate (EMA over instantaneous delta/dt) so end()
        # knows how hard the content was being thrown at release.
        t = time.monotonic() if now is None else now
        if self._last_sample_t is not None:
            dt = min(max(t - self._last_sample_t, 1e-4), 0.1)
            alpha = 1.0 - math.exp(-dt / _VEL_TAU_S)
            self._vel_v += alpha * (sdv / dt - self._vel_v)
            self._vel_h += alpha * (sdh / dt - self._vel_h)
        self._last_sample_t = t

        step_v = int(self._acc_v)
        step_h = int(self._acc_h)
        if not step_v and not step_h:
            return False
        self._acc_v -= step_v
        self._acc_h -= step_h
        self._emit(step_v, step_h)
        return True

    def end(self, now=None):
        """End the hold and drop any sub-unit remainder.

        With momentum enabled, a release mid-flick returns a ``PanCoast`` for
        the hook to run; otherwise (momentum off, drag paused before release,
        or too slow to count as a throw) returns ``None``.
        """
        self._active = False
        self._acc_v = 0.0
        self._acc_h = 0.0
        vel_v, vel_h = self._vel_v, self._vel_h
        last_t = self._last_sample_t
        self._vel_v = 0.0
        self._vel_h = 0.0
        self._last_sample_t = None

        if not self._momentum or last_t is None:
            return None
        t = time.monotonic() if now is None else now
        if t - last_t > _FLICK_MAX_GAP_S:
            return None
        speed = math.hypot(vel_v, vel_h)
        if speed < _FLICK_MIN_SPEED:
            return None
        if speed > _FLICK_MAX_SPEED:
            scale = _FLICK_MAX_SPEED / speed
            vel_v *= scale
            vel_h *= scale
        return PanCoast(vel_v, vel_h, self._glide_tau)
