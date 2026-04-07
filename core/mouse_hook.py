"""
Low-level mouse hook — supports Windows (via ctypes/Win32) and macOS (via
Quartz CGEventTap).
Intercepts mouse button presses and horizontal scroll events
so we can remap them before they reach applications.
"""

import queue
import sys
import threading
import time

try:
    from core.hid_gesture import HidGestureListener
except Exception:              # ImportError or hidapi missing
    HidGestureListener = None


# ==================================================================
# Shared: MouseEvent (platform-neutral)
# ==================================================================

class MouseEvent:
    """Represents a captured mouse event."""
    XBUTTON1_DOWN = "xbutton1_down"
    XBUTTON1_UP = "xbutton1_up"
    XBUTTON2_DOWN = "xbutton2_down"
    XBUTTON2_UP = "xbutton2_up"
    MIDDLE_DOWN = "middle_down"
    MIDDLE_UP = "middle_up"
    GESTURE_DOWN = "gesture_down"      # MX Master 3S gesture button
    GESTURE_UP = "gesture_up"
    GESTURE_CLICK = "gesture_click"
    GESTURE_SWIPE_LEFT = "gesture_swipe_left"
    GESTURE_SWIPE_RIGHT = "gesture_swipe_right"
    GESTURE_SWIPE_UP = "gesture_swipe_up"
    GESTURE_SWIPE_DOWN = "gesture_swipe_down"
    HSCROLL_LEFT = "hscroll_left"
    HSCROLL_RIGHT = "hscroll_right"
    MODE_SHIFT_DOWN = "mode_shift_down"
    MODE_SHIFT_UP = "mode_shift_up"
    DPI_SWITCH_DOWN = "dpi_switch_down"
    DPI_SWITCH_UP = "dpi_switch_up"

    def __init__(self, event_type, raw_data=None):
        self.event_type = event_type
        self.raw_data = raw_data
        self.timestamp = time.time()


def _format_debug_details(raw_data):
    if raw_data is None:
        return ""
    if isinstance(raw_data, dict):
        parts = [f"{k}={v}" for k, v in raw_data.items()]
        return " " + " ".join(parts)
    return f" value={raw_data}"


# ==================================================================
# Windows implementation
# ==================================================================

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes
    from ctypes import (CFUNCTYPE, POINTER, Structure, c_int, c_uint, c_ushort,
                        c_ulong, c_void_p, sizeof, byref, create_string_buffer, windll)

    # Windows constants
    WH_MOUSE_LL = 14
    WM_XBUTTONDOWN = 0x020B
    WM_XBUTTONUP = 0x020C
    WM_MBUTTONDOWN = 0x0207
    WM_MBUTTONUP = 0x0208
    WM_MOUSEHWHEEL = 0x020E
    WM_MOUSEWHEEL = 0x020A

    HC_ACTION = 0
    XBUTTON1 = 0x0001
    XBUTTON2 = 0x0002

    class MSLLHOOKSTRUCT(Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    HOOKPROC = CFUNCTYPE(ctypes.c_long, c_int, wintypes.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT))

    SetWindowsHookExW = windll.user32.SetWindowsHookExW
    SetWindowsHookExW.restype = wintypes.HHOOK
    SetWindowsHookExW.argtypes = [c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]

    CallNextHookEx = windll.user32.CallNextHookEx
    CallNextHookEx.restype = ctypes.c_long
    CallNextHookEx.argtypes = [wintypes.HHOOK, c_int, wintypes.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT)]

    UnhookWindowsHookEx = windll.user32.UnhookWindowsHookEx
    UnhookWindowsHookEx.restype = wintypes.BOOL
    UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

    GetModuleHandleW = windll.kernel32.GetModuleHandleW
    GetModuleHandleW.restype = wintypes.HMODULE
    GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    GetMessageW = windll.user32.GetMessageW
    PostThreadMessageW = windll.user32.PostThreadMessageW

    WM_QUIT = 0x0012
    INJECTED_FLAG = 0x00000001

    # Raw Input constants
    WM_INPUT = 0x00FF
    RIDEV_INPUTSINK = 0x00000100
    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE = 0
    RIM_TYPEKEYBOARD = 1
    RIM_TYPEHID = 2
    RIDI_DEVICENAME = 0x20000007
    SW_HIDE = 0
    STANDARD_BUTTON_MASK = 0x1F

    class RAWINPUTDEVICE(Structure):
        _fields_ = [
            ("usUsagePage", c_ushort),
            ("usUsage", c_ushort),
            ("dwFlags", c_ulong),
            ("hwndTarget", wintypes.HWND),
        ]

    class RAWINPUTHEADER(Structure):
        _fields_ = [
            ("dwType", c_ulong),
            ("dwSize", c_ulong),
            ("hDevice", c_void_p),
            ("wParam", POINTER(c_ulong)),
        ]

    class RAWMOUSE(Structure):
        _fields_ = [
            ("usFlags", c_ushort),
            ("usButtonFlags", c_ushort),
            ("usButtonData", c_ushort),
            ("ulRawButtons", c_ulong),
            ("lLastX", c_int),
            ("lLastY", c_int),
            ("ulExtraInformation", c_ulong),
        ]

    class RAWHID(Structure):
        _fields_ = [
            ("dwSizeHid", c_ulong),
            ("dwCount", c_ulong),
        ]

    WNDPROC_TYPE = CFUNCTYPE(ctypes.c_longlong, wintypes.HWND, c_uint,
                              wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(Structure):
        _fields_ = [
            ("cbSize", c_uint),
            ("style", c_uint),
            ("lpfnWndProc", WNDPROC_TYPE),
            ("cbClsExtra", c_int),
            ("cbWndExtra", c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    RegisterRawInputDevices = windll.user32.RegisterRawInputDevices
    GetRawInputData = windll.user32.GetRawInputData
    GetRawInputData.argtypes = [c_void_p, c_uint, c_void_p, POINTER(c_uint), c_uint]
    GetRawInputData.restype = c_uint
    GetRawInputDeviceInfoW = windll.user32.GetRawInputDeviceInfoW
    RegisterClassExW = windll.user32.RegisterClassExW

    CreateWindowExW = windll.user32.CreateWindowExW
    CreateWindowExW.restype = wintypes.HWND
    CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        c_int, c_int, c_int, c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]

    ShowWindow = windll.user32.ShowWindow
    DefWindowProcW = windll.user32.DefWindowProcW
    DefWindowProcW.restype = ctypes.c_longlong
    DefWindowProcW.argtypes = [wintypes.HWND, c_uint, wintypes.WPARAM, wintypes.LPARAM]

    TranslateMessage = windll.user32.TranslateMessage
    DispatchMessageW = windll.user32.DispatchMessageW
    DestroyWindow = windll.user32.DestroyWindow

    def hiword(dword):
        val = (dword >> 16) & 0xFFFF
        if val >= 0x8000:
            val -= 0x10000
        return val

    # Custom messages for deferred scroll injection
    WM_APP = 0x8000
    WM_APP_INJECT_VSCROLL = WM_APP + 1
    WM_APP_INJECT_HSCROLL = WM_APP + 2

    # Device change notification constants
    WM_DEVICECHANGE = 0x0219
    DBT_DEVNODES_CHANGED = 0x0007

    from core.key_simulator import inject_scroll as _inject_scroll_impl
    from core.key_simulator import MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL

    PostMessageW = windll.user32.PostMessageW
    PostMessageW.argtypes = [wintypes.HWND, c_uint, wintypes.WPARAM, wintypes.LPARAM]
    PostMessageW.restype = wintypes.BOOL

    class MouseHook:
        """
        Installs a low-level mouse hook on Windows to intercept
        side-button clicks and horizontal scroll events.
        """

        def __init__(self):
            self._hook = None
            self._hook_thread = None
            self._thread_id = None
            self._running = False
            self._callbacks = {}
            self._blocked_events = set()
            self._hook_proc = None
            self._debug_callback = None
            self._gesture_callback = None
            self.debug_mode = False
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._pending_vscroll = 0
            self._pending_hscroll = 0
            self._vscroll_posted = False
            self._hscroll_posted = False
            self._ri_wndproc_ref = None
            self._ri_hwnd = None
            self._device_name_cache = {}
            self.divert_mode_shift = False
            self.divert_dpi_switch = False
            self._gesture_active = False
            self._prev_raw_buttons = {}
            self._hid_gesture = None
            self._last_rehook_time = 0
            self._device_connected = False
            self._connection_change_cb = None
            self._startup_event = threading.Event()
            self._startup_ok = False
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
            self._connected_device = None
            self._dispatch_queue = queue.Queue()
            self._dispatch_worker_thread = None

        def register(self, event_type, callback):
            self._callbacks.setdefault(event_type, []).append(callback)

        def block(self, event_type):
            self._blocked_events.add(event_type)

        def unblock(self, event_type):
            self._blocked_events.discard(event_type)

        def reset_bindings(self):
            self._callbacks.clear()
            self._blocked_events.clear()

        def configure_gestures(self, enabled=False, threshold=50,
                               deadzone=40, timeout_ms=3000, cooldown_ms=500):
            self._gesture_direction_enabled = bool(enabled)
            self._gesture_threshold = float(max(5, threshold))
            self._gesture_deadzone = float(max(0, deadzone))
            self._gesture_timeout_ms = max(250, int(timeout_ms))
            self._gesture_cooldown_ms = max(0, int(cooldown_ms))
            if not self._gesture_direction_enabled:
                self._gesture_tracking = False
                self._gesture_triggered = False
                self._gesture_input_source = None

        def set_connection_change_callback(self, cb):
            """Register ``cb(connected: bool)`` invoked on device connect/disconnect."""
            self._connection_change_cb = cb

        @property
        def device_connected(self):
            return self._device_connected

        @property
        def connected_device(self):
            return self._connected_device

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

        def _emit_debug(self, message):
            if self.debug_mode and self._debug_callback:
                try:
                    self._debug_callback(message)
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
                f"{_format_debug_details(event.raw_data)} callbacks={len(callbacks)}"
            )
            if event.event_type.startswith("gesture_"):
                self._emit_gesture_event({
                    "type": "dispatch",
                    "event_name": event.event_type,
                    "callbacks": len(callbacks),
                })
            if not callbacks:
                self._emit_debug(f"No mapped action for {event.event_type}")
                if event.event_type.startswith("gesture_"):
                    self._emit_gesture_event({
                        "type": "unmapped",
                        "event_name": event.event_type,
                    })
            for cb in callbacks:
                try:
                    cb(event)
                except Exception as e:
                    print(f"[MouseHook] callback error: {e}")

        def _hid_gesture_available(self):
            return self._hid_gesture is not None and self._device_connected

        def _dispatch_worker(self):
            """Background thread: drains the event queue so the hook callback returns fast."""
            while self._running:
                try:
                    event = self._dispatch_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    self._dispatch(event)
                except Exception as e:
                    print(f"[MouseHook] dispatch worker error: {e}")

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

        def _accumulate_gesture_delta(self, delta_x, delta_y, source):
            if not (self._gesture_direction_enabled and self._gesture_active):
                return
            if self._gesture_cooldown_active():
                self._emit_debug(
                    f"Gesture cooldown active source={source} "
                    f"dx={delta_x} dy={delta_y}"
                )
                self._emit_gesture_event({
                    "type": "cooldown_active",
                    "source": source,
                    "dx": delta_x,
                    "dy": delta_y,
                })
                return
            if not self._gesture_tracking:
                self._emit_debug(f"Gesture tracking started source={source}")
                self._emit_gesture_event({
                    "type": "tracking_started",
                    "source": source,
                })
                self._start_gesture_tracking()

            now = time.monotonic()
            idle_ms = (now - self._gesture_last_move_at) * 1000.0
            if idle_ms > self._gesture_timeout_ms:
                self._emit_debug(
                    f"Gesture segment reset timeout source={source} "
                    f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
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
            self._emit_gesture_event({
                "type": "segment",
                "source": source,
                "dx": self._gesture_delta_x,
                "dy": self._gesture_delta_y,
            })

            gesture_event = self._detect_gesture_event()
            if not gesture_event:
                return

            self._gesture_triggered = True
            self._emit_debug(
                "Gesture detected "
                f"{gesture_event} source={source} "
                f"delta_x={self._gesture_delta_x} delta_y={self._gesture_delta_y}"
            )
            self._emit_gesture_event({
                "type": "detected",
                "event_name": gesture_event,
                "source": source,
                "dx": self._gesture_delta_x,
                "dy": self._gesture_delta_y,
            })
            self._dispatch(
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
            self._emit_gesture_event({
                "type": "cooldown_started",
                "source": source,
                "for_ms": self._gesture_cooldown_ms,
            })
            self._finish_gesture_tracking()

        _WM_NAMES = {
            0x0200: "WM_MOUSEMOVE",
            0x0201: "WM_LBUTTONDOWN", 0x0202: "WM_LBUTTONUP",
            0x0204: "WM_RBUTTONDOWN", 0x0205: "WM_RBUTTONUP",
            0x0207: "WM_MBUTTONDOWN", 0x0208: "WM_MBUTTONUP",
            0x020A: "WM_MOUSEWHEEL",  0x020B: "WM_XBUTTONDOWN",
            0x020C: "WM_XBUTTONUP",   0x020E: "WM_MOUSEHWHEEL",
        }

        def _low_level_handler(self, nCode, wParam, lParam):
            try:
                return self._low_level_handler_inner(nCode, wParam, lParam)
            except Exception as exc:
                # CRITICAL: never let an exception escape the hook callback —
                # Windows would silently uninstall the hook, killing all remapping.
                try:
                    print(f"[MouseHook] CRITICAL _low_level_handler EXCEPTION: {exc}")
                    import traceback; traceback.print_exc()
                except Exception:
                    pass
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

        def _low_level_handler_inner(self, nCode, wParam, lParam):
            if nCode == HC_ACTION:
                data = lParam.contents
                mouse_data = data.mouseData
                flags = data.flags
                event = None
                should_block = False

                if self.debug_mode and self._debug_callback:
                    wm_name = self._WM_NAMES.get(wParam, f"0x{wParam:04X}")
                    if wParam != 0x0200:
                        extra = data.dwExtraInfo.contents.value if data.dwExtraInfo else 0
                        info = (f"{wm_name}  mouseData=0x{mouse_data:08X}  "
                                f"hiword={hiword(mouse_data)}  flags=0x{flags:04X}  "
                                f"extraInfo=0x{extra:X}")
                        try:
                            self._debug_callback(info)
                        except Exception:
                            pass

                if flags & INJECTED_FLAG:
                    return CallNextHookEx(self._hook, nCode, wParam, lParam)

                if wParam == WM_XBUTTONDOWN:
                    xbutton = hiword(mouse_data)
                    if xbutton == XBUTTON1:
                        event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                        should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
                    elif xbutton == XBUTTON2:
                        event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                        should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events

                elif wParam == WM_XBUTTONUP:
                    xbutton = hiword(mouse_data)
                    if xbutton == XBUTTON1:
                        event = MouseEvent(MouseEvent.XBUTTON1_UP)
                        should_block = MouseEvent.XBUTTON1_UP in self._blocked_events
                    elif xbutton == XBUTTON2:
                        event = MouseEvent(MouseEvent.XBUTTON2_UP)
                        should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

                elif wParam == WM_MBUTTONDOWN:
                    event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                    should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events

                elif wParam == WM_MBUTTONUP:
                    event = MouseEvent(MouseEvent.MIDDLE_UP)
                    should_block = MouseEvent.MIDDLE_UP in self._blocked_events

                elif wParam == WM_MOUSEWHEEL:
                    if self.invert_vscroll:
                        delta = hiword(mouse_data)
                        if delta != 0 and self._ri_hwnd:
                            self._pending_vscroll += (-delta)
                            if self._vscroll_posted:
                                return 1
                            if PostMessageW(self._ri_hwnd, WM_APP_INJECT_VSCROLL, 0, 0):
                                self._vscroll_posted = True
                                return 1
                            self._pending_vscroll -= (-delta)
                        elif delta != 0:
                            self._emit_debug("Invert vertical scroll skipped: raw input window unavailable")

                elif wParam == WM_MOUSEHWHEEL:
                    delta = hiword(mouse_data)
                    if delta > 0:
                        event = MouseEvent(MouseEvent.HSCROLL_LEFT, abs(delta))
                        should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events
                    elif delta < 0:
                        event = MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(delta))
                        should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events

                    if self.invert_hscroll:
                        # When horizontal scroll is remapped, preserve the mapped
                        # action instead of short-circuiting into synthetic wheel injection.
                        if delta != 0 and self._ri_hwnd and not should_block:
                            self._pending_hscroll += (-delta)
                            if self._hscroll_posted:
                                return 1
                            if PostMessageW(self._ri_hwnd, WM_APP_INJECT_HSCROLL, 0, 0):
                                self._hscroll_posted = True
                                return 1
                            self._pending_hscroll -= (-delta)
                        elif delta != 0 and not should_block:
                            self._emit_debug("Invert horizontal scroll skipped: raw input window unavailable")

                if event:
                    self._dispatch_queue.put(event)
                    if should_block:
                        return 1

            return CallNextHookEx(self._hook, nCode, wParam, lParam)

        def _get_device_name(self, hDevice):
            if hDevice in self._device_name_cache:
                return self._device_name_cache[hDevice]
            try:
                sz = c_uint(0)
                GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, None, byref(sz))
                if sz.value > 0:
                    buf = ctypes.create_unicode_buffer(sz.value + 1)
                    GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, buf, byref(sz))
                    name = buf.value
                else:
                    name = ""
            except Exception:
                name = ""
            self._device_name_cache[hDevice] = name
            return name

        def _is_logitech(self, hDevice):
            return "046d" in self._get_device_name(hDevice).lower()

        def _ri_wndproc(self, hwnd, msg, wParam, lParam):
            if msg == WM_INPUT:
                try:
                    self._process_raw_input(lParam)
                except Exception as e:
                    print(f"[MouseHook] Raw Input error: {e}")
                return 0

            if msg == WM_APP_INJECT_VSCROLL:
                delta = self._pending_vscroll
                self._pending_vscroll = 0
                self._vscroll_posted = False
                if delta != 0:
                    _inject_scroll_impl(MOUSEEVENTF_WHEEL, delta)
                return 0

            if msg == WM_APP_INJECT_HSCROLL:
                delta = self._pending_hscroll
                self._pending_hscroll = 0
                self._hscroll_posted = False
                if delta != 0:
                    _inject_scroll_impl(MOUSEEVENTF_HWHEEL, delta)
                return 0

            if msg == WM_DEVICECHANGE:
                if wParam == DBT_DEVNODES_CHANGED:
                    self._on_device_change()
                return 0

            return DefWindowProcW(hwnd, msg, wParam, lParam)

        def _process_raw_input(self, lParam):
            sz = c_uint(0)
            GetRawInputData(lParam, RID_INPUT, None, byref(sz),
                            sizeof(RAWINPUTHEADER))
            if sz.value == 0:
                return
            buf = create_string_buffer(sz.value)
            ret = GetRawInputData(lParam, RID_INPUT, buf, byref(sz),
                                  sizeof(RAWINPUTHEADER))
            if ret == 0xFFFFFFFF:
                return
            header = RAWINPUTHEADER.from_buffer_copy(buf)
            if not self._is_logitech(header.hDevice):
                return
            if header.dwType == RIM_TYPEMOUSE:
                self._check_raw_mouse_gesture(header.hDevice, buf)

        def _check_raw_mouse_gesture(self, hDevice, buf):
            if self._hid_gesture_available():
                return
            mouse = RAWMOUSE.from_buffer_copy(buf, sizeof(RAWINPUTHEADER))
            raw_btns = mouse.ulRawButtons
            prev_btns = self._prev_raw_buttons.get(hDevice, 0)
            self._prev_raw_buttons[hDevice] = raw_btns

            extra_now = raw_btns & ~STANDARD_BUTTON_MASK
            extra_prev = prev_btns & ~STANDARD_BUTTON_MASK

            if extra_now == extra_prev:
                return
            if extra_now and not extra_prev:
                if not self._gesture_active:
                    self._gesture_active = True
                    self._gesture_triggered = False
                    print(f"[MouseHook] Gesture DOWN (rawBtns extra: 0x{extra_now:X})")
            elif not extra_now and extra_prev:
                if self._gesture_active:
                    self._gesture_active = False
                    print("[MouseHook] Gesture UP")
                    self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

        def _setup_raw_input(self):
            hInst = GetModuleHandleW(None)
            cls_name = f"MouserRawInput_{id(self)}"
            self._ri_wndproc_ref = WNDPROC_TYPE(self._ri_wndproc)

            wc = WNDCLASSEXW()
            wc.cbSize = sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._ri_wndproc_ref
            wc.hInstance = hInst
            wc.lpszClassName = cls_name
            RegisterClassExW(byref(wc))

            self._ri_hwnd = CreateWindowExW(
                0, cls_name, "Mouser RI", 0,
                0, 0, 1, 1,
                None, None, hInst, None,
            )
            if not self._ri_hwnd:
                print("[MouseHook] CreateWindowExW failed — gesture detection unavailable")
                return False

            ShowWindow(self._ri_hwnd, SW_HIDE)

            rid = (RAWINPUTDEVICE * 4)()
            rid[0].usUsagePage = 0x01
            rid[0].usUsage = 0x02
            rid[0].dwFlags = RIDEV_INPUTSINK
            rid[0].hwndTarget = self._ri_hwnd
            rid[1].usUsagePage = 0xFF43
            rid[1].usUsage = 0x0202
            rid[1].dwFlags = RIDEV_INPUTSINK
            rid[1].hwndTarget = self._ri_hwnd
            rid[2].usUsagePage = 0xFF43
            rid[2].usUsage = 0x0204
            rid[2].dwFlags = RIDEV_INPUTSINK
            rid[2].hwndTarget = self._ri_hwnd
            rid[3].usUsagePage = 0x0C
            rid[3].usUsage = 0x01
            rid[3].dwFlags = RIDEV_INPUTSINK
            rid[3].hwndTarget = self._ri_hwnd

            if RegisterRawInputDevices(rid, 4, sizeof(RAWINPUTDEVICE)):
                print("[MouseHook] Raw Input: mice + Logitech HID + consumer")
                return True
            if RegisterRawInputDevices(rid, 2, sizeof(RAWINPUTDEVICE)):
                print("[MouseHook] Raw Input: mice + Logitech HID short")
                return True
            if RegisterRawInputDevices(rid, 1, sizeof(RAWINPUTDEVICE)):
                print("[MouseHook] Raw Input: mice only")
                return True
            print("[MouseHook] Raw Input registration failed")
            return False

        def _run_hook(self):
            self._thread_id = windll.kernel32.GetCurrentThreadId()
            self._hook_proc = HOOKPROC(self._low_level_handler)
            self._hook = SetWindowsHookExW(
                WH_MOUSE_LL, self._hook_proc, GetModuleHandleW(None), 0)
            if not self._hook:
                self._startup_ok = False
                self._startup_event.set()
                print("[MouseHook] Failed to install hook!")
                return
            print("[MouseHook] Hook installed successfully")
            self._setup_raw_input()
            self._running = True
            self._startup_ok = True
            self._startup_event.set()

            msg = wintypes.MSG()
            while self._running:
                result = GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))

            if self._ri_hwnd:
                DestroyWindow(self._ri_hwnd)
                self._ri_hwnd = None
            if self._hook:
                UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._running = False
            print("[MouseHook] Hook removed")

        def _on_device_change(self):
            now = time.time()
            if now - self._last_rehook_time < 2.0:
                return
            self._last_rehook_time = now
            print("[MouseHook] Device change detected — refreshing hook")
            self._device_name_cache.clear()
            self._prev_raw_buttons.clear()
            self._reinstall_hook()

        def _reinstall_hook(self):
            if self._hook:
                UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._hook_proc = HOOKPROC(self._low_level_handler)
            self._hook = SetWindowsHookExW(
                WH_MOUSE_LL, self._hook_proc, GetModuleHandleW(None), 0)
            if self._hook:
                print("[MouseHook] Hook reinstalled successfully")
            else:
                print("[MouseHook] Failed to reinstall hook!")

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
                self._emit_gesture_event({
                    "type": "button_up",
                    "click_candidate": should_click,
                })
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
            self._emit_debug(
                f"HID rawxy move dx={delta_x} dy={delta_y}"
            )
            self._emit_gesture_event({
                "type": "move",
                "source": "hid_rawxy",
                "dx": delta_x,
                "dy": delta_y,
            })
            self._accumulate_gesture_delta(delta_x, delta_y, "hid_rawxy")

        def _on_hid_connect(self):
            self._connected_device = (
                self._hid_gesture.connected_device if self._hid_gesture else None
            )
            self._set_device_connected(True)

        def _on_hid_disconnect(self):
            self._connected_device = None
            self._set_device_connected(False)

        def start(self):
            if self._hook_thread and self._hook_thread.is_alive():
                return True
            self._startup_ok = False
            self._startup_event.clear()
            self._hook_thread = threading.Thread(target=self._run_hook, daemon=True)
            self._hook_thread.start()
            if not self._startup_event.wait(2):
                print("[MouseHook] Hook startup timed out")
                self.stop()
                return False
            if not self._startup_ok:
                return False
            if HidGestureListener is not None:
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
                listener = HidGestureListener(
                    on_down=self._on_hid_gesture_down,
                    on_up=self._on_hid_gesture_up,
                    on_move=self._on_hid_gesture_move,
                    on_connect=self._on_hid_connect,
                    on_disconnect=self._on_hid_disconnect,
                    extra_diverts=extra,
                )
                self._hid_gesture = listener
                if not listener.start():
                    self._hid_gesture = None
            # Start the dispatch worker — processes events off the hook thread
            self._dispatch_worker_thread = threading.Thread(
                target=self._dispatch_worker, daemon=True, name="HookDispatch")
            self._dispatch_worker_thread.start()
            return True

        def stop(self):
            self._running = False
            if self._hid_gesture:
                self._hid_gesture.stop()
                self._hid_gesture = None
            self._connected_device = None
            if self._dispatch_worker_thread:
                self._dispatch_worker_thread.join(timeout=1)
                self._dispatch_worker_thread = None
            if self._thread_id:
                PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            if self._hook_thread:
                self._hook_thread.join(timeout=2)
            self._hook = None
            self._ri_hwnd = None
            self._thread_id = None
            self._startup_ok = False
            self._startup_event.clear()


# ==================================================================
# macOS implementation
# ==================================================================

elif sys.platform == "darwin":
    try:
        import Quartz
        _QUARTZ_OK = True
    except ImportError:
        _QUARTZ_OK = False
        print("[MouseHook] pyobjc-framework-Quartz not installed — "
              "pip install pyobjc-framework-Quartz")

    # HID button numbers (typical USB/BT HID mapping on macOS)
    _BTN_MIDDLE = 2
    _BTN_BACK = 3
    _BTN_FORWARD = 4
    _SCROLL_INVERT_MARKER = 0x4D4F5553
    _kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    _kCGEventTapDisabledByUserInput = 0xFFFFFFFF

    class MouseHook:
        """
        Uses CGEventTap on macOS to intercept mouse button presses and scroll
        events.  Requires Accessibility permission:
        System Settings -> Privacy & Security -> Accessibility
        """

        def __init__(self):
            self._running = False
            self._callbacks = {}
            self._blocked_events = set()
            self._tap = None
            self._tap_source = None
            self._debug_callback = None
            self._gesture_callback = None
            self.debug_mode = False
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._gesture_active = False
            self._hid_gesture = None
            self._wake_observer = None
            self._session_resign_observer = None
            self._session_activate_observer = None
            self._dispatch_queue = queue.Queue()
            self._dispatch_thread = None
            self._first_event_logged = False
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
            self._connected_device = None

        def register(self, event_type, callback):
            self._callbacks.setdefault(event_type, []).append(callback)

        def block(self, event_type):
            self._blocked_events.add(event_type)

        def unblock(self, event_type):
            self._blocked_events.discard(event_type)

        def reset_bindings(self):
            self._callbacks.clear()
            self._blocked_events.clear()

        def configure_gestures(self, enabled=False, threshold=50,
                               deadzone=40, timeout_ms=3000, cooldown_ms=500):
            self._gesture_direction_enabled = bool(enabled)
            self._gesture_threshold = float(max(5, threshold))
            self._gesture_deadzone = float(max(0, deadzone))
            self._gesture_timeout_ms = max(250, int(timeout_ms))
            self._gesture_cooldown_ms = max(0, int(cooldown_ms))
            if not self._gesture_direction_enabled:
                self._gesture_tracking = False
                self._gesture_triggered = False

        def set_connection_change_callback(self, cb):
            self._connection_change_cb = cb

        @property
        def device_connected(self):
            return self._device_connected

        @property
        def connected_device(self):
            return self._connected_device

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

        def _emit_debug(self, message):
            if self.debug_mode and self._debug_callback:
                try:
                    self._debug_callback(message)
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
                f"{_format_debug_details(event.raw_data)} callbacks={len(callbacks)}"
            )
            if event.event_type.startswith("gesture_"):
                self._emit_gesture_event({
                    "type": "dispatch",
                    "event_name": event.event_type,
                    "callbacks": len(callbacks),
                })
            if not callbacks:
                self._emit_debug(f"No mapped action for {event.event_type}")
                if event.event_type.startswith("gesture_"):
                    self._emit_gesture_event({
                        "type": "unmapped",
                        "event_name": event.event_type,
                    })
            for cb in callbacks:
                try:
                    cb(event)
                except Exception as e:
                    print(f"[MouseHook] callback error: {e}")

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
                    (axis == 1 and self.invert_vscroll) or
                    (axis == 2 and self.invert_hscroll)
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

        def _accumulate_gesture_delta(self, delta_x, delta_y, source):
            if not (self._gesture_direction_enabled and self._gesture_active):
                return
            if self._gesture_cooldown_active():
                self._emit_debug(
                    f"Gesture cooldown active source={source} "
                    f"dx={delta_x} dy={delta_y}"
                )
                self._emit_gesture_event({
                    "type": "cooldown_active",
                    "source": source,
                    "dx": delta_x,
                    "dy": delta_y,
                })
                return
            if not self._gesture_tracking:
                self._emit_debug(f"Gesture tracking started source={source}")
                self._emit_gesture_event({
                    "type": "tracking_started",
                    "source": source,
                })
                self._start_gesture_tracking()

            now = time.monotonic()
            idle_ms = (now - self._gesture_last_move_at) * 1000.0
            if idle_ms > self._gesture_timeout_ms:
                self._emit_debug(
                    f"Gesture segment reset timeout source={source} "
                    f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
                )
                self._start_gesture_tracking()

            # Prefer device-provided RawXY over CGEventTap deltas. On fast swipes
            # the event tap can emit a tiny starter delta before the HID stream
            # arrives; if we keep that lock, the real swipe is discarded and the
            # release falls through as a click.
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
            self._emit_gesture_event({
                "type": "segment",
                "source": source,
                "dx": self._gesture_delta_x,
                "dy": self._gesture_delta_y,
            })

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
                self._emit_gesture_event({
                    "type": "detected",
                    "event_name": gesture_event,
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                })
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
                self._emit_gesture_event({
                    "type": "cooldown_started",
                    "source": source,
                    "for_ms": self._gesture_cooldown_ms,
                })
                self._finish_gesture_tracking()
                return

        def _dispatch_worker(self):
            """Background thread: drains the event queue so tap callback returns fast."""
            while self._running:
                try:
                    event = self._dispatch_queue.get(timeout=0.05)
                    self._dispatch(event)
                except queue.Empty:
                    continue

        def _event_tap_callback(self, proxy, event_type, cg_event, refcon):
            """CGEventTap callback.  Return the event to pass through, or None to suppress."""
            try:
                if event_type in (
                    _kCGEventTapDisabledByTimeout,
                    _kCGEventTapDisabledByUserInput,
                ):
                    print(f"[MouseHook] CGEventTap disabled by system "
                          f"(type=0x{event_type:X}), re-enabling", flush=True)
                    Quartz.CGEventTapEnable(self._tap, True)
                    return cg_event

                if not self._first_event_logged:
                    self._first_event_logged = True
                    print("[MouseHook] CGEventTap: first event received", flush=True)

                mouse_event = None
                should_block = False

                if (event_type in (
                        Quartz.kCGEventMouseMoved,
                        Quartz.kCGEventOtherMouseDragged,
                    ) and
                        self._gesture_direction_enabled and self._gesture_active):
                    self._emit_debug(
                        "Gesture move event "
                        f"type={int(event_type)} "
                        f"dx={Quartz.CGEventGetIntegerValueField(cg_event, Quartz.kCGMouseEventDeltaX)} "
                        f"dy={Quartz.CGEventGetIntegerValueField(cg_event, Quartz.kCGMouseEventDeltaY)}"
                    )
                    self._emit_gesture_event({
                        "type": "move",
                        "source": "event_tap",
                        "dx": Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaX),
                        "dy": Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaY),
                    })
                    if self._gesture_input_source == "hid_rawxy":
                        return None
                    self._accumulate_gesture_delta(
                        Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaX),
                        Quartz.CGEventGetIntegerValueField(
                            cg_event, Quartz.kCGMouseEventDeltaY),
                        "event_tap",
                    )
                    return None

                if event_type == Quartz.kCGEventOtherMouseDown:
                    btn = Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGMouseEventButtonNumber)
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
                        cg_event, Quartz.kCGMouseEventButtonNumber)
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
                        ) == _SCROLL_INVERT_MARKER
                    ):
                        return cg_event
                    # Pass through trackpad / Magic Mouse continuous scroll
                    # events untouched — only intercept discrete mouse wheel.
                    _kCGScrollWheelEventIsContinuous = 88
                    if Quartz.CGEventGetIntegerValueField(
                        cg_event, _kCGScrollWheelEventIsContinuous
                    ):
                        return cg_event
                    h_delta = Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis2)
                    h_delta = h_delta / 65536.0
                    if self.debug_mode and self._debug_callback:
                        try:
                            v_delta = Quartz.CGEventGetIntegerValueField(
                                cg_event,
                                Quartz.kCGScrollWheelEventFixedPtDeltaAxis1) / 65536.0
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

            except Exception as e:
                print(f"[MouseHook] event tap callback error: {e}")
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
                self._emit_gesture_event({
                    "type": "button_up",
                    "click_candidate": should_click,
                })
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
            self._emit_debug(
                f"HID rawxy move dx={delta_x} dy={delta_y}"
            )
            self._emit_gesture_event({
                "type": "move",
                "source": "hid_rawxy",
                "dx": delta_x,
                "dy": delta_y,
            })
            self._accumulate_gesture_delta(delta_x, delta_y, "hid_rawxy")

        def _on_hid_connect(self):
            self._connected_device = (
                self._hid_gesture.connected_device if self._hid_gesture else None
            )
            self._set_device_connected(True)

        def _on_hid_disconnect(self):
            self._connected_device = None
            self._set_device_connected(False)

        def _register_wake_observer(self):
            """Register NSWorkspace observers for wake and fast-user-switch events.

            On wake or session-activate: re-enable the CGEventTap and request a
            full HID++ reconnect so button diverts (including CID 0x00C4) are
            re-applied after the device soft-resets.
            """
            try:
                from AppKit import NSWorkspace
            except ImportError:
                return
            nc = NSWorkspace.sharedWorkspace().notificationCenter()
            hg = self._hid_gesture

            def _re_enable_tap_and_reconnect(reason):
                if self._tap and self._running:
                    Quartz.CGEventTapEnable(self._tap, True)
                    ok = Quartz.CGEventTapIsEnabled(self._tap)
                    print(f"[MouseHook] Event tap re-enabled ({reason}): "
                          f"{'OK' if ok else 'FAILED — may need restart'}", flush=True)
                if hg:
                    hg.force_reconnect()

            def _on_wake(n):
                _re_enable_tap_and_reconnect("wake")

            def _on_session_resign(n):
                print("[MouseHook] Session deactivated", flush=True)

            def _on_session_activate(n):
                _re_enable_tap_and_reconnect("user-switch")

            self._wake_observer = nc.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceDidWakeNotification", None, None, _on_wake)
            self._session_resign_observer = nc.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidResignActiveNotification", None, None, _on_session_resign)
            self._session_activate_observer = nc.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidBecomeActiveNotification", None, None, _on_session_activate)

        def _unregister_wake_observer(self):
            try:
                from AppKit import NSWorkspace
                nc = NSWorkspace.sharedWorkspace().notificationCenter()
                for attr in ("_wake_observer", "_session_resign_observer", "_session_activate_observer"):
                    obs = getattr(self, attr, None)
                    if obs is not None:
                        nc.removeObserver_(obs)
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
                Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved) |
                Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown) |
                Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp) |
                Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDragged) |
                Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
            )

            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault,
                event_mask,
                self._event_tap_callback,
                None
            )

            if self._tap is None:
                print("[MouseHook] ERROR: Failed to create CGEventTap!")
                print("[MouseHook] Grant Accessibility permission in:")
                print("[MouseHook]   System Settings -> Privacy & Security -> Accessibility")
                return False

            print("[MouseHook] CGEventTap created successfully", flush=True)

            self._tap_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(),
                self._tap_source,
                Quartz.kCFRunLoopCommonModes
            )
            Quartz.CGEventTapEnable(self._tap, True)
            print("[MouseHook] CGEventTap enabled and integrated with run loop", flush=True)
            self._running = True

            self._dispatch_thread = threading.Thread(
                target=self._dispatch_worker, daemon=True, name="MouseHook-dispatch")
            self._dispatch_thread.start()

            if HidGestureListener is not None:
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
                listener = HidGestureListener(
                    on_down=self._on_hid_gesture_down,
                    on_up=self._on_hid_gesture_up,
                    on_move=self._on_hid_gesture_move,
                    on_connect=self._on_hid_connect,
                    on_disconnect=self._on_hid_disconnect,
                    extra_diverts=extra,
                )
                self._hid_gesture = listener
                if not listener.start():
                    self._hid_gesture = None
            self._register_wake_observer()
            return True

        def stop(self):
            self._unregister_wake_observer()
            self._running = False
            if self._hid_gesture:
                self._hid_gesture.stop()
                self._hid_gesture = None
            self._connected_device = None

            if self._tap:
                Quartz.CGEventTapEnable(self._tap, False)
                if self._tap_source:
                    Quartz.CFRunLoopRemoveSource(
                        Quartz.CFRunLoopGetCurrent(),
                        self._tap_source,
                        Quartz.kCFRunLoopCommonModes
                    )
                    self._tap_source = None
                self._tap = None
                print("[MouseHook] CGEventTap disabled and removed", flush=True)

            if self._dispatch_thread:
                self._dispatch_thread.join(timeout=1)
                self._dispatch_thread = None


# ==================================================================
# Linux implementation
# ==================================================================

elif sys.platform == "linux":
    try:
        import select as _select_mod
        import evdev as _evdev_mod
        from evdev import ecodes as _ecodes, UInput as _UInput, InputDevice as _InputDevice
        _EVDEV_OK = True
    except ImportError:
        _EVDEV_OK = False
        print("[MouseHook] python-evdev not installed — pip install evdev")

    from core.logi_devices import build_evdev_connected_device_info

    _LOGI_VENDOR = 0x046D

    class MouseHook:
        """
        Uses evdev on Linux to intercept mouse button presses and scroll
        events.  Grabs the mouse device for exclusive access and forwards
        non-blocked events via a uinput virtual mouse.
        Requires read access to /dev/input/event* and write access to
        /dev/uinput (add user to 'input' group).
        """

        def __init__(self):
            self._running = False
            self._callbacks = {}
            self._blocked_events = set()
            self._debug_callback = None
            self._gesture_callback = None
            self.debug_mode = False
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._gesture_active = False
            self._hid_gesture = None
            self._device_connected = False
            self._evdev_ready = False
            self._hid_ready = False
            self._connection_change_cb = None
            self._connected_device = None
            self._evdev_connected_device = None
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
            self._gesture_lock = threading.Lock()
            # Linux-specific
            self._evdev_device = None
            self._uinput = None
            self._evdev_thread = None
            self._rescan_requested = threading.Event()
            self._evdev_wakeup = threading.Event()
            self._ignored_non_logitech = set()

        # -- standard interface methods ---------------------------------

        def register(self, event_type, callback):
            self._callbacks.setdefault(event_type, []).append(callback)

        def block(self, event_type):
            self._blocked_events.add(event_type)

        def unblock(self, event_type):
            self._blocked_events.discard(event_type)

        def reset_bindings(self):
            self._callbacks.clear()
            self._blocked_events.clear()

        def configure_gestures(self, enabled=False, threshold=50,
                               deadzone=40, timeout_ms=3000, cooldown_ms=500):
            self._gesture_direction_enabled = bool(enabled)
            self._gesture_threshold = float(max(5, threshold))
            self._gesture_deadzone = float(max(0, deadzone))
            self._gesture_timeout_ms = max(250, int(timeout_ms))
            self._gesture_cooldown_ms = max(0, int(cooldown_ms))
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
        def evdev_ready(self):
            return self._evdev_ready

        @property
        def hid_ready(self):
            return self._hid_ready

        @property
        def connected_device(self):
            return self._connected_device

        def dump_device_info(self):
            hg = getattr(self, "_hid_gesture", None)
            if hg and hasattr(hg, "dump_device_info"):
                return hg.dump_device_info()
            return None

        def _set_evdev_ready(self, ready):
            if ready == self._evdev_ready:
                return
            self._evdev_ready = ready
            self._refresh_device_state(force=True)

        def _set_device_connected(self, connected, force=False):
            changed = connected != self._device_connected
            if not changed and not force:
                return
            self._device_connected = connected
            if changed:
                state = "Connected" if connected else "Disconnected"
                print(f"[MouseHook] Device {state}")
            if self._connection_change_cb:
                try:
                    self._connection_change_cb(connected)
                except Exception:
                    pass

        def _build_evdev_connected_device(self, dev):
            info = getattr(dev, "info", None)
            return build_evdev_connected_device_info(
                product_id=getattr(info, "product", None) if info else None,
                product_name=getattr(dev, "name", None),
                transport="evdev",
                source="evdev",
            )

        def _refresh_device_state(self, force=False):
            previous = self._connected_device
            next_device = None
            if self._hid_ready and self._hid_gesture:
                next_device = self._hid_gesture.connected_device
            if next_device is None:
                next_device = self._evdev_connected_device
            self._connected_device = next_device

            prev_source = getattr(previous, "source", None) if previous is not None else None
            next_source = getattr(next_device, "source", None) if next_device is not None else None
            if prev_source != next_source:
                if next_source == "evdev":
                    print("[MouseHook] Using evdev fallback device info")
                elif prev_source == "evdev" and next_device is not None:
                    print("[MouseHook] Device info upgraded from evdev fallback to HID++")

            self._set_device_connected(self._evdev_ready, force=force)

        def set_debug_callback(self, callback):
            self._debug_callback = callback

        def set_gesture_callback(self, callback):
            self._gesture_callback = callback

        def _emit_debug(self, message):
            if self.debug_mode and self._debug_callback:
                try:
                    self._debug_callback(message)
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
                f"{_format_debug_details(event.raw_data)} callbacks={len(callbacks)}"
            )
            if event.event_type.startswith("gesture_"):
                self._emit_gesture_event({
                    "type": "dispatch",
                    "event_name": event.event_type,
                    "callbacks": len(callbacks),
                })
            if not callbacks:
                self._emit_debug(f"No mapped action for {event.event_type}")
                if event.event_type.startswith("gesture_"):
                    self._emit_gesture_event({
                        "type": "unmapped",
                        "event_name": event.event_type,
                    })
            for cb in callbacks:
                try:
                    cb(event)
                except Exception as e:
                    print(f"[MouseHook] callback error: {e}")

        def _hid_gesture_available(self):
            return self._hid_gesture is not None and self._evdev_ready

        # -- gesture detection (shared logic) ---------------------------

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

        def _accumulate_gesture_delta(self, delta_x, delta_y, source):
            dispatch_event = None
            with self._gesture_lock:
                if not (self._gesture_direction_enabled and self._gesture_active):
                    return
                if self._gesture_cooldown_active():
                    self._emit_debug(
                        f"Gesture cooldown active source={source} "
                        f"dx={delta_x} dy={delta_y}"
                    )
                    self._emit_gesture_event({
                        "type": "cooldown_active",
                        "source": source,
                        "dx": delta_x,
                        "dy": delta_y,
                    })
                    return
                if not self._gesture_tracking:
                    self._emit_debug(f"Gesture tracking started source={source}")
                    self._emit_gesture_event({
                        "type": "tracking_started",
                        "source": source,
                    })
                    self._start_gesture_tracking()

                now = time.monotonic()
                idle_ms = (now - self._gesture_last_move_at) * 1000.0
                if idle_ms > self._gesture_timeout_ms:
                    self._emit_debug(
                        f"Gesture segment reset timeout source={source} "
                        f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
                    )
                    self._start_gesture_tracking()

                # Prefer device-provided RawXY over evdev deltas.
                if source == "hid_rawxy" and self._gesture_input_source == "evdev":
                    self._emit_debug(
                        "Gesture source promoted from evdev to hid_rawxy "
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
                self._emit_gesture_event({
                    "type": "segment",
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                })

                gesture_event = self._detect_gesture_event()
                if not gesture_event:
                    return

                self._gesture_triggered = True
                self._emit_debug(
                    "Gesture detected "
                    f"{gesture_event} source={source} "
                    f"delta_x={self._gesture_delta_x} delta_y={self._gesture_delta_y}"
                )
                self._emit_gesture_event({
                    "type": "detected",
                    "event_name": gesture_event,
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                })
                dispatch_event = MouseEvent(
                    gesture_event,
                    {
                        "delta_x": self._gesture_delta_x,
                        "delta_y": self._gesture_delta_y,
                        "source": source,
                    },
                )
                self._gesture_cooldown_until = (
                    time.monotonic() + self._gesture_cooldown_ms / 1000.0
                )
                self._emit_debug(
                    f"Gesture cooldown started source={source} "
                    f"for_ms={self._gesture_cooldown_ms}"
                )
                self._emit_gesture_event({
                    "type": "cooldown_started",
                    "source": source,
                    "for_ms": self._gesture_cooldown_ms,
                })
                self._finish_gesture_tracking()

            # Dispatch outside lock to avoid deadlock with callbacks
            if dispatch_event:
                self._dispatch(dispatch_event)

        # -- HID gesture callbacks --------------------------------------

        def _on_hid_gesture_down(self):
            with self._gesture_lock:
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
            dispatch_click = False
            with self._gesture_lock:
                if self._gesture_active:
                    should_click = not self._gesture_triggered
                    self._gesture_active = False
                    self._finish_gesture_tracking()
                    self._gesture_triggered = False
                    self._emit_debug(
                        f"HID gesture button up click_candidate={str(should_click).lower()}"
                    )
                    self._emit_gesture_event({
                        "type": "button_up",
                        "click_candidate": should_click,
                    })
                    dispatch_click = should_click
            if dispatch_click:
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
            self._emit_debug(
                f"HID rawxy move dx={delta_x} dy={delta_y}"
            )
            self._emit_gesture_event({
                "type": "move",
                "source": "hid_rawxy",
                "dx": delta_x,
                "dy": delta_y,
            })
            self._accumulate_gesture_delta(delta_x, delta_y, "hid_rawxy")

        def _on_hid_connect(self):
            self._hid_ready = True
            self._refresh_device_state(force=True)
            dev = self._evdev_device
            should_wake_evdev = (
                self._running
                and _EVDEV_OK
                and (
                    dev is None
                    or not self._evdev_ready
                    or dev.info.vendor != _LOGI_VENDOR
                )
            )
            if should_wake_evdev:
                print("[MouseHook] Logitech HID connected; waking evdev scan")
                self._rescan_requested.set()
                self._evdev_wakeup.set()

        def _on_hid_disconnect(self):
            self._hid_ready = False
            if self._gesture_active:
                self._gesture_active = False
                self._finish_gesture_tracking()
                self._gesture_triggered = False
            self._refresh_device_state(force=True)

        # -- Linux evdev specifics --------------------------------------

        def _find_mouse_device(self):
            """Find the best Logitech mouse evdev device."""
            logi_mice = []
            for path in _evdev_mod.list_devices():
                try:
                    dev = _InputDevice(path)
                except Exception:
                    continue
                try:
                    caps = dev.capabilities(absinfo=False)
                    if _ecodes.EV_REL not in caps or _ecodes.EV_KEY not in caps:
                        dev.close()
                        continue
                    rel_caps = set(caps.get(_ecodes.EV_REL, []))
                    key_caps = set(caps.get(_ecodes.EV_KEY, []))
                    if _ecodes.REL_X not in rel_caps or _ecodes.REL_Y not in rel_caps:
                        dev.close()
                        continue
                    if not key_caps.intersection({
                        _ecodes.BTN_LEFT, _ecodes.BTN_RIGHT, _ecodes.BTN_MIDDLE,
                    }):
                        dev.close()
                        continue
                    has_side = bool(key_caps.intersection({
                        _ecodes.BTN_SIDE, _ecodes.BTN_EXTRA,
                    }))
                except Exception:
                    dev.close()
                    continue
                if dev.info.vendor == _LOGI_VENDOR:
                    logi_mice.append((dev, has_side))
                else:
                    info = getattr(dev, "info", None)
                    dedupe_key = (
                        dev.path,
                        getattr(info, "vendor", 0),
                        getattr(info, "product", 0),
                        dev.name or "",
                    )
                    if dedupe_key not in self._ignored_non_logitech:
                        self._ignored_non_logitech.add(dedupe_key)
                        print(
                            "[MouseHook] Ignoring non-Logitech evdev candidate: "
                            f"{dev.name} ({dev.path}) "
                            f"vendor=0x{getattr(info, 'vendor', 0):04X} "
                            f"product=0x{getattr(info, 'product', 0):04X}"
                        )
                    dev.close()

            ordered = sorted(logi_mice, key=lambda x: -x[1])
            if ordered:
                chosen = ordered[0][0]
                for dev, _ in ordered[1:]:
                    dev.close()
                print(f"[MouseHook] Found mouse: {chosen.name} ({chosen.path}) "
                      f"vendor=0x{chosen.info.vendor:04X}")
                return chosen
            return None

        def _setup_evdev(self):
            """Find mouse, create uinput mirror, grab device."""
            dev = self._find_mouse_device()
            if not dev:
                return False
            try:
                self._uinput = _UInput.from_device(
                    dev, name="Mouser Virtual Mouse",
                )
                dev.grab()
                self._evdev_device = dev
                self._evdev_connected_device = self._build_evdev_connected_device(dev)
                self._set_evdev_ready(True)
                print(f"[MouseHook] Grabbed {dev.name} ({dev.path})")
                return True
            except PermissionError:
                print("[MouseHook] Permission denied — add user to 'input' group "
                      "and ensure /dev/uinput is writable")
                dev.close()
            except Exception as e:
                print(f"[MouseHook] Failed to setup evdev: {e}")
                dev.close()
            return False

        def _cleanup_evdev(self):
            """Release grab and close devices."""
            if self._evdev_device:
                try:
                    self._evdev_device.ungrab()
                except Exception:
                    pass
                try:
                    self._evdev_device.close()
                except Exception:
                    pass
                self._evdev_device = None
                print("[MouseHook] evdev device released")
            if self._uinput:
                try:
                    self._uinput.close()
                except Exception:
                    pass
                self._uinput = None
            self._evdev_connected_device = None
            self._set_evdev_ready(False)

        def _evdev_loop(self):
            """Outer loop: find device -> listen -> reconnect on error."""
            while self._running:
                self._rescan_requested.clear()
                if not self._setup_evdev():
                    if self._running:
                        self._wait_for_evdev_wakeup(2)
                    continue
                try:
                    self._listen_loop()
                except OSError as e:
                    if self._running:
                        print(f"[MouseHook] Device disconnected: {e}")
                except Exception as e:
                    if self._running:
                        print(f"[MouseHook] evdev error: {e}")
                finally:
                    self._cleanup_evdev()
                if self._running:
                    if self._rescan_requested.is_set():
                        continue
                    self._wait_for_evdev_wakeup(1)

        def _wait_for_evdev_wakeup(self, timeout):
            self._evdev_wakeup.wait(timeout)
            self._evdev_wakeup.clear()

        def _listen_loop(self):
            """Read events from the grabbed device, forward or block."""
            fd = self._evdev_device.fd
            while self._running:
                if self._rescan_requested.is_set():
                    print("[MouseHook] Rescan requested; leaving listen loop")
                    return
                readable, _, _ = _select_mod.select([fd], [], [], 0.5)
                if not readable:
                    continue
                for event in self._evdev_device.read():
                    if not self._running:
                        return
                    if event.type == _ecodes.EV_SYN:
                        self._uinput.write_event(event)
                    elif event.type == _ecodes.EV_KEY:
                        self._handle_button(event)
                    elif event.type == _ecodes.EV_REL:
                        self._handle_rel(event)
                    else:
                        self._uinput.write_event(event)

        def _handle_button(self, event):
            """Process a key/button event, dispatch and optionally block."""
            mouse_event = None
            should_block = False

            if event.code == _ecodes.BTN_SIDE:
                if event.value == 1:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                    should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
                elif event.value == 0:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_UP)
                    should_block = MouseEvent.XBUTTON1_UP in self._blocked_events

            elif event.code == _ecodes.BTN_EXTRA:
                if event.value == 1:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                    should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events
                elif event.value == 0:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_UP)
                    should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

            elif event.code == _ecodes.BTN_MIDDLE:
                if event.value == 1:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                    should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events
                elif event.value == 0:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_UP)
                    should_block = MouseEvent.MIDDLE_UP in self._blocked_events

            if mouse_event:
                self._dispatch(mouse_event)

            if not should_block:
                self._uinput.write_event(event)

        def _handle_rel(self, event):
            """Process a relative axis event (movement, scroll)."""
            code = event.code
            value = event.value

            # Mouse movement
            if code == _ecodes.REL_X or code == _ecodes.REL_Y:
                if self._gesture_direction_enabled and self._gesture_active:
                    if self._gesture_input_source != "hid_rawxy":
                        if code == _ecodes.REL_X:
                            self._accumulate_gesture_delta(value, 0, "evdev")
                        else:
                            self._accumulate_gesture_delta(0, value, "evdev")
                    return  # suppress cursor during gesture
                self._uinput.write_event(event)
                return

            # Vertical scroll (low-res and hi-res)
            _REL_WHEEL_HI_RES = getattr(_ecodes, "REL_WHEEL_HI_RES", 0x0B)
            if code == _ecodes.REL_WHEEL or code == _REL_WHEEL_HI_RES:
                if self.invert_vscroll:
                    self._uinput.write(_ecodes.EV_REL, code, -value)
                else:
                    self._uinput.write_event(event)
                return

            # Horizontal scroll (low-res and hi-res)
            _REL_HWHEEL_HI_RES = getattr(_ecodes, "REL_HWHEEL_HI_RES", 0x0C)
            if code == _ecodes.REL_HWHEEL or code == _REL_HWHEEL_HI_RES:
                should_block = False
                if value > 0:
                    should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events
                elif value < 0:
                    should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events

                # Dispatch action only from low-res to avoid double-trigger
                if code == _ecodes.REL_HWHEEL:
                    if value > 0:
                        self._dispatch(
                            MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(value)))
                    elif value < 0:
                        self._dispatch(
                            MouseEvent(MouseEvent.HSCROLL_LEFT, abs(value)))

                if should_block:
                    return
                if self.invert_hscroll:
                    self._uinput.write(_ecodes.EV_REL, code, -value)
                else:
                    self._uinput.write_event(event)
                return

            # Other relative events: forward as-is
            self._uinput.write_event(event)

        # -- lifecycle --------------------------------------------------

        def _install_crash_guard(self):
            """Register signal handlers to release the evdev grab on abnormal exit."""
            import signal
            import atexit
            atexit.register(self._cleanup_evdev)
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                prev = signal.getsignal(sig)
                def _handler(signum, frame, _prev=prev):
                    self._cleanup_evdev()
                    if callable(_prev) and _prev not in (signal.SIG_DFL, signal.SIG_IGN):
                        _prev(signum, frame)
                    else:
                        raise SystemExit(128 + signum)
                signal.signal(sig, _handler)

        def start(self):
            self._running = True

            # Start HID gesture listener (works even without evdev)
            if HidGestureListener is not None:
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
                listener = HidGestureListener(
                    on_down=self._on_hid_gesture_down,
                    on_up=self._on_hid_gesture_up,
                    on_move=self._on_hid_gesture_move,
                    on_connect=self._on_hid_connect,
                    on_disconnect=self._on_hid_disconnect,
                    extra_diverts=extra,
                )
                self._hid_gesture = listener
                if not listener.start():
                    self._hid_gesture = None

            # Start evdev hook if available
            if _EVDEV_OK:
                self._install_crash_guard()
                self._evdev_thread = threading.Thread(
                    target=self._evdev_loop, daemon=True,
                    name="MouseHook-evdev")
                self._evdev_thread.start()
            else:
                print("[MouseHook] evdev not available — "
                      "button remapping disabled")

            return True

        def stop(self):
            self._running = False
            if self._hid_gesture:
                self._hid_gesture.stop()
                self._hid_gesture = None
            self._hid_ready = False
            self._connected_device = None
            self._evdev_connected_device = None
            self._rescan_requested.set()
            self._evdev_wakeup.set()
            if self._evdev_thread:
                self._evdev_thread.join(timeout=2)
                self._evdev_thread = None
            self._cleanup_evdev()


# ==================================================================
# Unsupported platform stub
# ==================================================================

else:
    class MouseHook:
        """Stub for unsupported platforms."""
        def __init__(self):
            self._callbacks = {}
            self._blocked_events = set()
            self.debug_mode = False
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._hid_gesture = None
            self._device_connected = False
            self._connection_change_cb = None
            self._gesture_callback = None
            self._connected_device = None
            self.divert_mode_shift = False
            self.divert_dpi_switch = False
            print(f"[MouseHook] Platform \'{sys.platform}\' not supported")

        def register(self, event_type, callback): pass
        def block(self, event_type): pass
        def unblock(self, event_type): pass
        def reset_bindings(self): pass
        def configure_gestures(self, enabled=False, threshold=50,
                               deadzone=40, timeout_ms=3000, cooldown_ms=500): pass
        def set_debug_callback(self, callback): pass
        def set_gesture_callback(self, callback): pass
        def set_connection_change_callback(self, cb): pass
        @property
        def device_connected(self): return False
        @property
        def connected_device(self): return None
        def dump_device_info(self): return None
        def start(self): pass
        def stop(self): pass
