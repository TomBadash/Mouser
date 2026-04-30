"""Linux device permission checks for Logitech HID++ access."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import os
import sys


LOGITECH_VENDOR_ID = 0x046D
INSTALL_HELPER = "install-linux-permissions.sh"


@dataclass(frozen=True)
class LinuxHidrawNode:
    path: str
    product_id: int | None = None
    product_name: str = ""
    bus_id: int | None = None


@dataclass(frozen=True)
class LinuxPermissionReport:
    hidraw_nodes: tuple[LinuxHidrawNode, ...]
    blocked_hidraw_paths: tuple[str, ...]
    input_event_paths: tuple[str, ...]
    input_events_readable: bool
    uinput_path: str
    uinput_writable: bool
    uinput_exists: bool

    @property
    def has_issue(self) -> bool:
        return bool(
            self.blocked_hidraw_paths
            or (self.input_event_paths and not self.input_events_readable)
            or not self.uinput_exists
            or not self.uinput_writable
        )

    def issue_parts(self) -> list[str]:
        parts: list[str] = []
        if self.blocked_hidraw_paths:
            paths = ", ".join(self.blocked_hidraw_paths[:3])
            if len(self.blocked_hidraw_paths) > 3:
                paths += ", ..."
            parts.append(f"blocked hidraw access ({paths})")
        if self.input_event_paths and not self.input_events_readable:
            parts.append("no readable /dev/input/event* nodes")
        if not self.uinput_exists:
            parts.append("/dev/uinput is missing")
        elif not self.uinput_writable:
            parts.append("/dev/uinput is not writable")
        return parts


def _parse_hid_id(value: str):
    try:
        bus_hex, vid_hex, pid_hex = value.split(":", 2)
        return int(bus_hex, 16), int(vid_hex, 16), int(pid_hex, 16)
    except (AttributeError, ValueError):
        return None


def _read_uevent_props(path: str) -> dict[str, str]:
    props: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.strip().partition("=")
                if sep:
                    props[key] = value
    except OSError:
        pass
    return props


def logitech_hidraw_nodes(
    *,
    sysfs_base: str = "/sys/class/hidraw",
    dev_base: str = "/dev",
) -> tuple[LinuxHidrawNode, ...]:
    """Return Logitech hidraw nodes visible through sysfs."""

    try:
        entries = sorted(os.listdir(sysfs_base))
    except OSError:
        return ()

    nodes: list[LinuxHidrawNode] = []
    for entry in entries:
        if not entry.startswith("hidraw"):
            continue
        props = _read_uevent_props(
            os.path.join(sysfs_base, entry, "device", "uevent")
        )
        parsed = _parse_hid_id(props.get("HID_ID", ""))
        if not parsed:
            continue
        bus_id, vendor_id, product_id = parsed
        if vendor_id != LOGITECH_VENDOR_ID:
            continue
        nodes.append(
            LinuxHidrawNode(
                path=os.path.join(dev_base, entry),
                product_id=product_id,
                product_name=props.get("HID_NAME", ""),
                bus_id=bus_id,
            )
        )
    return tuple(nodes)


def linux_permission_report(
    *,
    sysfs_base: str = "/sys/class/hidraw",
    dev_base: str = "/dev",
    input_event_glob: str = "/dev/input/event*",
    uinput_path: str = "/dev/uinput",
) -> LinuxPermissionReport | None:
    """Inspect Linux device-node access when a Logitech hidraw node is visible."""

    if not sys.platform.startswith("linux"):
        return None

    hidraw_nodes = logitech_hidraw_nodes(sysfs_base=sysfs_base, dev_base=dev_base)
    if not hidraw_nodes:
        return LinuxPermissionReport((), (), (), True, uinput_path, True, True)

    blocked_hidraw_paths = tuple(
        node.path
        for node in hidraw_nodes
        if not os.access(node.path, os.R_OK | os.W_OK)
    )
    input_event_paths = tuple(sorted(glob.glob(input_event_glob)))
    input_events_readable = (
        not input_event_paths
        or any(os.access(path, os.R_OK) for path in input_event_paths)
    )
    uinput_exists = os.path.exists(uinput_path)
    uinput_writable = uinput_exists and os.access(uinput_path, os.W_OK)

    return LinuxPermissionReport(
        hidraw_nodes=hidraw_nodes,
        blocked_hidraw_paths=blocked_hidraw_paths,
        input_event_paths=input_event_paths,
        input_events_readable=input_events_readable,
        uinput_path=uinput_path,
        uinput_writable=uinput_writable,
        uinput_exists=uinput_exists,
    )


def linux_permission_status_message(report: LinuxPermissionReport | None) -> str:
    if report is None or not report.has_issue:
        return ""
    return (
        "Linux permissions may block Mouser. Run "
        f"{INSTALL_HELPER}, reconnect the mouse, then restart Mouser."
    )


def linux_permission_log_message(report: LinuxPermissionReport | None) -> str:
    if report is None or not report.has_issue:
        return ""
    return (
        "[LinuxPermissions] Device access issue: "
        + "; ".join(report.issue_parts())
        + f". Install the bundled udev rule with {INSTALL_HELPER}."
    )
