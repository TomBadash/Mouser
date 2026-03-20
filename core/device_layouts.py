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
            "normX": 0.35,
            "normY": 0.40,
            "labelSide": "right",
            "labelOffX": 100,
            "labelOffY": -160,
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
    **GENERIC_MOUSE_LAYOUT,
    "key": "mx_anywhere",
    "label": "MX Anywhere family",
    "note": (
        "MX Anywhere support is wired for device detection and HID++ probing. "
        "A dedicated overlay image and hotspot map still need to be added."
    ),
}

MX_VERTICAL_LAYOUT = {
    **GENERIC_MOUSE_LAYOUT,
    "key": "mx_vertical",
    "label": "MX Vertical family",
    "note": (
        "MX Vertical uses a different physical shape, so Mouser falls back to a "
        "generic device card until a dedicated overlay is added."
    ),
}


DEVICE_LAYOUTS = {
    "mx_master": MX_MASTER_LAYOUT,
    "mx_anywhere": MX_ANYWHERE_LAYOUT,
    "mx_vertical": MX_VERTICAL_LAYOUT,
    "generic_mouse": GENERIC_MOUSE_LAYOUT,
}


def get_device_layout(layout_key=None):
    layout = DEVICE_LAYOUTS.get(layout_key or "", DEVICE_LAYOUTS["generic_mouse"])
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
