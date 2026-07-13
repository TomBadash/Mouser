"""Actions Ring controller -- state machine for radial quick-action overlay."""

import math
import threading

DEAD_ZONE_RADIUS = 30


class ActionsRingController:
    """Manages the Actions Ring interaction with two modes:

    **Held mode** (buttons with down/up events):
      button_down → WAITING → hold timer → SHOWING_HELD → button_up selects sector

    **Toggle mode** (quick tap or single-fire buttons):
      quick tap / on_click → SHOWING_TOGGLE → ring stays open until
      trigger pressed again, or overlay click selects/dismisses.
    """

    IDLE = "idle"
    WAITING = "waiting"
    SHOWING_HELD = "showing_held"
    SHOWING_TOGGLE = "showing_toggle"

    def __init__(self, slots, hold_ms,
                 execute_cb, play_haptic_cb,
                 show_ring_cb, hide_ring_cb,
                 get_cursor_pos_cb=None,
                 move_cb=None):
        self._slots = list(slots)
        self._hold_ms = hold_ms
        self._execute_cb = execute_cb
        self._play_haptic_cb = play_haptic_cb
        self._show_ring_cb = show_ring_cb
        self._hide_ring_cb = hide_ring_cb
        self._get_cursor_pos_cb = get_cursor_pos_cb
        self._move_cb = move_cb

        self._lock = threading.Lock()
        self._state = self.IDLE
        self._timer = None
        self._anchor_pos = None
        self._current_sector = -1

    @property
    def state(self) -> str:
        return self._state

    @property
    def anchor_pos(self):
        return self._anchor_pos

    @property
    def current_sector(self) -> int:
        return self._current_sector

    def on_button_down(self):
        """Called on button press for buttons with down/up events.

        IDLE → WAITING (start hold timer).
        SHOWING_TOGGLE → IDLE (dismiss ring on re-press).
        """
        do_hide = False
        timer_to_start = None
        with self._lock:
            if self._state == self.IDLE:
                self._state = self.WAITING
                timer = threading.Timer(
                    self._hold_ms / 1000.0, self._on_hold_triggered)
                timer.daemon = True
                self._timer = timer
                timer_to_start = timer
            elif self._state == self.SHOWING_TOGGLE:
                self._state = self.IDLE
                self._anchor_pos = None
                self._current_sector = -1
                do_hide = True
            else:
                return
        if timer_to_start is not None:
            timer_to_start.start()
        elif do_hide:
            self._hide_ring_cb()

    def on_button_up(self, sector_override=None):
        """Called on button release for buttons with down/up events.

        WAITING → SHOWING_TOGGLE (quick tap opens ring in toggle mode).
        SHOWING_HELD → IDLE (release selects sector or dismisses).
        SHOWING_TOGGLE → no-op (ring stays open).
        """
        do_hide = False
        do_show_toggle = False
        action_to_execute = None
        with self._lock:
            if self._state == self.WAITING:
                self._cancel_timer()
                self._state = self.SHOWING_TOGGLE
                do_show_toggle = True
            elif self._state == self.SHOWING_HELD:
                sector = (sector_override if sector_override is not None
                          else self._current_sector)
                self._state = self.IDLE
                self._anchor_pos = None
                self._current_sector = -1
                do_hide = True
                if 0 <= sector < len(self._slots):
                    action_to_execute = self._slots[sector]
            elif self._state == self.SHOWING_TOGGLE:
                return
            else:
                return
        if do_show_toggle:
            if self._get_cursor_pos_cb:
                self._anchor_pos = self._get_cursor_pos_cb()
            self._play_haptic_cb(0)
            self._show_ring_cb(list(self._slots), True)
        elif do_hide:
            self._hide_ring_cb()
            if action_to_execute is not None:
                self._execute_cb(action_to_execute)
                self._play_haptic_cb(7)

    def on_click(self):
        """Called for single-fire buttons (e.g. gesture_click).

        Toggles the ring: IDLE → SHOWING_TOGGLE, SHOWING_TOGGLE → IDLE.
        """
        do_show = False
        do_hide = False
        with self._lock:
            if self._state == self.IDLE:
                self._state = self.SHOWING_TOGGLE
                do_show = True
            elif self._state == self.SHOWING_TOGGLE:
                self._state = self.IDLE
                self._anchor_pos = None
                self._current_sector = -1
                do_hide = True
        if do_show:
            if self._get_cursor_pos_cb:
                self._anchor_pos = self._get_cursor_pos_cb()
            self._play_haptic_cb(0)
            self._show_ring_cb(list(self._slots), True)
        elif do_hide:
            self._hide_ring_cb()

    def on_toggle_select(self, sector):
        """Called from the overlay when user clicks a sector in toggle mode."""
        action_to_execute = None
        do_hide = False
        with self._lock:
            if self._state != self.SHOWING_TOGGLE:
                return
            self._state = self.IDLE
            self._anchor_pos = None
            self._current_sector = -1
            do_hide = True
            if 0 <= sector < len(self._slots):
                action_to_execute = self._slots[sector]
        if do_hide:
            self._hide_ring_cb()
            if action_to_execute is not None:
                self._execute_cb(action_to_execute)
                self._play_haptic_cb(7)

    def on_toggle_dismiss(self):
        """Called from the overlay when user clicks center X or outside in toggle mode."""
        do_hide = False
        with self._lock:
            if self._state != self.SHOWING_TOGGLE:
                return
            self._state = self.IDLE
            self._anchor_pos = None
            self._current_sector = -1
            do_hide = True
        if do_hide:
            self._hide_ring_cb()

    def on_move(self, dx, dy):
        """Forward rawXY deltas to the UI when the ring is showing in held mode."""
        if self._state == self.SHOWING_HELD and self._move_cb:
            try:
                self._move_cb(dx, dy)
            except Exception:
                pass

    def set_current_sector(self, sector):
        """Update the current sector (called from overlay's cursor poll)."""
        self._current_sector = sector

    def _on_hold_triggered(self):
        """Timer callback — transition WAITING -> SHOWING_HELD."""
        do_show = False
        with self._lock:
            if self._state != self.WAITING:
                return
            self._state = self.SHOWING_HELD
            if self._get_cursor_pos_cb:
                self._anchor_pos = self._get_cursor_pos_cb()
            slots = list(self._slots)
            do_show = True
        if do_show:
            self._play_haptic_cb(0)
            self._show_ring_cb(slots, False)

    def resolve_sector(self, cursor_x, cursor_y) -> int:
        """Compute sector from cursor position relative to anchor."""
        anchor = self._anchor_pos
        if anchor is None or not self._slots:
            self._current_sector = -1
            return -1
        dx = cursor_x - anchor[0]
        dy = cursor_y - anchor[1]
        sector = angle_to_sector(dx, dy, len(self._slots))
        self._current_sector = sector
        return sector

    def shutdown(self):
        """Cancel pending timer, reset state."""
        hide = False
        with self._lock:
            self._cancel_timer()
            if self._state in (self.SHOWING_HELD, self.SHOWING_TOGGLE):
                hide = True
            self._state = self.IDLE
            self._anchor_pos = None
            self._current_sector = -1
        if hide:
            self._hide_ring_cb()

    def _cancel_timer(self):
        """Cancel and discard the hold timer (must hold lock)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def angle_to_sector(dx, dy, num_sectors) -> int:
    """Pure geometry: map (dx, dy) offset to a sector index, or -1 for dead zone."""
    if num_sectors <= 0:
        return -1
    dist = math.hypot(dx, dy)
    if dist < DEAD_ZONE_RADIUS:
        return -1
    # 0 = up, clockwise
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    sector_size = 360.0 / num_sectors
    return int((angle + sector_size / 2) % 360 / sector_size)
