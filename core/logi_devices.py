"""
Known Logitech device metadata used to scale Mouser beyond a single mouse model.

This module intentionally keeps the catalog lightweight: enough structure to
identify common HID++ mice, surface the right model name in the UI, and hang
future per-device capabilities off a single place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.logi_device_catalog import LOGI_DEVICE_SPECS


DEFAULT_GESTURE_CIDS = (0x00C3, 0x00D7)
DEFAULT_DPI_MIN = 200
DEFAULT_DPI_MAX = 8000

# -- Per-family button layouts ------------------------------------------------
# Each tuple lists the config button keys the device physically supports.

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

# Conservative fallback for generic MX Anywhere-family overrides. Exact
# cataloged MX Anywhere devices provide their own button sets.
MX_ANYWHERE_BUTTONS = (
    "middle",
    "gesture",
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
    "xbutton1",
    "xbutton2",
)

# MX Vertical has no gesture button, no horizontal scroll, no mode-shift,
# but has a dedicated DPI switch button on top.
MX_VERTICAL_BUTTONS = (
    "middle",
    "xbutton1",
    "xbutton2",
    "dpi_switch",
)

# Safe minimum for any unrecognised Logitech mouse.
GENERIC_BUTTONS = (
    "middle",
    "xbutton1",
    "xbutton2",
)

# Backward-compat alias used by config.py and other modules.
DEFAULT_BUTTON_LAYOUT = MX_MASTER_BUTTONS

_GESTURE_BUTTON_KEYS = (
    "gesture",
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
)
_CID_GATED_BUTTONS = {
    "mode_shift": 0x00C4,
    "dpi_switch": 0x00FD,
}
_KEY_FLAG_DIVERTABLE = 0x0020
_KEY_FLAG_RAW_XY = 0x0100
_KEY_FLAG_FORCE_RAW_XY = 0x0200
_MAPPING_FLAG_RAW_XY_DIVERTED = 0x0010
_MAPPING_FLAG_FORCE_RAW_XY_DIVERTED = 0x0040


@dataclass(frozen=True)
class LogiDeviceSpec:
    key: str
    display_name: str
    product_ids: tuple[int, ...] = ()
    aliases: tuple[str, ...] = ()
    gesture_cids: tuple[int, ...] = DEFAULT_GESTURE_CIDS
    ui_layout: str = "mx_master"
    image_asset: str = "mouse.png"
    supported_buttons: tuple[str, ...] = DEFAULT_BUTTON_LAYOUT
    dpi_min: int = DEFAULT_DPI_MIN
    dpi_max: int = DEFAULT_DPI_MAX

    def matches(self, product_id=None, product_name=None) -> bool:
        if product_id is not None and int(product_id) in self.product_ids:
            return True
        normalized_name = _normalize_name(product_name)
        if not normalized_name:
            return False
        names = (self.display_name, self.key, *self.aliases)
        return any(_normalize_name(candidate) == normalized_name for candidate in names)


@dataclass(frozen=True)
class ConnectedDeviceInfo:
    key: str
    display_name: str
    product_id: int | None = None
    product_name: str | None = None
    transport: str | None = None
    source: str | None = None
    ui_layout: str = "generic_mouse"
    image_asset: str = "icons/mouse-simple.svg"
    supported_buttons: tuple[str, ...] = DEFAULT_BUTTON_LAYOUT
    gesture_cids: tuple[int, ...] = DEFAULT_GESTURE_CIDS
    dpi_min: int = DEFAULT_DPI_MIN
    dpi_max: int = DEFAULT_DPI_MAX


# Seeded from Mouser's own device catalog first, then extended with broader
# family support for devices that still use a shared layout.
KNOWN_LOGI_DEVICES = tuple(
    LogiDeviceSpec(**spec) for spec in LOGI_DEVICE_SPECS
) + (
    LogiDeviceSpec(
        key="mx_vertical",
        display_name="MX Vertical",
        product_ids=(0xB020,),
        aliases=("MX Vertical Wireless Mouse", "MX Vertical Advanced Ergonomic Mouse"),
        ui_layout="mx_vertical",
        image_asset="mx_vertical.png",
        supported_buttons=MX_VERTICAL_BUTTONS,
        dpi_max=4000,
    ),
)


def _normalize_name(value) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def iter_known_devices() -> Iterable[LogiDeviceSpec]:
    return KNOWN_LOGI_DEVICES


def clamp_dpi(value, device=None) -> int:
    dpi_min = getattr(device, "dpi_min", DEFAULT_DPI_MIN) or DEFAULT_DPI_MIN
    dpi_max = getattr(device, "dpi_max", DEFAULT_DPI_MAX) or DEFAULT_DPI_MAX
    dpi = int(value)
    return max(dpi_min, min(dpi_max, dpi))


def resolve_device(product_id=None, product_name=None) -> LogiDeviceSpec | None:
    for device in KNOWN_LOGI_DEVICES:
        if device.matches(product_id=product_id, product_name=product_name):
            return device
    return None


def _control_cid(control) -> int | None:
    if not isinstance(control, dict):
        return None
    cid = control.get("cid")
    if cid in (None, ""):
        return None
    try:
        return int(cid, 0) if isinstance(cid, str) else int(cid)
    except (TypeError, ValueError):
        return None


def _control_int(control, field) -> int | None:
    if not isinstance(control, dict):
        return None
    value = control.get(field)
    if value in (None, ""):
        return None
    try:
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None


def _control_by_cid(controls) -> dict[int, dict]:
    by_cid = {}
    for control in controls:
        cid = _control_cid(control)
        if cid is not None and isinstance(control, dict):
            by_cid[cid] = control
    return by_cid


def _control_is_divertable(control) -> bool:
    flags = _control_int(control, "flags")
    if flags is None:
        # Older tests and manually supplied dumps may only include CIDs.  Do not
        # narrow those more aggressively than the previous CID-only behavior.
        return True
    return bool(flags & _KEY_FLAG_DIVERTABLE)


def _control_has_raw_xy(control) -> bool:
    flags = _control_int(control, "flags")
    mapping_flags = _control_int(control, "mapping_flags")
    if flags is None and mapping_flags is None:
        return True
    flags = flags or 0
    mapping_flags = mapping_flags or 0
    return bool(
        flags & (_KEY_FLAG_RAW_XY | _KEY_FLAG_FORCE_RAW_XY)
        or mapping_flags
        & (_MAPPING_FLAG_RAW_XY_DIVERTED | _MAPPING_FLAG_FORCE_RAW_XY_DIVERTED)
    )


def derive_supported_buttons_from_reprog_controls(
    static_buttons: tuple[str, ...],
    controls,
    gesture_cids=None,
    active_gesture_cid=None,
    gesture_rawxy_enabled=None,
) -> tuple[str, ...]:
    """Narrow HID++-gated buttons using discovered REPROG_V4 controls.

    OS-level buttons and horizontal scroll remain catalog-driven because they
    are not always represented as divertable HID++ controls.
    """
    if not controls:
        return static_buttons

    controls_by_cid = _control_by_cid(controls)
    if not controls_by_cid:
        return static_buttons

    allowed = set(static_buttons)
    gesture_candidates = tuple(gesture_cids or DEFAULT_GESTURE_CIDS)
    active_cid = _control_cid({"cid": active_gesture_cid})
    if active_cid is None:
        active_cid = next(
            (
                cid
                for cid in gesture_candidates
                if cid in controls_by_cid and _control_is_divertable(controls_by_cid[cid])
            ),
            None,
        )
    gesture_control = controls_by_cid.get(active_cid)
    if not gesture_control or not _control_is_divertable(gesture_control):
        allowed.difference_update(_GESTURE_BUTTON_KEYS)
    elif not (
        (gesture_rawxy_enabled is not False)
        and _control_has_raw_xy(gesture_control)
    ):
        allowed.difference_update(
            ("gesture_left", "gesture_right", "gesture_up", "gesture_down")
        )

    for button_key, cid in _CID_GATED_BUTTONS.items():
        control = controls_by_cid.get(cid)
        if not control or not _control_is_divertable(control):
            allowed.discard(button_key)

    return tuple(button for button in static_buttons if button in allowed)


# Maps family layout keys to their button sets so the override picker can
# resolve buttons even when individual devices use per-device ui_layout keys.
_LAYOUT_BUTTONS = {
    "mx_master": MX_MASTER_BUTTONS,
    "mx_anywhere": MX_ANYWHERE_BUTTONS,
    "mx_vertical": MX_VERTICAL_BUTTONS,
    "generic_mouse": GENERIC_BUTTONS,
}


def get_buttons_for_layout(ui_layout_key: str) -> tuple[str, ...] | None:
    """Return supported_buttons for a layout key (family or per-device)."""
    if ui_layout_key in _LAYOUT_BUTTONS:
        return _LAYOUT_BUTTONS[ui_layout_key]
    for device in KNOWN_LOGI_DEVICES:
        if device.ui_layout == ui_layout_key:
            return device.supported_buttons
    return None


def build_connected_device_info(
    *,
    product_id=None,
    product_name=None,
    transport=None,
    source=None,
    gesture_cids=None,
    reprog_controls=None,
    active_gesture_cid=None,
    gesture_rawxy_enabled=None,
) -> ConnectedDeviceInfo:
    spec = resolve_device(product_id=product_id, product_name=product_name)
    pid = int(product_id) if product_id not in (None, "") else None
    if spec:
        resolved_gesture_cids = tuple(gesture_cids or spec.gesture_cids)
        return ConnectedDeviceInfo(
            key=spec.key,
            display_name=spec.display_name,
            product_id=pid,
            product_name=product_name or spec.display_name,
            transport=transport,
            source=source,
            ui_layout=spec.ui_layout,
            image_asset=spec.image_asset,
            supported_buttons=derive_supported_buttons_from_reprog_controls(
                spec.supported_buttons,
                reprog_controls,
                gesture_cids=resolved_gesture_cids,
                active_gesture_cid=active_gesture_cid,
                gesture_rawxy_enabled=gesture_rawxy_enabled,
            ),
            gesture_cids=resolved_gesture_cids,
            dpi_min=spec.dpi_min,
            dpi_max=spec.dpi_max,
        )

    # Fallback for unrecognized devices (e.g., USB Receiver PID 0xC52B which contains
    # multiple devices). Default to MX Master 3S layout, the most compatible option.
    display_name = product_name or (
        f"Logitech PID 0x{pid:04X}" if pid is not None else "Logitech mouse"
    )
    key = _normalize_name(display_name).replace(" ", "_") or "logitech_mouse"
    return ConnectedDeviceInfo(
        key=key,
        display_name=display_name,
        product_id=pid,
        product_name=product_name or display_name,
        transport=transport,
        source=source,
        ui_layout="mx_master_3s",
        image_asset="logitech-mice/mx_master_3s/mouse.png",
        supported_buttons=MX_MASTER_BUTTONS,
        gesture_cids=tuple(gesture_cids or DEFAULT_GESTURE_CIDS),
    )


def build_evdev_connected_device_info(
    *,
    product_id=None,
    product_name=None,
    transport="evdev",
    source="evdev",
    gesture_cids=None,
) -> ConnectedDeviceInfo:
    return build_connected_device_info(
        product_id=product_id,
        product_name=product_name,
        transport=transport,
        source=source,
        gesture_cids=gesture_cids,
    )
