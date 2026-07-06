"""
Shared mouse hook behavior used by platform implementations.
"""

import queue
import time

try:
    from core.hid_gesture import HidGestureListener
except Exception:
    HidGestureListener = None

from core.mouse_hook_types import HidRuntimeState, MouseEvent, format_debug_details

# Default hold floor (ms) below which an owner-button press is a click, not a
# gesture (D4). Mirrors core.config GESTURE_HOLD_FLOOR_MS_DEFAULT.
_GESTURE_HOLD_FLOOR_MS_DEFAULT = 80

# Release-decision outcomes for an event-tap gesture-owner button.
CLICK = "click"
GESTURE = "gesture"


def _gesture_direction(dx, dy, threshold, deadzone):
    """Cardinal swipe direction for accumulated deltas, or None if none.

    Pure mirror of BaseMouseHook._detect_gesture_event so the event-tap
    on-release decision matches the live HID detector exactly.
    """
    abs_x = abs(dx)
    abs_y = abs(dy)
    dominant = max(abs_x, abs_y)
    if dominant < threshold:
        return None
    cross_limit = max(deadzone, dominant * 0.35)
    if abs_x > abs_y:
        if abs_y > cross_limit:
            return None
        return MouseEvent.GESTURE_SWIPE_RIGHT if dx > 0 else MouseEvent.GESTURE_SWIPE_LEFT
    if abs_x > cross_limit:
        return None
    return MouseEvent.GESTURE_SWIPE_DOWN if dy > 0 else MouseEvent.GESTURE_SWIPE_UP


def decide_gesture(held_ms, dx, dy, hold_floor_ms, threshold, deadzone):
    """Classify a gesture-owner button release as a click or a directional gesture.

    Returns (CLICK, None) or (GESTURE, MouseEvent.GESTURE_SWIPE_*). Objc-free so
    the CGEventTap handler and unit tests share one decision. A release is a
    gesture only when held >= the floor AND the slide resolves to a direction;
    everything else replays the button's normal click (dual-mode, D2/D4).
    """
    if held_ms < hold_floor_ms:
        return CLICK, None
    direction = _gesture_direction(dx, dy, threshold, deadzone)
    if direction is None:
        return CLICK, None
    return GESTURE, direction


def should_arm_gesture(gesture_active, btn_owner, owners):
    """First-wins arming gate: arm an event-tap gesture only for an owner button
    while no gesture (event-tap or HID) is already active; else pass it through."""
    if btn_owner not in owners:
        return False
    return not gesture_active


class BaseMouseHook:
    def __init__(self):
        self._callbacks = {}
        self._blocked_events = set()
        self._debug_callback = None
        self._gesture_callback = None
        self._status_callback = None
        self.debug_mode = False
        self.invert_vscroll = False
        self.invert_hscroll = False
        self._gesture_active = False
        self._hid_gesture = None
        self._device_connected = False
        self._connection_change_cb = None
        self.divert_mode_shift = False
        self.divert_dpi_switch = False
        self._gesture_direction_enabled = False
        self._gesture_threshold = 50.0
        self._gesture_deadzone = 40.0
        self._gesture_timeout_ms = 3000
        self._gesture_cooldown_ms = 500
        self._gesture_tracking = False
        self._gesture_triggered = False
        self._gesture_started_at = 0.0
        self._gesture_last_move_at = 0.0
        self._gesture_delta_x = 0.0
        self._gesture_delta_y = 0.0
        self._gesture_cooldown_until = 0.0
        self._gesture_input_source = None
        self._gesture_owners = set()
        self._gesture_hold_floor_ms = _GESTURE_HOLD_FLOOR_MS_DEFAULT
        self._tilt_gesture_owners = set()
        self._tilt_release_ms = 150
        self._connected_device = None
        self._dispatch_queue = None

    def _init_dispatch_queue(self, maxsize=0):
        """Initialize dispatch queue storage for subclasses with event threads."""
        self._dispatch_queue = queue.Queue(maxsize=max(0, int(maxsize)))

    def _enqueue_dispatch_event(self, event):
        """Best-effort enqueue that bounds memory when queue has a max size."""
        q = self._dispatch_queue
        if q is None:
            return
        if q.maxsize <= 0:
            q.put(event)
            return
        try:
            q.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(event)
        except queue.Full:
            self._emit_debug(f"Dropped event due to full dispatch queue: {event.event_type}")

    def register(self, event_type, callback):
        self._callbacks.setdefault(event_type, []).append(callback)

    def block(self, event_type):
        self._blocked_events.add(event_type)

    def unblock(self, event_type):
        self._blocked_events.discard(event_type)

    def reset_bindings(self):
        self._callbacks.clear()
        self._blocked_events.clear()

    def configure_gestures(
        self,
        enabled=False,
        threshold=50,
        deadzone=40,
        timeout_ms=3000,
        cooldown_ms=500,
        owners=None,
        hold_floor_ms=None,
        tilt_owners=None,
        tilt_release_ms=None,
    ):
        self._gesture_direction_enabled = bool(enabled)
        self._gesture_threshold = float(max(5, threshold))
        self._gesture_deadzone = float(max(0, deadzone))
        self._gesture_timeout_ms = max(250, int(timeout_ms))
        self._gesture_cooldown_ms = max(0, int(cooldown_ms))
        # Per-button event-tap gesture owners are independent of the HID
        # direction feature above; issue 004 supplies both from config.
        self._gesture_owners = set(owners) if owners else set()
        # Tilt (horizontal-scroll) gesture owners ("tilt_left"/"tilt_right"),
        # armed off the hscroll pulse stream (macOS hook) rather than a button.
        self._tilt_gesture_owners = set(tilt_owners) if tilt_owners else set()
        if tilt_release_ms is not None:
            self._tilt_release_ms = max(50, int(tilt_release_ms))
        if hold_floor_ms is not None:
            self._gesture_hold_floor_ms = max(0, int(hold_floor_ms))
        if not self._gesture_direction_enabled:
            self._gesture_tracking = False
            self._gesture_triggered = False
            self._gesture_input_source = None

    def set_connection_change_callback(self, cb):
        self._connection_change_cb = cb

    @property
    def device_connected(self):
        return self._device_connected

    @property
    def connected_device(self):
        return self._connected_device

    @property
    def hid_runtime_state(self):
        hg = getattr(self, "_hid_gesture", None)
        hid_device = getattr(hg, "connected_device", None) if hg else None
        return HidRuntimeState(
            input_ready=bool(self._device_connected),
            hid_ready=hid_device is not None,
            connected_device=self._connected_device,
        )

    def dump_device_info(self):
        hg = getattr(self, "_hid_gesture", None)
        if hg and hasattr(hg, "dump_device_info"):
            return hg.dump_device_info()
        return None

    def _set_device_connected(self, connected):
        if connected == self._device_connected:
            return
        self._device_connected = connected
        state = "Connected" if connected else "Disconnected"
        print(f"[MouseHook] Device {state}")
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass

    def set_debug_callback(self, callback):
        self._debug_callback = callback

    def set_gesture_callback(self, callback):
        self._gesture_callback = callback

    def set_status_callback(self, callback):
        self._status_callback = callback

    def _emit_debug(self, message):
        if self.debug_mode and self._debug_callback:
            try:
                self._debug_callback(message)
            except Exception:
                pass

    def _emit_status(self, message):
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass

    def _emit_gesture_event(self, event):
        if self.debug_mode and self._gesture_callback:
            try:
                self._gesture_callback(event)
            except Exception:
                pass

    def _dispatch(self, event):
        callbacks = self._callbacks.get(event.event_type, [])
        self._emit_debug(
            f"Dispatch {event.event_type}"
            f"{format_debug_details(event.raw_data)} callbacks={len(callbacks)}"
        )
        if event.event_type.startswith("gesture_"):
            self._emit_gesture_event(
                {
                    "type": "dispatch",
                    "event_name": event.event_type,
                    "callbacks": len(callbacks),
                }
            )
        if not callbacks:
            self._emit_debug(f"No mapped action for {event.event_type}")
            if event.event_type.startswith("gesture_"):
                self._emit_gesture_event(
                    {
                        "type": "unmapped",
                        "event_name": event.event_type,
                    }
                )
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                print(f"[MouseHook] callback error: {exc}")

    def _hid_gesture_available(self):
        return self._hid_gesture is not None and self._device_connected

    def _gesture_cooldown_active(self):
        return time.monotonic() < self._gesture_cooldown_until

    def _start_gesture_tracking(self):
        self._gesture_tracking = self._gesture_direction_enabled
        self._gesture_started_at = time.monotonic()
        self._gesture_last_move_at = self._gesture_started_at
        self._gesture_delta_x = 0.0
        self._gesture_delta_y = 0.0
        self._gesture_input_source = None

    def _finish_gesture_tracking(self):
        self._gesture_tracking = False
        self._gesture_started_at = 0.0
        self._gesture_last_move_at = 0.0
        self._gesture_delta_x = 0.0
        self._gesture_delta_y = 0.0
        self._gesture_input_source = None

    def _detect_gesture_event(self):
        delta_x = self._gesture_delta_x
        delta_y = self._gesture_delta_y

        abs_x = abs(delta_x)
        abs_y = abs(delta_y)
        dominant = max(abs_x, abs_y)
        if dominant < self._gesture_threshold:
            return None

        cross_limit = max(self._gesture_deadzone, dominant * 0.35)

        if abs_x > abs_y:
            if abs_y > cross_limit:
                return None
            if delta_x > 0:
                return MouseEvent.GESTURE_SWIPE_RIGHT
            return MouseEvent.GESTURE_SWIPE_LEFT

        if abs_x > cross_limit:
            return None
        if delta_y > 0:
            return MouseEvent.GESTURE_SWIPE_DOWN
        return MouseEvent.GESTURE_SWIPE_UP

    def _build_extra_diverts(self):
        extra = {}
        if self.divert_mode_shift:
            extra[0x00C4] = {
                "on_down": self._on_hid_mode_shift_down,
                "on_up": self._on_hid_mode_shift_up,
            }
        if self.divert_dpi_switch:
            extra[0x00FD] = {
                "on_down": self._on_hid_dpi_switch_down,
                "on_up": self._on_hid_dpi_switch_up,
            }
        return extra

    def _start_hid_listener(self):
        platform_module = getattr(self.__class__, "_platform_module", None)
        listener_cls = getattr(platform_module, "HidGestureListener", HidGestureListener)
        if listener_cls is None:
            return None
        listener = listener_cls(
            on_down=self._on_hid_gesture_down,
            on_up=self._on_hid_gesture_up,
            on_move=self._on_hid_gesture_move,
            on_connect=self._on_hid_connect,
            on_disconnect=self._on_hid_disconnect,
            extra_diverts=self._build_extra_diverts(),
        )
        self._hid_gesture = listener
        if not listener.start():
            self._hid_gesture = None
        return self._hid_gesture

    def _stop_hid_listener(self):
        if self._hid_gesture:
            self._hid_gesture.stop()
            self._hid_gesture = None

    def _on_hid_connect(self):
        self._connected_device = (
            self._hid_gesture.connected_device if self._hid_gesture else None
        )
        self._set_device_connected(True)

    def _on_hid_disconnect(self):
        self._connected_device = None
        self._set_device_connected(False)

    def _on_hid_gesture_down(self):
        self._dispatch(MouseEvent(MouseEvent.GESTURE_DOWN))

    def _on_hid_gesture_up(self):
        self._dispatch(MouseEvent(MouseEvent.GESTURE_UP))

    def _on_hid_gesture_move(self, dx, dy):
        self._accumulate_gesture_delta(dx, dy, "hid_rawxy")

    def _on_hid_mode_shift_down(self):
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))
