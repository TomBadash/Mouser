"""
Keyboard and mouse action simulator.
Supports Windows (SendInput API) and macOS (Quartz CGEvent / NSEvent).
"""

import os
import sys
import threading
import time


# ==================================================================
# Custom shortcut helpers (shared across platforms)
# ==================================================================

def custom_action_label(action_id):
    """Convert 'custom:ctrl+shift+a' → 'Ctrl + Shift + A'."""
    if not action_id.startswith("custom:"):
        return action_id
    parts = action_id[7:].split("+")
    return " + ".join(p.capitalize() for p in parts)


def valid_custom_key_names():
    """Return the sorted list of valid key names for custom shortcuts."""
    try:
        return sorted(_KEY_NAME_TO_CODE.keys())
    except NameError:
        return []


def _parse_custom_combo(action_id, key_name_to_code):
    """Parse 'custom:ctrl+a' → list of platform key codes using given mapping."""
    if not action_id.startswith("custom:"):
        return None
    parts = action_id[7:].split("+")
    codes = []
    for name in parts:
        name = name.strip()
        if not name:
            continue
        code = key_name_to_code.get(name.lower())
        if code is None:
            print(f"[KeySimulator] Unknown key name: {name}")
            return None
        codes.append(code)
    return codes


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
    KEYEVENTF_SCANCODE = 0x0008

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

    VK_PRIOR = 0x21   # Page Up
    VK_NEXT  = 0x22   # Page Down
    VK_END   = 0x23   # End
    VK_HOME  = 0x24   # Home

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

    MOUSEEVENTF_LEFTDOWN   = 0x0002
    MOUSEEVENTF_LEFTUP     = 0x0004
    MOUSEEVENTF_RIGHTDOWN  = 0x0008
    MOUSEEVENTF_RIGHTUP    = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP   = 0x0040
    MOUSEEVENTF_XDOWN      = 0x0080
    MOUSEEVENTF_XUP        = 0x0100
    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    XBUTTON1 = 0x0001
    XBUTTON2 = 0x0002

    # Mapping from mouse-button action IDs to (down_flag, up_flag, mouseData)
    _MOUSE_BUTTON_MAP = {
        "mouse_left_click":    (MOUSEEVENTF_LEFTDOWN,   MOUSEEVENTF_LEFTUP,   0),
        "mouse_right_click":   (MOUSEEVENTF_RIGHTDOWN,  MOUSEEVENTF_RIGHTUP,  0),
        "mouse_middle_click":  (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
        "mouse_back_click":    (MOUSEEVENTF_XDOWN,      MOUSEEVENTF_XUP,      XBUTTON1),
        "mouse_forward_click": (MOUSEEVENTF_XDOWN,      MOUSEEVENTF_XUP,      XBUTTON2),
    }

    def _make_mouse_input(flags, mouse_data=0):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dwFlags = flags
        inp.union.mi.mouseData = mouse_data
        return inp

    def inject_mouse_down(action_id):
        """Inject a mouse button press for the given mouse-button action."""
        try:
            entry = _MOUSE_BUTTON_MAP.get(action_id)
            if not entry:
                print(f"[KeySimulator] inject_mouse_down: unknown action '{action_id}'")
                return
            down_flag, _, mouse_data = entry
            print(f"[KeySimulator] inject_mouse_down({action_id}) flags=0x{down_flag:04X} mouseData=0x{mouse_data:04X}")
            inp = _make_mouse_input(down_flag, mouse_data)
            arr = (INPUT * 1)(inp)
            result = SendInput(1, arr, sizeof(INPUT))
            if result == 0:
                err = ctypes.get_last_error() if hasattr(ctypes, 'get_last_error') else 'N/A'
                print(f"[KeySimulator] inject_mouse_down: SendInput returned 0! error={err}")
        except Exception as exc:
            print(f"[KeySimulator] inject_mouse_down EXCEPTION: {exc}")
            import traceback; traceback.print_exc()

    def inject_mouse_up(action_id):
        """Inject a mouse button release for the given mouse-button action."""
        try:
            entry = _MOUSE_BUTTON_MAP.get(action_id)
            if not entry:
                print(f"[KeySimulator] inject_mouse_up: unknown action '{action_id}'")
                return
            _, up_flag, mouse_data = entry
            print(f"[KeySimulator] inject_mouse_up({action_id}) flags=0x{up_flag:04X} mouseData=0x{mouse_data:04X}")
            inp = _make_mouse_input(up_flag, mouse_data)
            arr = (INPUT * 1)(inp)
            result = SendInput(1, arr, sizeof(INPUT))
            if result == 0:
                err = ctypes.get_last_error() if hasattr(ctypes, 'get_last_error') else 'N/A'
                print(f"[KeySimulator] inject_mouse_up: SendInput returned 0! error={err}")
        except Exception as exc:
            print(f"[KeySimulator] inject_mouse_up EXCEPTION: {exc}")
            import traceback; traceback.print_exc()

    def is_mouse_button_action(action_id):
        """Return True if the action simulates a mouse button."""
        return action_id in _MOUSE_BUTTON_MAP

    def inject_scroll(flags, delta):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.mouseData = delta & 0xFFFFFFFF
        inp.union.mi.dwFlags = flags
        arr = (INPUT * 1)(inp)
        SendInput(1, arr, sizeof(INPUT))

    # VKs that require the KEYEVENTF_EXTENDEDKEY flag in SendInput
    _EXTENDED_VKS = frozenset({
        VK_BROWSER_BACK, VK_BROWSER_FORWARD, VK_BROWSER_REFRESH,
        VK_BROWSER_STOP, VK_BROWSER_HOME,
        VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP,
        VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK,
        VK_MEDIA_STOP, VK_MEDIA_PLAY_PAUSE,
        VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN,
        VK_DELETE, VK_RETURN, VK_TAB,
        VK_PRIOR, VK_NEXT, VK_HOME, VK_END,   # navigation cluster (extended)
    })

    def _is_extended(vk):
        return vk in _EXTENDED_VKS

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

    def _send_phased_alt_arrow(arrow_vk, hold_ms=50):
        # Some Chromium-based browsers silently drop batched VK-only SendInput chords;
        # phased modifier-down → key-tap → modifier-up with pauses is accepted reliably.
        pause = max(hold_ms, 1) / 1000.0
        ext = KEYEVENTF_EXTENDEDKEY
        alt_down = _make_key_input(VK_LMENU, 0)
        alt_up   = _make_key_input(VK_LMENU, KEYEVENTF_KEYUP)
        arr_down = _make_key_input(arrow_vk, ext)
        arr_up   = _make_key_input(arrow_vk, ext | KEYEVENTF_KEYUP)

        def _send(*events):
            arr = (INPUT * len(events))(*events)
            SendInput(len(events), arr, sizeof(INPUT))

        _send(alt_down)
        time.sleep(pause)
        _send(arr_down, arr_up)
        time.sleep(pause)
        _send(alt_up)

    _BROWSER_NAV_ARROW = {
        "browser_back":    VK_LEFT,
        "browser_forward": VK_RIGHT,
    }

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
            "keys": [VK_MENU, VK_LEFT],
            "category": "Browser",
        },
        "browser_forward": {
            "label": "Browser Forward",
            "keys": [VK_MENU, VK_RIGHT],
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
        "next_tab": {
            "label": "Next Tab (Ctrl+Tab)",
            "keys": [VK_CONTROL, VK_TAB],
            "category": "Browser",
        },
        "prev_tab": {
            "label": "Previous Tab (Ctrl+Shift+Tab)",
            "keys": [VK_CONTROL, VK_SHIFT, VK_TAB],
            "category": "Browser",
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
        "space_left": {
            "label": "Previous Desktop",
            "keys": [VK_CONTROL, VK_LWIN, VK_LEFT],
            "category": "Navigation",
        },
        "space_right": {
            "label": "Next Desktop",
            "keys": [VK_CONTROL, VK_LWIN, VK_RIGHT],
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
        "page_up": {
            "label": "Page Up",
            "keys": [VK_PRIOR],
            "category": "Navigation",
        },
        "page_down": {
            "label": "Page Down",
            "keys": [VK_NEXT],
            "category": "Navigation",
        },
        "home": {
            "label": "Home",
            "keys": [VK_HOME],
            "category": "Navigation",
        },
        "end": {
            "label": "End",
            "keys": [VK_END],
            "category": "Navigation",
        },
        "switch_scroll_mode": {
            "label": "Switch Scroll Mode (Ratchet / Free Spin)",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "toggle_smart_shift": {
            "label": "Toggle SmartShift",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "cycle_dpi": {
            "label": "Cycle DPI Presets",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "mouse_left_click": {
            "label": "Left Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_right_click": {
            "label": "Right Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_middle_click": {
            "label": "Middle Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_back_click": {
            "label": "Back (Mouse Button 4)",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_forward_click": {
            "label": "Forward (Mouse Button 5)",
            "keys": [],
            "category": "Mouse",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

    _KEY_NAME_TO_CODE = {
        "ctrl": VK_CONTROL, "shift": VK_SHIFT, "alt": VK_MENU,
        "super": VK_LWIN, "tab": VK_TAB, "space": VK_SPACE,
        "enter": VK_RETURN, "esc": VK_ESCAPE, "backspace": VK_BACK,
        "delete": VK_DELETE, "left": VK_LEFT, "right": VK_RIGHT,
        "up": VK_UP, "down": VK_DOWN,
        "pageup": VK_PRIOR, "pagedown": VK_NEXT, "home": VK_HOME, "end": VK_END,
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
        "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
        "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
        "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
        "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
        "z": 0x5A,
        "f1": VK_F1, "f2": VK_F2, "f3": VK_F3, "f4": VK_F4,
        "f5": VK_F5, "f6": VK_F6, "f7": VK_F7, "f8": VK_F8,
        "f9": VK_F9, "f10": VK_F10, "f11": VK_F11, "f12": VK_F12,
        "volumeup": VK_VOLUME_UP, "volumedown": VK_VOLUME_DOWN,
        "mute": VK_VOLUME_MUTE, "playpause": VK_MEDIA_PLAY_PAUSE,
        "nexttrack": VK_MEDIA_NEXT_TRACK, "prevtrack": VK_MEDIA_PREV_TRACK,
    }

    def execute_action(action_id):
        try:
            print(f"[KeySimulator] execute_action({action_id})")
            if action_id.startswith("custom:"):
                keys = _parse_custom_combo(action_id, _KEY_NAME_TO_CODE)
                if keys:
                    send_key_combo(keys)
                return
            if is_mouse_button_action(action_id):
                print(f"[KeySimulator] execute_action: mouse click for {action_id}")
                inject_mouse_down(action_id)
                inject_mouse_up(action_id)
                return
            action = ACTIONS.get(action_id)
            if not action or not action["keys"]:
                print(f"[KeySimulator] execute_action: no keys for '{action_id}'")
                return
            arrow_vk = _BROWSER_NAV_ARROW.get(action_id)
            if arrow_vk is not None:
                _send_phased_alt_arrow(arrow_vk)
            else:
                send_key_combo(action["keys"])
        except Exception as exc:
            print(f"[KeySimulator] execute_action EXCEPTION: {exc}")
            import traceback; traceback.print_exc()


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

    try:
        import AppKit as _AppKit
        _APPKIT_OK = True
    except ImportError:
        _AppKit = None
        _APPKIT_OK = False

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
    kVK_Home = 0x73
    kVK_End = 0x77
    kVK_PageUp = 0x74
    kVK_PageDown = 0x79

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

    # Mouse button simulation
    # CGEvent mouse button constants
    _MAC_MOUSE_MAP = {
        "mouse_left_click": {
            "down_type": Quartz.kCGEventLeftMouseDown if _QUARTZ_OK else 1,
            "up_type":   Quartz.kCGEventLeftMouseUp   if _QUARTZ_OK else 2,
            "button": 0,
        },
        "mouse_right_click": {
            "down_type": Quartz.kCGEventRightMouseDown if _QUARTZ_OK else 3,
            "up_type":   Quartz.kCGEventRightMouseUp   if _QUARTZ_OK else 4,
            "button": 1,
        },
        "mouse_middle_click": {
            "down_type": Quartz.kCGEventOtherMouseDown if _QUARTZ_OK else 25,
            "up_type":   Quartz.kCGEventOtherMouseUp   if _QUARTZ_OK else 26,
            "button": 2,
        },
        "mouse_back_click": {
            "down_type": Quartz.kCGEventOtherMouseDown if _QUARTZ_OK else 25,
            "up_type":   Quartz.kCGEventOtherMouseUp   if _QUARTZ_OK else 26,
            "button": 3,
        },
        "mouse_forward_click": {
            "down_type": Quartz.kCGEventOtherMouseDown if _QUARTZ_OK else 25,
            "up_type":   Quartz.kCGEventOtherMouseUp   if _QUARTZ_OK else 26,
            "button": 4,
        },
    } if _QUARTZ_OK else {}

    def _inject_mac_mouse(action_id, is_down):
        entry = _MAC_MOUSE_MAP.get(action_id)
        if not entry or not _QUARTZ_OK:
            return
        evt_type = entry["down_type"] if is_down else entry["up_type"]
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        ev = Quartz.CGEventCreateMouseEvent(None, evt_type, loc, entry["button"])
        if ev:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def inject_mouse_down(action_id):
        _inject_mac_mouse(action_id, True)

    def inject_mouse_up(action_id):
        _inject_mac_mouse(action_id, False)

    def is_mouse_button_action(action_id):
        return action_id in _MAC_MOUSE_MAP

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
            ev_down = _AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xa00, 0, 0, None, 8, (key_id << 16) | (0xa << 8), -1
            )
            ev_up = _AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
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
        "next_tab": {
            "label": "Next Tab (Cmd+Shift+])",
            "keys": [kVK_Command, kVK_Shift, 0x1E],  # kVK_ANSI_RightBracket
            "category": "Browser",
        },
        "prev_tab": {
            "label": "Previous Tab (Cmd+Shift+[)",
            "keys": [kVK_Command, kVK_Shift, 0x21],  # kVK_ANSI_LeftBracket
            "category": "Browser",
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
            "label": "Previous Desktop",
            "keys": _MAC_ACTION_FALLBACKS["space_left"],
            "category": "Navigation",
        },
        "space_right": {
            "label": "Next Desktop",
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
        "page_up": {
            "label": "Page Up",
            "keys": [kVK_PageUp],
            "category": "Navigation",
        },
        "page_down": {
            "label": "Page Down",
            "keys": [kVK_PageDown],
            "category": "Navigation",
        },
        "home": {
            "label": "Home",
            "keys": [kVK_Home],
            "category": "Navigation",
        },
        "end": {
            "label": "End",
            "keys": [kVK_End],
            "category": "Navigation",
        },
        "switch_scroll_mode": {
            "label": "Switch Scroll Mode (Ratchet / Free Spin)",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "toggle_smart_shift": {
            "label": "Toggle SmartShift",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "cycle_dpi": {
            "label": "Cycle DPI Presets",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "mouse_left_click": {
            "label": "Left Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_right_click": {
            "label": "Right Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_middle_click": {
            "label": "Middle Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_back_click": {
            "label": "Back (Mouse Button 4)",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_forward_click": {
            "label": "Forward (Mouse Button 5)",
            "keys": [],
            "category": "Mouse",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

    _KEY_NAME_TO_CODE = {
        "ctrl": kVK_Control, "shift": kVK_Shift, "alt": kVK_Option,
        "super": kVK_Command, "tab": kVK_Tab, "space": kVK_Space,
        "enter": kVK_Return, "esc": kVK_Escape, "backspace": kVK_Delete,
        "delete": kVK_ForwardDelete, "left": kVK_LeftArrow,
        "right": kVK_RightArrow, "up": kVK_UpArrow, "down": kVK_DownArrow,
        "pageup": kVK_PageUp, "pagedown": kVK_PageDown,
        "home": kVK_Home, "end": kVK_End,
        "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E,
        "f": 0x03, "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26,
        "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D, "o": 0x1F,
        "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11,
        "u": 0x20, "v": 0x09, "w": 0x0D,
        "x": 0x07, "y": 0x10, "z": 0x06,
        "f1": kVK_F1, "f2": kVK_F2, "f3": kVK_F3, "f4": kVK_F4,
        "f5": kVK_F5, "f6": kVK_F6, "f7": kVK_F7, "f8": kVK_F8,
        "f9": kVK_F9, "f10": kVK_F10, "f11": kVK_F11, "f12": kVK_F12,
    }

    def execute_action(action_id):
        if action_id.startswith("custom:"):
            keys = _parse_custom_combo(action_id, _KEY_NAME_TO_CODE)
            if keys:
                send_key_combo(keys)
            return
        if is_mouse_button_action(action_id):
            inject_mouse_down(action_id)
            inject_mouse_up(action_id)
            return
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

elif sys.platform == "linux":
    # Linux input key codes (stable, from linux/input-event-codes.h)
    KEY_LEFTALT = 56
    KEY_LEFTSHIFT = 42
    KEY_LEFTCTRL = 29
    KEY_LEFTMETA = 125
    KEY_TAB = 15
    KEY_SPACE = 57
    KEY_ENTER = 28
    KEY_BACKSPACE = 14
    KEY_DELETE = 111
    KEY_ESC = 1
    KEY_LEFT = 105
    KEY_UP = 103
    KEY_RIGHT = 106
    KEY_DOWN = 108
    KEY_PAGEUP = 104
    KEY_PAGEDOWN = 109
    KEY_HOME = 102
    KEY_END = 107
    KEY_A = 30; KEY_B = 48; KEY_C = 46; KEY_D = 32; KEY_E = 18
    KEY_F = 33; KEY_G = 34; KEY_H = 35; KEY_I = 23; KEY_J = 36
    KEY_K = 37; KEY_L = 38; KEY_M = 50; KEY_N = 49; KEY_O = 24
    KEY_P = 25; KEY_Q = 16; KEY_R = 19; KEY_S = 31; KEY_T = 20
    KEY_U = 22; KEY_V = 47; KEY_W = 17; KEY_X = 45; KEY_Y = 21
    KEY_Z = 44
    KEY_BACK = 158
    KEY_FORWARD = 159
    KEY_VOLUMEUP = 115
    KEY_VOLUMEDOWN = 114
    KEY_MUTE = 113
    KEY_PLAYPAUSE = 164
    KEY_NEXTSONG = 163
    KEY_PREVIOUSSONG = 165
    KEY_F1 = 59
    KEY_F2 = 60
    KEY_F3 = 61
    KEY_F4 = 62
    KEY_F5 = 63
    KEY_F6 = 64
    KEY_F7 = 65
    KEY_F8 = 66
    KEY_F9 = 67
    KEY_F10 = 68
    KEY_F11 = 87
    KEY_F12 = 88

    _ALL_KEY_CODES = [
        KEY_LEFTALT, KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_LEFTMETA,
        KEY_TAB, KEY_SPACE, KEY_ENTER, KEY_BACKSPACE, KEY_DELETE, KEY_ESC,
        KEY_LEFT, KEY_UP, KEY_RIGHT, KEY_DOWN,
        KEY_PAGEUP, KEY_PAGEDOWN, KEY_HOME, KEY_END,
        KEY_A, KEY_B, KEY_C, KEY_D, KEY_E, KEY_F, KEY_G, KEY_H, KEY_I,
        KEY_J, KEY_K, KEY_L, KEY_M, KEY_N, KEY_O, KEY_P, KEY_Q, KEY_R,
        KEY_S, KEY_T, KEY_U, KEY_V, KEY_W, KEY_X, KEY_Y, KEY_Z,
        KEY_BACK, KEY_FORWARD,
        KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE,
        KEY_PLAYPAUSE, KEY_NEXTSONG, KEY_PREVIOUSSONG,
        KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5, KEY_F6,
        KEY_F7, KEY_F8, KEY_F9, KEY_F10, KEY_F11, KEY_F12,
    ]

    EV_KEY = 1
    EV_REL = 2
    REL_WHEEL = 8
    REL_HWHEEL = 6

    # Mouse button codes (linux/input-event-codes.h)
    BTN_LEFT   = 0x110
    BTN_RIGHT  = 0x111
    BTN_MIDDLE = 0x112
    BTN_SIDE   = 0x113   # Back / Mouse Button 4
    BTN_EXTRA  = 0x114   # Forward / Mouse Button 5

    _LINUX_MOUSE_BUTTON_MAP = {
        "mouse_left_click":    BTN_LEFT,
        "mouse_right_click":   BTN_RIGHT,
        "mouse_middle_click":  BTN_MIDDLE,
        "mouse_back_click":    BTN_SIDE,
        "mouse_forward_click": BTN_EXTRA,
    }

    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    _virtual_kbd = None
    _virtual_kbd_lock = threading.Lock()

    def _get_virtual_kbd():
        global _virtual_kbd
        if _virtual_kbd is not None:
            return _virtual_kbd
        with _virtual_kbd_lock:
            if _virtual_kbd is not None:
                return _virtual_kbd
            try:
                from evdev import ecodes, UInput
                _virtual_kbd = UInput(
                    {ecodes.EV_KEY: _ALL_KEY_CODES + list(_LINUX_MOUSE_BUTTON_MAP.values())},
                    name="Mouser Virtual Keyboard",
                )
                return _virtual_kbd
            except ImportError:
                print("[KeySimulator] python-evdev not installed — pip install evdev")
            except PermissionError:
                print("[KeySimulator] Permission denied for /dev/uinput — "
                      "add user to 'input' group")
            except Exception as e:
                print(f"[KeySimulator] Failed to create virtual keyboard: {e}")
            return None

    def send_key_combo(keys, hold_ms=50):
        kbd = _get_virtual_kbd()
        if not kbd:
            return
        for key in keys:
            kbd.write(EV_KEY, key, 1)
            kbd.syn()
        if hold_ms:
            time.sleep(hold_ms / 1000.0)
        for key in reversed(keys):
            kbd.write(EV_KEY, key, 0)
            kbd.syn()

    def send_key_press(vk):
        send_key_combo([vk])

    def inject_scroll(flags, delta):
        kbd = _get_virtual_kbd()
        if not kbd:
            return
        if flags == MOUSEEVENTF_WHEEL:
            detents = delta // 120 if abs(delta) >= 120 else (1 if delta > 0 else -1)
            kbd.write(EV_REL, REL_WHEEL, detents)
        else:
            detents = delta // 120 if abs(delta) >= 120 else (1 if delta > 0 else -1)
            kbd.write(EV_REL, REL_HWHEEL, detents)
        kbd.syn()

    def inject_mouse_down(action_id):
        btn = _LINUX_MOUSE_BUTTON_MAP.get(action_id)
        if btn is None:
            return
        kbd = _get_virtual_kbd()
        if kbd:
            kbd.write(EV_KEY, btn, 1)
            kbd.syn()

    def inject_mouse_up(action_id):
        btn = _LINUX_MOUSE_BUTTON_MAP.get(action_id)
        if btn is None:
            return
        kbd = _get_virtual_kbd()
        if kbd:
            kbd.write(EV_KEY, btn, 0)
            kbd.syn()

    def is_mouse_button_action(action_id):
        return action_id in _LINUX_MOUSE_BUTTON_MAP

    _LINUX_DESKTOP = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    def _linux_workspace_keys(direction: str):
        if "GNOME" in _LINUX_DESKTOP:
            return (
                [KEY_LEFTMETA, KEY_PAGEUP]
                if direction == "left"
                else [KEY_LEFTMETA, KEY_PAGEDOWN]
            )
        # KDE/Plasma defaults, and a pragmatic fallback for other desktops.
        return (
            [KEY_LEFTCTRL, KEY_LEFTMETA, KEY_LEFT]
            if direction == "left"
            else [KEY_LEFTCTRL, KEY_LEFTMETA, KEY_RIGHT]
        )

    ACTIONS = {
        "alt_tab": {
            "label": "Alt + Tab (Switch Windows)",
            "keys": [KEY_LEFTALT, KEY_TAB],
            "category": "Navigation",
        },
        "alt_shift_tab": {
            "label": "Alt + Shift + Tab (Switch Windows Reverse)",
            "keys": [KEY_LEFTALT, KEY_LEFTSHIFT, KEY_TAB],
            "category": "Navigation",
        },
        "browser_back": {
            "label": "Browser Back",
            "keys": [KEY_BACK],
            "category": "Browser",
        },
        "browser_forward": {
            "label": "Browser Forward",
            "keys": [KEY_FORWARD],
            "category": "Browser",
        },
        "copy": {
            "label": "Copy (Ctrl+C)",
            "keys": [KEY_LEFTCTRL, KEY_C],
            "category": "Editing",
        },
        "paste": {
            "label": "Paste (Ctrl+V)",
            "keys": [KEY_LEFTCTRL, KEY_V],
            "category": "Editing",
        },
        "cut": {
            "label": "Cut (Ctrl+X)",
            "keys": [KEY_LEFTCTRL, KEY_X],
            "category": "Editing",
        },
        "undo": {
            "label": "Undo (Ctrl+Z)",
            "keys": [KEY_LEFTCTRL, KEY_Z],
            "category": "Editing",
        },
        "select_all": {
            "label": "Select All (Ctrl+A)",
            "keys": [KEY_LEFTCTRL, KEY_A],
            "category": "Editing",
        },
        "save": {
            "label": "Save (Ctrl+S)",
            "keys": [KEY_LEFTCTRL, KEY_S],
            "category": "Editing",
        },
        "close_tab": {
            "label": "Close Tab (Ctrl+W)",
            "keys": [KEY_LEFTCTRL, KEY_W],
            "category": "Browser",
        },
        "new_tab": {
            "label": "New Tab (Ctrl+T)",
            "keys": [KEY_LEFTCTRL, KEY_T],
            "category": "Browser",
        },
        "find": {
            "label": "Find (Ctrl+F)",
            "keys": [KEY_LEFTCTRL, KEY_F],
            "category": "Editing",
        },
        "win_d": {
            "label": "Show Desktop (Super+D)",
            "keys": [KEY_LEFTMETA, KEY_D],
            "category": "Navigation",
        },
        "task_view": {
            "label": "Activities (Super)",
            "keys": [KEY_LEFTMETA],
            "category": "Navigation",
        },
        "space_left": {
            "label": "Previous Desktop",
            "keys": _linux_workspace_keys("left"),
            "category": "Navigation",
        },
        "space_right": {
            "label": "Next Desktop",
            "keys": _linux_workspace_keys("right"),
            "category": "Navigation",
        },
        "volume_up": {
            "label": "Volume Up",
            "keys": [KEY_VOLUMEUP],
            "category": "Media",
        },
        "volume_down": {
            "label": "Volume Down",
            "keys": [KEY_VOLUMEDOWN],
            "category": "Media",
        },
        "volume_mute": {
            "label": "Volume Mute",
            "keys": [KEY_MUTE],
            "category": "Media",
        },
        "play_pause": {
            "label": "Play / Pause",
            "keys": [KEY_PLAYPAUSE],
            "category": "Media",
        },
        "next_track": {
            "label": "Next Track",
            "keys": [KEY_NEXTSONG],
            "category": "Media",
        },
        "prev_track": {
            "label": "Previous Track",
            "keys": [KEY_PREVIOUSSONG],
            "category": "Media",
        },
        "page_up": {
            "label": "Page Up",
            "keys": [KEY_PAGEUP],
            "category": "Navigation",
        },
        "page_down": {
            "label": "Page Down",
            "keys": [KEY_PAGEDOWN],
            "category": "Navigation",
        },
        "home": {
            "label": "Home",
            "keys": [KEY_HOME],
            "category": "Navigation",
        },
        "end": {
            "label": "End",
            "keys": [KEY_END],
            "category": "Navigation",
        },
        "switch_scroll_mode": {
            "label": "Switch Scroll Mode (Ratchet / Free Spin)",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "toggle_smart_shift": {
            "label": "Toggle SmartShift",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "cycle_dpi": {
            "label": "Cycle DPI Presets",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "mouse_left_click": {
            "label": "Left Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_right_click": {
            "label": "Right Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_middle_click": {
            "label": "Middle Click",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_back_click": {
            "label": "Back (Mouse Button 4)",
            "keys": [],
            "category": "Mouse",
        },
        "mouse_forward_click": {
            "label": "Forward (Mouse Button 5)",
            "keys": [],
            "category": "Mouse",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

    _KEY_NAME_TO_CODE = {
        "ctrl": KEY_LEFTCTRL, "shift": KEY_LEFTSHIFT, "alt": KEY_LEFTALT,
        "super": KEY_LEFTMETA, "tab": KEY_TAB, "space": KEY_SPACE,
        "enter": KEY_ENTER, "esc": KEY_ESC, "backspace": KEY_BACKSPACE,
        "delete": KEY_DELETE, "left": KEY_LEFT, "right": KEY_RIGHT,
        "up": KEY_UP, "down": KEY_DOWN,
        "pageup": KEY_PAGEUP, "pagedown": KEY_PAGEDOWN,
        "home": KEY_HOME, "end": KEY_END,
        "a": KEY_A, "b": KEY_B, "c": KEY_C, "d": KEY_D, "e": KEY_E,
        "f": KEY_F, "g": KEY_G, "h": KEY_H, "i": KEY_I, "j": KEY_J,
        "k": KEY_K, "l": KEY_L, "m": KEY_M, "n": KEY_N, "o": KEY_O,
        "p": KEY_P, "q": KEY_Q, "r": KEY_R, "s": KEY_S, "t": KEY_T,
        "u": KEY_U, "v": KEY_V, "w": KEY_W, "x": KEY_X, "y": KEY_Y,
        "z": KEY_Z,
        "f1": KEY_F1, "f2": KEY_F2, "f3": KEY_F3, "f4": KEY_F4,
        "f5": KEY_F5, "f6": KEY_F6, "f7": KEY_F7, "f8": KEY_F8,
        "f9": KEY_F9, "f10": KEY_F10, "f11": KEY_F11, "f12": KEY_F12,
        "volumeup": KEY_VOLUMEUP, "volumedown": KEY_VOLUMEDOWN,
        "mute": KEY_MUTE, "playpause": KEY_PLAYPAUSE,
        "nexttrack": KEY_NEXTSONG, "prevtrack": KEY_PREVIOUSSONG,
    }

    def execute_action(action_id):
        if action_id.startswith("custom:"):
            keys = _parse_custom_combo(action_id, _KEY_NAME_TO_CODE)
            if keys:
                send_key_combo(keys)
            return
        if is_mouse_button_action(action_id):
            inject_mouse_down(action_id)
            inject_mouse_up(action_id)
            return
        action = ACTIONS.get(action_id)
        if not action or not action["keys"]:
            return
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
    def inject_mouse_down(action_id): pass
    def inject_mouse_up(action_id): pass
    def is_mouse_button_action(action_id): return False

    ACTIONS = {
        "switch_scroll_mode": {
            "label": "Switch Scroll Mode (Ratchet / Free Spin)",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "toggle_smart_shift": {
            "label": "Toggle SmartShift",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "cycle_dpi": {
            "label": "Cycle DPI Presets",
            "keys": [],               # handled by Engine, not key_simulator
            "category": "Scroll",
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }
