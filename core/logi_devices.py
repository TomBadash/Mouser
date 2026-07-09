"""
Known Logitech device metadata used to scale Mouser beyond a single mouse model.

This module intentionally keeps the catalog lightweight: enough structure to
identify common HID++ mice, surface the right model name in the UI, and hang
future per-device capabilities off a single place.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
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

# MX Master 4 adds an Actions Ring / Haptic Sense button on the thumb rest.
MX_MASTER_4_BUTTONS = MX_MASTER_BUTTONS + ("actions_ring",)

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
_HSCROLL_CIDS = (0x005B, 0x005D)
_KNOWN_UNSUPPORTED_CONTROLS = {
    0x00ED: "precision_mode",
}
_KEY_FLAG_DIVERTABLE = 0x0020
_KEY_FLAG_RAW_XY = 0x0100
_KEY_FLAG_FORCE_RAW_XY = 0x0200
_MAPPING_FLAG_RAW_XY_DIVERTED = 0x0010
_MAPPING_FLAG_FORCE_RAW_XY_DIVERTED = 0x0040

_FEATURE_NAMES = {
    0x0000: "IROOT",
    0x0005: "DEVICE_NAME",
    0x1000: "BATTERY_STATUS",
    0x1004: "UNIFIED_BATTERY",
    0x1B04: "REPROG_CONTROLS_V4",
    0x2110: "SMART_SHIFT",
    0x2111: "SMART_SHIFT_ENHANCED",
    0x2120: "HIRES_WHEEL",
    0x2121: "HIRES_WHEEL_ENHANCED",
    0x2130: "LOWRES_WHEEL",
    0x2150: "THUMB_WHEEL",
    0x2201: "ADJUSTABLE_DPI",
}
_WHEEL_FEATURES = (0x2110, 0x2111, 0x2120, 0x2121, 0x2130, 0x2150)


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
class HidppFeatureInfo:
    feature_id: int
    index: int | None = None
    version: int | None = None
    flags: int | None = None
    hidden: bool = False
    internal: bool = False
    name: str = ""

    def to_dict(self) -> dict[str, object]:
        result = {
            "feature_id": _format_cid(self.feature_id),
            "name": self.name or _FEATURE_NAMES.get(self.feature_id, "UNKNOWN"),
        }
        if self.index is not None:
            result["index"] = f"0x{self.index:02X}"
        if self.version is not None:
            result["version"] = self.version
        if self.flags is not None:
            result["flags"] = f"0x{self.flags:02X}"
        if self.hidden:
            result["hidden"] = True
        if self.internal:
            result["internal"] = True
        return result


@dataclass(frozen=True)
class ReprogControlDetail:
    index: int | None
    cid: int
    task: int | None = None
    flags: int | None = None
    pos: int | None = None
    group: int | None = None
    gmask: int | None = None
    mapped_to: int | None = None
    mapping_flags: int | None = None

    @property
    def divertable(self) -> bool:
        return bool((self.flags or 0) & _KEY_FLAG_DIVERTABLE)

    @property
    def raw_xy_support(self) -> bool:
        return bool((self.flags or 0) & _KEY_FLAG_RAW_XY)

    @property
    def force_raw_xy_support(self) -> bool:
        return bool((self.flags or 0) & _KEY_FLAG_FORCE_RAW_XY)

    @property
    def virtual(self) -> bool:
        return bool((self.flags or 0) & 0x0080)

    @property
    def diverted(self) -> bool:
        return bool((self.mapping_flags or 0) & 0x0001)

    @property
    def remappable(self) -> bool:
        return bool((self.flags or 0) & 0x0010)

    def to_dict(self) -> dict[str, object]:
        result = {
            "cid": _format_cid(self.cid),
            "divertable": self.divertable,
            "raw_xy_support": self.raw_xy_support,
            "force_raw_xy_support": self.force_raw_xy_support,
            "virtual": self.virtual,
            "diverted": self.diverted,
            "remappable": self.remappable,
        }
        optional_hex = {
            "task": self.task,
            "flags": self.flags,
            "mapped_to": self.mapped_to,
            "mapping_flags": self.mapping_flags,
        }
        if self.index is not None:
            result["index"] = self.index
        for key, value in optional_hex.items():
            if value is not None:
                width = 4 if key != "mapping_flags" else 4
                result[key] = f"0x{value:0{width}X}"
        if self.pos is not None:
            result["position"] = self.pos
        if self.group is not None:
            result["group"] = self.group
        if self.gmask is not None:
            result["group_mask"] = f"0x{self.gmask:02X}"
        return result


@dataclass(frozen=True)
class WheelFeatureInfo:
    feature_id: int
    index: int | None = None
    present: bool = False
    ratchet_state: str | None = None
    target_mode: str | None = None
    inversion: bool | None = None
    multiplier: int | None = None
    notifications: bool | None = None

    def to_dict(self) -> dict[str, object]:
        result = {
            "feature_id": _format_cid(self.feature_id),
            "name": _FEATURE_NAMES.get(self.feature_id, "UNKNOWN"),
            "present": self.present,
        }
        if self.index is not None:
            result["index"] = f"0x{self.index:02X}"
        for key in (
            "ratchet_state",
            "target_mode",
            "inversion",
            "multiplier",
            "notifications",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class DiagnosticBlocker:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class DeviceCapabilityInventory:
    """Runtime HID++ capabilities derived from the connected device dump."""

    device_identity: tuple[tuple[str, str], ...] = ()
    raw_features: tuple[HidppFeatureInfo, ...] = ()
    reprog_control_details: tuple[ReprogControlDetail, ...] = ()
    wheel_features: tuple[WheelFeatureInfo, ...] = ()
    diagnostics: tuple[DiagnosticBlocker, ...] = ()
    has_reprog_controls: bool = False
    control_cids: tuple[int, ...] = ()
    active_gesture_cid: int | None = None
    divertable_gesture_cids: tuple[int, ...] = ()
    gesture_click: bool = False
    gesture_directions: bool = False
    mode_shift: bool = False
    dpi_switch: bool = False
    hscroll_cids: tuple[int, ...] = ()
    smart_shift: bool = False
    adjustable_dpi: bool = False
    battery: bool = False
    known_unsupported_controls: tuple[tuple[int, str], ...] = ()

    def supported_buttons(self, static_buttons: tuple[str, ...]) -> tuple[str, ...]:
        if not self.has_reprog_controls:
            return static_buttons

        allowed = set(static_buttons)
        if not self.gesture_click:
            allowed.difference_update(_GESTURE_BUTTON_KEYS)
        elif not self.gesture_directions:
            allowed.difference_update(
                ("gesture_left", "gesture_right", "gesture_up", "gesture_down")
            )

        if not self.mode_shift:
            allowed.discard("mode_shift")
        if not self.dpi_switch:
            allowed.discard("dpi_switch")

        return tuple(button for button in static_buttons if button in allowed)

    def to_dict(self) -> dict[str, object]:
        return {
            "device_identity": dict(self.device_identity),
            "raw_features": [feature.to_dict() for feature in self.raw_features],
            "reprog_control_details": [
                control.to_dict() for control in self.reprog_control_details
            ],
            "wheel_features": [
                feature.to_dict() for feature in self.wheel_features
            ],
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
            "has_reprog_controls": self.has_reprog_controls,
            "control_cids": [_format_cid(cid) for cid in self.control_cids],
            "active_gesture_cid": (
                _format_cid(self.active_gesture_cid)
                if self.active_gesture_cid is not None
                else None
            ),
            "divertable_gesture_cids": [
                _format_cid(cid) for cid in self.divertable_gesture_cids
            ],
            "gesture_click": self.gesture_click,
            "gesture_directions": self.gesture_directions,
            "mode_shift": self.mode_shift,
            "dpi_switch": self.dpi_switch,
            "hscroll": bool(self.hscroll_cids),
            "hscroll_cids": [_format_cid(cid) for cid in self.hscroll_cids],
            "smart_shift": self.smart_shift,
            "adjustable_dpi": self.adjustable_dpi,
            "battery": self.battery,
            "known_unsupported_controls": [
                {"cid": _format_cid(cid), "name": name}
                for cid, name in self.known_unsupported_controls
            ],
        }


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
    capability_inventory: DeviceCapabilityInventory = DeviceCapabilityInventory()


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


def _format_cid(cid: int) -> str:
    return f"0x{cid:04X}"


def _normalize_identity(identity) -> tuple[tuple[str, str], ...]:
    if not identity:
        return ()
    if isinstance(identity, dict):
        items = identity.items()
    else:
        items = identity
    normalized = []
    for key, value in items:
        if value in (None, ""):
            continue
        if isinstance(value, int) and "id" in str(key):
            value = _format_cid(value)
        normalized.append((str(key), str(value)))
    return tuple(sorted(normalized))


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


def _parse_feature_id(value) -> int | None:
    if isinstance(value, int):
        return int(value)
    if not value:
        return None
    text = str(value)
    match = re.search(r"0x([0-9a-fA-F]{4})", text)
    if match:
        return int(match.group(1), 16)
    match = re.search(r"\b([0-9]{4,5})\b", text)
    if match:
        try:
            return int(match.group(1), 10)
        except ValueError:
            return None
    return None


def _parse_feature_index(value) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return _parse_feature_index(value.get("index"))
    if not value:
        return None
    match = re.search(r"index\s+0x([0-9a-fA-F]{1,2})", str(value))
    return int(match.group(1), 16) if match else None


def _feature_name(feature_id: int, fallback="") -> str:
    return fallback or _FEATURE_NAMES.get(feature_id, "UNKNOWN")


def _feature_entries(discovered_features) -> tuple[HidppFeatureInfo, ...]:
    if not discovered_features:
        return ()
    entries = []
    if isinstance(discovered_features, dict):
        iterable = discovered_features.items()
    else:
        iterable = ((value, None) for value in discovered_features)
    seen = set()
    for key, value in iterable:
        raw = (
            value if isinstance(value, dict)
            else key if isinstance(key, dict)
            else {}
        )
        feature_id = (
            _parse_feature_id(raw.get("feature_id"))
            if isinstance(raw, dict)
            else None
        )
        if feature_id is None:
            feature_id = _parse_feature_id(key)
        if feature_id is None:
            feature_id = _parse_feature_id(value)
        if feature_id is None or feature_id in seen:
            continue
        seen.add(feature_id)
        name = raw.get("name", "") if isinstance(raw, dict) else ""
        if not name and not isinstance(key, (int, dict)):
            name = str(key).split("(", 1)[0].strip()
        entries.append(HidppFeatureInfo(
            feature_id=feature_id,
            index=_parse_feature_index(raw if isinstance(raw, dict) else value),
            version=_control_int(raw, "version") if isinstance(raw, dict) else None,
            flags=_control_int(raw, "flags") if isinstance(raw, dict) else None,
            hidden=bool(raw.get("hidden", False)) if isinstance(raw, dict) else False,
            internal=bool(raw.get("internal", False)) if isinstance(raw, dict) else False,
            name=_feature_name(feature_id, name),
        ))
    return tuple(sorted(entries, key=lambda feature: feature.feature_id))


def _control_details(controls) -> tuple[ReprogControlDetail, ...]:
    details = []
    for control in controls or ():
        cid = _control_cid(control)
        if cid is None:
            continue
        pos = _control_int(control, "pos")
        if pos is None:
            pos = _control_int(control, "position")
        gmask = _control_int(control, "gmask")
        if gmask is None:
            gmask = _control_int(control, "group_mask")
        details.append(ReprogControlDetail(
            index=_control_int(control, "index"),
            cid=cid,
            task=_control_int(control, "task"),
            flags=_control_int(control, "flags"),
            pos=pos,
            group=_control_int(control, "group"),
            gmask=gmask,
            mapped_to=_control_int(control, "mapped_to"),
            mapping_flags=_control_int(control, "mapping_flags"),
        ))
    return tuple(details)


def _wheel_feature_inventory(features) -> tuple[WheelFeatureInfo, ...]:
    by_id = {feature.feature_id: feature for feature in features}
    return tuple(
        WheelFeatureInfo(
            feature_id=feature_id,
            index=by_id.get(feature_id).index if feature_id in by_id else None,
            present=feature_id in by_id,
        )
        for feature_id in _WHEEL_FEATURES
    )


def _diagnostics(diagnostics, *, controls_by_cid, features) -> tuple[DiagnosticBlocker, ...]:
    result = []
    for item in diagnostics or ():
        if isinstance(item, DiagnosticBlocker):
            result.append(item)
        elif isinstance(item, dict):
            result.append(DiagnosticBlocker(
                code=str(item.get("code", "unknown")),
                severity=str(item.get("severity", "info")),
                message=str(item.get("message", "")),
            ))
        else:
            result.append(DiagnosticBlocker(
                code="note",
                severity="info",
                message=str(item),
            ))
    feature_ids = {feature.feature_id for feature in features}
    if 0x1B04 not in feature_ids and not controls_by_cid:
        result.append(DiagnosticBlocker(
            code="reprog_controls_unavailable",
            severity="info",
            message="REPROG_CONTROLS_V4 was not discovered; runtime remap evidence is limited.",
        ))
    return tuple(result)


def _control_by_cid(controls) -> dict[int, dict]:
    by_cid = {}
    for control in controls:
        cid = _control_cid(control)
        if cid is not None and isinstance(control, dict):
            by_cid[cid] = control
    return by_cid


def _feature_tokens(discovered_features) -> tuple[str, ...]:
    if not discovered_features:
        return ()
    entries = _feature_entries(discovered_features)
    if entries:
        return tuple(
            token
            for feature in entries
            for token in (
                _format_cid(feature.feature_id).lower(),
                feature.name.lower(),
            )
        )
    if isinstance(discovered_features, dict):
        values = discovered_features.keys()
    else:
        values = discovered_features
    tokens = []
    for value in values:
        if isinstance(value, int):
            tokens.append(_format_cid(value).lower())
        else:
            tokens.append(str(value).strip().lower())
    return tuple(tokens)


def _has_feature(tokens: tuple[str, ...], *needles: str) -> bool:
    return any(
        needle.lower() in token
        for token in tokens
        for needle in needles
    )


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


def build_device_capability_inventory(
    controls=None,
    *,
    device_identity=None,
    gesture_cids=None,
    active_gesture_cid=None,
    gesture_rawxy_enabled=None,
    discovered_features=None,
    diagnostics=None,
) -> DeviceCapabilityInventory:
    controls_by_cid = _control_by_cid(controls or ())
    feature_entries = _feature_entries(discovered_features)
    feature_tokens = _feature_tokens(discovered_features)
    gesture_candidates = tuple(gesture_cids or DEFAULT_GESTURE_CIDS)
    divertable_gesture_cids = tuple(
        cid
        for cid in gesture_candidates
        if cid in controls_by_cid and _control_is_divertable(controls_by_cid[cid])
    )

    active_cid = _control_cid({"cid": active_gesture_cid})
    if active_cid is None or active_cid not in controls_by_cid:
        active_cid = divertable_gesture_cids[0] if divertable_gesture_cids else None

    gesture_control = controls_by_cid.get(active_cid)
    gesture_click = bool(gesture_control and _control_is_divertable(gesture_control))
    gesture_directions = bool(
        gesture_click
        and gesture_rawxy_enabled is not False
        and _control_has_raw_xy(gesture_control)
    )

    mode_shift_control = controls_by_cid.get(_CID_GATED_BUTTONS["mode_shift"])
    dpi_switch_control = controls_by_cid.get(_CID_GATED_BUTTONS["dpi_switch"])
    known_unsupported = tuple(
        (cid, _KNOWN_UNSUPPORTED_CONTROLS[cid])
        for cid in sorted(_KNOWN_UNSUPPORTED_CONTROLS)
        if cid in controls_by_cid
    )

    return DeviceCapabilityInventory(
        device_identity=_normalize_identity(device_identity),
        raw_features=feature_entries,
        reprog_control_details=_control_details(controls or ()),
        wheel_features=_wheel_feature_inventory(feature_entries),
        diagnostics=_diagnostics(
            diagnostics,
            controls_by_cid=controls_by_cid,
            features=feature_entries,
        ),
        has_reprog_controls=bool(controls_by_cid),
        control_cids=tuple(sorted(controls_by_cid)),
        active_gesture_cid=active_cid,
        divertable_gesture_cids=divertable_gesture_cids,
        gesture_click=gesture_click,
        gesture_directions=gesture_directions,
        mode_shift=bool(
            mode_shift_control and _control_is_divertable(mode_shift_control)
        ),
        dpi_switch=bool(
            dpi_switch_control and _control_is_divertable(dpi_switch_control)
        ),
        hscroll_cids=tuple(
            cid
            for cid in _HSCROLL_CIDS
            if cid in controls_by_cid and _control_is_divertable(controls_by_cid[cid])
        ),
        smart_shift=_has_feature(
            feature_tokens, "smart_shift", "0x2110", "0x2111"
        ),
        adjustable_dpi=_has_feature(feature_tokens, "adjustable_dpi", "0x2201"),
        battery=_has_feature(feature_tokens, "battery", "0x1000", "0x1004"),
        known_unsupported_controls=known_unsupported,
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
    inventory = build_device_capability_inventory(
        controls,
        gesture_cids=gesture_cids,
        active_gesture_cid=active_gesture_cid,
        gesture_rawxy_enabled=gesture_rawxy_enabled,
    )
    return inventory.supported_buttons(static_buttons)


# Maps family layout keys to their button sets so the override picker can
# resolve buttons even when individual devices use per-device ui_layout keys.
_LAYOUT_BUTTONS = {
    "mx_master": MX_MASTER_BUTTONS,
    "mx_master_4": MX_MASTER_4_BUTTONS,
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
    discovered_features=None,
    device_identity=None,
    diagnostics=None,
) -> ConnectedDeviceInfo:
    spec = resolve_device(product_id=product_id, product_name=product_name)
    pid = int(product_id) if product_id not in (None, "") else None
    identity = {
        "product_id": pid,
        "product_name": product_name,
        "transport": transport,
        "source": source,
        **dict(device_identity or {}),
    }
    inventory = build_device_capability_inventory(
        reprog_controls,
        device_identity=identity,
        gesture_cids=gesture_cids or getattr(spec, "gesture_cids", None),
        active_gesture_cid=active_gesture_cid,
        gesture_rawxy_enabled=gesture_rawxy_enabled,
        discovered_features=discovered_features,
        diagnostics=diagnostics,
    )
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
            supported_buttons=inventory.supported_buttons(spec.supported_buttons),
            gesture_cids=resolved_gesture_cids,
            dpi_min=spec.dpi_min,
            dpi_max=spec.dpi_max,
            capability_inventory=inventory,
        )

    # Fallback for unrecognized devices (e.g., USB Receiver PID 0xC52B which
    # contains multiple devices). Use the generic layout rather than borrowing
    # an MX-family UI with controls the device may not physically have.
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
        ui_layout="generic_mouse",
        image_asset="icons/mouse-simple.svg",
        supported_buttons=GENERIC_BUTTONS,
        gesture_cids=tuple(gesture_cids or DEFAULT_GESTURE_CIDS),
        capability_inventory=inventory,
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
