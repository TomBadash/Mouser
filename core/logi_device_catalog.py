"""
Small Logitech device catalog entries.

These records are maintained device by device after the Mouser UI has been
checked locally. We keep the catalog small so supported devices stay easy to
review and maintain.
"""

from __future__ import annotations


MX_MASTER_BUTTONS = (
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
    "mode_shift",
)

# MX Master 4 layout: two gesture-capable controls, each with its own swipe
# set (config keys are tied to the physical button — see core/config.py):
#  - Sense Panel (CID 0x01A0): large top surface → config key "actions_ring",
#    labeled "Actions Ring". Primary gesture control; tap can activate the
#    Actions Ring, and (when tap = Do Nothing) it has its own swipe set
#    "actions_ring_left/right/up/down".
#  - Gesture button (CID 0x00C3): small thumb-area button → config key
#    "gesture", labeled "Gesture button". Its click uses the gesture_* family
#    and (when tap = Do Nothing) it has its own swipe set
#    "gesture_left/right/up/down" via a rawXY hand-off while held.
MX_MASTER_4_BUTTONS = (
    "middle",
    "actions_ring",
    "actions_ring_left",
    "actions_ring_right",
    "actions_ring_up",
    "actions_ring_down",
    "gesture",
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
    "xbutton1",
    "xbutton2",
    "hscroll_left",
    "hscroll_right",
    "mode_shift",
)

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
    # MX Keys' F4 exposes App Switch / Launchpad as 0x00E1 (verified on hardware)
    # instead of the 0x00FF the Craft uses. Keep both; each keyboard advertises
    # only the control id its firmware reports.
    {"key": "kbd_launchpad",       "cid": 0x00E1, "label": "Launchpad / App Switch"},
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

# MX Keys top-row controls (no crown). Every standard keyboard key the device
# actually advertises over REPROG_CONTROLS_V4 — verified on hardware with
# tools/craft_probe.py --keys (PID 0xB35B, Bluetooth). The MX Keys exposes all
# of STANDARD_KEYBOARD_KEYS except App Switch (0x00FF), which it does not report.
# Matches the keys placed on the mx_keys interactive layout; keep the two in sync.
MX_KEYS_BUTTONS = (
    "kbd_brightness_down",
    "kbd_brightness_up",
    "kbd_task_view",
    "kbd_launchpad",
    "kbd_show_desktop",
    "kbd_backlight_down",
    "kbd_backlight_up",
    "kbd_prev_track",
    "kbd_play_pause",
    "kbd_next_track",
    "kbd_mute",
    "kbd_volume_down",
    "kbd_volume_up",
    "kbd_calculator",
    "kbd_screen_capture",
    "kbd_context_menu",
    "kbd_screen_lock",
)


def keyboard_buttons_for_cids(cids) -> tuple[str, ...]:
    """Standard keyboard buttons whose HID++ control id the device advertises.

    Lets an unrecognized keyboard (no catalog entry) expose exactly the top-row
    keys it physically has, in canonical table order.
    """
    present = {int(c) for c in (cids or ()) if c is not None}
    return tuple(
        k["key"] for k in STANDARD_KEYBOARD_KEYS if k["cid"] in present
    )

# G502 family (G-series gaming mice). These run onboard profiles and do not
# expose REPROG_CONTROLS_V4 (0x1B04), so HID++ button diversion -- gesture,
# mode_shift, dpi_switch -- is unavailable. The buttons below are the ones the
# firmware emits as standard OS events in its default profile: middle click,
# back/forward side buttons, and wheel tilt left/right. The DPI up/down and
# sniper buttons are consumed onboard and never reach the OS. ADJUSTABLE_DPI
# (0x2201) is exposed, so the DPI slider works.
G502_BUTTONS = (
    "middle",
    "xbutton1",
    "xbutton2",
    "hscroll_left",
    "hscroll_right",
)

# M650 Signature family: no horizontal scroll, no mode-shift, no dedicated gesture button.
# Exposes a Virtual Gesture Button (CID 0x00D7) via REPROG_CONTROLS_V4 but no physical
# gesture key. Middle click, back, and forward side buttons are the configurable controls.
M650_BUTTONS = (
    "middle",
    "xbutton1",
    "xbutton2",
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
    *,
    manual_selectable: bool = False,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "image_asset": image_asset,
        "image_width": image_width,
        "image_height": image_height,
        "interactive": True,
        "manual_selectable": manual_selectable,
        "note": "",
        "hotspots": hotspots,
    }


# Default normalized size of a keyboard key-region hotspot (fraction of image).
_KBD_KEY_W = 0.030
_KBD_KEY_H = 0.075


def _key(
    button_key: str,
    norm_x: float,
    norm_y: float,
    *,
    norm_w: float = _KBD_KEY_W,
    norm_h: float = _KBD_KEY_H,
) -> dict[str, object]:
    """A clickable keyboard key region centered at (norm_x, norm_y).

    The printed label comes from KEYBOARD_KEY_LABELS so it stays in sync with
    STANDARD_KEYBOARD_KEYS; the QML overlay shows the assigned action on the key.
    """
    return {
        "buttonKey": button_key,
        "label": KEYBOARD_KEY_LABELS.get(button_key, button_key),
        "summaryType": "mapping",
        "normX": norm_x,
        "normY": norm_y,
        "normW": norm_w,
        "normH": norm_h,
        "kind": "key",
    }


def _crown(
    norm_x: float,
    norm_y: float,
    norm_r: float,
    buttons: tuple[str, ...] = CROWN_BUTTONS,
) -> dict[str, object]:
    """The Craft Crown dial: a clickable circle that exposes its sub-actions."""
    return {
        "normX": norm_x,
        "normY": norm_y,
        "normR": norm_r,
        "buttons": list(buttons),
    }


def _kbd_layout(
    key: str,
    label: str,
    image_asset: str,
    image_width: int,
    image_height: int,
    keys: list[dict[str, object]],
    *,
    crown: dict[str, object] | None = None,
    note: str = "",
    key_w: float | None = None,
    key_h: float | None = None,
) -> dict[str, object]:
    """Interactive keyboard layout: a device photo with clickable key regions
    (and, for the Craft, an interactive Crown dial). ``key_w``/``key_h`` set a
    uniform key-region size (fraction of the image) for every key."""
    for hotspot in keys:
        if key_w is not None:
            hotspot["normW"] = key_w
        if key_h is not None:
            hotspot["normH"] = key_h
    layout = {
        "key": key,
        "label": label,
        "image_asset": image_asset,
        "image_width": image_width,
        "image_height": image_height,
        "interactive": True,
        "manual_selectable": False,
        "note": note,
        "layout_kind": "keyboard",
        "hotspots": keys,
    }
    if crown is not None:
        layout["crown"] = crown
    return layout


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
        "supported_buttons": MX_MASTER_4_BUTTONS,
        "has_hires_wheel": True,
        "has_thumbwheel": True,
        "gesture_cids": (0x01A0, 0x00C3, 0x00D7),
        "thumb_button_cid": 0x00C3,
        "gesture_via_sense_panel": True,
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
        "has_hires_wheel": True,
        "has_thumbwheel": True,
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
        "has_hires_wheel": True,
        "has_thumbwheel": True,
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
        "has_hires_wheel": True,
        "has_thumbwheel": True,
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
        "has_hires_wheel": True,
        "has_thumbwheel": True,
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
        "image_asset": "logitech-keyboards/craft/keyboard.webp",
        "supported_buttons": CRAFT_BUTTONS,
        "gesture_cids": (),
        "dpi_min": 0,
        "dpi_max": 0,
        "device_type": "keyboard",
    },
    {
        # MX Keys (full-size). Like the Craft it pairs over a Unifying receiver
        # (shared PID 0xC52B), so match by HID++ name. No crown — only the
        # top-row media/brightness keys are remapped over HID++.
        "key": "mx_keys",
        "display_name": "MX Keys",
        "product_ids": (),
        "aliases": (
            "MX Keys Wireless Keyboard",
            "MX Keys",
            "Wireless Keyboard MX Keys",
        ),
        "ui_layout": "mx_keys",
        "image_asset": "logitech-keyboards/mx_keys/keyboard.webp",
        "supported_buttons": MX_KEYS_BUTTONS,
        "gesture_cids": (),
        "dpi_min": 0,
        "dpi_max": 0,
        "device_type": "keyboard",
    },
    # -- M650 Signature family ------------------------------------------------
    # Compact wireless mouse (middle, back, forward buttons). Connects via Logi
    # Bolt receiver or Bluetooth LE. HID++ reports device name "Signature M650".
    # Confirmed via live HID++ probe: REPROG_CONTROLS_V4 (slot 2 on Bolt receiver),
    # LOWRES_WHEEL, ADJUSTABLE_DPI (200–4000 DPI), UNIFIED_BATTERY.
    # Bluetooth LE product ID confirmed in issue #215 as 0xB02A; keep the
    # common HID/OS name variants as fallbacks because some platforms only
    # surface the product string.
    {
        "key": "m650",
        "display_name": "M650 Signature",
        "product_ids": (0xB02A,),
        "aliases": (
            "Signature M650",
            "Logi M650",
            "Logitech Signature M650",
            "M650",
            "M650 Signature",
            "Logitech M650 Signature",
            "M650 L",
            "M650 L Signature",
            "Signature M650 L",
            "M650 Signature for Business",
        ),
        "ui_layout": "m650",
        "image_asset": "icons/mouse-simple.svg",
        "supported_buttons": M650_BUTTONS,
        "dpi_min": 200,
        "dpi_max": 4000,
    },
    # -- G502 family ----------------------------------------------------------
    # Product IDs verified against Solaar's device descriptors. Wireless
    # variants list both the wired USB PID and the Lightspeed receiver WPID.
    {
        "key": "g502_hero",
        "display_name": "G502 HERO",
        "product_ids": (0xC08B,),
        "aliases": (
            "G502 HERO Gaming Mouse",
            "G502 SE HERO Gaming Mouse",
            "G502 HERO SE",
        ),
        "ui_layout": "g502",
        "image_asset": "icons/mouse-simple.svg",
        "supported_buttons": G502_BUTTONS,
        "dpi_min": 100,
        "dpi_max": 25600,
    },
    {
        "key": "g502_lightspeed",
        "display_name": "G502 LIGHTSPEED",
        "product_ids": (0xC08D, 0x407F),
        "aliases": (
            "G502 LIGHTSPEED Wireless Gaming Mouse",
            "G502 Lightspeed Gaming Mouse",
        ),
        "ui_layout": "g502",
        "image_asset": "icons/mouse-simple.svg",
        "supported_buttons": G502_BUTTONS,
        "dpi_min": 100,
        "dpi_max": 25600,
    },
    {
        "key": "g502_x",
        "display_name": "G502 X",
        "product_ids": (0xC099, 0xC098, 0xC095, 0x409F, 0x4099),
        "aliases": (
            "G502 X Gaming Mouse",
            "G502 X LIGHTSPEED",
            "G502 X PLUS",
        ),
        "ui_layout": "g502",
        "image_asset": "icons/mouse-simple.svg",
        "supported_buttons": G502_BUTTONS,
        "dpi_min": 100,
        "dpi_max": 25600,
    },
    {
        "key": "g502",
        "display_name": "G502",
        "product_ids": (0xC07D, 0xC332),
        "aliases": (
            "G502 Gaming Mouse",
            "Tunable FPS Gaming Mouse G502",
            "G502 Proteus Spectrum",
            "G502 Proteus Core",
        ),
        "ui_layout": "g502",
        "image_asset": "icons/mouse-simple.svg",
        "supported_buttons": G502_BUTTONS,
        "dpi_min": 200,
        "dpi_max": 12000,
    },
)


LOGI_DEVICE_LAYOUTS = {
    # Interactive Craft layout: device photo with clickable top-row keys and the
    # Crown dial. Coordinates are normalized (0-1) over the image; tune visually.
    "craft": _kbd_layout(
        "craft",
        "Craft Advanced Keyboard",
        "logitech-keyboards/craft/keyboard.webp",
        820,
        461,
        [
            _key("kbd_brightness_down", 0.1635, 0.382),
            _key("kbd_brightness_up",   0.2021, 0.382),
            _key("kbd_task_view",       0.2406, 0.382),
            _key("kbd_app_switch",      0.2792, 0.382),
            _key("kbd_show_desktop",    0.3178, 0.382),
            _key("kbd_backlight_down",  0.3564, 0.382),
            _key("kbd_backlight_up",    0.3950, 0.382),
            _key("kbd_prev_track",      0.4335, 0.382),
            _key("kbd_play_pause",      0.4721, 0.382),
            _key("kbd_next_track",      0.5107, 0.382),
            _key("kbd_mute",            0.5492, 0.382),
            _key("kbd_volume_down",     0.5878, 0.382),
            _key("kbd_volume_up",       0.6264, 0.382),
            _key("kbd_calculator",      0.7918, 0.382),
            _key("kbd_screen_capture",  0.8305, 0.382),
            _key("kbd_context_menu",    0.8691, 0.382),
            _key("kbd_screen_lock",     0.9078, 0.382),
        ],
        crown=_crown(0.0935, 0.2834, 0.030),
        note="Crown dial and top-row keys remapped over HID++.",
        key_w=0.034,
        key_h=0.050,
    ),
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
    # Interactive MX Keys layout: device photo with clickable top-row keys.
    "mx_keys": _kbd_layout(
        "mx_keys",
        "MX Keys",
        "logitech-keyboards/mx_keys/keyboard.webp",
        820,
        410,
        [
            _key("kbd_brightness_down", 0.1649, 0.328),
            _key("kbd_brightness_up",   0.2031, 0.328),
            _key("kbd_task_view",       0.2412, 0.328),
            _key("kbd_launchpad",       0.2794, 0.328),
            _key("kbd_show_desktop",    0.3176, 0.328),
            _key("kbd_backlight_down",  0.3558, 0.328),
            _key("kbd_backlight_up",    0.3939, 0.328),
            _key("kbd_prev_track",      0.4320, 0.328),
            _key("kbd_play_pause",      0.4701, 0.328),
            _key("kbd_next_track",      0.5083, 0.328),
            _key("kbd_mute",            0.5464, 0.328),
            _key("kbd_volume_down",     0.5846, 0.328),
            _key("kbd_volume_up",       0.6227, 0.328),
            _key("kbd_calculator",      0.7882, 0.332),
            _key("kbd_screen_capture",  0.8269, 0.332),
            _key("kbd_context_menu",    0.8655, 0.332),
            _key("kbd_screen_lock",     0.9042, 0.332),
        ],
        note="Top-row keys remapped over HID++.",
        key_w=0.034,
        key_h=0.048,
    ),
    # M650 Signature: no device art yet; shows generic silhouette with the
    # three-button layout. Interactive hotspot diagram can be added once
    # mouse artwork is sourced and product_ids are confirmed.
    "m650": {
        "key": "m650",
        "label": "M650 Signature",
        "image_asset": "icons/mouse-simple.svg",
        "image_width": 220,
        "image_height": 220,
        "interactive": False,
        "manual_selectable": True,
        "note": (
            "M650 Signature — middle click, back, and forward side buttons "
            "are all configurable. No gesture button or horizontal scroll."
        ),
        "hotspots": [],
    },
    # Shared placeholder for the G502 family: no device art has been
    # contributed yet, so the page shows the generic silhouette with the
    # G502 button list instead of an interactive hotspot diagram.
    "g502": {
        "key": "g502",
        "label": "G502 family",
        "image_asset": "icons/mouse-simple.svg",
        "image_width": 220,
        "image_height": 220,
        "interactive": False,
        # Manual-selectable so G502 owners whose device connects with an
        # unrecognized PID/name (e.g. via a receiver) can still pick the
        # right button set from the layout dropdown.
        "manual_selectable": True,
        "note": (
            "G502 buttons are remapped at the OS level. DPI up/down and the "
            "sniper button are handled by the mouse's onboard profile and "
            "cannot be remapped here yet."
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
                0.741,
                0.226,
                label_side="right",
                label_off_x=85,
                label_off_y=-16,
            ),
            _hotspot(
                "actions_ring",
                "Actions Ring",
                "gesture",
                0.289,
                0.698,
                label_side="left",
                label_off_x=-75,
                label_off_y=49,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.441,
                0.496,
                label_side="left",
                label_off_x=-143,
                label_off_y=-30,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.550,
                0.510,
                label_side="right",
                label_off_x=138,
                label_off_y=90,
                is_hscroll=True,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.477,
                0.590,
                label_side="left",
                label_off_x=-165,
                label_off_y=18,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.403,
                0.388,
                label_side="left",
                label_off_x=-62,
                label_off_y=-57,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.810,
                0.425,
                label_side="right",
                label_off_x=90,
                label_off_y=9,
            ),
        ],
        manual_selectable=True,
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
                0.7,
                0.1864,
                label_side="right",
                label_off_x=74,
                label_off_y=-44,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.4227,
                0.5522,
                label_side="left",
                label_off_x=-124,
                label_off_y=108,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.3663,
                0.4465,
                label_side="left",
                label_off_x=-63,
                label_off_y=-90,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.095,
                0.5978,
                label_side="left",
                label_off_x=-64,
                label_off_y=-31,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.4959,
                0.4639,
                label_side="right",
                label_off_x=157,
                label_off_y=66,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.7994,
                0.3741,
                label_side="right",
                label_off_x=78,
                label_off_y=-14,
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
                0.7,
                0.1864,
                label_side="right",
                label_off_x=74,
                label_off_y=-44,
            ),
            _hotspot(
                "xbutton1",
                "Back button",
                "mapping",
                0.4227,
                0.5522,
                label_side="left",
                label_off_x=-124,
                label_off_y=108,
            ),
            _hotspot(
                "xbutton2",
                "Forward button",
                "mapping",
                0.3663,
                0.4465,
                label_side="left",
                label_off_x=-63,
                label_off_y=-90,
            ),
            _hotspot(
                "gesture",
                "Gesture button",
                "gesture",
                0.095,
                0.5978,
                label_side="left",
                label_off_x=-64,
                label_off_y=-31,
            ),
            _hotspot(
                "hscroll_left",
                "Horizontal scroll",
                "hscroll",
                0.4959,
                0.4639,
                label_side="right",
                label_off_x=157,
                label_off_y=66,
                is_hscroll=True,
            ),
            _hotspot(
                "mode_shift",
                "Mode shift button",
                "mapping",
                0.7994,
                0.3741,
                label_side="right",
                label_off_x=78,
                label_off_y=-14,
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
                "Horizontal scroll",
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
                "Horizontal scroll",
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
