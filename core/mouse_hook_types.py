"""
Shared mouse hook types and helpers.
"""

import time


class MouseEvent:
    """Represents a captured mouse event."""

    XBUTTON1_DOWN = "xbutton1_down"
    XBUTTON1_UP = "xbutton1_up"
    XBUTTON2_DOWN = "xbutton2_down"
    XBUTTON2_UP = "xbutton2_up"
    MIDDLE_DOWN = "middle_down"
    MIDDLE_UP = "middle_up"
    GESTURE_DOWN = "gesture_down"
    GESTURE_UP = "gesture_up"
    GESTURE_CLICK = "gesture_click"
    GESTURE_SWIPE_LEFT = "gesture_swipe_left"
    GESTURE_SWIPE_RIGHT = "gesture_swipe_right"
    GESTURE_SWIPE_UP = "gesture_swipe_up"
    GESTURE_SWIPE_DOWN = "gesture_swipe_down"
    HSCROLL_LEFT = "hscroll_left"
    HSCROLL_RIGHT = "hscroll_right"
    MODE_SHIFT_DOWN = "mode_shift_down"
    MODE_SHIFT_UP = "mode_shift_up"
    DPI_SWITCH_DOWN = "dpi_switch_down"
    DPI_SWITCH_UP = "dpi_switch_up"

    def __init__(self, event_type, raw_data=None):
        self.event_type = event_type
        self.raw_data = raw_data
        self.timestamp = time.time()


def format_debug_details(raw_data):
    if raw_data is None:
        return ""
    if isinstance(raw_data, dict):
        parts = [f"{key}={value}" for key, value in raw_data.items()]
        return " " + " ".join(parts)
    return f" value={raw_data}"
