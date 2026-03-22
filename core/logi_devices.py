"""
Known Logitech device metadata used to scale Mouser beyond a single mouse model.

This module intentionally keeps the catalog lightweight: enough structure to
identify common HID++ mice, surface the right model name in the UI, and hang
future per-device capabilities off a single place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DEFAULT_GESTURE_CIDS = (0x00C3, 0x00D7)
DEFAULT_DPI_MIN = 200
DEFAULT_DPI_MAX = 8000
DEFAULT_BUTTON_LAYOUT = (
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


# Seeded from Mouser's existing support plus upstream identifiers seen in
# Solaar/logiops for the major MX-family mice we want to grow into first.
KNOWN_LOGI_DEVICES = (
    LogiDeviceSpec(
        key="mx_master_4",
        display_name="MX Master 4",
        product_ids=(0xB042,),
        aliases=(
            "Logitech MX Master 4",
            "MX Master 4 for Mac",
            "MX_Master_4",
            "MX Master 4 for Business",
        ),
        ui_layout="mx_master",
    ),
    LogiDeviceSpec(
        key="mx_master_3s",
        display_name="MX Master 3S",
        product_ids=(0xB034,),
        aliases=("Logitech MX Master 3S", "MX Master 3S for Mac"),
        ui_layout="mx_master",
    ),
    LogiDeviceSpec(
        key="mx_master_3",
        display_name="MX Master 3",
        product_ids=(0xB023,),
        aliases=("Wireless Mouse MX Master 3", "MX Master 3 for Mac", "MX Master 3 Mac"),
        ui_layout="mx_master",
    ),
    LogiDeviceSpec(
        key="mx_master_2s",
        display_name="MX Master 2S",
        product_ids=(0xB019,),
        aliases=("Wireless Mouse MX Master 2S",),
        ui_layout="mx_master",
        dpi_max=4000,
    ),
    LogiDeviceSpec(
        key="mx_master",
        display_name="MX Master",
        product_ids=(0xB012,),
        aliases=("Wireless Mouse MX Master",),
        ui_layout="mx_master",
        dpi_max=4000,
    ),
    LogiDeviceSpec(
        key="mx_vertical",
        display_name="MX Vertical",
        product_ids=(0xB020,),
        aliases=("MX Vertical Wireless Mouse", "MX Vertical Advanced Ergonomic Mouse"),
        ui_layout="mx_vertical",
        dpi_max=4000,
    ),
    LogiDeviceSpec(
        key="mx_anywhere_3s",
        display_name="MX Anywhere 3S",
        product_ids=(0xB037,),
        aliases=("MX Anywhere 3S for Mac",),
        ui_layout="mx_anywhere",
        dpi_max=8000,
    ),
    LogiDeviceSpec(
        key="mx_anywhere_3",
        display_name="MX Anywhere 3",
        product_ids=(0xB025,),
        aliases=("MX Anywhere 3 for Mac",),
        ui_layout="mx_anywhere",
        dpi_max=4000,
    ),
    LogiDeviceSpec(
        key="mx_anywhere_2s",
        display_name="MX Anywhere 2S",
        product_ids=(0xB01A,),
        aliases=("Wireless Mobile Mouse MX Anywhere 2S",),
        ui_layout="mx_anywhere",
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


def build_connected_device_info(
    *,
    product_id=None,
    product_name=None,
    transport=None,
    source=None,
    gesture_cids=None,
) -> ConnectedDeviceInfo:
    spec = resolve_device(product_id=product_id, product_name=product_name)
    pid = int(product_id) if product_id not in (None, "") else None
    if spec:
        return ConnectedDeviceInfo(
            key=spec.key,
            display_name=spec.display_name,
            product_id=pid,
            product_name=product_name or spec.display_name,
            transport=transport,
            source=source,
            ui_layout=spec.ui_layout,
            image_asset=spec.image_asset,
            supported_buttons=spec.supported_buttons,
            gesture_cids=tuple(gesture_cids or spec.gesture_cids),
            dpi_min=spec.dpi_min,
            dpi_max=spec.dpi_max,
        )

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
        gesture_cids=tuple(gesture_cids or DEFAULT_GESTURE_CIDS),
    )
