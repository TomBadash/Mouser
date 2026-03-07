"""
Keyboard and mouse action simulator.
Supports Windows (via SendInput API) and macOS (via Quartz CGEvent).
Handles key combos (e.g. Alt+Tab), single keys, media keys,
and browser navigation keys.
"""

import sys
import time


# ══════════════════════════════════════════════════════════════════
# Windows implementation
# ══════════════════════════════════════════════════════════════════

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
        """Inject a mouse scroll event via SendInput."""
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
        """Press and release a combination of keys."""
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


# ══════════════════════════════════════════════════════════════════
# macOS implementation
# ══════════════════════════════════════════════════════════════════

elif sys.platform == "darwin":
    try:
        import Quartz
        _QUARTZ_OK = True
    except ImportError:
        _QUARTZ_OK = False

    # macOS virtual key codes (from Carbon HIToolbox/Events.h)
    # These are used as string identifiers in the ACTIONS table — the
    # actual CGKeyCode values are looked up at dispatch time.

    # We represent actions as semantic strings; the table below maps
    # them to (modifier_flags, key_code) tuples.
    # CGKeyCode values: https://github.com/phracker/MacOSX-SDKs/blob/master/MacOSX10.6.sdk/System/Library/Frameworks/Carbon.framework/Versions/A/Frameworks/HIToolbox.framework/Versions/A/Headers/Events.h

    # Quartz modifier flags
    _kCGEventFlagMaskCommand  = 0x00100000
    _kCGEventFlagMaskShift    = 0x00020000
    _kCGEventFlagMaskControl  = 0x00040000
    _kCGEventFlagMaskAlternate = 0x00080000  # Option/Alt

    # CGKeyCode constants (hardware-independent virtual key codes)
    _kVK_ANSI_A = 0x00
    _kVK_ANSI_C = 0x08
    _kVK_ANSI_D = 0x02
    _kVK_ANSI_F = 0x03
    _kVK_ANSI_N = 0x2D
    _kVK_ANSI_S = 0x01
    _kVK_ANSI_T = 0x11
    _kVK_ANSI_V = 0x09
    _kVK_ANSI_W = 0x0D
    _kVK_ANSI_X = 0x07
    _kVK_ANSI_Z = 0x06

    _kVK_Return  = 0x24
    _kVK_Tab     = 0x30
    _kVK_Space   = 0x31
    _kVK_Delete  = 0x33   # Backspace
    _kVK_Escape  = 0x35
    _kVK_Command = 0x37
    _kVK_Shift   = 0x38
    _kVK_Option  = 0x3A   # Alt
    _kVK_Control = 0x3B
    _kVK_LeftArrow  = 0x7B
    _kVK_RightArrow = 0x7C
    _kVK_DownArrow  = 0x7D
    _kVK_UpArrow    = 0x7E

    _kVK_F1  = 0x7A
    _kVK_F2  = 0x78
    _kVK_F3  = 0x63
    _kVK_F4  = 0x76
    _kVK_F5  = 0x60
    _kVK_F6  = 0x61
    _kVK_F7  = 0x62
    _kVK_F8  = 0x64
    _kVK_F9  = 0x65
    _kVK_F10 = 0x6D
    _kVK_F11 = 0x67
    _kVK_F12 = 0x6F

    # NX system-defined key codes for media/volume (use CGEventPost with NSSystemDefined)
    # We use CGEventCreateKeyboardEvent with the special F-key equivalents on macOS.
    # macOS maps media keys through NXEventHandle; the cleanest approach for Python is
    # to use the HID usage page via Quartz or osascript. We use NSEvent-based posting.
    _kVK_VolumeUp   = 0x48
    _kVK_VolumeDown = 0x49
    _kVK_Mute       = 0x4A

    # For media keys (play/pause, next, prev) macOS exposes them as NX events.
    # We use NSEvent to post them.
    NX_KEYTYPE_PLAY       = 16
    NX_KEYTYPE_NEXT       = 17
    NX_KEYTYPE_PREVIOUS   = 18
    NX_KEYTYPE_SOUND_UP   = 0
    NX_KEYTYPE_SOUND_DOWN = 1
    NX_KEYTYPE_MUTE       = 7

    # Scroll event flags (not used directly on macOS but kept for API compat)
    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def inject_scroll(flags, delta):
        """Inject a scroll event via CGEvent on macOS."""
        if not _QUARTZ_OK:
            return
        if flags == MOUSEEVENTF_WHEEL:
            event = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitPixel, 1, delta)
        else:
            # Horizontal scroll: axis 2
            event = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitPixel, 2, 0, delta)
        if event:
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, event)

    def _post_key(key_code, flags, key_down):
        """Post a single CGKeyboardEvent."""
        event = Quartz.CGEventCreateKeyboardEvent(None, key_code, key_down)
        if event and flags:
            Quartz.CGEventSetFlags(event, flags)
        if event:
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, event)

    def _post_media_key(nx_key_type, key_down):
        """Post a media key event via NSEvent on macOS."""
        try:
            import AppKit
            flags = 0xA00 if key_down else 0xB00
            event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                AppKit.NSSystemDefined,
                AppKit.NSPoint(0, 0),
                flags,
                0,
                0,
                None,
                8,   # subtype: NX_SUBTYPE_AUX_CONTROL_BUTTONS
                (nx_key_type << 16) | ((0xA if key_down else 0xB) << 8),
                -1,
            )
            cg_event = event.CGEvent()
            if cg_event:
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, cg_event)
        except Exception as e:
            print(f"[KeySim] media key error: {e}")

    def send_key_combo(keys, hold_ms=50):
        """
        Press and release a combination of keys.
        `keys` is a list of (flags, key_code) tuples as defined in ACTIONS.
        All modifiers are pressed before the main key.
        """
        if not _QUARTZ_OK or not keys:
            return
        # Each entry in `keys` is a (modifier_flags, CGKeyCode) tuple
        # We press all modifiers first, then the key, then release in reverse
        combined_flags = 0
        key_codes = []
        for flags, kc in keys:
            combined_flags |= flags
            key_codes.append(kc)

        # Press all keys (modifiers first, in order)
        for kc in key_codes:
            _post_key(kc, combined_flags, True)
            time.sleep(0.01)

        time.sleep(hold_ms / 1000.0)

        # Release in reverse order
        for kc in reversed(key_codes):
            _post_key(kc, 0, False)
            time.sleep(0.01)

    def send_key_press(key_code_tuple):
        send_key_combo([key_code_tuple])


# ══════════════════════════════════════════════════════════════════
# Unsupported platform stubs
# ══════════════════════════════════════════════════════════════════

else:
    MOUSEEVENTF_WHEEL  = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def inject_scroll(flags, delta):
        pass

    def send_key_combo(keys, hold_ms=50):
        pass

    def send_key_press(vk):
        pass


# ══════════════════════════════════════════════════════════════════
# ACTIONS table — platform-aware key definitions
# ══════════════════════════════════════════════════════════════════
#
# On Windows each entry's "keys" is a list of VK codes.
# On macOS each entry's "keys" is a list of (modifier_flags, CGKeyCode).
# The "mac_fn" key (optional) lets an action use a special function
# instead of key codes (e.g. media keys via NSEvent).

if sys.platform == "win32":
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

elif sys.platform == "darwin":
    # On macOS, keys are (modifier_flags, CGKeyCode) tuples.
    # Modifier-only combos: use (flags, main_key_code).
    # For actions that need a special function (media), use "mac_fn".
    _CMD  = _kCGEventFlagMaskCommand
    _OPT  = _kCGEventFlagMaskAlternate
    _CTRL = _kCGEventFlagMaskControl
    _SHF  = _kCGEventFlagMaskShift

    ACTIONS = {
        "alt_tab": {
            "label": "Mission Control / App Switcher (Cmd+Tab)",
            "keys": [(_CMD, _kVK_Tab)],
            "category": "Navigation",
        },
        "alt_shift_tab": {
            "label": "App Switcher Reverse (Cmd+Shift+Tab)",
            "keys": [(_CMD | _SHF, _kVK_Tab)],
            "category": "Navigation",
        },
        "browser_back": {
            "label": "Browser Back (Cmd+[)",
            # Cmd+[ = browser back in Safari/Chrome
            "keys": [(_CMD, 0x21)],   # 0x21 = kVK_ANSI_LeftBracket
            "category": "Browser",
        },
        "browser_forward": {
            "label": "Browser Forward (Cmd+])",
            "keys": [(_CMD, 0x1E)],   # 0x1E = kVK_ANSI_RightBracket
            "category": "Browser",
        },
        "copy": {
            "label": "Copy (Cmd+C)",
            "keys": [(_CMD, _kVK_ANSI_C)],
            "category": "Editing",
        },
        "paste": {
            "label": "Paste (Cmd+V)",
            "keys": [(_CMD, _kVK_ANSI_V)],
            "category": "Editing",
        },
        "cut": {
            "label": "Cut (Cmd+X)",
            "keys": [(_CMD, _kVK_ANSI_X)],
            "category": "Editing",
        },
        "undo": {
            "label": "Undo (Cmd+Z)",
            "keys": [(_CMD, _kVK_ANSI_Z)],
            "category": "Editing",
        },
        "select_all": {
            "label": "Select All (Cmd+A)",
            "keys": [(_CMD, _kVK_ANSI_A)],
            "category": "Editing",
        },
        "save": {
            "label": "Save (Cmd+S)",
            "keys": [(_CMD, _kVK_ANSI_S)],
            "category": "Editing",
        },
        "close_tab": {
            "label": "Close Tab (Cmd+W)",
            "keys": [(_CMD, _kVK_ANSI_W)],
            "category": "Browser",
        },
        "new_tab": {
            "label": "New Tab (Cmd+T)",
            "keys": [(_CMD, _kVK_ANSI_T)],
            "category": "Browser",
        },
        "find": {
            "label": "Find (Cmd+F)",
            "keys": [(_CMD, _kVK_ANSI_F)],
            "category": "Editing",
        },
        "win_d": {
            "label": "Show Desktop (Mission Control)",
            "keys": [(_CMD | _OPT, 0x64)],  # Not a standard shortcut; use F3 (Expose) instead
            "category": "Navigation",
            "mac_fn": lambda: _post_key(_kVK_F3, 0, True) or time.sleep(0.05) or _post_key(_kVK_F3, 0, False),
        },
        "task_view": {
            "label": "Mission Control (Ctrl+Up)",
            "keys": [(_CTRL, _kVK_UpArrow)],
            "category": "Navigation",
        },
        "volume_up": {
            "label": "Volume Up",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_SOUND_UP, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_SOUND_UP, False)),
        },
        "volume_down": {
            "label": "Volume Down",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_SOUND_DOWN, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_SOUND_DOWN, False)),
        },
        "volume_mute": {
            "label": "Volume Mute",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_MUTE, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_MUTE, False)),
        },
        "play_pause": {
            "label": "Play / Pause",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_PLAY, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_PLAY, False)),
        },
        "next_track": {
            "label": "Next Track",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_NEXT, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_NEXT, False)),
        },
        "prev_track": {
            "label": "Previous Track",
            "keys": [],
            "category": "Media",
            "mac_fn": lambda: (_post_media_key(NX_KEYTYPE_PREVIOUS, True),
                               time.sleep(0.05),
                               _post_media_key(NX_KEYTYPE_PREVIOUS, False)),
        },
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }

else:
    ACTIONS = {
        "none": {
            "label": "Do Nothing (Pass-through)",
            "keys": [],
            "category": "Other",
        },
    }


# ══════════════════════════════════════════════════════════════════
# Shared: execute_action
# ══════════════════════════════════════════════════════════════════

def execute_action(action_id):
    """Execute a named action by sending the associated key combo."""
    action = ACTIONS.get(action_id)
    if not action:
        return

    # macOS: prefer mac_fn if present
    if sys.platform == "darwin":
        mac_fn = action.get("mac_fn")
        if mac_fn:
            try:
                mac_fn()
            except Exception as e:
                print(f"[KeySim] mac_fn error for '{action_id}': {e}")
            return

    if action.get("keys"):
        send_key_combo(action["keys"])
