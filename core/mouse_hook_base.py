"""
Shared mouse hook behavior used by platform implementations.
"""

import queue

try:
    from core.hid_gesture import HidGestureListener
except Exception:
    HidGestureListener = None

from core.mouse_hook_types import HidRuntimeState, MouseEvent, format_debug_details
from core.gesture_recognizer import GestureRecognizer


# Recognizer swipe directions → dispatched MouseEvent types.
_SWIPE_EVENTS = {
    "left": MouseEvent.GESTURE_SWIPE_LEFT,
    "right": MouseEvent.GESTURE_SWIPE_RIGHT,
    "up": MouseEvent.GESTURE_SWIPE_UP,
    "down": MouseEvent.GESTURE_SWIPE_DOWN,
}


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
        self._gesture_recognizer = GestureRecognizer(
            on_swipe=self._on_recognized_swipe,
            on_debug=self._emit_gesture_event,
        )
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
        commit_window_ms=400,
        settle_ms=90,
        cross_ratio=0.5,
    ):
        self._gesture_direction_enabled = bool(enabled)
        self._gesture_recognizer.configure(
            enabled=bool(enabled),
            threshold=threshold,
            commit_window_ms=commit_window_ms,
            settle_ms=settle_ms,
            cross_ratio=cross_ratio,
        )

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
        if getattr(self, "_ui_passthrough", False):
            return
        if self._gesture_active:
            return
        self._gesture_recognizer.begin()
        self._gesture_active = True
        self._emit_debug("HID gesture button down")
        self._emit_gesture_event({"type": "button_down"})

    def _on_hid_gesture_up(self):
        if getattr(self, "_ui_passthrough", False):
            return
        if not self._gesture_active:
            return
        self._gesture_active = False
        was_click = self._gesture_recognizer.end()
        self._log_gesture_summary()
        self._emit_debug(
            f"HID gesture button up click_candidate={str(was_click).lower()}"
        )
        self._emit_gesture_event(
            {"type": "button_up", "click_candidate": was_click}
        )
        if was_click:
            self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _log_gesture_summary(self):
        """Print a one-line trace of the gesture hold that just ended.

        Always on — one line per gesture-button press — so swipe-vs-click
        behaviour is visible in ~/Library/Logs/Mouser/mouser.log. It is the
        fastest way to tune the recognizer against real hardware.
        """
        s = self._gesture_recognizer.summary()
        outcome = "+".join(s["fired"]) if s["fired"] else "click"
        print(
            f"[Gesture] hold={s['duration_ms']:.0f}ms samples={s['samples']} "
            f"net=({s['net_x']:+.0f},{s['net_y']:+.0f}) "
            f"peak={s['peak_speed']:.0f}u/s src={s['source'] or '-'} "
            f"-> {outcome}"
        )

    def _on_hid_gesture_move(self, dx, dy):
        if getattr(self, "_ui_passthrough", False):
            return
        self._emit_gesture_event(
            {"type": "move", "source": "hid_rawxy", "dx": dx, "dy": dy}
        )
        self._gesture_recognizer.sample(dx, dy, "hid_rawxy")

    def _on_recognized_swipe(self, direction):
        """Recognizer callback — dispatch a recognized swipe as a MouseEvent.

        Invoked on the HID listener thread (or, on macOS, the event-tap
        thread, when raw XY is unavailable).
        """
        event_type = _SWIPE_EVENTS.get(direction)
        if event_type is not None:
            self._emit_gesture_swipe(MouseEvent(event_type))

    def _emit_gesture_swipe(self, mouse_event):
        """Deliver a recognized swipe event. Platform hooks that own a
        dedicated dispatch thread override this to hand the event off there
        instead of dispatching inline."""
        self._dispatch(mouse_event)

    def _on_hid_mode_shift_down(self):
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))
