"""
macOS mouse hook implementation.
"""

import functools
import queue
import sys
import threading
import time

from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import MouseEvent

try:
    import objc
except ImportError as exc:
    raise ImportError(
        "PyObjC is required on macOS. Run "
        "`python -m pip install -r requirements.txt`."
    ) from exc

try:
    import Quartz

    _QUARTZ_OK = True
except ImportError:
    _QUARTZ_OK = False
    print(
        "[MouseHook] pyobjc-framework-Quartz not installed — "
        "pip install pyobjc-framework-Quartz"
    )


def _autoreleased(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with objc.autorelease_pool():
            return fn(*args, **kwargs)
    return wrapper


_BTN_MIDDLE = 2
_BTN_BACK = 3
_BTN_FORWARD = 4
_SCROLL_INVERT_MARKER = 0x4D4F5553
_INJECTED_EVENT_MARKER = 0x4D4F5554
_kCGEventTapDisabledByTimeout = 0xFFFFFFFE
_kCGEventTapDisabledByUserInput = 0xFFFFFFFF


class MouseHook(BaseMouseHook):
    """
    Uses CGEventTap on macOS to intercept mouse button presses and scroll
    events. Requires Accessibility permission.
    """

    def __init__(self):
        super().__init__()
        self._running = False
        self._tap = None
        self._tap_source = None
        self.ignore_trackpad = True
        self._wake_observer = None
        self._session_resign_observer = None
        self._session_activate_observer = None
        self._dispatch_queue = queue.Queue()
        self._dispatch_thread = None
        self._first_event_logged = False

    def _negate_scroll_axis(self, cg_event, axis):
        for field_name in (
            f"kCGScrollWheelEventDeltaAxis{axis}",
            f"kCGScrollWheelEventFixedPtDeltaAxis{axis}",
            f"kCGScrollWheelEventPointDeltaAxis{axis}",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            if value:
                Quartz.CGEventSetIntegerValueField(cg_event, field, -value)

    def _post_inverted_scroll_event(self, cg_event):
        v_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis1
        )
        h_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis2
        )
        if self.invert_vscroll:
            v_point = -v_point
        if self.invert_hscroll:
            h_point = -h_point

        inverted = Quartz.CGEventCreateScrollWheelEvent(
            None,
            Quartz.kCGScrollEventUnitPixel,
            2,
            v_point,
            h_point,
        )
        if not inverted:
            return False
        Quartz.CGEventSetFlags(inverted, Quartz.CGEventGetFlags(cg_event))
        Quartz.CGEventSetIntegerValueField(
            inverted, Quartz.kCGEventSourceUserData, _SCROLL_INVERT_MARKER
        )
        for axis in (1, 2):
            sign = -1 if (
                (axis == 1 and self.invert_vscroll)
                or (axis == 2 and self.invert_hscroll)
            ) else 1
            for field_name in (
                f"kCGScrollWheelEventDeltaAxis{axis}",
                f"kCGScrollWheelEventFixedPtDeltaAxis{axis}",
                f"kCGScrollWheelEventPointDeltaAxis{axis}",
            ):
                field = getattr(Quartz, field_name, None)
                if field is None:
                    continue
                value = Quartz.CGEventGetIntegerValueField(cg_event, field)
                Quartz.CGEventSetIntegerValueField(inverted, field, sign * value)
        for field_name in (
            "kCGScrollWheelEventScrollPhase",
            "kCGScrollWheelEventMomentumPhase",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            Quartz.CGEventSetIntegerValueField(inverted, field, value)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, inverted)
        return True

    def _accumulate_gesture_delta(self, delta_x, delta_y, source):
        if not (self._gesture_direction_enabled and self._gesture_active):
            return
        if self._gesture_cooldown_active():
            self._emit_debug(
                f"Gesture cooldown active source={source} dx={delta_x} dy={delta_y}"
            )
            self._emit_gesture_event(
                {
                    "type": "cooldown_active",
                    "source": source,
                    "dx": delta_x,
                    "dy": delta_y,
                }
            )
            return
        if not self._gesture_tracking:
            self._emit_debug(f"Gesture tracking started source={source}")
            self._emit_gesture_event(
                {
                    "type": "tracking_started",
                    "source": source,
                }
            )
            self._start_gesture_tracking()

        now = time.monotonic()
        idle_ms = (now - self._gesture_last_move_at) * 1000.0
        if idle_ms > self._gesture_timeout_ms:
            self._emit_debug(
                f"Gesture segment reset timeout source={source} "
                f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
            )
            self._start_gesture_tracking()

        if source == "hid_rawxy" and self._gesture_input_source == "event_tap":
            self._emit_debug(
                "Gesture source promoted from event_tap to hid_rawxy "
                f"prev_accum_x={self._gesture_delta_x} "
                f"prev_accum_y={self._gesture_delta_y}"
            )
            self._start_gesture_tracking()

        if self._gesture_input_source not in (None, source):
            self._emit_debug(
                f"Gesture source locked to {self._gesture_input_source}; "
                f"ignoring {source} dx={delta_x} dy={delta_y}"
            )
            return
        self._gesture_input_source = source

        self._gesture_delta_x += delta_x
        self._gesture_delta_y += delta_y
        self._gesture_last_move_at = now
        self._emit_debug(
            f"Gesture segment source={source} "
            f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
        )
        self._emit_gesture_event(
            {
                "type": "segment",
                "source": source,
                "dx": self._gesture_delta_x,
                "dy": self._gesture_delta_y,
            }
        )

        while True:
            gesture_event = self._detect_gesture_event()
            if not gesture_event:
                return

            self._gesture_triggered = True
            self._emit_debug(
                "Gesture detected "
                f"{gesture_event} source={source} "
                f"delta_x={self._gesture_delta_x} delta_y={self._gesture_delta_y}"
            )
            self._emit_gesture_event(
                {
                    "type": "detected",
                    "event_name": gesture_event,
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                }
            )
            self._dispatch_queue.put(
                MouseEvent(
                    gesture_event,
                    {
                        "delta_x": self._gesture_delta_x,
                        "delta_y": self._gesture_delta_y,
                        "source": source,
                    },
                )
            )
            self._gesture_cooldown_until = (
                time.monotonic() + self._gesture_cooldown_ms / 1000.0
            )
            self._emit_debug(
                f"Gesture cooldown started source={source} "
                f"for_ms={self._gesture_cooldown_ms}"
            )
            self._emit_gesture_event(
                {
                    "type": "cooldown_started",
                    "source": source,
                    "for_ms": self._gesture_cooldown_ms,
                }
            )
            self._finish_gesture_tracking()
            return

    def _dispatch_worker(self):
        while self._running:
            try:
                event = self._dispatch_queue.get(timeout=0.05)
                self._dispatch(event)
            except queue.Empty:
                continue

    @_autoreleased
    def _event_tap_callback(self, proxy, event_type, cg_event, refcon):
        try:
            if event_type in (
                _kCGEventTapDisabledByTimeout,
                _kCGEventTapDisabledByUserInput,
            ):
                print(
                    f"[MouseHook] CGEventTap disabled by system "
                    f"(type=0x{event_type:X}), re-enabling",
                    flush=True,
                )
                Quartz.CGEventTapEnable(self._tap, True)
                return cg_event

            if not self._first_event_logged:
                self._first_event_logged = True
                print("[MouseHook] CGEventTap: first event received", flush=True)

            try:
                if (
                    Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGEventSourceUserData
                    )
                    == _INJECTED_EVENT_MARKER
                ):
                    return cg_event
            except Exception:
                pass
            mouse_event = None
            should_block = False

            if (
                event_type
                in (
                    Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventOtherMouseDragged,
                )
                and self._gesture_direction_enabled
                and self._gesture_active
            ):
                self._emit_debug(
                    "Gesture move event "
                    f"type={int(event_type)} "
                    f"dx={Quartz.CGEventGetIntegerValueField(cg_event, Quartz.kCGMouseEventDeltaX)} "
                    f"dy={Quartz.CGEventGetIntegerValueField(cg_event, Quartz.kCGMouseEventDeltaY)}"
                )
                self._emit_gesture_event(
                    {
                        "type": "move",
                        "source": "event_tap",
                        "dx": Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaX
                        ),
                        "dy": Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaY
                        ),
                    }
                )
                if self._gesture_input_source == "hid_rawxy":
                    return None
                self._accumulate_gesture_delta(
                    Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGMouseEventDeltaX
                    ),
                    Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGMouseEventDeltaY
                    ),
                    "event_tap",
                )
                return None

            if event_type == Quartz.kCGEventOtherMouseDown:
                btn = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventButtonNumber
                )
                if self.debug_mode and self._debug_callback:
                    try:
                        self._debug_callback(f"OtherMouseDown btn={btn}")
                    except Exception:
                        pass
                if btn == _BTN_MIDDLE:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                    should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events
                elif btn == _BTN_BACK:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                    should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
                elif btn == _BTN_FORWARD:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                    should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events

            elif event_type == Quartz.kCGEventOtherMouseUp:
                btn = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventButtonNumber
                )
                if self.debug_mode and self._debug_callback:
                    try:
                        self._debug_callback(f"OtherMouseUp btn={btn}")
                    except Exception:
                        pass
                if btn == _BTN_MIDDLE:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_UP)
                    should_block = MouseEvent.MIDDLE_UP in self._blocked_events
                elif btn == _BTN_BACK:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_UP)
                    should_block = MouseEvent.XBUTTON1_UP in self._blocked_events
                elif btn == _BTN_FORWARD:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_UP)
                    should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

            elif event_type == Quartz.kCGEventScrollWheel:
                if (
                    Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGEventSourceUserData
                    )
                    == _SCROLL_INVERT_MARKER
                ):
                    return cg_event
                if self.ignore_trackpad:
                    is_continuous_field = 88
                    if Quartz.CGEventGetIntegerValueField(cg_event, is_continuous_field):
                        return cg_event
                h_delta = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis2
                )
                h_delta = h_delta / 65536.0
                if self.debug_mode and self._debug_callback:
                    try:
                        v_delta = (
                            Quartz.CGEventGetIntegerValueField(
                                cg_event,
                                Quartz.kCGScrollWheelEventFixedPtDeltaAxis1,
                            )
                            / 65536.0
                        )
                        self._debug_callback(f"ScrollWheel v={v_delta} h={h_delta}")
                    except Exception:
                        pass
                if h_delta != 0:
                    if h_delta > 0:
                        mouse_event = MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(h_delta))
                        should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events
                    else:
                        mouse_event = MouseEvent(MouseEvent.HSCROLL_LEFT, abs(h_delta))
                        should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events
                if mouse_event:
                    self._dispatch_queue.put(mouse_event)
                    mouse_event = None
                if should_block:
                    return None
                if self.invert_vscroll or self.invert_hscroll:
                    if self._post_inverted_scroll_event(cg_event):
                        return None

            if mouse_event:
                self._dispatch_queue.put(mouse_event)

            if should_block:
                return None
            return cg_event

        except Exception as exc:
            print(f"[MouseHook] event tap callback error: {exc}")
            return cg_event

    def _on_hid_gesture_down(self):
        if not self._gesture_active:
            self._gesture_active = True
            self._gesture_triggered = False
            self._emit_debug("HID gesture button down")
            self._emit_gesture_event({"type": "button_down"})
            if self._gesture_direction_enabled and not self._gesture_cooldown_active():
                self._start_gesture_tracking()
            else:
                self._gesture_tracking = False
                self._gesture_triggered = False

    def _on_hid_gesture_up(self):
        if self._gesture_active:
            should_click = not self._gesture_triggered
            self._gesture_active = False
            self._finish_gesture_tracking()
            self._gesture_triggered = False
            self._emit_debug(
                f"HID gesture button up click_candidate={str(should_click).lower()}"
            )
            self._emit_gesture_event(
                {
                    "type": "button_up",
                    "click_candidate": should_click,
                }
            )
            if should_click:
                self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _on_hid_mode_shift_down(self):
        self._emit_debug("HID mode shift button down")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        self._emit_debug("HID mode shift button up")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        self._emit_debug("HID DPI switch button down")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._emit_debug("HID DPI switch button up")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))

    def _on_hid_gesture_move(self, delta_x, delta_y):
        self._emit_debug(f"HID rawxy move dx={delta_x} dy={delta_y}")
        self._emit_gesture_event(
            {
                "type": "move",
                "source": "hid_rawxy",
                "dx": delta_x,
                "dy": delta_y,
            }
        )
        self._accumulate_gesture_delta(delta_x, delta_y, "hid_rawxy")

    def _register_wake_observer(self):
        try:
            from AppKit import NSWorkspace
        except ImportError:
            return
        notification_center = NSWorkspace.sharedWorkspace().notificationCenter()
        hg = self._hid_gesture

        def _re_enable_tap_and_reconnect(reason):
            if self._tap and self._running:
                Quartz.CGEventTapEnable(self._tap, True)
                ok = Quartz.CGEventTapIsEnabled(self._tap)
                print(
                    f"[MouseHook] Event tap re-enabled ({reason}): "
                    f"{'OK' if ok else 'FAILED — may need restart'}",
                    flush=True,
                )
            if hg:
                hg.force_reconnect()

        def _on_wake(notification):
            _re_enable_tap_and_reconnect("wake")

        def _on_session_resign(notification):
            print("[MouseHook] Session deactivated", flush=True)

        def _on_session_activate(notification):
            _re_enable_tap_and_reconnect("user-switch")

        self._wake_observer = notification_center.addObserverForName_object_queue_usingBlock_(
            "NSWorkspaceDidWakeNotification",
            None,
            None,
            _on_wake,
        )
        self._session_resign_observer = (
            notification_center.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidResignActiveNotification",
                None,
                None,
                _on_session_resign,
            )
        )
        self._session_activate_observer = (
            notification_center.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidBecomeActiveNotification",
                None,
                None,
                _on_session_activate,
            )
        )

    def _unregister_wake_observer(self):
        try:
            from AppKit import NSWorkspace

            notification_center = NSWorkspace.sharedWorkspace().notificationCenter()
            for attr in (
                "_wake_observer",
                "_session_resign_observer",
                "_session_activate_observer",
            ):
                observer = getattr(self, attr, None)
                if observer is not None:
                    notification_center.removeObserver_(observer)
                    setattr(self, attr, None)
        except Exception:
            pass

    def start(self):
        if not _QUARTZ_OK:
            print("[MouseHook] Quartz not available — hook not installed")
            return False
        if self._running:
            return True

        event_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDragged)
            | Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        )

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            self._event_tap_callback,
            None,
        )

        if self._tap is None:
            print("[MouseHook] ERROR: Failed to create CGEventTap!")
            print("[MouseHook] Grant Accessibility permission in:")
            print(
                "[MouseHook]   System Settings -> Privacy & Security -> Accessibility"
            )
            return False

        print("[MouseHook] CGEventTap created successfully", flush=True)

        self._tap_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            self._tap_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)
        print("[MouseHook] CGEventTap enabled and integrated with run loop", flush=True)
        self._running = True

        self._dispatch_thread = threading.Thread(
            target=self._dispatch_worker,
            daemon=True,
            name="MouseHook-dispatch",
        )
        self._dispatch_thread.start()

        self._start_hid_listener()
        self._register_wake_observer()
        return True

    def stop(self):
        self._unregister_wake_observer()
        self._running = False
        self._stop_hid_listener()
        self._connected_device = None

        if self._tap:
            Quartz.CGEventTapEnable(self._tap, False)
            if self._tap_source:
                Quartz.CFRunLoopRemoveSource(
                    Quartz.CFRunLoopGetCurrent(),
                    self._tap_source,
                    Quartz.kCFRunLoopCommonModes,
                )
                self._tap_source = None
            self._tap = None
            print("[MouseHook] CGEventTap disabled and removed", flush=True)

        if self._dispatch_thread:
            self._dispatch_thread.join(timeout=1)
            self._dispatch_thread = None


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "Quartz",
    "_QUARTZ_OK",
    "_BTN_MIDDLE",
    "_BTN_BACK",
    "_BTN_FORWARD",
    "_SCROLL_INVERT_MARKER",
    "_INJECTED_EVENT_MARKER",
    "_kCGEventTapDisabledByTimeout",
    "_kCGEventTapDisabledByUserInput",
]
