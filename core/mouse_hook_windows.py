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
from core.mouse_hook_types import MouseEvent

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

WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007

PostMessageW = windll.user32.PostMessageW
PostMessageW.argtypes = [wintypes.HWND, c_uint, wintypes.WPARAM, wintypes.LPARAM]
PostMessageW.restype = wintypes.BOOL


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
        self._vscroll_posted = False
        self._hscroll_posted = False
        self._ri_wndproc_ref = None
        self._ri_hwnd = None
        self._device_name_cache = {}
        self._startup_event = threading.Event()
        self._startup_ok = False
        self._prev_raw_buttons = {}
        self._last_rehook_time = 0
        self._dispatch_queue = queue.Queue()
        self._dispatch_worker_thread = None

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
        self._emit_gesture_event(
            {
                "type": "cooldown_started",
                "source": source,
                "for_ms": self._gesture_cooldown_ms,
            }
        )
        self._finish_gesture_tracking()

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
            data = lParam.contents
            mouse_data = data.mouseData
            flags = data.flags
            event = None
            should_block = False

            if self.debug_mode and self._debug_callback:
                wm_name = self._WM_NAMES.get(wParam, f"0x{wParam:04X}")
                if wParam != 0x0200:
                    extra = data.dwExtraInfo.contents.value if data.dwExtraInfo else 0
                    info = (
                        f"{wm_name}  mouseData=0x{mouse_data:08X}  "
                        f"hiword={hiword(mouse_data)}  flags=0x{flags:04X}  "
                        f"extraInfo=0x{extra:X}"
                    )
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
                if delta > 0:
                    event = MouseEvent(MouseEvent.HSCROLL_LEFT, abs(delta))
                    should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events
                elif delta < 0:
                    event = MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(delta))
                    should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events

                if self.invert_hscroll:
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
                self._dispatch_queue.put(event)
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

        if msg == WM_DEVICECHANGE:
            if wParam == DBT_DEVNODES_CHANGED:
                self._on_device_change()
            return 0

        return DefWindowProcW(hwnd, msg, wParam, lParam)

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
        if not self._is_logitech(header.hDevice):
            return
        if header.dwType == RIM_TYPEMOUSE:
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
                self._gesture_active = True
                self._gesture_triggered = False
                print(f"[MouseHook] Gesture DOWN (rawBtns extra: 0x{extra_now:X})")
        elif not extra_now and extra_prev:
            if self._gesture_active:
                self._gesture_active = False
                print("[MouseHook] Gesture UP")
                self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

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

        if RegisterRawInputDevices(devices, 4, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice + Logitech HID + consumer")
            return True
        if RegisterRawInputDevices(devices, 2, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice + Logitech HID short")
            return True
        if RegisterRawInputDevices(devices, 1, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice only")
            return True
        print("[MouseHook] Raw Input registration failed")
        return False

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
            WH_MOUSE_LL,
            self._hook_proc,
            GetModuleHandleW(None),
            0,
        )
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
        return True

    def stop(self):
        self._running = False
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
