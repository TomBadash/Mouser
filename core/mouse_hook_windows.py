"""
Windows mouse hook implementation.
"""

import ctypes
import ctypes.wintypes as wintypes
import queue
import sys
import threading
import time
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    byref,
    c_int,
    c_uint,
    c_ulong,
    c_ushort,
    c_void_p,
    create_string_buffer,
    sizeof,
    windll,
)

from core.key_simulator import MOUSEEVENTF_HWHEEL, MOUSEEVENTF_WHEEL
from core.key_simulator import inject_scroll as _inject_scroll_impl
from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import MouseEvent, hscroll_event_type

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
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
        # ULONG_PTR: an opaque *value* the event's sender attached, not an
        # address. Declaring it as a pointer and reading ``.contents`` treats
        # whatever number Windows put here as memory to dereference, which
        # kills the process outright on any event carrying a non-zero value
        # (issue #252 / #253 -- it fired from the debug logging path).
        ("dwExtraInfo", wintypes.WPARAM),
    ]


HOOKPROC = CFUNCTYPE(
    ctypes.c_long,
    c_int,
    wintypes.WPARAM,
    ctypes.POINTER(MSLLHOOKSTRUCT),
)

SetWindowsHookExW = windll.user32.SetWindowsHookExW
SetWindowsHookExW.restype = wintypes.HHOOK
SetWindowsHookExW.argtypes = [c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]

CallNextHookEx = windll.user32.CallNextHookEx
CallNextHookEx.restype = ctypes.c_long
CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    c_int,
    wintypes.WPARAM,
    ctypes.POINTER(MSLLHOOKSTRUCT),
]

UnhookWindowsHookEx = windll.user32.UnhookWindowsHookEx
UnhookWindowsHookEx.restype = wintypes.BOOL
UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

GetModuleHandleW = windll.kernel32.GetModuleHandleW
GetModuleHandleW.restype = wintypes.HMODULE
GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

GetMessageW = windll.user32.GetMessageW
PostThreadMessageW = windll.user32.PostThreadMessageW

GetAsyncKeyState = windll.user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [c_int]
GetAsyncKeyState.restype = ctypes.c_short

VK_SHIFT = 0x10

WM_QUIT = 0x0012
INJECTED_FLAG = 0x00000001

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


WNDPROC_TYPE = CFUNCTYPE(
    ctypes.c_longlong,
    wintypes.HWND,
    c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


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
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    c_int,
    c_int,
    c_int,
    c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]

ShowWindow = windll.user32.ShowWindow
DefWindowProcW = windll.user32.DefWindowProcW
DefWindowProcW.restype = ctypes.c_longlong
DefWindowProcW.argtypes = [
    wintypes.HWND,
    c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
]

TranslateMessage = windll.user32.TranslateMessage
DispatchMessageW = windll.user32.DispatchMessageW
DestroyWindow = windll.user32.DestroyWindow


def hiword(dword):
    value = (dword >> 16) & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value


WM_APP = 0x8000
WM_APP_INJECT_VSCROLL = WM_APP + 1
WM_APP_INJECT_HSCROLL = WM_APP + 2
WM_APP_INJECT_SHIFT_HSCROLL = WM_APP + 3
# Re-arm the OS-level capture (reinstall the low-level hook, re-register raw
# input). Always posted rather than called: SetWindowsHookExW binds the hook
# to the calling thread, and only the hook thread pumps messages, so a rehook
# from any other thread would install a hook nothing ever delivers to.
WM_APP_REARM = WM_APP + 4

WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007

# ── Power / session notifications ────────────────────────────────────
# Windows never reports that it dropped a low-level hook, and a resumed
# machine can hand the mouse a fresh device stack while our HID handle stays
# open against the old one. Both are silent, so the resume itself is the only
# reliable cue to rebuild them (issue #263).
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000
# Modern Standby (S0 low-power idle) does not reliably raise the APM resume
# messages, so we also watch the console display state — display-on is the
# moment the user is back and the device stack has been rebuilt.
GUID_CONSOLE_DISPLAY_STATE = (
    0x6FE69556, 0x704A, 0x47A0, (0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
)
DISPLAY_STATE_ON = 0x1

WM_WTSSESSION_CHANGE = 0x02B1
NOTIFY_FOR_THIS_SESSION = 0x0000
WTS_SESSION_LOGON = 0x5
WTS_SESSION_UNLOCK = 0x8


class GUID(Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_parts(cls, d1, d2, d3, d4):
        return cls(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


class POWERBROADCAST_SETTING(Structure):
    _fields_ = [
        ("PowerSetting", GUID),
        ("DataLength", wintypes.DWORD),
        ("Data", ctypes.c_ubyte * 1),
    ]


PostMessageW = windll.user32.PostMessageW
PostMessageW.argtypes = [wintypes.HWND, c_uint, wintypes.WPARAM, wintypes.LPARAM]
PostMessageW.restype = wintypes.BOOL

RegisterPowerSettingNotification = windll.user32.RegisterPowerSettingNotification
RegisterPowerSettingNotification.restype = wintypes.HANDLE
RegisterPowerSettingNotification.argtypes = [
    wintypes.HANDLE,
    POINTER(GUID),
    wintypes.DWORD,
]

UnregisterPowerSettingNotification = windll.user32.UnregisterPowerSettingNotification
UnregisterPowerSettingNotification.restype = wintypes.BOOL
UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]

_CONSOLE_DISPLAY_STATE_BYTES = bytes(GUID.from_parts(*GUID_CONSOLE_DISPLAY_STATE))


class MouseHook(BaseMouseHook):
    """
    Installs a low-level mouse hook on Windows to intercept side-button clicks
    and horizontal scroll events.
    """

    def __init__(self):
        super().__init__()
        self._hook = None
        self._hook_thread = None
        self._thread_id = None
        self._running = False
        self._hook_proc = None
        self._pending_vscroll = 0
        self._pending_hscroll = 0
        self._pending_shift_hscroll = 0
        self._vscroll_posted = False
        self._hscroll_posted = False
        self._shift_hscroll_posted = False
        self._ri_wndproc_ref = None
        self._ri_hwnd = None
        self._device_name_cache = {}
        self._startup_event = threading.Event()
        self._startup_ok = False
        self._prev_raw_buttons = {}
        self._last_rehook_time = 0
        # Watchdog / resume-recovery state (see _platform_liveness_check).
        self._last_hook_event_at = 0.0
        self._last_raw_input_at = 0.0
        self._last_resume_at = 0.0
        self._power_notify_handle = None
        self._session_notify_registered = False
        # Per-button slide gesture: last cursor position while an owner button
        # is held, to derive per-move deltas from the LL hook's absolute point.
        self._btn_gesture_last_x = 0
        self._btn_gesture_last_y = 0
        self._debug_burst_last_at = 0.0
        self._debug_burst_skipped = 0
        self._init_dispatch_queue(maxsize=512)
        self._dispatch_worker_thread = None

    # Wheel messages arrive in bursts -- a hi-res wheel emits ~15 per detent --
    # and each debug line costs a Qt signal plus a QML list rebuild. Coalesce
    # them so turning debug mode on during a scroll doesn't stall the app.
    _DEBUG_BURST_MESSAGES = (WM_MOUSEWHEEL, WM_MOUSEHWHEEL)
    _DEBUG_BURST_INTERVAL_S = 0.25

    def _debug_event_allowed(self, wParam):
        """Return ``(emit, skipped)`` for one debug line from the hook proc."""
        if wParam not in self._DEBUG_BURST_MESSAGES:
            return True, 0
        now = time.monotonic()
        if now - self._debug_burst_last_at < self._DEBUG_BURST_INTERVAL_S:
            self._debug_burst_skipped += 1
            return False, 0
        skipped = self._debug_burst_skipped
        self._debug_burst_skipped = 0
        self._debug_burst_last_at = now
        return True, skipped

    _WM_NAMES = {
        0x0200: "WM_MOUSEMOVE",
        0x0201: "WM_LBUTTONDOWN",
        0x0202: "WM_LBUTTONUP",
        0x0204: "WM_RBUTTONDOWN",
        0x0205: "WM_RBUTTONUP",
        0x0207: "WM_MBUTTONDOWN",
        0x0208: "WM_MBUTTONUP",
        0x020A: "WM_MOUSEWHEEL",
        0x020B: "WM_XBUTTONDOWN",
        0x020C: "WM_XBUTTONUP",
        0x020E: "WM_MOUSEHWHEEL",
    }

    def _low_level_handler(self, nCode, wParam, lParam):
        try:
            return self._low_level_handler_inner(nCode, wParam, lParam)
        except Exception as exc:
            try:
                print(f"[MouseHook] CRITICAL _low_level_handler EXCEPTION: {exc}")
                import traceback

                traceback.print_exc()
            except Exception:
                pass
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _low_level_handler_inner(self, nCode, wParam, lParam):
        if nCode == HC_ACTION:
            # Proof-of-life for the hook watchdog. Stamped before every early
            # return below (injected events, the KVM guard) so a hook that is
            # merely passing traffic through still counts as alive.
            self._last_hook_event_at = time.monotonic()
            data = lParam.contents
            mouse_data = data.mouseData
            flags = data.flags
            event = None
            should_block = False

            if self.debug_mode and self._debug_callback and wParam != WM_MOUSEMOVE:
                allowed, skipped = self._debug_event_allowed(wParam)
                if allowed:
                    wm_name = self._WM_NAMES.get(wParam, f"0x{wParam:04X}")
                    extra = int(data.dwExtraInfo)
                    info = (
                        f"{wm_name}  mouseData=0x{mouse_data:08X}  "
                        f"hiword={hiword(mouse_data)}  flags=0x{flags:04X}  "
                        f"extraInfo=0x{extra:X}"
                    )
                    if skipped:
                        info += f"  (+{skipped} more)"
                    try:
                        self._debug_callback(info)
                    except Exception:
                        pass

            if flags & INJECTED_FLAG:
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            # KVM / cold-start guard: when no Logitech is currently bound to
            # this host, the WH_MOUSE_LL hook must be a complete pass-through.
            # The hook sees events from every input device, so without this
            # guard a trackpad scroll or generic USB mouse's xbutton click
            # would still run through Mouser's remap pipeline -- the exact
            # failure mode users hit when their KVM switches the Logitech
            # to another machine while Mouser keeps running here.
            if not self._should_intercept_events():
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            # ── Per-button slide gestures (back/forward/middle) ──────────
            # When a button is armed as a gesture pad, its press starts the
            # shared recognizer and is swallowed; pointer motion while held is
            # fed to the recognizer (which fires a button_swipe event on a
            # committed slide); the release ends the hold. A quick tap with no
            # slide simply ends as a no-op. Fast None-check when idle.
            if self._button_gesture_active_owner is not None and wParam == WM_MOUSEMOVE:
                # First move of a hold that armed without a start point (e.g.
                # mode shift over HID): establish the origin, don't sample yet.
                if self._button_gesture_origin_needed:
                    self._btn_gesture_last_x = data.pt.x
                    self._btn_gesture_last_y = data.pt.y
                    self._button_gesture_origin_needed = False
                    return CallNextHookEx(self._hook, nCode, wParam, lParam)
                dx = data.pt.x - self._btn_gesture_last_x
                dy = data.pt.y - self._btn_gesture_last_y
                self._btn_gesture_last_x = data.pt.x
                self._btn_gesture_last_y = data.pt.y
                self.sample_button_gesture(dx, dy, "os_motion")
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            gesture_owner = None
            if wParam in (WM_MBUTTONDOWN, WM_MBUTTONUP):
                gesture_owner = "middle"
            elif wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                xb = hiword(mouse_data)
                if xb == XBUTTON1:
                    gesture_owner = "xbutton1"
                elif xb == XBUTTON2:
                    gesture_owner = "xbutton2"

            if gesture_owner is not None:
                if wParam in (WM_MBUTTONDOWN, WM_XBUTTONDOWN):
                    if (self.is_button_gesture_owner(gesture_owner)
                            and self.arm_button_gesture(gesture_owner)):
                        # Origin is known from this press point.
                        self._btn_gesture_last_x = data.pt.x
                        self._btn_gesture_last_y = data.pt.y
                        self._button_gesture_origin_needed = False
                        return 1
                elif self._button_gesture_active_owner == gesture_owner:
                    # owner-button up while armed -> resolve and swallow
                    self.release_button_gesture(gesture_owner)
                    return 1

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
                delta = hiword(mouse_data)
                if delta != 0 and (GetAsyncKeyState(VK_SHIFT) & 0x8000):
                    if self._ri_hwnd:
                        h_delta = -delta if self.invert_hscroll else delta
                        self._pending_shift_hscroll += h_delta
                        if self._shift_hscroll_posted:
                            return 1
                        if PostMessageW(
                            self._ri_hwnd, WM_APP_INJECT_SHIFT_HSCROLL, 0, 0
                        ):
                            self._shift_hscroll_posted = True
                            return 1
                        self._pending_shift_hscroll -= h_delta
                    else:
                        self._emit_debug(
                            "Shift+wheel translation skipped: "
                            "raw input window unavailable"
                        )
                if self.invert_vscroll and not self.wheel_native_invert_active:
                    if delta != 0 and self._ri_hwnd:
                        self._pending_vscroll += -delta
                        if self._vscroll_posted:
                            return 1
                        if PostMessageW(self._ri_hwnd, WM_APP_INJECT_VSCROLL, 0, 0):
                            self._vscroll_posted = True
                            return 1
                        self._pending_vscroll -= -delta
                    elif delta != 0:
                        self._emit_debug(
                            "Invert vertical scroll skipped: raw input window unavailable"
                        )

            elif wParam == WM_MOUSEHWHEEL:
                delta = hiword(mouse_data)
                event_type = hscroll_event_type(delta)
                if event_type:
                    event = MouseEvent(event_type, abs(delta))
                    should_block = event_type in self._blocked_events

                if self.invert_hscroll and not self.wheel_native_invert_active:
                    if delta != 0 and self._ri_hwnd and not should_block:
                        self._pending_hscroll += -delta
                        if self._hscroll_posted:
                            return 1
                        if PostMessageW(self._ri_hwnd, WM_APP_INJECT_HSCROLL, 0, 0):
                            self._hscroll_posted = True
                            return 1
                        self._pending_hscroll -= -delta
                    elif delta != 0 and not should_block:
                        self._emit_debug(
                            "Invert horizontal scroll skipped: raw input window unavailable"
                        )

            if event:
                self._enqueue_dispatch_event(event)
                if should_block:
                    return 1

        return CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _get_device_name(self, hDevice):
        if hDevice in self._device_name_cache:
            return self._device_name_cache[hDevice]
        try:
            size = c_uint(0)
            GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, None, byref(size))
            if size.value > 0:
                buffer = ctypes.create_unicode_buffer(size.value + 1)
                GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, buffer, byref(size))
                name = buffer.value
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
            except Exception as exc:
                print(f"[MouseHook] Raw Input error: {exc}")
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

        if msg == WM_APP_INJECT_SHIFT_HSCROLL:
            delta = self._pending_shift_hscroll
            self._pending_shift_hscroll = 0
            self._shift_hscroll_posted = False
            if delta != 0:
                _inject_scroll_impl(MOUSEEVENTF_HWHEEL, delta)
            return 0

        if msg == WM_APP_REARM:
            self._rearm_os_capture()
            return 0

        if msg == WM_DEVICECHANGE:
            if wParam == DBT_DEVNODES_CHANGED:
                self._on_device_change()
            return 0

        if msg == WM_POWERBROADCAST:
            if wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                self._on_system_resume("power resume")
            elif wParam == PBT_APMSUSPEND:
                print("[MouseHook] System suspending")
            elif wParam == PBT_POWERSETTINGCHANGE:
                if self._is_display_on_notification(lParam):
                    self._on_system_resume("display on")
            return 1

        if msg == WM_WTSSESSION_CHANGE:
            if wParam in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON):
                self._on_system_resume("session unlock")
            return 0

        return DefWindowProcW(hwnd, msg, wParam, lParam)

    @staticmethod
    def _is_display_on_notification(lParam):
        """True when a PBT_POWERSETTINGCHANGE payload says the console
        display just turned on."""
        try:
            setting = POWERBROADCAST_SETTING.from_address(lParam)
            if bytes(setting.PowerSetting) != _CONSOLE_DISPLAY_STATE_BYTES:
                return False
            return setting.DataLength >= 1 and setting.Data[0] == DISPLAY_STATE_ON
        except Exception:
            return False

    def _process_raw_input(self, lParam):
        size = c_uint(0)
        GetRawInputData(lParam, RID_INPUT, None, byref(size), sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buffer = create_string_buffer(size.value)
        ret = GetRawInputData(
            lParam,
            RID_INPUT,
            buffer,
            byref(size),
            sizeof(RAWINPUTHEADER),
        )
        if ret == 0xFFFFFFFF:
            return
        header = RAWINPUTHEADER.from_buffer_copy(buffer)
        if header.dwType == RIM_TYPEMOUSE:
            # Raw input and the low-level hook are independent deliveries of
            # the same events, which is what makes them a usable cross-check:
            # raw input keeps arriving after Windows drops the hook. Only
            # mouse-type reports count -- the vendor (0xFF43) and consumer
            # collections we also register for never reach a WH_MOUSE_LL hook,
            # so counting them would read a healthy hook as dead.
            self._last_raw_input_at = time.monotonic()
        if not self._is_logitech(header.hDevice):
            return
        if header.dwType == RIM_TYPEMOUSE:
            # Proof the Logitech itself is awake and in use, for the HID
            # liveness watchdog.
            self._note_os_mouse_activity()
            self._check_raw_mouse_gesture(header.hDevice, buffer)

    def _check_raw_mouse_gesture(self, hDevice, buffer):
        if self._hid_gesture_available():
            return
        mouse = RAWMOUSE.from_buffer_copy(buffer, sizeof(RAWINPUTHEADER))
        raw_buttons = mouse.ulRawButtons
        prev_buttons = self._prev_raw_buttons.get(hDevice, 0)
        self._prev_raw_buttons[hDevice] = raw_buttons

        extra_now = raw_buttons & ~STANDARD_BUTTON_MASK
        extra_prev = prev_buttons & ~STANDARD_BUTTON_MASK

        if extra_now == extra_prev:
            return
        if extra_now and not extra_prev:
            if not self._gesture_active:
                self._gesture_recognizer.begin()
                self._gesture_active = True
                print(f"[MouseHook] Gesture DOWN (rawBtns extra: 0x{extra_now:X})")
        elif not extra_now and extra_prev:
            if self._gesture_active:
                self._gesture_active = False
                was_click = self._gesture_recognizer.end()
                print("[MouseHook] Gesture UP")
                if was_click:
                    self._enqueue_dispatch_event(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _setup_raw_input(self):
        instance = GetModuleHandleW(None)
        class_name = f"MouserRawInput_{id(self)}"
        self._ri_wndproc_ref = WNDPROC_TYPE(self._ri_wndproc)

        window_class = WNDCLASSEXW()
        window_class.cbSize = sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = self._ri_wndproc_ref
        window_class.hInstance = instance
        window_class.lpszClassName = class_name
        RegisterClassExW(byref(window_class))

        self._ri_hwnd = CreateWindowExW(
            0,
            class_name,
            "Mouser RI",
            0,
            0,
            0,
            1,
            1,
            None,
            None,
            instance,
            None,
        )
        if not self._ri_hwnd:
            print("[MouseHook] CreateWindowExW failed — gesture detection unavailable")
            return False

        ShowWindow(self._ri_hwnd, SW_HIDE)
        self._register_power_notifications()
        return self._register_raw_input_devices()

    def _register_raw_input_devices(self, log=True):
        if not self._ri_hwnd:
            return False

        devices = (RAWINPUTDEVICE * 4)()
        devices[0].usUsagePage = 0x01
        devices[0].usUsage = 0x02
        devices[0].dwFlags = RIDEV_INPUTSINK
        devices[0].hwndTarget = self._ri_hwnd
        devices[1].usUsagePage = 0xFF43
        devices[1].usUsage = 0x0202
        devices[1].dwFlags = RIDEV_INPUTSINK
        devices[1].hwndTarget = self._ri_hwnd
        devices[2].usUsagePage = 0xFF43
        devices[2].usUsage = 0x0204
        devices[2].dwFlags = RIDEV_INPUTSINK
        devices[2].hwndTarget = self._ri_hwnd
        devices[3].usUsagePage = 0x0C
        devices[3].usUsage = 0x01
        devices[3].dwFlags = RIDEV_INPUTSINK
        devices[3].hwndTarget = self._ri_hwnd

        for count, label in (
            (4, "mice + Logitech HID + consumer"),
            (2, "mice + Logitech HID short"),
            (1, "mice only"),
        ):
            if RegisterRawInputDevices(devices, count, sizeof(RAWINPUTDEVICE)):
                if log:
                    print(f"[MouseHook] Raw Input: {label}")
                return True
        print("[MouseHook] Raw Input registration failed")
        return False

    def _register_power_notifications(self):
        """Subscribe the message window to resume and unlock notifications.

        Best-effort: every one of these is a recovery *cue*, not a
        requirement, and the watchdog still covers us if a subscription
        fails, so a failure here must never take the hook down with it.
        """
        try:
            guid = GUID.from_parts(*GUID_CONSOLE_DISPLAY_STATE)
            self._power_notify_handle = RegisterPowerSettingNotification(
                self._ri_hwnd, byref(guid), DEVICE_NOTIFY_WINDOW_HANDLE
            )
            if not self._power_notify_handle:
                self._power_notify_handle = None
                print("[MouseHook] Display-state notifications unavailable")
        except Exception as exc:
            self._power_notify_handle = None
            print(f"[MouseHook] Display-state notifications unavailable: {exc}")

        try:
            if windll.wtsapi32.WTSRegisterSessionNotification(
                self._ri_hwnd, NOTIFY_FOR_THIS_SESSION
            ):
                self._session_notify_registered = True
            else:
                print("[MouseHook] Session notifications unavailable")
        except Exception as exc:
            print(f"[MouseHook] Session notifications unavailable: {exc}")

    def _unregister_power_notifications(self):
        if self._power_notify_handle:
            try:
                UnregisterPowerSettingNotification(self._power_notify_handle)
            except Exception:
                pass
            self._power_notify_handle = None
        if self._session_notify_registered:
            try:
                windll.wtsapi32.WTSUnRegisterSessionNotification(self._ri_hwnd)
            except Exception:
                pass
            self._session_notify_registered = False

    def _dispatch_worker(self):
        while self._running:
            try:
                event = self._dispatch_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._dispatch(event)
            except Exception as exc:
                print(f"[MouseHook] dispatch worker error: {exc}")

    def _run_hook(self):
        self._thread_id = windll.kernel32.GetCurrentThreadId()
        self._hook_proc = HOOKPROC(self._low_level_handler)
        self._hook = SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            GetModuleHandleW(None),
            0,
        )
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

        message = wintypes.MSG()
        while self._running:
            result = GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0 or result == -1:
                break
            TranslateMessage(ctypes.byref(message))
            DispatchMessageW(ctypes.byref(message))

        if self._ri_hwnd:
            self._unregister_power_notifications()
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
        print("[MouseHook] Device change detected — refreshing hook")
        self._rearm_os_capture()

    def _request_rearm(self, reason):
        """Ask the hook thread to rebuild the OS-level capture. Safe to call
        from any thread — the work itself must happen on the hook thread."""
        hwnd = self._ri_hwnd
        if not hwnd or not self._running:
            return False
        print(f"[MouseHook] Re-arm requested ({reason})")
        return bool(PostMessageW(hwnd, WM_APP_REARM, 0, 0))

    def _rearm_os_capture(self):
        """Rebuild everything the OS can silently take away from us.
        Hook-thread only (see WM_APP_REARM)."""
        self._last_rehook_time = time.time()
        self._device_name_cache.clear()
        self._prev_raw_buttons.clear()
        self._reinstall_hook()
        self._register_raw_input_devices(log=False)

    def _reinstall_hook(self):
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
        self._hook_proc = HOOKPROC(self._low_level_handler)
        self._hook = SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            GetModuleHandleW(None),
            0,
        )
        if self._hook:
            # Treat the fresh hook as alive, so the watchdog gives it a full
            # silence window to prove itself instead of firing again at once.
            self._last_hook_event_at = time.monotonic()
            print("[MouseHook] Hook reinstalled successfully")
        else:
            print("[MouseHook] Failed to reinstall hook!")

    # ── Resume recovery ───────────────────────────────────────────────
    # Rebuilding once on the resume message is not enough: the USB/Bolt stack
    # comes back over several seconds, so an immediate reconnect can probe a
    # receiver whose mouse has not re-paired yet and fail for reasons that
    # have nothing to do with us (issue #81). Retry on a widening ladder and
    # stop as soon as the device is back.
    _RESUME_REARM_DELAYS_S = (0.5, 3.0, 10.0)
    _RESUME_DEDUPE_S = 5.0

    def _on_system_resume(self, reason):
        """Entry point for every resume-ish cue. Windows commonly raises
        several for one wake (APM resume, then display-on, then unlock), so
        collapse a burst into a single recovery pass."""
        now = time.monotonic()
        if now - self._last_resume_at < self._RESUME_DEDUPE_S:
            return False
        self._last_resume_at = now
        print(f"[MouseHook] System resume detected ({reason}) — recovering")
        threading.Thread(
            target=self._resume_recovery_worker,
            args=(reason,),
            daemon=True,
            name="MouseHook-resume",
        ).start()
        return True

    def _resume_recovery_worker(self, reason):
        elapsed = 0.0
        for index, deadline in enumerate(self._RESUME_REARM_DELAYS_S):
            time.sleep(max(0.0, deadline - elapsed))
            elapsed = deadline
            if not self._running:
                return
            self._request_rearm(f"resume: {reason}")
            hg = self._hid_gesture
            if hg is None:
                continue
            # The first pass always drops the HID handle: after a resume it
            # can stay open against a device stack Windows has already
            # replaced, and from the outside that is indistinguishable from a
            # healthy connection. Later passes only step in if the device has
            # not come back on its own.
            if index == 0 or not self._device_connected:
                try:
                    hg.force_reconnect()
                except Exception as exc:
                    print(f"[MouseHook] resume reconnect request failed: {exc}")

    # ── Hook watchdog ─────────────────────────────────────────────────
    # Windows removes a low-level hook whose procedure overruns
    # LowLevelHooksTimeout (300 ms by default) and tells nobody: the HHOOK
    # stays non-NULL and simply never fires again. Resume is the classic
    # trigger — the process is still being scheduled back in while a burst of
    # input arrives — but it also happens under load, which is what leaves
    # users with a dead Mouser and no explanation (#257 / #246).
    #
    # There is no API to ask whether a hook is still installed, so we compare
    # it against raw input: same events, independent delivery path, already
    # registered. Raw input live + hook silent is the signature of a dropped
    # hook. Both silent just means nobody is touching the mouse.
    _HOOK_ACTIVITY_WINDOW_S = 3.0
    _HOOK_SILENCE_LIMIT_S = 3.0

    def _platform_liveness_check(self, now=None):
        if not self._running or not self._ri_hwnd:
            return False
        now = time.monotonic() if now is None else now
        if not self._last_raw_input_at or not self._last_hook_event_at:
            return False
        if now - self._last_raw_input_at > self._HOOK_ACTIVITY_WINDOW_S:
            return False
        hook_silence = now - self._last_hook_event_at
        if hook_silence < self._HOOK_SILENCE_LIMIT_S:
            return False
        print(
            f"[MouseHook] Low-level hook silent for {hook_silence:.0f}s while "
            "raw input is live — Windows dropped it; reinstalling"
        )
        self._request_rearm("hook watchdog")
        # Assume recovery until the reinstall lands, so a slow rehook does not
        # queue a second one behind the first.
        self._last_hook_event_at = now
        return True

    def _emit_gesture_swipe(self, mouse_event):
        """Route gesture swipes through the dispatch queue so they run on
        the dispatch-worker thread, not inline on the HID callback thread."""
        self._enqueue_dispatch_event(mouse_event)

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
        self._start_hid_listener()
        self._dispatch_worker_thread = threading.Thread(
            target=self._dispatch_worker,
            daemon=True,
            name="HookDispatch",
        )
        self._dispatch_worker_thread.start()
        self._start_liveness_watchdog()
        return True

    def stop(self):
        self._running = False
        self._stop_liveness_watchdog()
        self.abort_button_gesture("stop")
        self._stop_hid_listener()
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


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "MSLLHOOKSTRUCT",
    "WM_XBUTTONDOWN",
    "WM_XBUTTONUP",
    "WM_MBUTTONDOWN",
    "WM_MBUTTONUP",
    "WM_MOUSEHWHEEL",
    "WM_MOUSEWHEEL",
]
