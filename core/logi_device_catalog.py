"""
Small Logitech device catalog entries.

These records are maintained device by device after the Mouser UI has been
checked locally. We keep the catalog small so supported devices stay easy to
review and maintain.
"""

from __future__ import annotations


MX_ANYWHERE_BUTTONS = (
    "middle",
    "gesture",
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
    "xbutton1",
    "xbutton2",
    "hscroll_left",
    "hscroll_right",
)

MX_ANYWHERE_SMARTSHIFT_BUTTONS = (
    *MX_ANYWHERE_BUTTONS,
    "mode_shift",
)

# Logitech Craft keyboard. The Crown dial exposes a rotate layer, a physical
# click, and a second rotate layer used while the crown is clicked/held.
CROWN_BUTTONS = (
    "crown_left",
    "crown_right",
    "crown_tap",
    "crown_touch",
    "crown_press_left",
    "crown_press_right",
)

# Standard Logitech keyboard top-row keys, exposed as remappable controls. These
# CIDs are shared across the Logitech keyboard line (Craft, MX Keys, …), so the
# table is device-agnostic: any keyboard exposes the subset of these keys its
# REPROG_CONTROLS_V4 inventory actually advertises (see keyboard_buttons_for_cids
# and the auto-classifier in logi_devices.classify_device_kind). Each is a
# divertable control; "cid" is the HID++ control id, "label" is the default
# printed function. Default mapping is "none" (the key keeps its native function
# until the user remaps it, at which point Mouser diverts just that control).
# Captured with tools/craft_probe.py --keys; see the craft-hidpp-protocol notes.
# Easy-Switch (host) and arrow controls are intentionally omitted so host
# switching and navigation stay native.
STANDARD_KEYBOARD_KEYS = (
    {"key": "kbd_brightness_down", "cid": 0x00C7, "label": "Brightness Down"},
    {"key": "kbd_brightness_up",   "cid": 0x00C8, "label": "Brightness Up"},
    {"key": "kbd_task_view",       "cid": 0x00E0, "label": "Task View"},
    {"key": "kbd_app_switch",      "cid": 0x00FF, "label": "App Switch / Dashboard"},
    {"key": "kbd_show_desktop",    "cid": 0x006E, "label": "Show Desktop"},
    {"key": "kbd_backlight_down",  "cid": 0x00E2, "label": "Backlight Down"},
    {"key": "kbd_backlight_up",    "cid": 0x00E3, "label": "Backlight Up"},
    {"key": "kbd_prev_track",      "cid": 0x00E4, "label": "Previous Track"},
    {"key": "kbd_play_pause",      "cid": 0x00E5, "label": "Play / Pause"},
    {"key": "kbd_next_track",      "cid": 0x00E6, "label": "Next Track"},
    {"key": "kbd_mute",            "cid": 0x00E7, "label": "Mute"},
    {"key": "kbd_volume_down",     "cid": 0x00E8, "label": "Volume Down"},
    {"key": "kbd_volume_up",       "cid": 0x00E9, "label": "Volume Up"},
    {"key": "kbd_calculator",      "cid": 0x000A, "label": "Calculator"},
    {"key": "kbd_screen_capture",  "cid": 0x00BF, "label": "Screen Capture"},
    {"key": "kbd_context_menu",    "cid": 0x00EA, "label": "Context Menu"},
    {"key": "kbd_screen_lock",     "cid": 0x006F, "label": "Screen Lock"},
)

KEYBOARD_KEY_BUTTONS = tuple(k["key"] for k in STANDARD_KEYBOARD_KEYS)

# button key → HID++ control id, for diverting only the keys the user remaps.
KEYBOARD_KEY_CIDS = {k["key"]: k["cid"] for k in STANDARD_KEYBOARD_KEYS}

# HID++ control id → button key (reverse lookup for divert/classification).
KEYBOARD_CID_TO_BUTTON = {k["cid"]: k["key"] for k in STANDARD_KEYBOARD_KEYS}

# button key → default printed label (UI fallback before localization).
KEYBOARD_KEY_LABELS = {k["key"]: k["label"] for k in STANDARD_KEYBOARD_KEYS}

# The Craft is the standard key set PLUS its unique Crown dial.
CRAFT_BUTTONS = CROWN_BUTTONS + KEYBOARD_KEY_BUTTONS


def keyboard_buttons_for_cids(cids) -> tuple[str, ...]:
    """Standard keyboard buttons whose HID++ control id the device advertises.

    Lets an unrecognized keyboard (no catalog entry) expose exactly the top-row
    keys it physically has, in canonical table order.
    """
    present = {int(c) for c in (cids or ()) if c is not None}
    return tuple(
        k["key"] for k in STANDARD_KEYBOARD_KEYS if k["cid"] in present
    )


def _hotspot(
    button_key: str,
    label: str,
    summary_type: str,
    norm_x: float,
    norm_y: float,
    *,
    label_side: str,
    label_off_x: int,
    label_off_y: int,
    is_hscroll: bool = False,
) -> dict[str, object]:
    return {
        "buttonKey": button_key,
        "label": label,
        "summaryType": summary_type,
        "normX": norm_x,
        "normY": norm_y,
        "labelSide": label_side,
        "labelOffX": label_off_x,
        "labelOffY": label_off_y,
        "isHScroll": is_hscroll,
    }


def _layout(
    key: str,
    label: str,
    image_asset: str,
    image_width: int,
    image_height: int,
    hotspots: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "image_asset": image_asset,
        "image_width": image_width,
        "image_height": image_height,
        "interactive": True,
        "manual_selectable": False,
        "note": "",
        "hotspots": hotspots,
    }


LOGI_DEVICE_SPECS = (
    {
        "key": "mx_master_4",
        "display_name": "MX Master 4",
        "product_ids": (0xB042, 0xB048),
        "aliases": (
            "Logitech MX Master 4",
            "Wireless Mouse MX Master 4",
            "MX Master 4 for Mac",
            "MX Master 4 for Business",
            "MX_Master_4",
        ),
        "ui_layout": "mx_master_4",
        "image_asset": "logitech-mice/mx_master_4/mouse.png",
    },
    {
        "key": "mx_master_3s",
        "display_name": "MX Master 3S",
        "product_ids": (0xB034, 0xB043),
        "aliases": (
            "Logitech MX Master 3S",
            "MX Master 3S for Mac",
            "MX Master 3S for Business",
        ),
        "ui_layout": "mx_master_3s",
        "image_asset": "logitech-mice/mx_master_3s/mouse.png",
    },
    {
        "key": "mx_master_3",
        "display_name": "MX Master 3",
        "product_ids": (0xB023, 0xB028),
        "aliases": (
            "Wireless Mouse MX Master 3",
            "MX Master 3 for Mac",
            "MX Master 3 Mac",
            "MX Master 3 for Business",
        ),
        "ui_layout": "mx_master_3",
        "image_asset": "logitech-mice/mx_master_3/mouse.png",
    },
    {
        "key": "mx_master_2s",
        "display_name": "MX Master 2S",
        "product_ids": (0xB019,),
        "aliases": (
            "Wireless Mouse MX Master 2S",
            "MX Master 2S",
        ),
        "ui_layout": "mx_master_2s",
        "image_asset": "logitech-mice/mx_master_2s/mouse.png",
        "dpi_max": 4000,
    },
    {
        "key": "mx_master",
        "display_name": "MX Master",
        "product_ids": (0xB012,),
        "aliases": (
            "Wireless Mouse MX Master",
            "MX Master",
        ),
        "ui_layout": "mx_master_classic",
        "image_asset": "logitech-mice/mx_master/mouse.png",
        "dpi_max": 4000,
    },
    {
        "key": "mx_anywhere_3s",
        "display_name": "MX Anywhere 3S",
        "product_ids": (0xB037,),
        "aliases": (
            "Logitech MX Anywhere 3S",
            "MX Anywhere 3S for Mac",
        ),
        "ui_layout": "mx_anywhere_3s",
        "image_asset": "logitech-mice/mx_anywhere_3s/mouse.png",
        "supported_buttons": MX_ANYWHERE_SMARTSHIFT_BUTTONS,
        "dpi_max": 8000,
    },
    {
        "key": "mx_anywhere_3",
        "display_name": "MX Anywhere 3",
        "product_ids": (0xB025, 0xB02D),
        "aliases": (
            "MX Anywhere 3 for Mac",
            "MX Anywhere 3 for Business",
        ),
        "ui_layout": "mx_anywhere_3",
        "image_asset": "logitech-mice/mx_anywhere_3/mouse.png",
        "supported_buttons": MX_ANYWHERE_SMARTSHIFT_BUTTONS,
        "dpi_max": 4000,
    },
    {
        "key": "mx_anywhere_2s",
        "display_name": "MX Anywhere 2S",
        "product_ids": (0xB01A,),
        "aliases": (
            "Wireless Mobile Mouse MX Anywhere 2S",
            "MX Anywhere 2S",
        ),
        "ui_layout": "mx_anywhere_2s",
        "image_asset": "logitech-mice/mx_anywhere_2s/mouse.png",
        "supported_buttons": MX_ANYWHERE_BUTTONS,
        "dpi_max": 4000,
    },
    {
        # Craft Advanced Keyboard. Over a Unifying receiver the USB product_id
        # is the shared receiver (0xC52B), so we match by the HID++ device name
        # instead. The Crown dial and top-row keys are driven over HID++
        # (feature 0x4600 + REPROG_CONTROLS_V4); no keyboard hook is involved.
        "key": "craft",
        "display_name": "Craft Advanced Keyboard",
        "product_ids": (),
        "aliases": (
            "Craft Advanced Keyboard",
            "Logitech Craft",
            "Craft",
        ),
        "ui_layout": "craft",
        "image_asset": "icons/keyboard-simple.svg",
        "supported_buttons": CRAFT_BUTTONS,
        "gesture_cids": (),
        "dpi_min": 0,
        "dpi_max": 0,
        "device_type": "keyboard",
    },
)


LOGI_DEVICE_LAYOUTS = {
    "craft": {
        "key": "craft",
        "label": "Craft Advanced Keyboard",
        "image_asset": "icons/keyboard-simple.svg",
        "image_width": 220,
        "image_height": 220,
        "interactive": False,
        "manual_selectable": False,
        "note": (
            "The Crown dial and top-row keys are remapped over HID++. Use the "
            "control list to assign actions; a dedicated keyboard diagram may "
            "come later."
        ),
        "hotspots": [],
    },
    "generic_keyboard": {
        "key": "generic_keyboard",
        "label": "Logitech Keyboard",
        "image_asset": "icons/keyboard-simple.svg",
        "image_width": 220,
        "image_height": 220,
        "interactive": False,
        "manual_selectable": False,
        "note": (
            "Auto-detected Logitech keyboard. The top-row keys it reports are "
            "remappable over HID++ — assign actions from the control list. "
            "Un-mapped keys keep their native function."
        ),
        "hotspots": [],
    },
    "mx_master_4": _layout(
        "mx_master_4",
        "MX Master 4",
        "logitech-mice/mx_master_4/mouse.png",
        256,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.755,
                0.19,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.473,
                0.60,
                label_side="right",
                label_off_x=160,
                label_off_y=20,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.425,
                0.47,
                label_side="right",
                label_off_x=160,
                label_off_y=-90,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.386,
                0.361,
                label_side="left",
                label_off_x=-260,
                label_off_y=20,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll left",
                "hscroll",
                0.565,
                0.564,
                label_side="right",
                label_off_x=160,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.805,
                0.395,
                label_side="right",
                label_off_x=160,
                label_off_y=60,
            ),
        ],
    ),
    "mx_master_3s": _layout(
        "mx_master_3s",
        "MX Master 3S",
        "logitech-mice/mx_master_3s/mouse.png",
        248,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.71,
                0.15,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.45,
                0.60,
                label_side="right",
                label_off_x=160,
                label_off_y=20,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.35,
                0.43,
                label_side="left",
                label_off_x=-260,
                label_off_y=-10,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.08,
                0.58,
                label_side="left",
                label_off_x=-260,
                label_off_y=40,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll left",
                "hscroll",
                0.55,
                0.515,
                label_side="right",
                label_off_x=160,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.81,
                0.34,
                label_side="right",
                label_off_x=160,
                label_off_y=60,
            ),
        ],
    ),
    "mx_master_3": _layout(
        "mx_master_3",
        "MX Master 3",
        "logitech-mice/mx_master_3/mouse.png",
        248,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.71,
                0.15,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.45,
                0.60,
                label_side="right",
                label_off_x=160,
                label_off_y=20,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.35,
                0.43,
                label_side="left",
                label_off_x=-260,
                label_off_y=-10,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.08,
                0.58,
                label_side="left",
                label_off_x=-260,
                label_off_y=40,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll left",
                "hscroll",
                0.55,
                0.515,
                label_side="right",
                label_off_x=160,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.81,
                0.34,
                label_side="right",
                label_off_x=160,
                label_off_y=60,
            ),
        ],
    ),
    "mx_master_2s": _layout(
        "mx_master_2s",
        "MX Master 2S",
        "logitech-mice/mx_master_2s/mouse.png",
        261,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.73,
                0.18,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.49,
                0.70,
                label_side="right",
                label_off_x=160,
                label_off_y=20,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.47,
                0.58,
                label_side="right",
                label_off_x=160,
                label_off_y=-30,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.13,
                0.69,
                label_side="left",
                label_off_x=-260,
                label_off_y=40,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll left",
                "hscroll",
                0.40,
                0.46,
                label_side="left",
                label_off_x=-240,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.79,
                0.36,
                label_side="right",
                label_off_x=160,
                label_off_y=0,
            ),
        ],
    ),
    "mx_master_classic": _layout(
        "mx_master_classic",
        "MX Master",
        "logitech-mice/mx_master/mouse.png",
        262,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.73,
                0.18,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.49,
                0.70,
                label_side="right",
                label_off_x=160,
                label_off_y=20,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.47,
                0.58,
                label_side="right",
                label_off_x=160,
                label_off_y=-30,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.13,
                0.69,
                label_side="left",
                label_off_x=-260,
                label_off_y=40,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll left",
                "hscroll",
                0.40,
                0.46,
                label_side="left",
                label_off_x=-240,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.79,
                0.36,
                label_side="right",
                label_off_x=160,
                label_off_y=0,
            ),
        ],
    ),
    "mx_anywhere_2s": _layout(
        "mx_anywhere_2s",
        "MX Anywhere 2S",
        "logitech-mice/mx_anywhere_2s/mouse.png",
        253,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.52,
                0.385,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.02,
                0.58,
                label_side="left",
                label_off_x=-240,
                label_off_y=10,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.02,
                0.44,
                label_side="left",
                label_off_x=-260,
                label_off_y=-10,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.38,
                0.195,
                label_side="left",
                label_off_x=-240,
                label_off_y=-70,
                is_hscroll=True,
            ),
        ],
    ),
    "mx_anywhere_3": _layout(
        "mx_anywhere_3",
        "MX Anywhere 3",
        "logitech-mice/mx_anywhere_3/mouse.png",
        239,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.72,
                0.17,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.28,
                0.61,
                label_side="left",
                label_off_x=-240,
                label_off_y=10,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.22,
                0.43,
                label_side="left",
                label_off_x=-260,
                label_off_y=-10,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.70,
                0.19,
                label_side="right",
                label_off_x=160,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.75,
                0.34,
                label_side="right",
                label_off_x=160,
                label_off_y=0,
            ),
        ],
    ),
    "mx_anywhere_3s": _layout(
        "mx_anywhere_3s",
        "MX Anywhere 3S",
        "logitech-mice/mx_anywhere_3s/mouse.png",
        239,
        400,
        [
            _hotspot(
                "middle",
                "Middle button",
                "mapping",
                0.71,
                0.16,
                label_side="right",
                label_off_x=120,
                label_off_y=-120,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.28,
                0.60,
                label_side="left",
                label_off_x=-240,
                label_off_y=10,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.22,
                0.41,
                label_side="left",
                label_off_x=-260,
                label_off_y=-10,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.37,
                0.24,
                label_side="left",
                label_off_x=-240,
                label_off_y=-70,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.75,
                0.34,
                label_side="right",
                label_off_x=160,
                label_off_y=0,
            ),
        ],
    ),
}
