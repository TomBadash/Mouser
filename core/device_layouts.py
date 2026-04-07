"""
Device-layout registry for Mouser's interactive mouse view.

The goal is to keep device-specific visual layout data out of QML so adding a
new Logitech family becomes a data change instead of a UI rewrite.
"""

from __future__ import annotations

from copy import deepcopy


MX_MASTER_LAYOUT = {
    "key": "mx_master",
    "label": "MX Master family",
    "image_asset": "mouse.png",
    "image_width": 460,
    "image_height": 360,
    "interactive": True,
    "manual_selectable": True,
    "note": "",
    "hotspots": [
        {
            "buttonKey": "middle",
            "label": "Middle button",
            "summaryType": "mapping",
            "normX": 0.33,
            "normY": 0.45,
            "labelSide": "left",
            "labelOffX": -80,
            "labelOffY": -100,
        },
        {
            "buttonKey": "gesture",
            "label": "Gesture button",
            "summaryType": "gesture",
            "normX": 0.70,
            "normY": 0.63,
            "labelSide": "left",
            "labelOffX": -200,
            "labelOffY": 60,
        },
        {
            "buttonKey": "xbutton2",
            "label": "Forward button",
            "summaryType": "mapping",
            "normX": 0.60,
            "normY": 0.48,
            "labelSide": "left",
            "labelOffX": -300,
            "labelOffY": 0,
        },
        {
            "buttonKey": "xbutton1",
            "label": "Back button",
            "summaryType": "mapping",
            "normX": 0.65,
            "normY": 0.40,
            "labelSide": "right",
            "labelOffX": 200,
            "labelOffY": 50,
        },
        {
            "buttonKey": "hscroll_left",
            "label": "Horizontal scroll",
            "summaryType": "hscroll",
            "isHScroll": True,
            "normX": 0.60,
            "normY": 0.375,
            "labelSide": "right",
            "labelOffX": 200,
            "labelOffY": -50,
        },
        {
            "buttonKey": "mode_shift",
            "label": "Mode shift button",
            "summaryType": "mapping",
            "normX": 0.43,
            "normY": 0.25,
            "labelSide": "right",
            "labelOffX": 150,
            "labelOffY": -80,
        },
    ],
}

GENERIC_MOUSE_LAYOUT = {
    "key": "generic_mouse",
    "label": "Generic mouse",
    "image_asset": "icons/mouse-simple.svg",
    "image_width": 220,
    "image_height": 220,
    "interactive": False,
    "manual_selectable": False,
    "note": (
        "This device is detected and the backend can still probe HID++ features, "
        "but Mouser does not have a dedicated visual overlay for it yet."
    ),
    "hotspots": [],
}

MX_ANYWHERE_LAYOUT = {
    "key": "mx_anywhere",
    "label": "MX Anywhere family",
    "image_asset": "mouse_mx_anywhere_3s.png",
    "image_width": 400,
    "image_height": 320,
    "interactive": True,
    "manual_selectable": True,
    "note": "",
    "hotspots": [
        {
            "buttonKey": "middle",
            "label": "Middle button",
            "summaryType": "mapping",
            "normX": 0.33,
            "normY": 0.46,
            "labelSide": "left",
            "labelOffX": -200,
            "labelOffY": -60,
        },
        {
            "buttonKey": "gesture",
            "label": "Gesture button",
            "summaryType": "gesture",
            "normX": 0.46,
            "normY": 0.28,
            "labelSide": "right",
            "labelOffX": 150,
            "labelOffY": -70,
        },
        {
            "buttonKey": "xbutton2",
            "label": "Forward button",
            "summaryType": "mapping",
            "normX": 0.69,
            "normY": 0.53,
            "labelSide": "right",
            "labelOffX": 150,
            "labelOffY": 30,
        },
        {
            "buttonKey": "xbutton1",
            "label": "Back button",
            "summaryType": "mapping",
            "normX": 0.75,
            "normY": 0.45,
            "labelSide": "right",
            "labelOffX": 200,
            "labelOffY": -45,
        },
    ],
}

MX_VERTICAL_LAYOUT = {
    "key": "mx_vertical",
    "label": "MX Vertical family",
    "image_asset": "mx_vertical.png",
    "image_width": 380,
    "image_height": 360,
    "interactive": True,
    "manual_selectable": True,
    "note": "",
    "hotspots": [
        {
            "buttonKey": "middle",
            "label": "Middle button",
            "summaryType": "mapping",
            "normX": 0.22,
            "normY": 0.38,
            "labelSide": "left",
            "labelOffX": -200,
            "labelOffY": -30,
        },
        {
            "buttonKey": "xbutton2",
            "label": "Forward button",
            "summaryType": "mapping",
            "normX": 0.55,
            "normY": 0.32,
            "labelSide": "right",
            "labelOffX": 160,
            "labelOffY": 80,
        },
        {
            "buttonKey": "xbutton1",
            "label": "Back button",
            "summaryType": "mapping",
            "normX": 0.63,
            "normY": 0.28,
            "labelSide": "right",
            "labelOffX": 200,
            "labelOffY": 30,
        },
        {
            "buttonKey": "dpi_switch",
            "label": "DPI switch",
            "summaryType": "mapping",
            "normX": 0.61,
            "normY": 0.12,
            "labelSide": "right",
            "labelOffX": 160,
            "labelOffY": -30,
        },
    ],
}


DEVICE_LAYOUTS = {
    "mx_master": MX_MASTER_LAYOUT,
    "mx_anywhere": MX_ANYWHERE_LAYOUT,
    "mx_vertical": MX_VERTICAL_LAYOUT,
    "generic_mouse": GENERIC_MOUSE_LAYOUT,
}

# Maps a device-specific key like "mx_master_3s" to its family layout key.
# Entries here let per-device keys fall back to the family layout until a
# dedicated layout is added.  Extend this dict as new devices are cataloged.
_FAMILY_FALLBACKS = {
    "mx_master_4": "mx_master",
    "mx_master_3s": "mx_master",
    "mx_master_3": "mx_master",
    "mx_master_2s": "mx_master",
    "mx_anywhere_3s": "mx_anywhere",
    "mx_anywhere_3": "mx_anywhere",
    "mx_anywhere_2s": "mx_anywhere",
}


def get_device_layout(layout_key=None):
    """Return the layout dict for *layout_key* with a fallback chain.

    1. Exact match in DEVICE_LAYOUTS  (device-specific, e.g. "mx_master_4")
    2. Family fallback via _FAMILY_FALLBACKS  (e.g. "mx_master_4" -> "mx_master")
    3. generic_mouse
    """
    key = layout_key or ""
    layout = DEVICE_LAYOUTS.get(key)
    if layout is None:
        family = _FAMILY_FALLBACKS.get(key, "")
        layout = DEVICE_LAYOUTS.get(family, DEVICE_LAYOUTS["generic_mouse"])
    return deepcopy(layout)


def get_manual_layout_choices():
    choices = [{"key": "", "label": "Auto-detect"}]
    for layout in DEVICE_LAYOUTS.values():
        if layout.get("manual_selectable"):
            choices.append({
                "key": layout["key"],
                "label": layout.get("label", layout["key"]),
            })
    return choices
