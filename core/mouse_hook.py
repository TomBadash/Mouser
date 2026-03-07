"""
Low-level mouse hook — supports Windows (via ctypes/Win32) and macOS (via Quartz CGEventTap).
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


# ══════════════════════════════════════════════════════════════════
# Shared: MouseEvent (platform-neutral)
# ══════════════════════════════════════════════════════════════════

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
    HSCROLL_LEFT = "hscroll_left"
    HSCROLL_RIGHT = "hscroll_right"

    def __init__(self, event_type, raw_data=None):
        self.event_type = event_type
        self.raw_data = raw_data
        self.timestamp = time.time()


# ══════════════════════════════════════════════════════════════════
# Windows implementation
# ══════════════════════════════════════════════════════════════════

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

    WM_APP = 0x8000
    WM_APP_INJECT_VSCROLL = WM_APP + 1
    WM_APP_INJECT_HSCROLL = WM_APP + 2

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
            self._gesture_active = False
            self._prev_raw_buttons = {}
            self._hid_gesture = None

        def register(self, event_type, callback):
            self._callbacks.setdefault(event_type, []).append(callback)

        def block(self, event_type):
            self._blocked_events.add(event_type)

        def unblock(self, event_type):
            self._blocked_events.discard(event_type)

        def reset_bindings(self):
            self._callbacks.clear()
            self._blocked_events.clear()

        def set_debug_callback(self, callback):
            self._debug_callback = callback

        def _dispatch(self, event):
            for cb in self._callbacks.get(event.event_type, []):
                try:
                    cb(event)
                except Exception as e:
                    print(f"[MouseHook] callback error: {e}")

        _WM_NAMES = {
            0x0200: "WM_MOUSEMOVE",
            0x0201: "WM_LBUTTONDOWN", 0x0202: "WM_LBUTTONUP",
            0x0204: "WM_RBUTTONDOWN", 0x0205: "WM_RBUTTONUP",
            0x0207: "WM_MBUTTONDOWN", 0x0208: "WM_MBUTTONUP",
            0x020A: "WM_MOUSEWHEEL",  0x020B: "WM_XBUTTONDOWN",
            0x020C: "WM_XBUTTONUP",   0x020E: "WM_MOUSEHWHEEL",
        }

        def _low_level_handler(self, nCode, wParam, lParam):
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
                        if delta != 0:
                            self._pending_vscroll += (-delta)
                            if not self._vscroll_posted and self._ri_hwnd:
                                self._vscroll_posted = True
                                PostMessageW(self._ri_hwnd, WM_APP_INJECT_VSCROLL, 0, 0)
                            return 1

                elif wParam == WM_MOUSEHWHEEL:
                    delta = hiword(mouse_data)
                    if self.invert_hscroll:
                        if delta != 0:
                            self._pending_hscroll += (-delta)
                            if not self._hscroll_posted and self._ri_hwnd:
                                self._hscroll_posted = True
                                PostMessageW(self._ri_hwnd, WM_APP_INJECT_HSCROLL, 0, 0)
                            return 1
                    if delta > 0:
                        event = MouseEvent(MouseEvent.HSCROLL_LEFT, abs(delta))
                        should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events
                    elif delta < 0:
                        event = MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(delta))
                        should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events

                if event:
                    self._dispatch(event)
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

            return DefWindowProcW(hwnd, msg, wParam, lParam)

        def _process_raw_input(self, lParam):
            sz = c_uint(0)
            GetRawInputData(lParam, RID_INPUT, None, byref(sz), sizeof(RAWINPUTHEADER))
            if sz.value == 0:
                return
            buf = create_string_buffer(sz.value)
            ret = GetRawInputData(lParam, RID_INPUT, buf, byref(sz), sizeof(RAWINPUTHEADER))
            if ret == 0xFFFFFFFF:
                return
            header = RAWINPUTHEADER.from_buffer_copy(buf)
            if not self._is_logitech(header.hDevice):
                return
            if header.dwType == RIM_TYPEMOUSE:
                self._check_raw_mouse_gesture(header.hDevice, buf)

        def _check_raw_mouse_gesture(self, hDevice, buf):
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
                    print(f"[MouseHook] Gesture DOWN (rawBtns extra: 0x{extra_now:X})")
                    self._dispatch(MouseEvent(MouseEvent.GESTURE_DOWN))
            elif not extra_now and extra_prev:
                if self._gesture_active:
                    self._gesture_active = False
                    print("[MouseHook] Gesture UP")
                    self._dispatch(MouseEvent(MouseEvent.GESTURE_UP))

        def _setup_raw_input(self):
            hInst = GetModuleHandleW(None)
            cls_name = f"LogiControlRawInput_{id(self)}"
            self._ri_wndproc_ref = WNDPROC_TYPE(self._ri_wndproc)

            wc = WNDCLASSEXW()
            wc.cbSize = sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._ri_wndproc_ref
            wc.hInstance = hInst
            wc.lpszClassName = cls_name

            RegisterClassExW(byref(wc))

            self._ri_hwnd = CreateWindowExW(
                0, cls_name, "LogiControl RI", 0,
                0, 0, 1, 1, None, None, hInst, None,
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
            self._hook = SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, GetModuleHandleW(None), 0)
            if not self._hook:
                print("[MouseHook] Failed to install hook!")
                return
            print("[MouseHook] Hook installed successfully")
            self._setup_raw_input()
            self._running = True

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
            print("[MouseHook] Hook removed")

        def _on_hid_gesture_down(self):
            if not self._gesture_active:
                self._gesture_active = True
                self._dispatch(MouseEvent(MouseEvent.GESTURE_DOWN))

        def _on_hid_gesture_up(self):
            if self._gesture_active:
                self._gesture_active = False
                self._dispatch(MouseEvent(MouseEvent.GESTURE_UP))

        def start(self):
            if self._hook_thread and self._hook_thread.is_alive():
                return
            if HidGestureListener is not None:
                self._hid_gesture = HidGestureListener(
                    on_down=self._on_hid_gesture_down,
                    on_up=self._on_hid_gesture_up,
                )
                self._hid_gesture.start()
            self._hook_thread = threading.Thread(target=self._run_hook, daemon=True)
            self._hook_thread.start()
            time.sleep(0.1)

        def stop(self):
            self._running = False
            if self._hid_gesture:
                self._hid_gesture.stop()
                self._hid_gesture = None
            if self._thread_id:
                PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            if self._hook_thread:
                self._hook_thread.join(timeout=2)
            self._hook = None
            self._ri_hwnd = None
            self._thread_id = None


# ══════════════════════════════════════════════════════════════════
# macOS implementation
# ══════════════════════════════════════════════════════════════════

elif sys.platform == "darwin":
    try:
        import AppKit
        import Quartz
        _APPKIT_OK = True
    except ImportError:
        _APPKIT_OK = False
        print("[MouseHook] pyobjc-framework-Cocoa/Quartz not installed — "
              "pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz")

    # HID button numbers (typical USB/BT HID mapping on macOS)
    _BTN_MIDDLE = 2
    _BTN_BACK = 3
    _BTN_FORWARD = 4

    class MouseHook:
        """
        Uses CGEventTap on macOS to intercept mouse button presses and scroll
        events. When an event is blocked, it is completely suppressed and does
        NOT reach the target application.

        Requires Accessibility permission:
          System Settings -> Privacy & Security -> Accessibility
        """

        def __init__(self):
            self._running = False
            self._callbacks = {}
            self._blocked_events = set()
            self._tap = None
            self._tap_source = None
            self._debug_callback = None
            self.debug_mode = False
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._gesture_active = False
            self._hid_gesture = None
            self._dispatch_queue = queue.Queue()
            self._dispatch_thread = None
            # diagnostic flags set from main_qml.py
            self._no_hid = False
            self._no_monitors = False
            self._first_event_logged = False

        def register(self, event_type, callback):
            self._callbacks.setdefault(event_type, []).append(callback)

        def block(self, event_type):
            self._blocked_events.add(event_type)

        def unblock(self, event_type):
            self._blocked_events.discard(event_type)

        def reset_bindings(self):
            self._callbacks.clear()
            self._blocked_events.clear()

        def set_debug_callback(self, callback):
            self._debug_callback = callback

        def _dispatch(self, event):
            for cb in self._callbacks.get(event.event_type, []):
                try:
                    cb(event)
                except Exception as e:
                    print(f"[MouseHook] callback error: {e}")

        def _dispatch_worker(self):
            """Background thread: drains the event queue so handlers return fast."""
            while self._running:
                try:
                    event = self._dispatch_queue.get(timeout=0.05)
                    self._dispatch(event)
                except queue.Empty:
                    continue

        def _event_tap_callback(self, proxy, event_type, cg_event, refcon):
            """
            CGEventTap callback. Return the event to pass it through, or None to suppress it.
            """
            try:
                if not self._first_event_logged:
                    self._first_event_logged = True
                    print(f"[MouseHook] FIRST EVENT: CGEventTap callback received", flush=True)

                # Map CGEventType to our event types
                mouse_event = None
                should_block = False

                # OtherMouseDown (middle, back, forward)
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

                # OtherMouseUp
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

                # ScrollWheel
                elif event_type == Quartz.kCGEventScrollWheel:
                    h_delta = Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis2)
                    # Convert from fixed-point (divide by 65536)
                    h_delta = h_delta / 65536.0
                    if self.debug_mode and self._debug_callback:
                        try:
                            v_delta = Quartz.CGEventGetIntegerValueField(
                                cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1) / 65536.0
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

                # Dispatch the event if we created one
                if mouse_event:
                    self._dispatch_queue.put(mouse_event)

                # Return None to suppress, or pass through the event
                if should_block:
                    return None  # Suppress the event
                else:
                    return cg_event  # Pass through

            except Exception as e:
                print(f"[MouseHook] event tap callback error: {e}")
                return cg_event  # On error, pass through

        def _on_hid_gesture_down(self):
            if not self._gesture_active:
                self._gesture_active = True
                self._dispatch(MouseEvent(MouseEvent.GESTURE_DOWN))

        def _on_hid_gesture_up(self):
            if self._gesture_active:
                self._gesture_active = False
                self._dispatch(MouseEvent(MouseEvent.GESTURE_UP))

        def start(self):
            if not _APPKIT_OK:
                print("[MouseHook] AppKit/Quartz not available — hook not installed")
                return
            print("[MouseHook] start: setting _running=True", flush=True)
            self._running = True
            if HidGestureListener is not None and not self._no_hid:
                print("[MouseHook] start: creating HidGestureListener...", flush=True)
                self._hid_gesture = HidGestureListener(
                    on_down=self._on_hid_gesture_down,
                    on_up=self._on_hid_gesture_up,
                )
                self._hid_gesture.start()
                print("[MouseHook] start: HidGestureListener started", flush=True)
            elif self._no_hid:
                print("[MouseHook] start: --no-hid flag set, skipping HidGestureListener", flush=True)
            print("[MouseHook] start: starting dispatch thread...", flush=True)
            self._dispatch_thread = threading.Thread(
                target=self._dispatch_worker, daemon=True, name="MouseHook-dispatch")
            self._dispatch_thread.start()
            print("[MouseHook] start: dispatch thread started", flush=True)

            if self._no_monitors:
                print("[MouseHook] start: --no-monitors flag set, skipping CGEventTap", flush=True)
                return

            # Create a CGEventTap to intercept mouse events
            # kCGSessionEventTap: intercepts events for the current user session
            # kCGHeadInsertEventTap: insert at the beginning of the event queue
            # We want: OtherMouseDown, OtherMouseUp, and ScrollWheel
            print("[MouseHook] start: creating CGEventTap...", flush=True)
            event_mask = (
                Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown) |
                Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp) |
                Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
            )
            
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,      # tap location
                Quartz.kCGHeadInsertEventTap,   # place at head
                Quartz.kCGEventTapOptionDefault, # active filter (can modify/suppress)
                event_mask,                      # events to intercept
                self._event_tap_callback,        # callback
                None                             # user data
            )
            
            if self._tap is None:
                print("[MouseHook] ERROR: Failed to create CGEventTap!")
                print("[MouseHook] Make sure Accessibility permission is granted:")
                print("[MouseHook]   System Settings -> Privacy & Security -> Accessibility")
                return

            print("[MouseHook] CGEventTap created successfully", flush=True)
            
            # Create a run loop source and add it to the current run loop
            # The Qt/Cocoa run loop will drive this
            self._tap_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(),
                self._tap_source,
                Quartz.kCFRunLoopCommonModes
            )
            
            # Enable the tap
            Quartz.CGEventTapEnable(self._tap, True)
            print("[MouseHook] CGEventTap enabled and integrated with run loop", flush=True)

        def stop(self):
            self._running = False
            if self._hid_gesture:
                self._hid_gesture.stop()
                self._hid_gesture = None
            
            # Disable and remove the event tap
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


# ══════════════════════════════════════════════════════════════════
# Unsupported platform stub
# ══════════════════════════════════════════════════════════════════

else:
    class MouseHook:
        """Stub for unsupported platforms."""
        def __init__(self):
            self._callbacks = {}
            self._blocked_events = set()
            self.invert_vscroll = False
            self.invert_hscroll = False
            self._hid_gesture = None
            print(f"[MouseHook] Platform '{sys.platform}' not supported")

        def register(self, event_type, callback): pass
        def block(self, event_type): pass
        def unblock(self, event_type): pass
        def reset_bindings(self): pass
        def set_debug_callback(self, callback): pass
        def start(self): pass
        def stop(self): pass
