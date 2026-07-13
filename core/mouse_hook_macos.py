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
_SHIFT_WHEEL_HSCROLL_MARKER = 0x4D4F5556
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
        self._init_dispatch_queue(maxsize=512)
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

    def _post_shift_hscroll_event(self, cg_event):
        """Translate Shift+vertical-wheel into a horizontal scroll event.

        The translated event has axis-1 zeroed and axis-1 deltas copied onto
        axis-2.  The Shift modifier is stripped so that apps which already
        translate Shift+scroll themselves do not double-translate.  The
        `invert_hscroll` setting flips the direction.
        """
        v_line = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventDeltaAxis1
        )
        v_fixed = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1
        )
        v_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis1
        )

        if self.invert_hscroll:
            v_line = -v_line
            v_fixed = -v_fixed
            v_point = -v_point

        is_continuous = Quartz.CGEventGetIntegerValueField(cg_event, 88)
        if is_continuous:
            unit = Quartz.kCGScrollEventUnitPixel
            primary_delta = v_point
        else:
            unit = Quartz.kCGScrollEventUnitLine
            primary_delta = v_line

        new_event = Quartz.CGEventCreateScrollWheelEvent(
            None, unit, 2, 0, primary_delta
        )
        if not new_event:
            return False

        flags = Quartz.CGEventGetFlags(cg_event)
        Quartz.CGEventSetFlags(new_event, flags & ~Quartz.kCGEventFlagMaskShift)
        Quartz.CGEventSetIntegerValueField(
            new_event,
            Quartz.kCGEventSourceUserData,
            _SHIFT_WHEEL_HSCROLL_MARKER,
        )

        for field_name, value in (
            ("kCGScrollWheelEventDeltaAxis2", v_line),
            ("kCGScrollWheelEventFixedPtDeltaAxis2", v_fixed),
            ("kCGScrollWheelEventPointDeltaAxis2", v_point),
            ("kCGScrollWheelEventDeltaAxis1", 0),
            ("kCGScrollWheelEventFixedPtDeltaAxis1", 0),
            ("kCGScrollWheelEventPointDeltaAxis1", 0),
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            Quartz.CGEventSetIntegerValueField(new_event, field, value)

        for field_name in (
            "kCGScrollWheelEventScrollPhase",
            "kCGScrollWheelEventMomentumPhase",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            Quartz.CGEventSetIntegerValueField(new_event, field, value)

        Quartz.CGEventPost(Quartz.kCGHIDEventTap, new_event)
        return True

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

    def _emit_gesture_swipe(self, mouse_event):
        self._enqueue_dispatch_event(mouse_event)

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

            # KVM / cold-start guard: when no Logitech is currently bound to
            # this host, the CGEventTap must be a complete pass-through. The
            # tap sees events from every mouse the OS knows about, so without
            # this guard a trackpad swipe or a generic USB mouse's xbutton
            # click would get routed through Mouser's remap pipeline -- the
            # exact failure mode users hit when their KVM switches the
            # Logitech to another machine while Mouser keeps running on
            # this one.
            if not self._should_intercept_events():
                return cg_event

            mouse_event = None
            should_block = False

            if (
                event_type
                in (
                    Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventOtherMouseDragged,
                )
                and self._gesture_active
            ):
                if not self._gesture_direction_enabled:
                    return cg_event
                dx = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaX
                )
                dy = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaY
                )
                self._emit_debug(
                    f"Gesture move event type={int(event_type)} dx={dx} dy={dy}"
                )
                self._gesture_recognizer.sample(dx, dy, "event_tap")
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
                source_marker = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGEventSourceUserData
                )
                if source_marker in (
                    _SCROLL_INVERT_MARKER,
                    _SHIFT_WHEEL_HSCROLL_MARKER,
                ):
                    return cg_event
                if self.ignore_trackpad:
                    scroll_phase = Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGScrollWheelEventScrollPhase
                    )
                    momentum_phase = Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGScrollWheelEventMomentumPhase
                    )
                    if scroll_phase != 0 or momentum_phase != 0:
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
                if h_delta == 0:
                    flags = Quartz.CGEventGetFlags(cg_event)
                    if flags & Quartz.kCGEventFlagMaskShift:
                        v_fixed = Quartz.CGEventGetIntegerValueField(
                            cg_event,
                            Quartz.kCGScrollWheelEventFixedPtDeltaAxis1,
                        )
                        if v_fixed != 0 and self._post_shift_hscroll_event(cg_event):
                            return None
                if h_delta != 0:
                    if h_delta > 0:
                        mouse_event = MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(h_delta))
                        should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events
                    else:
                        mouse_event = MouseEvent(MouseEvent.HSCROLL_LEFT, abs(h_delta))
                        should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events
                if mouse_event:
                    self._enqueue_dispatch_event(mouse_event)
                    mouse_event = None
                if should_block:
                    return None
                if (self.invert_vscroll or self.invert_hscroll) and not self.wheel_native_invert_active:
                    if self._post_inverted_scroll_event(cg_event):
                        return None

            if mouse_event:
                self._enqueue_dispatch_event(mouse_event)

            if should_block:
                return None
            return cg_event

        except Exception as exc:
            print(f"[MouseHook] event tap callback error: {exc}")
            return cg_event

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
    "_SHIFT_WHEEL_HSCROLL_MARKER",
    "_kCGEventTapDisabledByTimeout",
    "_kCGEventTapDisabledByUserInput",
]
