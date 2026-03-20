"""
Keyboard and mouse action simulator.
Supports Windows (SendInput API) and macOS (Quartz CGEvent / NSEvent).
"""

import sys
import time

# ==================================================================
# Windows implementation
# ==================================================================

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes
    from ctypes import Structure, Union, c_ulong, c_ushort, c_long, sizeof

    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    # Virtual key codes
    VK_MENU = 0x12
    VK_TAB = 0x09
    VK_LMENU = 0xA4
    VK_SHIFT = 0x10
    VK_CONTROL = 0x11
    VK_LWIN = 0x5B
    VK_ESCAPE = 0x1B
    VK_RETURN = 0x0D
    VK_SPACE = 0x20
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_DELETE = 0x2E
    VK_BACK = 0x08

    VK_BROWSER_BACK = 0xA6
    VK_BROWSER_FORWARD = 0xA7
    VK_BROWSER_REFRESH = 0xA8
    VK_BROWSER_STOP = 0xA9
    VK_BROWSER_HOME = 0xAC

    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3

    VK_F1 = 0x70
    VK_F2 = 0x71
    VK_F3 = 0x72
    VK_F4 = 0x73
    VK_F5 = 0x74
    VK_F6 = 0x75
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79
    VK_F11 = 0x7A
    VK_F12 = 0x7B

    VK_C = 0x43
    VK_V = 0x56
    VK_X = 0x58
    VK_Z = 0x5A
    VK_A = 0x41
    VK_S = 0x53
    VK_W = 0x57
    VK_T = 0x54
    VK_N = 0x4E
    VK_F = 0x46
    VK_D = 0x44

    class KEYBDINPUT(Structure):
        _fields_ = [
            ("wVk", c_ushort),
            ("wScan", c_ushort),
            ("dwFlags", c_ulong),
            ("time", c_ulong),
            ("dwExtraInfo", ctypes.POINTER(c_ulong)),
        ]

    class MOUSEINPUT(Structure):
        _fields_ = [
            ("dx", c_long),
            ("dy", c_long),
            ("mouseData", c_ulong),
            ("dwFlags", c_ulong),
            ("time", c_ulong),
            ("dwExtraInfo", ctypes.POINTER(c_ulong)),
        ]

    class HARDWAREINPUT(Structure):
        _fields_ = [
            ("uMsg", c_ulong),
            ("wParamL", c_ushort),
            ("wParamH", c_ushort),
        ]

    class _INPUTunion(Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(Structure):
        _fields_ = [
            ("type", c_ulong),
            ("union", _INPUTunion),
        ]

    SendInput = ctypes.windll.user32.SendInput
    SendInput.argtypes = [c_ulong, ctypes.POINTER(INPUT), ctypes.c_int]
    SendInput.restype = c_ulong

    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def inject_scroll(flags, delta):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.mouseData = delta & 0xFFFFFFFF
        inp.union.mi.dwFlags = flags
        arr = (INPUT * 1)(inp)
        SendInput(1, arr, sizeof(INPUT))

    def _make_key_input(vk, flags=0):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.dwFlags = flags
        inp.union.ki.dwExtraInfo = ctypes.pointer(c_ulong(0))
        return inp

    def send_key_combo(keys, hold_ms=50):
        inputs = []
        for vk in keys:
            flags = KEYEVENTF_EXTENDEDKEY if _is_extended(vk) else 0
            inputs.append(_make_key_input(vk, flags))
        for vk in reversed(keys):
            flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if _is_extended(vk) else 0)
            inputs.append(_make_key_input(vk, flags))
        arr = (INPUT * len(inputs))(*inputs)
        SendInput(len(inputs), arr, sizeof(INPUT))

    def send_key_press(vk):
        send_key_combo([vk])

    def _is_extended(vk):
        extended = {
            VK_BROWSER_BACK, VK_BROWSER_FORWARD, VK_BROWSER_REFRESH,
            VK_BROWSER_STOP, VK_BROWSER_HOME,
            VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP,
            VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK,
            VK_MEDIA_STOP, VK_MEDIA_PLAY_PAUSE,
            VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN,
            VK_DELETE, VK_RETURN, VK_TAB,
        }
        return vk in extended

    ACTIONS = {
        "alt_tab": {
            "label": "Alt + Tab (Switch Windows)",
            "keys": [VK_MENU, VK_TAB],
            "category": "Navigation",
        },
        "alt_shift_tab": {
            "label": "Alt + Shift + Tab (Switch Windows Reverse)",
            "keys": [VK_MENU, VK_SHIFT, VK_TAB],
            "category": "Navigation",
        },
        "browser_back": {
            "label": "Browser Back",
            "keys": [VK_BROWSER_BACK],
            "category": "Browser",
        },
        "browser_forward": {
            "label": "Browser Forward",
            "keys": [VK_BROWSER_FORWARD],
            "category": "Browser",
        },
        "copy": {
            "label": "Copy (Ctrl+C)",
            "keys": [VK_CONTROL, VK_C],
            "category": "Editing",
        },
        "paste": {
            "label": "Paste (Ctrl+V)",
            "keys": [VK_CONTROL, VK_V],
            "category": "Editing",
        },
        "cut": {
            "label": "Cut (Ctrl+X)",
            "keys": [VK_CONTROL, VK_X],
            "category": "Editing",
        },
        "undo": {
            "label": "Undo (Ctrl+Z)",
            "keys": [VK_CONTROL, VK_Z],
            "category": "Editing",
        },
        "select_all": {
            "label": "Select All (Ctrl+A)",
            "keys": [VK_CONTROL, VK_A],
            "category": "Editing",
        },
        "save": {
            "label": "Save (Ctrl+S)",
            "keys": [VK_CONTROL, VK_S],
            "category": "Editing",
        },
        "close_tab": {
            "label": "Close Tab (Ctrl+W)",
            "keys": [VK_CONTROL, VK_W],
            "category": "Browser",
        },
        "new_tab": {
            "label": "New Tab (Ctrl+T)",
            "keys": [VK_CONTROL, VK_T],
            "category": "Browser",
        },
        "find": {
            "label": "Find (Ctrl+F)",
            "keys": [VK_CONTROL, VK_F],
            "category": "Editing",
        },
        "win_d": {
            "label": "Show Desktop (Win+D)",
            "keys": [VK_LWIN, VK_D],
            "category": "Navigation",
        },
        "task_view": {
            "label": "Task View (Win+Tab)",
            "keys": [VK_LWIN, VK_TAB],
            "category": "Navigation",
        },
        "volume_up": {
            "label": "Volume Up",
            "keys": [VK_VOLUME_UP],
            "category": "Media",
        },
        "volume_down": {
            "label": "Volume Down",
            "keys": [VK_VOLUME_DOWN],
            "category": "Media",
        },
        "volume_mute": {
            "label": "Volume Mute",
            "keys": [VK_VOLUME_MUTE],
            "category": "Media",
        },
        "play_pause": {
            "label": "Play / Pause",
            "keys": [VK_MEDIA_PLAY_PAUSE],
            "category": "Media",
        },
        "next_track": {
            "label": "Next Track",
            "keys": [VK_MEDIA_NEXT_TRACK],
            "category": "Media",
        },
        "prev_track": {
            "label": "Previous Track",
            "keys": [VK_MEDIA_PREV_TRACK],
            "category": "Media",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

    def execute_action(action_id):
        action = ACTIONS.get(action_id)
        if not action or not action["keys"]:
            return
        send_key_combo(action["keys"])


# ==================================================================
# macOS implementation
# ==================================================================

elif sys.platform == "darwin":
    import ctypes

    try:
        import Quartz
        _QUARTZ_OK = True
    except ImportError:
        _QUARTZ_OK = False

    # CGKeyCode values used on macOS
    kVK_Command = 0x37
    kVK_Shift = 0x38
    kVK_Option = 0x3A
    kVK_Control = 0x3B
    kVK_Tab = 0x30
    kVK_Space = 0x31
    kVK_Return = 0x24
    kVK_Delete = 0x33       # Backspace
    kVK_ForwardDelete = 0x75
    kVK_Escape = 0x35
    kVK_LeftArrow = 0x7B
    kVK_RightArrow = 0x7C
    kVK_DownArrow = 0x7D
    kVK_UpArrow = 0x7E

    kVK_ANSI_A = 0x00
    kVK_ANSI_S = 0x01
    kVK_ANSI_D = 0x02
    kVK_ANSI_F = 0x03
    kVK_ANSI_N = 0x2D
    kVK_ANSI_T = 0x11
    kVK_ANSI_W = 0x0D
    kVK_ANSI_X = 0x07
    kVK_ANSI_C = 0x08
    kVK_ANSI_V = 0x09
    kVK_ANSI_Z = 0x06

    kVK_F1  = 0x7A
    kVK_F2  = 0x78
    kVK_F3  = 0x63
    kVK_F4  = 0x76
    kVK_F5  = 0x60
    kVK_F6  = 0x61
    kVK_F7  = 0x62
    kVK_F8  = 0x64
    kVK_F9  = 0x65
    kVK_F10 = 0x6D
    kVK_F11 = 0x67
    kVK_F12 = 0x6F

    # Not used by inject_scroll on macOS — stubs for import compatibility
    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def inject_scroll(flags, delta):
        """Inject a scroll event on macOS using CGEvent."""
        if not _QUARTZ_OK:
            return
        if flags == MOUSEEVENTF_WHEEL:
            event = Quartz.CGEventCreateScrollWheelEvent(None, 0, 1, delta)
        else:
            event = Quartz.CGEventCreateScrollWheelEvent(None, 0, 2, 0, delta)
        if event:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    # Modifier flag bits for CGEvent
    _MOD_FLAGS = {
        kVK_Command: Quartz.kCGEventFlagMaskCommand if _QUARTZ_OK else 0,
        kVK_Shift: Quartz.kCGEventFlagMaskShift if _QUARTZ_OK else 0,
        kVK_Option: Quartz.kCGEventFlagMaskAlternate if _QUARTZ_OK else 0,
        kVK_Control: Quartz.kCGEventFlagMaskControl if _QUARTZ_OK else 0,
    }

    def send_key_combo(keys, hold_ms=50):
        """Press and release a combination of CGKeyCodes."""
        if not _QUARTZ_OK:
            return
        # Compute modifier flags
        flags = 0
        for k in keys:
            flags |= _MOD_FLAGS.get(k, 0)

        # Press all
        for k in keys:
            ev = Quartz.CGEventCreateKeyboardEvent(None, k, True)
            if flags:
                Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

        if hold_ms:
            time.sleep(hold_ms / 1000.0)

        # Release in reverse
        for k in reversed(keys):
            ev = Quartz.CGEventCreateKeyboardEvent(None, k, False)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def send_key_press(vk):
        send_key_combo([vk])

    def _send_media_key(key_id):
        """Send a media key event via NSEvent (Fn-key based)."""
        try:
            import AppKit
            ev_down = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xa00, 0, 0, None, 8, (key_id << 16) | (0xa << 8), -1
            )
            ev_up = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xb00, 0, 0, None, 8, (key_id << 16) | (0xb << 8), -1
            )
            cg_down = ev_down.CGEvent()
            cg_up = ev_up.CGEvent()
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, cg_down)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, cg_up)
        except Exception as e:
            print(f"[KeySimulator] media key error: {e}")

    # NX key IDs (from IOKit/hidsystem)
    _NX_PLAY = 16
    _NX_NEXT = 17
    _NX_PREV = 18
    _NX_MUTE = 7
    _NX_VOL_UP = 0
    _NX_VOL_DOWN = 1

    _KCFSTRING_ENCODING_UTF8 = 0x08000100
    _MAC_ACTION_FALLBACKS = {
        "mission_control": [kVK_Control, kVK_UpArrow],
        "app_expose": [kVK_Control, kVK_DownArrow],
        "space_left": [kVK_Control, kVK_LeftArrow],
        "space_right": [kVK_Control, kVK_RightArrow],
        "show_desktop": [kVK_F11],
        "launchpad": [kVK_F4],
    }
    _SYMBOLIC_HOTKEY_SPACE_LEFT = 79
    _SYMBOLIC_HOTKEY_SPACE_RIGHT = 81

    try:
        _APP_SERVICES = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        _CORE_FOUNDATION = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        _APP_SERVICES.CoreDockSendNotification.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _APP_SERVICES.CoreDockSendNotification.restype = ctypes.c_int
        _APP_SERVICES.CGSGetSymbolicHotKeyValue.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        _APP_SERVICES.CGSGetSymbolicHotKeyValue.restype = ctypes.c_int
        _APP_SERVICES.CGSIsSymbolicHotKeyEnabled.argtypes = [ctypes.c_uint32]
        _APP_SERVICES.CGSIsSymbolicHotKeyEnabled.restype = ctypes.c_bool
        _APP_SERVICES.CGSSetSymbolicHotKeyEnabled.argtypes = [ctypes.c_uint32, ctypes.c_bool]
        _APP_SERVICES.CGSSetSymbolicHotKeyEnabled.restype = ctypes.c_int
        _CORE_FOUNDATION.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        _CORE_FOUNDATION.CFStringCreateWithCString.restype = ctypes.c_void_p
        _CORE_FOUNDATION.CFRelease.argtypes = [ctypes.c_void_p]
        _CORE_FOUNDATION.CFRelease.restype = None
        _PRIVATE_MAC_APIS_OK = True
    except Exception:
        _APP_SERVICES = None
        _CORE_FOUNDATION = None
        _PRIVATE_MAC_APIS_OK = False

    def _dock_notification(notification_name):
        if not _PRIVATE_MAC_APIS_OK:
            return False
        cf_string = _CORE_FOUNDATION.CFStringCreateWithCString(
            None, notification_name.encode("utf-8"), _KCFSTRING_ENCODING_UTF8
        )
        if not cf_string:
            return False
        try:
            return _APP_SERVICES.CoreDockSendNotification(cf_string, 0) == 0
        finally:
            _CORE_FOUNDATION.CFRelease(cf_string)

    def _post_symbolic_hotkey(hotkey):
        if not (_PRIVATE_MAC_APIS_OK and _QUARTZ_OK):
            return False
        key_equivalent = ctypes.c_uint16()
        virtual_key = ctypes.c_uint16()
        modifiers = ctypes.c_uint32()
        err = _APP_SERVICES.CGSGetSymbolicHotKeyValue(
            hotkey,
            ctypes.byref(key_equivalent),
            ctypes.byref(virtual_key),
            ctypes.byref(modifiers),
        )
        if err != 0:
            return False

        was_enabled = bool(_APP_SERVICES.CGSIsSymbolicHotKeyEnabled(hotkey))
        if not was_enabled:
            _APP_SERVICES.CGSSetSymbolicHotKeyEnabled(hotkey, True)
        try:
            key_down = Quartz.CGEventCreateKeyboardEvent(None, virtual_key.value, True)
            key_up = Quartz.CGEventCreateKeyboardEvent(None, virtual_key.value, False)
            if not key_down or not key_up:
                return False
            Quartz.CGEventSetFlags(key_down, modifiers.value)
            Quartz.CGEventSetFlags(key_up, modifiers.value)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, key_down)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, key_up)
            time.sleep(0.05)
            return True
        finally:
            if not was_enabled:
                _APP_SERVICES.CGSSetSymbolicHotKeyEnabled(hotkey, False)

    def _execute_mac_action(action_id):
        if action_id == "mission_control":
            return _dock_notification("com.apple.expose.awake")
        if action_id == "app_expose":
            return _dock_notification("com.apple.expose.front.awake")
        if action_id == "show_desktop":
            return _dock_notification("com.apple.showdesktop.awake")
        if action_id == "launchpad":
            return _dock_notification("com.apple.launchpad.toggle")
        if action_id == "space_left":
            return _post_symbolic_hotkey(_SYMBOLIC_HOTKEY_SPACE_LEFT)
        if action_id == "space_right":
            return _post_symbolic_hotkey(_SYMBOLIC_HOTKEY_SPACE_RIGHT)
        return False

    ACTIONS = {
        "alt_tab": {
            "label": "Cmd + Tab (Switch Windows)",
            "keys": [kVK_Command, kVK_Tab],
            "category": "Navigation",
        },
        "alt_shift_tab": {
            "label": "Cmd + Shift + Tab (Switch Windows Reverse)",
            "keys": [kVK_Command, kVK_Shift, kVK_Tab],
            "category": "Navigation",
        },
        "browser_back": {
            "label": "Browser Back (Cmd+[)",
            "keys": [kVK_Command, 0x21],   # kVK_ANSI_LeftBracket
            "category": "Browser",
        },
        "browser_forward": {
            "label": "Browser Forward (Cmd+])",
            "keys": [kVK_Command, 0x1E],   # kVK_ANSI_RightBracket
            "category": "Browser",
        },
        "copy": {
            "label": "Copy (Cmd+C)",
            "keys": [kVK_Command, kVK_ANSI_C],
            "category": "Editing",
        },
        "paste": {
            "label": "Paste (Cmd+V)",
            "keys": [kVK_Command, kVK_ANSI_V],
            "category": "Editing",
        },
        "cut": {
            "label": "Cut (Cmd+X)",
            "keys": [kVK_Command, kVK_ANSI_X],
            "category": "Editing",
        },
        "undo": {
            "label": "Undo (Cmd+Z)",
            "keys": [kVK_Command, kVK_ANSI_Z],
            "category": "Editing",
        },
        "select_all": {
            "label": "Select All (Cmd+A)",
            "keys": [kVK_Command, kVK_ANSI_A],
            "category": "Editing",
        },
        "save": {
            "label": "Save (Cmd+S)",
            "keys": [kVK_Command, kVK_ANSI_S],
            "category": "Editing",
        },
        "close_tab": {
            "label": "Close Tab (Cmd+W)",
            "keys": [kVK_Command, kVK_ANSI_W],
            "category": "Browser",
        },
        "new_tab": {
            "label": "New Tab (Cmd+T)",
            "keys": [kVK_Command, kVK_ANSI_T],
            "category": "Browser",
        },
        "find": {
            "label": "Find (Cmd+F)",
            "keys": [kVK_Command, kVK_ANSI_F],
            "category": "Editing",
        },
        "win_d": {
            "label": "Mission Control (Ctrl+Up)",
            "keys": [kVK_Control, kVK_UpArrow],
            "category": "Navigation",
        },
        "task_view": {
            "label": "Mission Control (Ctrl+Up)",
            "keys": [kVK_Control, kVK_UpArrow],
            "category": "Navigation",
        },
        "mission_control": {
            "label": "Mission Control",
            "keys": _MAC_ACTION_FALLBACKS["mission_control"],
            "category": "Navigation",
        },
        "app_expose": {
            "label": "App Expose",
            "keys": _MAC_ACTION_FALLBACKS["app_expose"],
            "category": "Navigation",
        },
        "space_left": {
            "label": "Previous Space",
            "keys": _MAC_ACTION_FALLBACKS["space_left"],
            "category": "Navigation",
        },
        "space_right": {
            "label": "Next Space",
            "keys": _MAC_ACTION_FALLBACKS["space_right"],
            "category": "Navigation",
        },
        "show_desktop": {
            "label": "Show Desktop",
            "keys": _MAC_ACTION_FALLBACKS["show_desktop"],
            "category": "Navigation",
        },
        "launchpad": {
            "label": "Launchpad",
            "keys": _MAC_ACTION_FALLBACKS["launchpad"],
            "category": "Navigation",
        },
        "volume_up": {
            "label": "Volume Up",
            "keys": [],
            "mac_fn": _NX_VOL_UP,
            "category": "Media",
        },
        "volume_down": {
            "label": "Volume Down",
            "keys": [],
            "mac_fn": _NX_VOL_DOWN,
            "category": "Media",
        },
        "volume_mute": {
            "label": "Volume Mute",
            "keys": [],
            "mac_fn": _NX_MUTE,
            "category": "Media",
        },
        "play_pause": {
            "label": "Play / Pause",
            "keys": [],
            "mac_fn": _NX_PLAY,
            "category": "Media",
        },
        "next_track": {
            "label": "Next Track",
            "keys": [],
            "mac_fn": _NX_NEXT,
            "category": "Media",
        },
        "prev_track": {
            "label": "Previous Track",
            "keys": [],
            "mac_fn": _NX_PREV,
            "category": "Media",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

    def execute_action(action_id):
        action = ACTIONS.get(action_id)
        if not action:
            return
        if _execute_mac_action(action_id):
            return
        if action.get("mac_fn") is not None:
            _send_media_key(action["mac_fn"])
        elif action["keys"]:
            send_key_combo(action["keys"])


# ==================================================================
# Unsupported platform stub
# ==================================================================

else:
    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def inject_scroll(flags, delta): pass
    def send_key_combo(keys, hold_ms=50): pass
    def send_key_press(vk): pass
    def execute_action(action_id): pass

    ACTIONS = {
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }
