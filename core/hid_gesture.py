"""
hid_gesture.py — Detect Logitech HID++ gesture controls and device features.

Many Logitech mice expose their gesture button and DPI/battery controls only
through the HID++ vendor channel instead of standard OS mouse events. This
module opens the Logitech HID interface, discovers REPROG_CONTROLS_V4 and
related features, diverts the best gesture candidate it can find, and reports
press/release or RawXY movement back to Mouser.

Requires:  pip install hidapi
Falls back gracefully if the package or device are unavailable.
"""

import os
import re
import stat
import sys
import queue
import threading
import time

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    build_connected_device_info,
    clamp_dpi,
    classify_device_kind,
    resolve_device,
)

_HID_MODULE_NAME = None
try:
    # The PyPI hidapi Linux wheels expose `hid` as the libusb backend and
    # `hidraw` as the hidraw backend. Bluetooth HID devices only work through
    # hidraw, so prefer it on Linux and fall back to `hid` for source builds
    # where `hid` itself was compiled against hidraw.
    if sys.platform.startswith("linux"):
        try:
            import hidraw as _hid
            _HID_MODULE_NAME = "hidraw"
        except ImportError:
            import hid as _hid
            _HID_MODULE_NAME = "hid"
    else:
        import hid as _hid
        _HID_MODULE_NAME = "hid"
    HIDAPI_OK = True
    HIDAPI_IMPORT_ERROR = None
    # On macOS, allow non-exclusive HID access so the mouse keeps working
    if sys.platform == "darwin" and hasattr(_hid, "hid_darwin_set_open_exclusive"):
        _hid.hid_darwin_set_open_exclusive(0)
except Exception as exc:
    HIDAPI_OK = False
    HIDAPI_IMPORT_ERROR = exc

# Support both hidapi/hidraw-style modules (device) and "pip install hid" (Device).
_HID_API_STYLE = None
if HIDAPI_OK:
    if hasattr(_hid, 'device'):
        _HID_API_STYLE = "hidapi"
    elif hasattr(_hid, 'Device'):
        _HID_API_STYLE = "hid"


_LOG_ONCE_KEYS = set()


def _log_once(key, message):
    if key in _LOG_ONCE_KEYS:
        return
    _LOG_ONCE_KEYS.add(key)
    print(message)


def _device_path_display(path):
    if isinstance(path, memoryview):
        path = bytes(path)
    if isinstance(path, bytes):
        return path.decode("utf-8", errors="replace")
    return str(path or "")


def _owner_name(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def _group_name(gid):
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except Exception:
        return str(gid)


def _format_linux_device_access(path):
    if isinstance(path, memoryview):
        path = bytes(path)
    display = _device_path_display(path)
    if not path:
        return "path=-"
    try:
        st = os.stat(path)
    except OSError as exc:
        return f"path={display} stat_error={exc}"

    mode = stat.S_IMODE(st.st_mode)
    can_read = os.access(path, os.R_OK)
    can_write = os.access(path, os.W_OK)
    can_rw = os.access(path, os.R_OK | os.W_OK)
    return (
        f"path={display} mode={mode:04o} "
        f"owner={_owner_name(st.st_uid)}({st.st_uid}) "
        f"group={_group_name(st.st_gid)}({st.st_gid}) "
        f"access=read:{can_read} write:{can_write} read_write:{can_rw}"
    )


class _HidDeviceCompat:
    """Wraps the ``hid`` package Device to match the ``hidapi`` interface."""

    def __init__(self, path):
        if isinstance(path, memoryview):
            path = bytes(path)
        elif isinstance(path, str):
            path = path.encode()
        self._dev = _hid.Device(path=path)

    def set_nonblocking(self, enabled):
        self._dev.nonblocking = bool(enabled)

    def write(self, data):
        return self._dev.write(bytes(data))

    def read(self, size, timeout_ms=0):
        data = self._dev.read(size, timeout=timeout_ms if timeout_ms else None)
        return data if data else None

    def close(self):
        self._dev.close()

_MAC_NATIVE_OK = False
if sys.platform == "darwin":
    try:
        import ctypes
        from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_uint8, c_void_p, create_string_buffer

        _cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        _iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")

        _cf.CFNumberCreate.argtypes = [c_void_p, c_int, c_void_p]
        _cf.CFNumberCreate.restype = c_void_p
        _cf.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
        _cf.CFNumberGetValue.restype = c_int
        _cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_int]
        _cf.CFStringCreateWithCString.restype = c_void_p
        _cf.CFStringGetCString.argtypes = [c_void_p, c_void_p, c_long, c_int]
        _cf.CFStringGetCString.restype = c_int
        _cf.CFDictionaryCreate.argtypes = [
            c_void_p, POINTER(c_void_p), POINTER(c_void_p), c_long, c_void_p, c_void_p,
        ]
        _cf.CFDictionaryCreate.restype = c_void_p
        _cf.CFSetGetCount.argtypes = [c_void_p]
        _cf.CFSetGetCount.restype = c_long
        _cf.CFSetGetValues.argtypes = [c_void_p, POINTER(c_void_p)]
        _cf.CFRelease.argtypes = [c_void_p]
        _cf.CFRetain.argtypes = [c_void_p]
        _cf.CFRetain.restype = c_void_p
        _cf.CFRunLoopGetCurrent.argtypes = []
        _cf.CFRunLoopGetCurrent.restype = c_void_p
        _cf.CFRunLoopRunInMode.argtypes = [c_void_p, ctypes.c_double, ctypes.c_bool]
        _cf.CFRunLoopRunInMode.restype = c_int

        _iokit.IOHIDManagerCreate.argtypes = [c_void_p, c_int]
        _iokit.IOHIDManagerCreate.restype = c_void_p
        _iokit.IOHIDManagerSetDeviceMatching.argtypes = [c_void_p, c_void_p]
        _iokit.IOHIDManagerOpen.argtypes = [c_void_p, c_int]
        _iokit.IOHIDManagerOpen.restype = c_int
        _iokit.IOHIDManagerCopyDevices.argtypes = [c_void_p]
        _iokit.IOHIDManagerCopyDevices.restype = c_void_p

        _iokit.IOHIDDeviceOpen.argtypes = [c_void_p, c_int]
        _iokit.IOHIDDeviceOpen.restype = c_int
        _iokit.IOHIDDeviceClose.argtypes = [c_void_p, c_int]
        _iokit.IOHIDDeviceClose.restype = c_int
        _iokit.IOHIDDeviceGetProperty.argtypes = [c_void_p, c_void_p]
        _iokit.IOHIDDeviceGetProperty.restype = c_void_p
        _iokit.IOHIDDeviceScheduleWithRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        _iokit.IOHIDDeviceUnscheduleFromRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        _iokit.IOHIDDeviceSetReport.argtypes = [c_void_p, c_int, c_long, POINTER(c_uint8), c_long]
        _iokit.IOHIDDeviceSetReport.restype = c_int
        _IOHID_REPORT_CALLBACK = ctypes.CFUNCTYPE(
            None,
            c_void_p,
            c_int,
            c_void_p,
            c_int,
            ctypes.c_uint32,
            POINTER(c_uint8),
            c_long,
        )
        _iokit.IOHIDDeviceRegisterInputReportCallback.argtypes = [
            c_void_p,
            POINTER(c_uint8),
            c_long,
            _IOHID_REPORT_CALLBACK,
            c_void_p,
        ]
        _iokit.IOHIDDeviceGetReport.argtypes = [c_void_p, c_int, c_long, POINTER(c_uint8), POINTER(c_long)]
        _iokit.IOHIDDeviceGetReport.restype = c_int

        _K_CF_NUMBER_SINT32 = 3
        _K_CF_STRING_ENCODING_UTF8 = 0x08000100
        _K_IOHID_REPORT_TYPE_INPUT = 0
        _K_IOHID_REPORT_TYPE_OUTPUT = 1
        _K_CF_RUN_LOOP_DEFAULT_MODE = c_void_p.in_dll(_cf, "kCFRunLoopDefaultMode")

        _MAC_NATIVE_OK = True
    except Exception as exc:
        print(f"[HidGesture] macOS native HID unavailable: {exc}")


def _default_backend_preference(platform_name=None):
    platform_name = sys.platform if platform_name is None else platform_name
    return "auto"


_BACKEND_PREFERENCE = _default_backend_preference()


def set_backend_preference(preference):
    normalized = (preference or "auto").strip().lower()
    if normalized not in {"auto", "hidapi", "iokit"}:
        raise ValueError("hid backend must be one of: auto, hidapi, iokit")
    if normalized == "hidapi" and not HIDAPI_OK:
        raise ValueError("hidapi backend requested but hidapi is not available")
    if normalized == "iokit":
        if sys.platform != "darwin":
            raise ValueError("iokit backend is only available on macOS")
        if not _MAC_NATIVE_OK:
            raise ValueError("iokit backend requested but native macOS HID is unavailable")

    global _BACKEND_PREFERENCE
    _BACKEND_PREFERENCE = normalized
    print(f"[HidGesture] Backend preference set to {normalized}")


def get_backend_preference():
    return _BACKEND_PREFERENCE


if _MAC_NATIVE_OK:
    class _MacNativeHidDevice:
        """Minimal IOHIDDevice wrapper for Logitech BLE HID++ on macOS."""

        def __init__(self, product_id, usage_page=0, usage=0, transport=None):
            self._product_id = int(product_id)
            self._usage_page = int(usage_page or 0)
            self._usage = int(usage or 0)
            self._transport = transport or None
            self._manager = None
            self._matching = None
            self._device = None
            self._matching_refs = []
            self._run_loop = None
            self._input_buffer = None
            self._report_callback = None
            self._report_queue = queue.Queue()

        @staticmethod
        def _cfstring(text):
            return _cf.CFStringCreateWithCString(
                None, text.encode("utf-8"), _K_CF_STRING_ENCODING_UTF8
            )

        @staticmethod
        def _cfnumber(value):
            num = c_int(int(value))
            return _cf.CFNumberCreate(None, _K_CF_NUMBER_SINT32, byref(num))

        @staticmethod
        def _cfnumber_to_int(ref):
            if not ref:
                return 0
            value = c_int()
            ok = _cf.CFNumberGetValue(ref, _K_CF_NUMBER_SINT32, byref(value))
            return int(value.value) if ok else 0

        @staticmethod
        def _cfstring_to_str(ref):
            if not ref:
                return None
            buf = create_string_buffer(256)
            ok = _cf.CFStringGetCString(ref, buf, len(buf), _K_CF_STRING_ENCODING_UTF8)
            return buf.value.decode("utf-8", errors="replace") if ok else None

        @classmethod
        def _get_property(cls, device_ref, name):
            key = cls._cfstring(name)
            try:
                return _iokit.IOHIDDeviceGetProperty(device_ref, key)
            finally:
                _cf.CFRelease(key)

        @classmethod
        def enumerate_infos(cls):
            infos = []
            manager = None
            matching = None
            matching_refs = []
            try:
                keys = [cls._cfstring("VendorID")]
                values = [cls._cfnumber(LOGI_VID)]
                key_array = (c_void_p * len(keys))(*keys)
                value_array = (c_void_p * len(values))(*values)
                matching = _cf.CFDictionaryCreate(
                    None, key_array, value_array, len(keys), None, None
                )
                matching_refs = keys + values

                manager = _iokit.IOHIDManagerCreate(None, 0)
                if not manager:
                    raise OSError("IOHIDManagerCreate failed")
                _iokit.IOHIDManagerSetDeviceMatching(manager, matching)
                res = _iokit.IOHIDManagerOpen(manager, 0)
                if res != 0:
                    raise OSError(f"IOHIDManagerOpen failed: 0x{res:08X}")

                devices = _iokit.IOHIDManagerCopyDevices(manager)
                if not devices:
                    return infos
                try:
                    count = _cf.CFSetGetCount(devices)
                    if count <= 0:
                        return infos
                    values_buf = (c_void_p * count)()
                    _cf.CFSetGetValues(devices, values_buf)
                    seen = set()
                    for device_ref in values_buf:
                        pid = cls._cfnumber_to_int(cls._get_property(device_ref, "ProductID"))
                        up = cls._cfnumber_to_int(cls._get_property(device_ref, "PrimaryUsagePage"))
                        usage = cls._cfnumber_to_int(cls._get_property(device_ref, "PrimaryUsage"))
                        transport = cls._cfstring_to_str(cls._get_property(device_ref, "Transport"))
                        product = cls._cfstring_to_str(cls._get_property(device_ref, "Product"))
                        if not pid:
                            continue
                        key = (pid, up, usage, transport or "", product or "")
                        if key in seen:
                            continue
                        seen.add(key)
                        infos.append({
                            "product_id": pid,
                            "usage_page": up,
                            "usage": usage,
                            "transport": transport,
                            "product_string": product,
                            "source": "iokit-enumerate",
                        })
                finally:
                    _cf.CFRelease(devices)
            except Exception as exc:
                print(f"[HidGesture] native enumerate error: {exc}")
            finally:
                if matching:
                    _cf.CFRelease(matching)
                if manager:
                    _cf.CFRelease(manager)
                for item in matching_refs:
                    _cf.CFRelease(item)
            return infos

        def open(self):
            keys = [
                self._cfstring("VendorID"),
                self._cfstring("ProductID"),
            ]
            values = [
                self._cfnumber(LOGI_VID),
                self._cfnumber(self._product_id),
            ]
            if self._usage_page > 0:
                keys.append(self._cfstring("PrimaryUsagePage"))
                values.append(self._cfnumber(self._usage_page))
            if self._usage > 0:
                keys.append(self._cfstring("PrimaryUsage"))
                values.append(self._cfnumber(self._usage))
            if self._transport:
                keys.append(self._cfstring("Transport"))
                values.append(self._cfstring(self._transport))
            key_array = (c_void_p * len(keys))(*keys)
            value_array = (c_void_p * len(values))(*values)
            self._matching = _cf.CFDictionaryCreate(
                None, key_array, value_array, len(keys), None, None
            )
            self._matching_refs = keys + values

            self._manager = _iokit.IOHIDManagerCreate(None, 0)
            if not self._manager:
                raise OSError("IOHIDManagerCreate failed")
            _iokit.IOHIDManagerSetDeviceMatching(self._manager, self._matching)
            res = _iokit.IOHIDManagerOpen(self._manager, 0)
            if res != 0:
                raise OSError(f"IOHIDManagerOpen failed: 0x{res:08X}")

            devices = _iokit.IOHIDManagerCopyDevices(self._manager)
            if not devices:
                raise OSError(self._describe_match_failure())
            try:
                count = _cf.CFSetGetCount(devices)
                if count <= 0:
                    raise OSError(self._describe_match_failure())
                values_buf = (c_void_p * count)()
                _cf.CFSetGetValues(devices, values_buf)
                self._device = _cf.CFRetain(values_buf[0])
            finally:
                _cf.CFRelease(devices)

            res = _iokit.IOHIDDeviceOpen(self._device, 0)
            if res != 0:
                raise OSError(f"IOHIDDeviceOpen failed: 0x{res:08X}")
            self._run_loop = _cf.CFRunLoopGetCurrent()
            self._input_buffer = (c_uint8 * 64)()
            self._report_callback = _IOHID_REPORT_CALLBACK(self._on_input_report)
            _iokit.IOHIDDeviceScheduleWithRunLoop(
                self._device,
                self._run_loop,
                _K_CF_RUN_LOOP_DEFAULT_MODE,
            )
            _iokit.IOHIDDeviceRegisterInputReportCallback(
                self._device,
                self._input_buffer,
                len(self._input_buffer),
                self._report_callback,
                None,
            )

        def _describe_match_failure(self):
            parts = [f"PID 0x{self._product_id:04X}"]
            if self._usage_page > 0:
                parts.append(f"UP 0x{self._usage_page:04X}")
            if self._usage > 0:
                parts.append(f"usage 0x{self._usage:04X}")
            if self._transport:
                parts.append(f'transport "{self._transport}"')
            return "No IOHIDDevice for " + " ".join(parts)

        def close(self):
            if self._device and self._run_loop:
                try:
                    _iokit.IOHIDDeviceUnscheduleFromRunLoop(
                        self._device,
                        self._run_loop,
                        _K_CF_RUN_LOOP_DEFAULT_MODE,
                    )
                except Exception:
                    pass
            if self._device:
                try:
                    _iokit.IOHIDDeviceClose(self._device, 0)
                except Exception:
                    pass
            if self._device:
                _cf.CFRelease(self._device)
                self._device = None
            if self._matching:
                _cf.CFRelease(self._matching)
                self._matching = None
            if self._manager:
                _cf.CFRelease(self._manager)
                self._manager = None
            for item in self._matching_refs:
                _cf.CFRelease(item)
            self._matching_refs = []
            self._run_loop = None
            self._input_buffer = None
            self._report_callback = None
            self._report_queue = queue.Queue()

        def set_nonblocking(self, _enabled):
            return None

        def write(self, buf):
            arr = (c_uint8 * len(buf))(*buf)
            res = _iokit.IOHIDDeviceSetReport(
                self._device,
                _K_IOHID_REPORT_TYPE_OUTPUT,
                int(buf[0]),
                arr,
                len(buf),
            )
            if res != 0:
                raise OSError(f"IOHIDDeviceSetReport failed: 0x{res:08X}")
            return len(buf)

        def _on_input_report(self, _context, result, _sender, _report_type,
                             _report_id, report, report_length):
            if result != 0 or report_length <= 0:
                return
            try:
                self._report_queue.put_nowait(
                    ctypes.string_at(report, int(report_length))
                )
            except Exception:
                pass

        def read(self, _size, timeout_ms=0):
            try:
                return self._report_queue.get_nowait()
            except queue.Empty:
                pass

            deadline = None
            if timeout_ms and timeout_ms > 0:
                deadline = time.monotonic() + timeout_ms / 1000.0

            while True:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return b""
                    slice_seconds = min(remaining, 0.05)
                else:
                    slice_seconds = 0.05

                _cf.CFRunLoopRunInMode(
                    _K_CF_RUN_LOOP_DEFAULT_MODE,
                    slice_seconds,
                    True,
                )
                try:
                    return self._report_queue.get_nowait()
                except queue.Empty:
                    if deadline is not None:
                        continue
                    return b""

# ── Constants ─────────────────────────────────────────────────────
LOGI_VID       = 0x046D


def _summarize_hid_infos(infos, limit=8):
    parts = []
    for info in list(infos)[:limit]:
        pid = int(info.get("product_id", 0) or 0)
        usage_page = int(info.get("usage_page", 0) or 0)
        usage = int(info.get("usage", 0) or 0)
        product = info.get("product_string") or "?"
        transport = info.get("transport") or "-"
        parts.append(
            f"PID=0x{pid:04X} UP=0x{usage_page:04X} "
            f"usage=0x{usage:04X} transport={transport} product={product}"
        )
    remaining = max(0, len(infos) - limit)
    if remaining:
        parts.append(f"... {remaining} more")
    return "; ".join(parts) if parts else "-"


def _linux_logitech_hidraw_nodes(base="/sys/class/hidraw"):
    if not sys.platform.startswith("linux"):
        return []
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return []

    nodes = []
    for entry in entries:
        if not entry.startswith("hidraw"):
            continue
        uevent_path = os.path.join(base, entry, "device", "uevent")
        try:
            with open(uevent_path, "r", encoding="utf-8", errors="replace") as fh:
                values = dict(
                    line.rstrip("\n").split("=", 1)
                    for line in fh
                    if "=" in line
                )
        except OSError:
            continue

        parts = values.get("HID_ID", "").split(":")
        if len(parts) < 3:
            continue
        try:
            vid = int(parts[1], 16)
            pid = int(parts[2], 16)
        except ValueError:
            continue
        if vid != LOGI_VID:
            continue

        product = values.get("HID_NAME") or "?"
        nodes.append(f"{entry} PID=0x{pid:04X} product={product}")
    return nodes


SHORT_ID       = 0x10        # HID++ short report (7 bytes total)
LONG_ID        = 0x11        # HID++ long  report (20 bytes total)
SHORT_LEN      = 7
LONG_LEN       = 20

BT_DEV_IDX     = 0xFF        # device-index for direct Bluetooth
# Known Logi Bolt receiver PID.
# Source: https://github.com/pwr-Solaar/Solaar/blob/master/lib/logitech_receiver/base_usb.py
BOLT_RECEIVER_PID = 0xC548
FEAT_IROOT     = 0x0000
FEAT_REPROG_V4 = 0x1B04      # Reprogrammable Controls V4
FEAT_ADJ_DPI   = 0x2201      # Adjustable DPI
FEAT_SMART_SHIFT          = 0x2110  # Smart Shift basic
FEAT_SMART_SHIFT_ENHANCED = 0x2111  # Smart Shift Enhanced (MX Master 3/3S, MX Master 4)
FEAT_HIRES_WHEEL          = 0x2120
FEAT_HIRES_WHEEL_ENHANCED = 0x2121
FEAT_LOWRES_WHEEL         = 0x2130
FEAT_THUMB_WHEEL          = 0x2150
FEAT_UNIFIED_BATT   = 0x1004      # Unified Battery (preferred)
FEAT_DEVICE_NAME    = 0x0005      # Device Name & Type
FEAT_BATTERY_STATUS = 0x1000      # Battery Status (fallback)
FEAT_CROWN          = 0x4600      # Crown dial (Logitech Craft keyboard)
FEAT_BACKLIGHT2     = 0x1982      # Keyboard backlight (Craft, MX Keys)
# BACKLIGHT2 function indices (Solaar): getBacklightConfig=0, setBacklightConfig=1.
BACKLIGHT2_GET_CONFIG = 0
BACKLIGHT2_SET_CONFIG = 1
# getBacklightConfig (fn 0) returns a config block whose byte 0 is the on/off
# flag. On the Craft, software brightness is NOT settable over 0x1982 (verified on
# hardware: supported byte reports no manual mode, and the level byte is ignored —
# the keyboard manages brightness itself via its ambient sensor and backlight
# keys). So we only toggle byte 0. See craft-hidpp-protocol / backlight notes.
BACKLIGHT2_ENABLED_IDX = 0
BACKLIGHT2_ENABLED_ON  = 0x01
BACKLIGHT2_ENABLED_OFF = 0x00
# Crown function indices follow Solaar (read_fnid 0x10 → fn 1, write 0x20 → fn 2).
CROWN_GET_MODE      = 1
CROWN_SET_MODE      = 2
CROWN_DIVERT_ON     = 0x02        # setCrownMode byte0: send HID++ notifications
CROWN_DIVERT_OFF    = 0x01
# setCrownMode byte1 selects the rotation feel. 0x00 = leave unchanged.
CROWN_SMOOTH_ON     = 0x01        # free-spinning
CROWN_SMOOTH_OFF    = 0x02        # ratchet (detented)
# Crown ratchet notification bytes (params = report bytes after the 4-byte
# header): params[1] = signed ratchet delta, params[5] == 1 = tap, params[6] =
# press progression (0x01 start … 0x05 end). See craft-hidpp-protocol memory.
CROWN_RATCHET_DELTA_IDX = 1
CROWN_TAP_IDX           = 5
CROWN_PRESS_IDX         = 6
# Accumulated |signed delta| that equals one emitted rotation step. One physical
# ratchet detent sums to roughly this; tunable on hardware.
CROWN_RATCHET_STEP      = 6
# A click is always preceded by a touch. After a touch we wait this long: if a
# physical click (or rotation) follows, the touch is suppressed; otherwise the
# touch is treated as its own command.
CROWN_TOUCH_CLICK_WINDOW_S = 0.25
# Receiver register that gates HID++ notification delivery. Writing
# wireless(0x000100) | software_present(0x000800) = 0x000900 makes crown events
# arrive reliably; without it they are dropped even when the crown is diverted.
RECEIVER_NOTIF_REGISTER = 0x00
RECEIVER_NOTIF_FLAGS    = (0x00, 0x09, 0x00)
# HID++ 1.0 receiver notifications (sub-id) for hot-plug: a paired device
# powering on/off after the initial scan.
RECEIVER_NOTIF_DEPARTURE = 0x40
RECEIVER_NOTIF_ARRIVAL   = 0x41
DEFAULT_GESTURE_CID = DEFAULT_GESTURE_CIDS[0]

MY_SW          = 0x0A        # arbitrary software-id used in our requests

HIDPP_ERROR_NAMES = {
    0x01: "UNKNOWN",
    0x02: "INVALID_ARGUMENT",
    0x03: "OUT_OF_RANGE",
    0x04: "HARDWARE_ERROR",
    0x05: "LOGITECH_ERROR",
    0x06: "INVALID_FEATURE_INDEX",
    0x07: "INVALID_FUNCTION",
    0x08: "BUSY",
    0x09: "UNSUPPORTED",
}

KNOWN_CID_NAMES = {
    0x00C3: "Mouse Gesture Button",
    0x00C4: "Smart Shift",
    0x00D7: "Virtual Gesture Button",
    0x00FD: "DPI Switch",
}

KEY_FLAG_BITS = (
    (0x0001, "mse"),
    (0x0002, "fn"),
    (0x0004, "nonstandard"),
    (0x0008, "fn_sensitive"),
    (0x0010, "reprogrammable"),
    (0x0020, "divertable"),
    (0x0040, "persist_divertable"),
    (0x0080, "virtual"),
    (0x0100, "raw_xy"),
    (0x0200, "force_raw_xy"),
    (0x0400, "analytics"),
    (0x0800, "raw_wheel"),
)

MAPPING_FLAG_BITS = (
    (0x0001, "diverted"),
    (0x0004, "persist_diverted"),
    (0x0010, "raw_xy_diverted"),
    (0x0040, "force_raw_xy_diverted"),
    (0x0100, "analytics_reporting"),
    (0x0400, "raw_wheel"),
)


# ── Helpers ───────────────────────────────────────────────────────

def _parse(raw):
    """Parse a read buffer → (dev_idx, feat_idx, func, sw, params) or None.

    On Windows the hidapi C backend strips the report-ID byte, so the
    first byte is device-index.  On other platforms / future versions
    the report-ID may be included.  We detect which layout we have by
    checking whether byte 0 looks like a valid HID++ report-ID.
    """
    if not raw or len(raw) < 4:
        return None
    off = 1 if raw[0] in (SHORT_ID, LONG_ID) else 0
    if off + 3 > len(raw):
        return None
    dev    = raw[off]
    feat   = raw[off + 1]
    fsw    = raw[off + 2]
    func   = (fsw >> 4) & 0x0F
    sw     = fsw & 0x0F
    params = raw[off + 3:]
    return dev, feat, func, sw, params


def _hex_bytes(data):
    if not data:
        return "-"
    return " ".join(f"{int(b) & 0xFF:02X}" for b in data)


def _format_flags(value, bit_names):
    names = [name for bit, name in bit_names if value & bit]
    return ",".join(names) if names else "none"


def _format_cid(cid):
    name = KNOWN_CID_NAMES.get(cid)
    return f"0x{cid:04X} ({name})" if name else f"0x{cid:04X}"


# ── Listener class ────────────────────────────────────────────────

class HidGestureListener:
    """Background thread: diverts the gesture button and listens via HID++."""

    def __init__(self, on_down=None, on_up=None, on_move=None,
                 on_connect=None, on_disconnect=None, extra_diverts=None,
                 on_crown=None):
        self._on_down       = on_down
        self._on_up         = on_up
        self._on_move       = on_move
        self._on_connect    = on_connect
        self._on_disconnect = on_disconnect
        self._on_crown      = on_crown
        # Base divert template; each device session gets its own copy so
        # held-state is tracked per device.
        self._base_extra_diverts = {
            cid: {**info, "held": False}
            for cid, info in (extra_diverts or {}).items()
        }
        self._extra_diverts = {
            cid: dict(info) for cid, info in self._base_extra_diverts.items()
        }
        self._dev       = None          # hid.device()
        self._thread    = None
        self._running   = False
        self._feat_idx  = None          # feature index of REPROG_V4
        self._dpi_idx   = None          # feature index of ADJUSTABLE_DPI
        self._battery_idx = None
        self._battery_feature_id = None
        self._dev_idx   = BT_DEV_IDX
        self._gesture_cid = DEFAULT_GESTURE_CID
        self._gesture_candidates = list(DEFAULT_GESTURE_CIDS)
        self._held      = False
        self._connected = False         # True while HID++ device is open
        self._rawxy_enabled = False
        self._pending_dpi = None        # set by set_dpi(), applied in loop
        self._dpi_result  = None        # True/False after apply
        self._smart_shift_idx = None      # feature index of SMART_SHIFT / SMART_SHIFT_ENHANCED
        self._smart_shift_enhanced = False  # True → use fn 1/2; False → fn 0/1
        self._wheel_feature_indexes = {}
        self._pending_smart_shift = None
        self._smart_shift_result = None
        self._smart_shift_call_lock = threading.Lock()
        self._smart_shift_slot_lock = threading.Lock()
        self._smart_shift_event = threading.Event()
        self._reconnect_requested = False
        self._pending_extra_diverts = None  # queued extra-divert set change
        self._pending_battery = None
        self._battery_result = None
        self._last_logged_battery = None
        self._connected_device_info = None
        self._last_controls = []   # REPROG_V4 controls from last connection
        self._consecutive_request_timeouts = 0
        # Crown (Logitech Craft) state.
        self._crown_idx = None          # feature index of CROWN, or None
        self._crown_accum = 0           # accumulated signed ratchet delta
        self._crown_pressed = False     # physical crown click held
        self._crown_rotated_while_pressed = False  # press+rotate vs plain click
        self._crown_touch_active = False    # capacitive touch edge state
        self._crown_touch_pending = False   # touch awaiting click/timeout
        self._crown_touch_timer = None      # threading.Timer for touch resolve
        self._crown_touch_lock = threading.Lock()
        self._crown_smooth_pref = False     # desired feel: True=smooth, False=ratchet
        self._pending_crown_smooth = None   # queued live feel change
        # Keyboard backlight (BACKLIGHT2, feature 0x1982) state.
        self._backlight_idx = None          # feature index of BACKLIGHT2, or None
        self._backlight_pref = None         # desired (enabled: bool, pct: int 0-100)
        self._pending_backlight = None      # queued live backlight change
        self._device_type = "mouse"         # current cursor device type
        # Multiplexer: per-device sessions keyed by a unique session id. The flat
        # self._* fields above act as a transient "cursor" reused by the
        # synchronous discovery/control helpers; persistent per-device state
        # (including its owning HID handle) lives in these session snapshots.
        # A USB receiver multiplexes several devices on one handle by
        # device-index (1..6); direct Bluetooth devices each own a separate
        # handle and all report on device-index 0xFF, so the session key must be
        # handle-aware rather than the device-index. See craft-multidevice notes.
        self._sessions = {}                 # session_key -> snapshot dict
        self._session_key = None            # cursor's current session key
        self._next_session_key = 0          # monotonic session-key allocator
        self._primary_session = None        # session_key of the primary device
        self._recv_handle = None        # short HID++ handle used to enable
                                        # receiver notifications (kept open)

    # ── public API ────────────────────────────────────────────────

    def start(self):
        if not HIDAPI_OK and not _MAC_NATIVE_OK:
            details = f": {HIDAPI_IMPORT_ERROR!r}" if HIDAPI_IMPORT_ERROR else ""
            print(f"[HidGesture] no HID backend available; install hidapi{details}")
            return False
        if not HIDAPI_OK and _MAC_NATIVE_OK:
            print("[HidGesture] hidapi unavailable; using native macOS HID backend only")
        if HIDAPI_OK:
            print(
                "[HidGesture] HID module: "
                f"{_HID_MODULE_NAME or '?'} API style: {_HID_API_STYLE or '?'}"
            )
            if sys.platform.startswith("linux") and _HID_MODULE_NAME != "hidraw":
                print(
                    "[HidGesture] Linux hidraw module is unavailable; Bluetooth "
                    "Logitech HID++ devices may not enumerate"
                )
        self._running = True
        self._thread = threading.Thread(
            target=self._main_loop, daemon=True, name="HidGesture")
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        d = self._dev
        if d:
            try:
                d.close()
            except Exception:
                pass
            self._dev = None
        self._close_recv_handle()
        self._connected_device_info = None
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def connected_device(self):
        # Primary device (backward compatible). Prefer the cursor's info, else
        # the primary session.
        if self._connected_device_info is not None:
            return self._connected_device_info
        s = self._sessions.get(self._primary_session)
        return s.get("_connected_device_info") if s else None

    @property
    def connected_devices(self):
        """All bound devices' ConnectedDeviceInfo (multiplexer)."""
        out = []
        for s in self._sessions.values():
            info = s.get("_connected_device_info")
            if info is not None:
                out.append(info)
        return out

    def _load_session_with(self, field):
        """Load the cursor with the first session whose *field* is set."""
        for key, s in self._sessions.items():
            if s.get(field) is not None:
                self._load_cursor(s)
                return key
        return None

    def _save_cursor_session(self):
        """Persist the current cursor back to its session."""
        if self._session_key in self._sessions:
            self._sessions[self._session_key] = self._snapshot_cursor()

    def _distinct_session_handles(self):
        """Every open HID handle backing a session (identity de-duplicated).

        A USB receiver yields a single handle shared by all its device
        sessions; direct Bluetooth devices each contribute their own handle."""
        handles = []
        for s in self._sessions.values():
            dev = s.get("_dev")
            if dev is not None and not any(dev is h for h in handles):
                handles.append(dev)
        return handles

    @staticmethod
    def _physical_device_key(info):
        """Stable identity for the physical device behind a HID interface.

        Used to de-duplicate the several HID collections a single Bluetooth
        device exposes (all sharing one serial/MAC), so we bind it once rather
        than once per collection. Prefers the serial number (a MAC for BLE),
        falling back to a collection-stripped device path plus PID."""
        serial = (info.get("serial_number") or "").strip()
        if serial:
            return ("sn", serial.lower())
        path = info.get("path") or b""
        if isinstance(path, bytes):
            path = path.decode("utf-8", "replace")
        # Group the per-collection paths of one device: drop the trailing
        # "&Col0N" collection suffix and the interface-GUID tail.
        base = re.split(r"&col[0-9a-f]+", path, flags=re.IGNORECASE)[0]
        base = base.split("#{", 1)[0]
        pid = int(info.get("product_id", 0) or 0)
        return ("path", pid, base.lower())

    def _discovered_feature_ids(self):
        feature_ids = []
        if self._feat_idx is not None:
            feature_ids.append(FEAT_REPROG_V4)
        if self._dpi_idx is not None:
            feature_ids.append(FEAT_ADJ_DPI)
        if self._smart_shift_idx is not None:
            feature_ids.append(
                FEAT_SMART_SHIFT_ENHANCED
                if self._smart_shift_enhanced
                else FEAT_SMART_SHIFT
            )
        if self._battery_idx is not None and self._battery_feature_id is not None:
            feature_ids.append(self._battery_feature_id)
        if self._crown_idx is not None:
            feature_ids.append(FEAT_CROWN)
        if self._backlight_idx is not None:
            feature_ids.append(FEAT_BACKLIGHT2)
        feature_ids.extend(sorted(self._wheel_feature_indexes))
        return tuple(feature_ids)

    def _discovered_feature_inventory(self):
        features = []
        if self._feat_idx is not None:
            features.append({"feature_id": FEAT_REPROG_V4, "index": self._feat_idx})
        if self._dpi_idx is not None:
            features.append({"feature_id": FEAT_ADJ_DPI, "index": self._dpi_idx})
        if self._smart_shift_idx is not None:
            features.append({
                "feature_id": (
                    FEAT_SMART_SHIFT_ENHANCED
                    if self._smart_shift_enhanced
                    else FEAT_SMART_SHIFT
                ),
                "index": self._smart_shift_idx,
            })
        if self._crown_idx is not None:
            features.append({"feature_id": FEAT_CROWN, "index": self._crown_idx})
        if self._backlight_idx is not None:
            features.append({"feature_id": FEAT_BACKLIGHT2, "index": self._backlight_idx})
        if self._battery_idx is not None and self._battery_feature_id is not None:
            features.append({
                "feature_id": self._battery_feature_id,
                "index": self._battery_idx,
            })
        for feature_id, index in sorted(self._wheel_feature_indexes.items()):
            features.append({"feature_id": feature_id, "index": index})
        return tuple(features)

    def dump_device_info(self):
        """Return a dict describing everything we know about the connected device.

        Intended for community contributors who want to submit device definitions.
        Returns None when no device is connected.
        """
        dev = self._connected_device_info
        if dev is None:
            return None

        features = {}
        if self._feat_idx is not None:
            features["REPROG_V4 (0x1B04)"] = f"index 0x{self._feat_idx:02X}"
        if self._dpi_idx is not None:
            features["ADJUSTABLE_DPI (0x2201)"] = f"index 0x{self._dpi_idx:02X}"
        if self._smart_shift_idx is not None:
            feat_name = ("SMART_SHIFT_ENHANCED (0x2111)"
                         if self._smart_shift_enhanced
                         else "SMART_SHIFT (0x2110)")
            features[feat_name] = f"index 0x{self._smart_shift_idx:02X}"
        if self._battery_idx is not None:
            feat_name = (f"0x{self._battery_feature_id:04X}"
                         if self._battery_feature_id else "unknown")
            features[f"BATTERY ({feat_name})"] = f"index 0x{self._battery_idx:02X}"
        for feature_id, index in sorted(self._wheel_feature_indexes.items()):
            features[f"WHEEL (0x{feature_id:04X})"] = f"index 0x{index:02X}"

        controls = []
        for c in self._last_controls:
            controls.append({
                "index": c["index"],
                "cid": f"0x{c['cid']:04X}",
                "task": f"0x{c['task']:04X}",
                "flags": f"0x{c['flags']:04X}",
                "position": c.get("pos"),
                "group": c.get("group"),
                "group_mask": f"0x{c.get('gmask', 0):02X}",
                "mapped_to": f"0x{c['mapped_to']:04X}",
                "mapping_flags": f"0x{c['mapping_flags']:04X}",
            })

        return {
            "device_key": dev.key,
            "display_name": dev.display_name,
            "product_id": f"0x{dev.product_id:04X}" if dev.product_id else None,
            "product_name": dev.product_name,
            "transport": dev.transport,
            "ui_layout": dev.ui_layout,
            "supported_buttons": list(dev.supported_buttons),
            "gesture_cids": [f"0x{c:04X}" for c in dev.gesture_cids],
            "dpi_range": [dev.dpi_min, dev.dpi_max],
            "discovered_features": features,
            "reprog_controls": controls,
            "gesture_candidates": [f"0x{c:04X}" for c in self._gesture_candidates],
            "capability_inventory": dev.capability_inventory.to_dict(),
        }

    # ── device discovery ──────────────────────────────────────────

    @staticmethod
    def _vendor_hid_infos():
        """Return candidate Logitech HID interfaces from hidapi and macOS IOKit."""
        out = []
        seen = set()

        def add_info(info):
            pid = int(info.get("product_id", 0) or 0)
            up = int(info.get("usage_page", 0) or 0)
            usage = int(info.get("usage", 0) or 0)
            transport = info.get("transport") or ""
            path = info.get("path") or b""
            if isinstance(path, str):
                path = path.encode("utf-8", errors="replace")
            key = (pid, up, usage, transport, bytes(path))
            if key in seen:
                return
            seen.add(key)
            out.append(info)

        if HIDAPI_OK and _BACKEND_PREFERENCE in ("auto", "hidapi"):
            try:
                raw_infos = list(_hid.enumerate(LOGI_VID, 0))
                if not raw_infos:
                    _log_once(
                        f"hidapi-empty-{_HID_MODULE_NAME}",
                        "[HidGesture] "
                        f"{_HID_MODULE_NAME or 'hidapi'} enumerate(0x{LOGI_VID:04X}) "
                        "returned no Logitech HID interfaces"
                    )
                    linux_nodes = _linux_logitech_hidraw_nodes()
                    if linux_nodes:
                        _log_once(
                            "linux-hidraw-logitech-present",
                            "[HidGesture] Linux sysfs sees Logitech hidraw nodes: "
                            f"{'; '.join(linux_nodes[:8])}. If hidapi still sees "
                            "none, check hidraw backend packaging and /dev/hidraw "
                            "permissions."
                        )
                    elif sys.platform.startswith("linux"):
                        _log_once(
                            "linux-hidraw-logitech-missing",
                            "[HidGesture] Linux sysfs sees no Logitech hidraw "
                            "nodes for VID 0x046D; verify the mouse is connected "
                            "as an active HID device, not only paired."
                        )
                hidapi_candidates = 0
                fallback_candidates = 0
                for info in raw_infos:
                    pid = int(info.get("product_id", 0) or 0)
                    usage_page = int(info.get("usage_page", 0) or 0)
                    usage = int(info.get("usage", 0) or 0)
                    product = info.get("product_string")
                    if usage_page >= 0xFF00:
                        add_info(dict(info, source="hidapi-enumerate"))
                        hidapi_candidates += 1
                        continue
                    if resolve_device(product_id=pid, product_name=product):
                        print(
                            "[HidGesture] Accepting known Logitech device "
                            "without vendor usage metadata for fallback probe "
                            f"PID=0x{pid:04X} UP=0x{usage_page:04X} "
                            f"usage=0x{usage:04X} product={product or '?'}"
                        )
                        add_info(dict(info, source="hidapi-enumerate-fallback"))
                        fallback_candidates += 1
                if raw_infos and not (hidapi_candidates or fallback_candidates):
                    print(
                        "[HidGesture] hidapi found Logitech interfaces, but none "
                        "matched vendor usage metadata or known-device fallback"
                    )
                    _log_once(
                        f"hidapi-filtered-{_HID_MODULE_NAME}",
                        "[HidGesture] Filtered Logitech HID interfaces: "
                        f"{_summarize_hid_infos(raw_infos)}"
                    )
            except Exception as exc:
                print(f"[HidGesture] hidapi enumerate error: {exc}")

        if (
            sys.platform == "darwin"
            and _MAC_NATIVE_OK
            and _BACKEND_PREFERENCE in ("auto", "iokit")
        ):
            for info in _MacNativeHidDevice.enumerate_infos():
                add_info(info)

        return out

    # ── low-level HID++ I/O ───────────────────────────────────────

    def _tx(self, report_id, feat, func, params):
        """Transmit an HID++ message.  Always uses 20-byte long format
        because BLE HID collections typically only support long output reports."""
        buf = [0] * LONG_LEN
        buf[0] = LONG_ID                 # always long for BLE compat
        buf[1] = self._dev_idx
        buf[2] = feat
        buf[3] = ((func & 0x0F) << 4) | (MY_SW & 0x0F)
        for i, b in enumerate(params):
            if 4 + i < LONG_LEN:
                buf[4 + i] = b & 0xFF
        self._dev.write(buf)

    def _rx(self, timeout_ms=2000):
        """Read one HID input report (blocking with timeout).
        Raises on device error (e.g., disconnection) so callers
        can trigger reconnection."""
        dev = self._dev
        if dev is None:
            return None
        d = dev.read(64, timeout_ms)
        return list(d) if d else None

    def _request(self, feat, func, params, timeout_ms=2000):
        """Send a long HID++ request, wait for matching response."""
        req_params = list(params)
        try:
            self._tx(LONG_ID, feat, func, req_params)
        except Exception as exc:
            print(f"[HidGesture] request tx failed feat=0x{feat:02X} func=0x{func:X} "
                  f"params=[{_hex_bytes(req_params)}]: {exc}")
            # Discovery probes should skip bad candidates, but an active session
            # transport failure means the live handle has died and the main loop
            # must run its existing cleanup/reconnect path.
            if self._connected:
                raise IOError(str(exc)) from exc
            return None
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                raw = self._rx(min(500, timeout_ms))
            except Exception as exc:
                print(f"[HidGesture] request rx failed feat=0x{feat:02X} func=0x{func:X} "
                      f"params=[{_hex_bytes(req_params)}]: {exc}")
                if self._connected:
                    raise IOError(str(exc)) from exc
                return None
            if raw is None:
                continue
            msg = _parse(raw)
            if msg is None:
                continue
            _, r_feat, r_func, r_sw, r_params = msg

            # HID++ error (feature-index 0xFF)
            if r_feat == 0xFF:
                code = r_params[1] if len(r_params) > 1 else 0
                code_name = HIDPP_ERROR_NAMES.get(code, "UNKNOWN")
                print(f"[HidGesture] HID++ error 0x{code:02X} ({code_name}) "
                      f"for feat=0x{feat:02X} func=0x{func:X} "
                      f"devIdx=0x{self._dev_idx:02X} req=[{_hex_bytes(req_params)}] "
                      f"resp=[{_hex_bytes(r_params)}]")
                return None

            expected_funcs = {func, (func + 1) & 0x0F}
            if r_feat == feat and r_sw == MY_SW and r_func in expected_funcs:
                self._consecutive_request_timeouts = 0
                return msg
            # Forward non-matching reports (e.g. diverted button events) so
            # button held-state tracking stays in sync during command exchanges.
            self._on_report(raw)
        self._consecutive_request_timeouts += 1
        print(f"[HidGesture] request timeout feat=0x{feat:02X} func=0x{func:X} "
              f"devIdx=0x{self._dev_idx:02X} params=[{_hex_bytes(req_params)}] "
              f"(consecutive={self._consecutive_request_timeouts})")
        return None

    # ── feature helpers ───────────────────────────────────────────

    def _find_feature(self, feature_id, timeout_ms=2000):
        """Use IRoot (feature 0x0000) to discover a feature index."""
        hi = (feature_id >> 8) & 0xFF
        lo = feature_id & 0xFF
        resp = self._request(0x00, 0, [hi, lo, 0x00], timeout_ms=timeout_ms)
        if resp:
            _, _, _, _, p = resp
            if p and p[0] != 0:
                return p[0]
        return None

    def _query_device_name(self):
        """Query device name via HID++ feature 0x0005 (DEVICE_NAME_TYPE)."""
        name_idx = self._find_feature(FEAT_DEVICE_NAME)
        if name_idx is None:
            return None
        resp = self._request(name_idx, 0, [0x00] * 3)
        if not resp:
            return None
        _, _, _, _, params = resp
        name_len = params[0]
        if name_len == 0:
            return None
        name_bytes = []
        offset = 0
        while offset < name_len:
            resp = self._request(name_idx, 1, [offset, 0x00, 0x00])
            if not resp:
                break
            _, _, _, _, chunk = resp
            remaining = name_len - offset
            name_bytes.extend(chunk[:remaining])
            offset += len(chunk)
            if len(chunk) == 0:
                break
        if not name_bytes:
            return None
        name = bytes(name_bytes).decode("ascii", errors="replace").strip("\x00").strip()
        return name if name else None

    def _get_cid_reporting(self, cid):
        if self._feat_idx is None:
            return None
        hi = (cid >> 8) & 0xFF
        lo = cid & 0xFF
        return self._request(self._feat_idx, 2, [hi, lo])

    def _set_cid_reporting(self, cid, flags):
        if self._feat_idx is None:
            return None
        hi = (cid >> 8) & 0xFF
        lo = cid & 0xFF
        return self._request(self._feat_idx, 3, [hi, lo, flags, 0x00, 0x00])

    def _discover_reprog_controls(self):
        controls = []
        if self._feat_idx is None:
            return controls
        resp = self._request(self._feat_idx, 0, [])
        if not resp:
            print("[HidGesture] Failed to read REPROG_V4 control count")
            return controls
        _, _, _, _, params = resp
        _MAX_REPROG_CONTROLS = 32
        count = params[0] if params else 0
        if count > _MAX_REPROG_CONTROLS:
            print(f"[HidGesture] Suspicious control count {count}, "
                  f"capping to {_MAX_REPROG_CONTROLS}")
            count = _MAX_REPROG_CONTROLS
        print(f"[HidGesture] REPROG_V4 exposes {count} controls")
        consecutive_failures = 0
        for index in range(count):
            key_resp = self._request(self._feat_idx, 1, [index], timeout_ms=500)
            if not key_resp:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print(f"[HidGesture] {consecutive_failures} consecutive "
                          f"failures, aborting discovery")
                    break
                print(f"[HidGesture] Failed to read control info for index {index}")
                continue
            consecutive_failures = 0
            _, _, _, _, key_params = key_resp
            if len(key_params) < 9:
                print(f"[HidGesture] Short control info for index {index}: "
                      f"[{_hex_bytes(key_params)}]")
                continue
            cid = (key_params[0] << 8) | key_params[1]
            task = (key_params[2] << 8) | key_params[3]
            flags = key_params[4] | (key_params[8] << 8)
            pos = key_params[5]
            group = key_params[6]
            gmask = key_params[7]
            control = {
                "index": index,
                "cid": cid,
                "task": task,
                "flags": flags,
                "pos": pos,
                "group": group,
                "gmask": gmask,
                "mapped_to": cid,
                "mapping_flags": 0,
            }
            map_resp = self._get_cid_reporting(cid)
            if map_resp:
                _, _, _, _, map_params = map_resp
                if len(map_params) >= 5:
                    mapped_cid = (map_params[0] << 8) | map_params[1]
                    map_flags = map_params[2]
                    mapped_to = (map_params[3] << 8) | map_params[4]
                    if len(map_params) >= 6:
                        map_flags |= map_params[5] << 8
                    control["mapped_to"] = mapped_to or mapped_cid or cid
                    control["mapping_flags"] = map_flags
            controls.append(control)
            print(
                "[HidGesture] Control "
                f"idx={index} cid={_format_cid(cid)} task=0x{task:04X} "
                f"flags=0x{flags:04X}[{_format_flags(flags, KEY_FLAG_BITS)}] "
                f"group={group} gmask=0x{gmask:02X} pos={pos} "
                f"mappedTo=0x{control['mapped_to']:04X} "
                f"reporting=0x{control['mapping_flags']:04X}"
                f"[{_format_flags(control['mapping_flags'], MAPPING_FLAG_BITS)}]"
            )
        return controls

    def _choose_gesture_candidates(self, controls, device_spec=None):
        present = {c["cid"] for c in controls}
        ordered = []
        preferred = tuple(
            getattr(device_spec, "gesture_cids", ()) or DEFAULT_GESTURE_CIDS
        )

        def add_candidate(cid):
            if cid in present and cid not in ordered:
                ordered.append(cid)

        for cid in preferred:
            add_candidate(cid)

        for control in controls:
            cid = control["cid"]
            flags = int(control.get("flags", 0) or 0)
            mapping_flags = int(control.get("mapping_flags", 0) or 0)
            raw_xy_capable = bool(
                flags & 0x0100
                or flags & 0x0200
                or mapping_flags & 0x0010
                or mapping_flags & 0x0040
            )
            virtual_or_named = bool(
                flags & 0x0080
                or "gesture" in KNOWN_CID_NAMES.get(cid, "").lower()
            )
            if raw_xy_capable and virtual_or_named and flags & 0x0020:
                add_candidate(cid)

        return ordered or list(preferred)

    def _control_present(self, cid):
        """True if *cid* is in the discovered REPROG control table. When no
        table was discovered, assume present so we don't over-filter."""
        if not self._last_controls:
            return True
        return any(c.get("cid") == cid for c in self._last_controls)

    def _divert(self):
        """Divert the selected gesture control and enable raw XY when supported."""
        if self._feat_idx is None:
            return False
        for cid in self._gesture_candidates:
            if not self._control_present(cid):
                continue  # device has no such control (e.g. a keyboard)
            self._gesture_cid = cid
            resp = self._set_cid_reporting(cid, 0x33)
            if resp is not None:
                self._rawxy_enabled = True
                print(f"[HidGesture] Divert {_format_cid(cid)} with RawXY: OK")
                return True
            self._rawxy_enabled = False
            resp = self._set_cid_reporting(cid, 0x03)
            ok = resp is not None
            print(f"[HidGesture] Divert {_format_cid(cid)}: "
                  f"{'OK' if ok else 'FAILED'}")
            if ok:
                return True
        self._gesture_cid = DEFAULT_GESTURE_CID
        return False

    def _divert_extras(self):
        """Divert additional CIDs (e.g. mode shift) without raw XY."""
        if self._feat_idx is None:
            return
        for cid, info in self._extra_diverts.items():
            if not self._control_present(cid):
                continue  # device has no such control (e.g. a keyboard)
            resp = self._set_cid_reporting(cid, 0x03)
            ok = resp is not None
            print(f"[HidGesture] Extra divert {_format_cid(cid)}: "
                  f"{'OK' if ok else 'FAILED'}")

    def update_extra_diverts(self, extra):
        """Queue a new set of extra-divert CIDs (mode shift, Craft keys, …).

        Callable from any thread; the change is applied on the listener thread so
        re-mapping a key in the UI takes effect live without a reconnect."""
        self._pending_extra_diverts = {
            cid: {**info, "held": False} for cid, info in (extra or {}).items()
        }

    def _apply_pending_extra_diverts(self):
        """Apply the queued extra-divert set to every device session (each only
        diverts the CIDs it actually has)."""
        pending = self._pending_extra_diverts
        self._pending_extra_diverts = None
        if pending is None:
            return
        targets = list(self._sessions) if self._sessions else [None]
        for dev_idx in targets:
            if dev_idx is not None:
                self._load_cursor(self._sessions[dev_idx])
            if self._feat_idx is None:
                continue
            self._apply_extra_divert_delta(pending)
            if dev_idx is not None:
                self._sessions[dev_idx] = self._snapshot_cursor()

    def _apply_extra_divert_delta(self, pending):
        """Converge the cursor device's diverts to *pending* (present CIDs only)."""
        old = set(self._extra_diverts)
        new = set(pending)
        for cid in old - new:
            hi, lo = (cid >> 8) & 0xFF, cid & 0xFF
            try:
                self._tx(LONG_ID, self._feat_idx, 3, [hi, lo, 0x02, 0x00, 0x00])
                print(f"[HidGesture] Extra undivert {_format_cid(cid)}")
            except Exception:
                pass
        for cid in new - old:
            if not self._control_present(cid):
                continue
            ok = self._set_cid_reporting(cid, 0x03) is not None
            print(f"[HidGesture] Extra divert {_format_cid(cid)}: "
                  f"{'OK' if ok else 'FAILED'}")
        # Preserve held-state for CIDs that remain diverted.
        merged = {}
        for cid, info in pending.items():
            info = dict(info)
            info["held"] = self._extra_diverts.get(cid, {}).get("held", False)
            merged[cid] = info
        self._extra_diverts = merged

    def _undivert(self):
        """Restore default button behaviour (best-effort)."""
        if self._feat_idx is None or self._dev is None:
            return
        # Undivert extra CIDs
        for cid in self._extra_diverts:
            hi = (cid >> 8) & 0xFF
            lo = cid & 0xFF
            try:
                self._tx(LONG_ID, self._feat_idx, 3,
                         [hi, lo, 0x02, 0x00, 0x00])
            except Exception:
                pass
        # Undivert gesture CID
        hi = (self._gesture_cid >> 8) & 0xFF
        lo = self._gesture_cid & 0xFF
        flags = 0x22 if self._rawxy_enabled else 0x02
        try:
            self._tx(LONG_ID, self._feat_idx, 3,
                     [hi, lo, flags, 0x00, 0x00])
        except Exception:
            pass
        self._rawxy_enabled = False

    # ── Crown (Logitech Craft) ────────────────────────────────────

    def _find_crown(self):
        """Locate the CROWN feature (0x4600) on the current device index."""
        fi = self._find_feature(FEAT_CROWN)
        if fi:
            self._crown_idx = fi
            print(f"[HidGesture] Found CROWN @0x{fi:02X}")
        return fi

    def _divert_crown(self):
        """Divert the crown (HID++ notifications) and set the rotation feel."""
        if self._crown_idx is None:
            return False
        smooth = CROWN_SMOOTH_ON if self._crown_smooth_pref else CROWN_SMOOTH_OFF
        resp = self._request(self._crown_idx, CROWN_SET_MODE,
                             [CROWN_DIVERT_ON, smooth])
        ok = resp is not None
        print(f"[HidGesture] Divert CROWN ({'smooth' if self._crown_smooth_pref else 'ratchet'}): "
              f"{'OK' if ok else 'FAILED'}")
        return ok

    def set_crown_smooth(self, smooth):
        """Set the crown rotation feel (True=smooth, False=ratchet). Callable
        from any thread; applied live on the listener thread when connected."""
        self._crown_smooth_pref = bool(smooth)
        self._pending_crown_smooth = bool(smooth)

    def _apply_pending_crown_smooth(self):
        smooth = self._pending_crown_smooth
        self._pending_crown_smooth = None
        if smooth is None:
            return
        if self._sessions:
            self._load_session_with("_crown_idx")
        if self._crown_idx is None:
            return
        byte1 = CROWN_SMOOTH_ON if smooth else CROWN_SMOOTH_OFF
        self._crown_smooth_pref = bool(smooth)
        self._request(self._crown_idx, CROWN_SET_MODE, [CROWN_DIVERT_ON, byte1])
        print(f"[HidGesture] Crown feel: {'smooth' if smooth else 'ratchet'}")
        self._save_cursor_session()

    def _undivert_crown(self):
        if self._crown_idx is None or self._dev is None:
            return
        try:
            self._tx(LONG_ID, self._crown_idx, CROWN_SET_MODE, [CROWN_DIVERT_OFF])
        except Exception:
            pass

    # ── Keyboard backlight (BACKLIGHT2, feature 0x1982) ───────────
    def _find_backlight(self):
        """Locate the BACKLIGHT2 feature (0x1982) on the current device index."""
        fi = self._find_feature(FEAT_BACKLIGHT2)
        if fi:
            self._backlight_idx = fi
            print(f"[HidGesture] Found BACKLIGHT2 @0x{fi:02X}")
        return fi

    def set_backlight(self, enabled, brightness):
        """Set keyboard backlight on/off and brightness (0-100). Callable from
        any thread; applied live on the listener thread when connected."""
        try:
            pct = max(0, min(100, int(brightness)))
        except (TypeError, ValueError):
            pct = 0
        self._backlight_pref = (bool(enabled), pct)
        self._pending_backlight = (bool(enabled), pct)

    def _apply_pending_backlight(self):
        pending = self._pending_backlight
        self._pending_backlight = None
        if pending is None:
            return
        enabled, pct = pending
        if self._sessions:
            self._load_session_with("_backlight_idx")
        if self._backlight_idx is None:
            return
        self._backlight_pref = (enabled, pct)
        # This firmware only honours the on/off (enabled) byte over 0x1982 — the
        # brightness level is firmware-managed (ambient sensor + the keyboard's own
        # backlight keys), so we toggle on/off and leave the level untouched via a
        # read-modify-write. Never let a backlight quirk tear down the session.
        try:
            # _request returns the full (devIdx, feat, func, sw, params) tuple.
            resp = self._request(self._backlight_idx, BACKLIGHT2_GET_CONFIG, [])
            cfg = list(resp[4]) if resp else []
            params = cfg + [0] * (16 - len(cfg)) if len(cfg) < 16 else cfg
            params[BACKLIGHT2_ENABLED_IDX] = (
                BACKLIGHT2_ENABLED_ON if enabled else BACKLIGHT2_ENABLED_OFF)
            self._request(self._backlight_idx, BACKLIGHT2_SET_CONFIG, params[:16])
            print(f"[HidGesture] Backlight: {'on' if enabled else 'off'}")
        except Exception as exc:
            print(f"[HidGesture] Backlight apply failed: {exc}")
        self._save_cursor_session()

    def _enable_receiver_notifications(self, pid):
        """Write the receiver NOTIFICATIONS register so crown events are
        delivered. Sent as a short HID++ report on the FF00/0x0001 collection;
        the handle is kept open for the session to match observed behaviour."""
        if not HIDAPI_OK or _HID_API_STYLE is None:
            return False
        try:
            for info in _hid.enumerate(LOGI_VID, 0):
                if (int(info.get("usage_page", 0) or 0) == 0xFF00
                        and int(info.get("usage", 0) or 0) == 0x0001
                        and int(info.get("product_id", 0) or 0) == int(pid or 0)):
                    path = info.get("path")
                    if not path:
                        continue
                    if _HID_API_STYLE == "hidapi":
                        h = _hid.device()
                        h.open_path(path)
                    else:
                        h = _HidDeviceCompat(path)
                    h.write([SHORT_ID, BT_DEV_IDX, 0x80, RECEIVER_NOTIF_REGISTER,
                             *RECEIVER_NOTIF_FLAGS])
                    try:
                        h.set_nonblocking(True)
                    except Exception:
                        pass
                    self._close_recv_handle()
                    self._recv_handle = h
                    print("[HidGesture] Enabled receiver HID++ notifications")
                    return True
        except Exception as exc:
            print(f"[HidGesture] enable receiver notifications failed: {exc}")
        return False

    def _discover_receiver_slots(self):
        """Ask the receiver to announce its connected devices and collect their
        device-indexes, so we probe only populated slots (fast + reliable).

        Writing receiver register 0x02 = 0x02 makes a Unifying/Bolt receiver
        re-emit a device-arrival (0x41) notification for every paired device.
        Returns a sorted slot list, or None if the receiver doesn't answer."""
        if self._recv_handle is None:
            return None
        try:
            self._recv_handle.write(
                [SHORT_ID, BT_DEV_IDX, 0x80, 0x02, 0x02, 0x00, 0x00])
        except Exception:
            return None
        slots = set()
        deadline = time.time() + 1.2
        while time.time() < deadline:
            try:
                # Receiver arrival/departure notifications are SHORT reports on
                # the 0xFF00/0x0001 collection (recv_handle), not the long one.
                data = self._recv_handle.read(64, 0)
            except Exception:
                break
            if not data:
                time.sleep(0.01)
                continue
            raw = list(data)
            msg = _parse(raw)
            if msg is None:
                continue
            dev_idx, feat, _func, _sw, _p = msg
            if feat == RECEIVER_NOTIF_ARRIVAL and 1 <= dev_idx <= 6:
                slots.add(dev_idx)
        # Drain any remaining announcement reports so the post-connect poll
        # doesn't mistake our own 0x41 burst for a genuine hot-plug arrival.
        for _ in range(50):
            try:
                if not self._recv_handle.read(64, 0):
                    break
            except Exception:
                break
        if slots:
            print(f"[HidGesture] Receiver announced device slots: "
                  + ", ".join(f"0x{s:02X}" for s in sorted(slots)))
        return sorted(slots) if slots else None

    def _poll_receiver_notifications(self):
        """Non-blocking poll of the receiver's short interface for device
        arrival/departure, so a device powered on after the initial scan
        triggers a re-scan that binds it (hot-plug)."""
        if self._recv_handle is None or self._reconnect_requested:
            return
        try:
            data = self._recv_handle.read(64, 0)
        except Exception:
            return
        if not data:
            return
        msg = _parse(list(data))
        if msg is None:
            return
        dev_idx, feat, _f, _s, _p = msg
        if feat in (RECEIVER_NOTIF_ARRIVAL, RECEIVER_NOTIF_DEPARTURE):
            print("[HidGesture] Receiver device "
                  f"{'arrival' if feat == RECEIVER_NOTIF_ARRIVAL else 'departure'} "
                  f"(devIdx=0x{dev_idx:02X}) -> re-scanning")
            self._reconnect_requested = True

    def _close_recv_handle(self):
        if self._recv_handle is not None:
            try:
                self._recv_handle.close()
            except Exception:
                pass
            self._recv_handle = None

    def _handle_crown(self, params):
        """Decode a CROWN notification → rotation / click / touch callbacks.

        The crown reports a capacitive touch (params[CROWN_TAP_IDX]) and a
        physical click (params[CROWN_PRESS_IDX], 0x01 start … 0x05 end). Because
        a click is always preceded by a touch, a touch is held briefly: if a
        click or rotation follows it is consumed, otherwise the touch fires as
        its own command.

        - rotate, not clicked       → crown_left / crown_right
        - rotate while clicked       → crown_press_left / crown_press_right
        - click (press + release)    → crown_tap
        - touch, no click/rotate     → crown_touch
        """
        if len(params) <= CROWN_PRESS_IDX:
            return

        press_val = params[CROWN_PRESS_IDX]
        pressed_now = 0x01 <= press_val <= 0x04
        if pressed_now and not self._crown_pressed:
            self._crown_pressed = True
            self._crown_rotated_while_pressed = False
            self._cancel_pending_touch()   # a click consumes the preceding touch

        ratchet = params[CROWN_RATCHET_DELTA_IDX]
        if ratchet:
            self._cancel_pending_touch()   # turning is not a discrete touch
            delta = ratchet - 256 if ratchet >= 0x80 else ratchet
            self._crown_accum += delta
            if self._crown_pressed:
                right_key, left_key = "crown_press_right", "crown_press_left"
            else:
                right_key, left_key = "crown_right", "crown_left"
            while self._crown_accum >= CROWN_RATCHET_STEP:
                self._crown_accum -= CROWN_RATCHET_STEP
                self._crown_rotated_while_pressed |= self._crown_pressed
                self._emit_crown(right_key)
            while self._crown_accum <= -CROWN_RATCHET_STEP:
                self._crown_accum += CROWN_RATCHET_STEP
                self._crown_rotated_while_pressed |= self._crown_pressed
                self._emit_crown(left_key)

        # Click = a press that ends without any rotation.
        if self._crown_pressed and not pressed_now:
            if not self._crown_rotated_while_pressed:
                self._emit_crown("crown_tap")
            self._crown_pressed = False
            self._crown_rotated_while_pressed = False

        # Touch start: arm the pending-touch timer (unless already clicking).
        touch_now = params[CROWN_TAP_IDX] == 0x01
        if touch_now and not self._crown_touch_active:
            self._crown_touch_active = True
            if not self._crown_pressed:
                self._arm_touch_timer()
        elif not touch_now and self._crown_touch_active:
            self._crown_touch_active = False

    def _arm_touch_timer(self):
        # Capture the session key so the timer resolves against the right
        # session even after the cursor has moved to another device.
        session_key = self._session_key
        with self._crown_touch_lock:
            self._cancel_pending_touch_locked()
            self._crown_touch_pending = True
            timer = threading.Timer(
                CROWN_TOUCH_CLICK_WINDOW_S, lambda: self._resolve_touch(session_key))
            timer.daemon = True
            self._crown_touch_timer = timer
            timer.start()

    def _resolve_touch(self, session_key=None):
        with self._crown_touch_lock:
            state = self._sessions.get(session_key) if session_key is not None else None
            if state is not None:
                if not state.get("_crown_touch_pending") or state.get("_crown_pressed"):
                    return
                state["_crown_touch_pending"] = False
                state["_crown_touch_timer"] = None
            else:
                if not self._crown_touch_pending or self._crown_pressed:
                    return
                self._crown_touch_pending = False
                self._crown_touch_timer = None
        self._emit_crown("crown_touch")

    def _cancel_pending_touch(self):
        with self._crown_touch_lock:
            self._cancel_pending_touch_locked()

    def _cancel_pending_touch_locked(self):
        self._crown_touch_pending = False
        if self._crown_touch_timer is not None:
            self._crown_touch_timer.cancel()
            self._crown_touch_timer = None

    def _emit_crown(self, button_key):
        print(f"[HidGesture] Crown {button_key}")
        if self._on_crown:
            try:
                self._on_crown(button_key)
            except Exception as exc:
                print(f"[HidGesture] crown callback error: {exc}")

    # ── DPI control ───────────────────────────────────────────────

    def set_dpi(self, dpi_value):
        """Queue a DPI change — will be applied on the listener thread.
        Can be called from any thread.  Returns True on success."""
        dpi = clamp_dpi(dpi_value, self._connected_device_info)
        self._dpi_result = None
        self._pending_dpi = dpi
        # Wait up to 3s for the listener thread to apply it
        for _ in range(30):
            if self._pending_dpi is None:
                return self._dpi_result is True
            time.sleep(0.1)
        print("[HidGesture] DPI set timed out")
        return False

    def _apply_pending_dpi(self):
        """Called from the listener thread to actually send DPI."""
        dpi = self._pending_dpi
        if dpi is None:
            return
        if self._sessions:
            self._load_session_with("_dpi_idx")
        if self._dpi_idx is None or self._dev is None:
            # Device has no Adjustable DPI feature (e.g. a keyboard); skip quietly.
            self._dpi_result = False
            self._pending_dpi = None
            return
        hi = (dpi >> 8) & 0xFF
        lo = dpi & 0xFF
        # setSensorDpi: function 3, params [sensorIdx=0, dpi_hi, dpi_lo]
        # (function 2 = getSensorDpi, function 3 = setSensorDpi)
        resp = self._request(self._dpi_idx, 3, [0x00, hi, lo])
        if resp:
            _, _, _, _, p = resp
            actual = (p[1] << 8 | p[2]) if len(p) >= 3 else dpi
            print(f"[HidGesture] DPI set to {actual}")
            self._dpi_result = True
        else:
            print("[HidGesture] DPI set FAILED")
            self._dpi_result = False
        self._pending_dpi = None

    def read_dpi(self):
        """Queue a DPI read — will be applied on the listener thread.
        Can be called from any thread.  Returns the DPI value or None."""
        self._dpi_result = None
        self._pending_dpi = "read"  # special sentinel
        for _ in range(30):
            if self._pending_dpi is None:
                return self._dpi_result
            time.sleep(0.1)
        print("[HidGesture] DPI read timed out")
        self._pending_dpi = None
        return None

    def _apply_pending_read_dpi(self):
        """Called from the listener thread to read current DPI."""
        if self._sessions:
            self._load_session_with("_dpi_idx")
        if self._dpi_idx is None or self._dev is None:
            self._dpi_result = None
            self._pending_dpi = None
            return
        # getSensorDpi: function 2, params [sensorIdx=0]
        resp = self._request(self._dpi_idx, 2, [0x00])
        if resp:
            _, _, _, _, p = resp
            current = (p[1] << 8 | p[2]) if len(p) >= 3 else None
            print(f"[HidGesture] Current DPI = {current}")
            self._dpi_result = current
        else:
            print("[HidGesture] DPI read FAILED")
            self._dpi_result = None
        self._pending_dpi = None

    # ── Smart Shift control ─────────────────────────────────────

    SMART_SHIFT_FREESPIN = 0x01
    SMART_SHIFT_RATCHET  = 0x02
    # auto_disengage byte: 1-50 → SmartShift active with that sensitivity threshold.
    # 0xFF → fixed ratchet (SmartShift effectively disabled, used by Logi Options+).
    SMART_SHIFT_THRESHOLD_MIN     = 1
    SMART_SHIFT_THRESHOLD_MAX     = 50
    SMART_SHIFT_DISABLE_THRESHOLD = 0xFF

    @property
    def smart_shift_supported(self):
        if self._sessions:
            return any(s.get("_smart_shift_idx") is not None
                       for s in self._sessions.values())
        return self._smart_shift_idx is not None

    @property
    def dpi_supported(self):
        # True when any bound device exposes Adjustable DPI (a mouse). A
        # keyboard-only session has no DPI feature, so a saved DPI value must
        # not be replayed against it (and its absence is not a failure).
        if self._sessions:
            return any(s.get("_dpi_idx") is not None
                       for s in self._sessions.values())
        return self._dpi_idx is not None

    @property
    def backlight_supported(self):
        # Check every bound device, not just the live cursor — in a multi-device
        # session the cursor flips between devices as reports are processed.
        if self._sessions:
            return any(s.get("_backlight_idx") is not None
                       for s in self._sessions.values())
        return self._backlight_idx is not None

    @property
    def crown_present(self):
        """True when any bound device exposes the crown (multi-device safe)."""
        if self._sessions:
            return any(s.get("_crown_idx") is not None
                       for s in self._sessions.values())
        return self._crown_idx is not None

    def set_smart_shift(self, mode, smart_shift_enabled=False, threshold=25):
        """Queue a Smart Shift settings change.
        mode: 'ratchet' or 'freespin' (fixed mode when smart_shift_enabled=False)
        smart_shift_enabled: True to enable auto SmartShift (auto-switching)
        threshold: 1-50 sensitivity when SmartShift is enabled
        Can be called from any thread.  Returns True on success."""
        pending = (mode, smart_shift_enabled, threshold)
        with self._smart_shift_call_lock:
            with self._smart_shift_slot_lock:
                self._smart_shift_result = None
                self._pending_smart_shift = pending
                self._smart_shift_event.clear()
            if not self._smart_shift_event.wait(3):
                with self._smart_shift_slot_lock:
                    if self._pending_smart_shift == pending:
                        self._smart_shift_result = False
                        self._pending_smart_shift = None
                        self._smart_shift_event.set()
                print("[HidGesture] Smart Shift set timed out")
                return False
            with self._smart_shift_slot_lock:
                return self._smart_shift_result is True

    def _apply_pending_smart_shift(self):
        with self._smart_shift_slot_lock:
            pending = self._pending_smart_shift
        if pending is None:
            return
        if self._sessions:
            self._load_session_with("_smart_shift_idx")
        if self._smart_shift_idx is None or self._dev is None:
            print("[HidGesture] Cannot set Smart Shift — not connected")
            self._finish_pending_smart_shift(None if pending == "read" else False)
            return
        if pending == "read":
            self._apply_pending_read_smart_shift()
            return
        mode, smart_shift_enabled, threshold = pending
        # Function IDs differ between basic (0x2110) and enhanced (0x2111):
        #   enhanced: read fn=1, write fn=2
        #   basic:    read fn=0, write fn=1
        write_fn = 2 if self._smart_shift_enhanced else 1
        if smart_shift_enabled:
            # SmartShift enabled: mode=ratchet (0x02) + autoDisengage threshold (1-50).
            # Sending mode=0x02 explicitly avoids "no-change" ambiguity with 0x00.
            threshold = max(self.SMART_SHIFT_THRESHOLD_MIN,
                            min(self.SMART_SHIFT_THRESHOLD_MAX, int(threshold)))
            resp = self._request(self._smart_shift_idx, write_fn,
                                 [self.SMART_SHIFT_RATCHET, threshold, 0x00])
            label = f"SmartShift enabled (threshold={threshold})"
        elif mode == "freespin":
            resp = self._request(self._smart_shift_idx, write_fn,
                                 [self.SMART_SHIFT_FREESPIN, 0x00, 0x00])
            label = "fixed freespin"
        else:
            # Disable SmartShift + fixed ratchet: threshold=0xFF means always-ratchet
            # (matches Solaar's max-threshold approach; hardware ignores auto_disengage for mode writes).
            resp = self._request(self._smart_shift_idx, write_fn,
                                 [self.SMART_SHIFT_RATCHET, self.SMART_SHIFT_DISABLE_THRESHOLD, 0x00])
            label = "fixed ratchet (SmartShift disabled)"
        if resp:
            print(f"[HidGesture] Smart Shift set to {label}")
            result = True
        else:
            print("[HidGesture] Smart Shift set FAILED")
            result = False
        self._finish_pending_smart_shift(result)

    def force_reconnect(self):
        """Request the listener thread to drop and re-establish the HID++ connection.

        Thread-safe: sets a flag checked at the top of the inner event loop.
        The loop raises IOError, which triggers full cleanup + _try_connect(),
        re-applying all button diverts (including CID 0x00C4).
        """
        self._reconnect_requested = True

    def read_smart_shift(self):
        """Queue a Smart Shift read.
        Returns dict {'mode': str, 'enabled': bool, 'threshold': int} or None."""
        with self._smart_shift_call_lock:
            with self._smart_shift_slot_lock:
                self._smart_shift_result = None
                self._pending_smart_shift = "read"
                self._smart_shift_event.clear()
            if not self._smart_shift_event.wait(3):
                with self._smart_shift_slot_lock:
                    if self._pending_smart_shift == "read":
                        self._smart_shift_result = None
                        self._pending_smart_shift = None
                        self._smart_shift_event.set()
                print("[HidGesture] Smart Shift read timed out")
                return None
            with self._smart_shift_slot_lock:
                return self._smart_shift_result

    def _finish_pending_smart_shift(self, result):
        with self._smart_shift_slot_lock:
            self._smart_shift_result = result
            self._pending_smart_shift = None
            self._smart_shift_event.set()

    def _abort_pending_smart_shift(self):
        with self._smart_shift_slot_lock:
            pending = self._pending_smart_shift
            if pending is None:
                self._smart_shift_result = None
                return
            self._smart_shift_result = None if pending == "read" else False
            self._pending_smart_shift = None
            self._smart_shift_event.set()

    def _apply_pending_read_smart_shift(self):
        if self._smart_shift_idx is None or self._dev is None:
            self._finish_pending_smart_shift(None)
            return
        # enhanced (0x2111): read fn=1; basic (0x2110): read fn=0
        read_fn = 1 if self._smart_shift_enhanced else 0
        resp = self._request(self._smart_shift_idx, read_fn, [])
        if resp:
            _, _, _, _, p = resp
            mode_byte = p[0] if p else 0
            auto_disengage = p[1] if len(p) > 1 else 0
            print(f"[HidGesture] Smart Shift raw: mode=0x{mode_byte:02X} auto_disengage=0x{auto_disengage:02X}")
            # Freespin mode means fixed free-spin — SmartShift auto-switching is always OFF.
            # The device preserves the auto_disengage byte in freespin state, so we must
            # not use it to infer enabled=True; only ratchet mode can have SmartShift active.
            # For ratchet: auto_disengage 1-50 → SmartShift active; 0 or ≥51 → disabled.
            mode = "freespin" if mode_byte == self.SMART_SHIFT_FREESPIN else "ratchet"
            if mode == "freespin":
                threshold = auto_disengage if self.SMART_SHIFT_THRESHOLD_MIN <= auto_disengage <= self.SMART_SHIFT_THRESHOLD_MAX else 25
                result = {"mode": "freespin", "enabled": False, "threshold": threshold}
            elif self.SMART_SHIFT_THRESHOLD_MIN <= auto_disengage <= self.SMART_SHIFT_THRESHOLD_MAX:
                result = {"mode": "ratchet", "enabled": True, "threshold": auto_disengage}
            else:
                result = {"mode": "ratchet", "enabled": False, "threshold": 25}
            print(f"[HidGesture] Smart Shift state = {result}")
            self._finish_pending_smart_shift(result)
        else:
            print("[HidGesture] Smart Shift read FAILED")
            self._finish_pending_smart_shift(None)

    def read_battery(self):
        """Queue a battery read and wait for the listener thread result."""
        self._battery_result = None
        self._pending_battery = "read"
        for _ in range(30):
            if self._pending_battery is None:
                return self._battery_result
            time.sleep(0.1)
        print("[HidGesture] Battery read timed out")
        self._pending_battery = None
        return None

    def read_all_batteries(self):
        """Queue a per-device battery read; return {device_type: level}."""
        self._battery_result = None
        self._pending_battery = "read_all"
        for _ in range(30):
            if self._pending_battery is None:
                return self._battery_result or {}
            time.sleep(0.1)
        print("[HidGesture] Battery read timed out")
        self._pending_battery = None
        return {}

    def _read_current_battery(self):
        """Read the battery level for the currently loaded cursor (or None)."""
        if self._battery_idx is None or self._dev is None:
            return None
        func = 1 if self._battery_feature_id == FEAT_UNIFIED_BATT else 0
        label = "unified" if func == 1 else "status"
        resp = self._request(self._battery_idx, func, [])
        if not resp:
            return None
        _, _, _, _, params = resp
        level = params[0] if params else None
        if level is None or not (0 <= level <= 100):
            return None
        if level != self._last_logged_battery:
            print(f"[HidGesture] Battery ({label}): {level}%")
            self._last_logged_battery = level
        return level

    def _apply_pending_read_battery(self):
        """Called from the listener thread to read current battery level."""
        if self._sessions:
            self._load_session_with("_battery_idx")
        self._battery_result = self._read_current_battery()
        self._pending_battery = None

    def _apply_pending_read_battery_all(self):
        """Read every device session's battery, keyed by device type."""
        results = {}
        if self._sessions:
            saved = self._snapshot_cursor()
            for dev_idx in list(self._sessions):
                self._load_cursor(self._sessions[dev_idx])
                level = self._read_current_battery()
                if level is not None:
                    results[self._device_type or "mouse"] = level
                # Persist any updated last-logged value back to the session.
                self._sessions[dev_idx] = self._snapshot_cursor()
            self._load_cursor(saved)
        else:
            level = self._read_current_battery()
            if level is not None:
                results[self._device_type or "mouse"] = level
        self._battery_result = results
        self._pending_battery = None

    # ── notification handling ─────────────────────────────────────

    @staticmethod
    def _decode_s16(hi, lo):
        value = (hi << 8) | lo
        if value & 0x8000:
            value -= 0x10000
        return value

    def _force_release_stale_holds(self):
        """Synthesize UP events for any buttons stuck in the held state, across
        every device session.

        Called from the main loop when consecutive _rx() calls return no data,
        indicating a device may have stalled or gone to sleep while a button
        was physically held.
        """
        for s in (list(self._sessions.values()) if self._sessions else [None]):
            if s is not None:
                self._load_cursor(s)
            changed = False
            if self._held:
                self._held = False
                changed = True
                print("[HidGesture] Gesture force-released (stale hold)")
                if self._on_up:
                    try:
                        self._on_up()
                    except Exception:
                        pass
            for info in self._extra_diverts.values():
                if info["held"]:
                    info["held"] = False
                    changed = True
                    cb = info.get("on_up")
                    if cb:
                        print("[HidGesture] Extra button force-released (stale hold)")
                        try:
                            cb()
                        except Exception:
                            pass
            if s is not None and changed:
                self._sessions[self._session_key] = self._snapshot_cursor()

    _CURSOR_FIELDS = (
        "_dev", "_session_key",
        "_dev_idx", "_feat_idx", "_dpi_idx", "_smart_shift_idx",
        "_smart_shift_enhanced", "_battery_idx", "_battery_feature_id",
        "_wheel_feature_indexes", "_crown_idx", "_gesture_cid",
        "_gesture_candidates", "_rawxy_enabled", "_held", "_crown_accum",
        "_crown_pressed", "_crown_rotated_while_pressed", "_crown_touch_active",
        "_crown_touch_pending", "_crown_touch_timer", "_extra_diverts",
        "_last_controls", "_connected_device_info", "_crown_smooth_pref",
        "_backlight_idx", "_backlight_pref",
        "_last_logged_battery", "_device_type",
    )

    def _snapshot_cursor(self):
        return {f: getattr(self, f) for f in self._CURSOR_FIELDS}

    def _load_cursor(self, session):
        for f in self._CURSOR_FIELDS:
            setattr(self, f, session[f])

    def _on_report(self, raw):
        """Route an incoming HID++ report to its device session, then process."""
        msg = _parse(raw)
        if msg is None:
            return
        dev_idx, feat, func, _sw, params = msg
        if self._sessions:
            key = self._route_session_key(dev_idx)
            if key is None:
                return  # report from a device we are not managing
            self._load_cursor(self._sessions[key])
            try:
                self._process_report(feat, func, params)
            finally:
                self._sessions[key] = self._snapshot_cursor()
            return
        # During connect (no sessions yet) process against the live cursor.
        self._process_report(feat, func, params)

    def _route_session_key(self, dev_idx):
        """Session key for an incoming report's device-index.

        Bluetooth devices all report on device-index 0xFF, so the handle the
        report was read from (self._dev) disambiguates them; a USB receiver
        instead shares one handle across device-indexes 1..6. Match on both
        handle and device-index first, then fall back to device-index alone."""
        for key, s in self._sessions.items():
            if s.get("_dev_idx") == dev_idx and s.get("_dev") is self._dev:
                return key
        for key, s in self._sessions.items():
            if s.get("_dev_idx") == dev_idx:
                return key
        return None

    def _process_report(self, feat, func, params):
        """Process a parsed report against the current cursor device state."""
        if self._crown_idx is not None and feat == self._crown_idx and func == 0:
            self._handle_crown(params)
            return

        if feat != self._feat_idx:
            return

        if func == 1:
            if not self._rawxy_enabled:
                return
            if len(params) < 4 or not self._held:
                return
            dx = self._decode_s16(params[0], params[1])
            dy = self._decode_s16(params[2], params[3])
            if (dx or dy) and self._on_move:
                try:
                    self._on_move(dx, dy)
                except Exception as e:
                    print(f"[HidGesture] move callback error: {e}")
            return

        if func != 0:
            return

        # Params: sequential CID pairs terminated by 0x0000
        cids = set()
        i = 0
        while i + 1 < len(params):
            c = (params[i] << 8) | params[i + 1]
            if c == 0:
                break
            cids.add(c)
            i += 2

        gesture_now = self._gesture_cid in cids

        if gesture_now and not self._held:
            self._held = True
            print("[HidGesture] Gesture DOWN")
            if self._on_down:
                try:
                    self._on_down()
                except Exception as e:
                    print(f"[HidGesture] down callback error: {e}")

        elif not gesture_now and self._held:
            self._held = False
            print("[HidGesture] Gesture UP")
            if self._on_up:
                try:
                    self._on_up()
                except Exception as e:
                    print(f"[HidGesture] up callback error: {e}")

        # Check extra diverted CIDs (e.g. mode shift)
        for cid, info in self._extra_diverts.items():
            btn_now = cid in cids
            if btn_now and not info["held"]:
                info["held"] = True
                print(f"[HidGesture] Extra {_format_cid(cid)} DOWN")
                cb = info.get("on_down")
                if cb:
                    try:
                        cb()
                    except Exception as e:
                        print(f"[HidGesture] extra down callback error: {e}")
            elif not btn_now and info["held"]:
                info["held"] = False
                print(f"[HidGesture] Extra {_format_cid(cid)} UP")
                cb = info.get("on_up")
                if cb:
                    try:
                        cb()
                    except Exception as e:
                        print(f"[HidGesture] extra up callback error: {e}")

    # ── connect / main loop ───────────────────────────────────────

    def _reset_device_cursor(self, device_spec):
        """Reset the per-device cursor before discovering a device-index, so a
        device never inherits a previous device's feature indexes/state."""
        self._feat_idx = None
        self._dpi_idx = None
        self._smart_shift_idx = None
        self._smart_shift_enhanced = False
        self._battery_idx = None
        self._battery_feature_id = None
        self._wheel_feature_indexes = {}
        self._crown_idx = None
        self._backlight_idx = None
        self._crown_accum = 0
        self._crown_pressed = False
        self._crown_rotated_while_pressed = False
        self._crown_touch_active = False
        self._cancel_pending_touch()
        self._gesture_cid = DEFAULT_GESTURE_CID
        self._gesture_candidates = list(
            getattr(device_spec, "gesture_cids", ()) or DEFAULT_GESTURE_CIDS
        )
        self._rawxy_enabled = False
        self._held = False
        self._last_controls = []
        self._connected_device_info = None
        self._last_logged_battery = None
        self._device_type = getattr(device_spec, "device_type", "mouse") or "mouse"
        self._extra_diverts = {
            cid: dict(info) for cid, info in self._base_extra_diverts.items()
        }

    def _try_connect(self):
        """Open the vendor HID collection(s), discover features, divert. Binds
        ALL HID++ devices as per-device sessions (multiplexer): every device on
        a USB receiver's single handle, plus each direct Bluetooth device on its
        own handle."""
        self._sessions = {}
        self._primary_session = None
        self._next_session_key = 0
        infos = self._vendor_hid_infos()
        if not infos:
            return False

        # Try direct devices (Bluetooth) before USB receivers, which require
        # scanning multiple slots with slow timeouts. Within a device, prefer
        # the HID++ 2.0 long-report collection (UP 0xFF00, usage 0x0002) where
        # feature access works, so we don't burn ~14s per wrong interface first
        # (e.g. the proprietary/DJ collections on a Unifying receiver).
        def _direct_device_first(info):
            name = (info.get("product_string") or "").lower()
            up = int(info.get("usage_page", 0) or 0)
            usage = int(info.get("usage", 0) or 0)
            if up == 0xFF00 and usage == 0x0002:
                iface_rank = 0
            elif up == 0xFF00 and usage == 0x0001:
                iface_rank = 1
            elif up == 0xFF00:
                iface_rank = 2
            else:
                iface_rank = 3
            return (1 if "receiver" in name else 0, iface_rank, name)

        infos.sort(key=_direct_device_first)

        print(f"[HidGesture] Backend preference: {_BACKEND_PREFERENCE}")
        print(f"[HidGesture] Candidate HID interfaces: {len(infos)}")
        for info in infos:
            pid = int(info.get("product_id", 0) or 0)
            up = int(info.get("usage_page", 0) or 0)
            usage = int(info.get("usage", 0) or 0)
            transport = info.get("transport")
            source = info.get("source", "unknown")
            product = info.get("product_string") or "?"
            path = _device_path_display(info.get("path"))
            print(f"[HidGesture] Candidate PID=0x{pid:04X} UP=0x{up:04X} "
                  f"usage=0x{usage:04X} transport={transport or '-'} "
                  f"source={source} product={product} path={path or '-'}")

        # Direct (Bluetooth) devices already bound via one of their HID
        # collections; skip their remaining collections so a device is not bound
        # twice (each BLE device exposes several 0xFF00 collections).
        bound_direct_keys = set()
        for info in infos:
            pid = info.get("product_id", 0)
            up = info.get("usage_page", 0)
            usage = info.get("usage", 0)
            product = info.get("product_string")
            source = info.get("source", "unknown")
            is_receiver = "receiver" in (product or "").lower()
            phys_key = None
            if not is_receiver:
                phys_key = self._physical_device_key(info)
                if phys_key in bound_direct_keys:
                    continue  # this direct device is already bound
            device_spec = resolve_device(product_id=pid, product_name=product)
            self._feat_idx = None
            self._dpi_idx = None
            self._smart_shift_idx = None
            self._battery_idx = None
            self._battery_feature_id = None
            self._wheel_feature_indexes = {}
            self._crown_idx = None
            self._crown_accum = 0
            self._crown_pressed = False
            self._crown_rotated_while_pressed = False
            self._crown_touch_active = False
            self._cancel_pending_touch()
            self._gesture_cid = DEFAULT_GESTURE_CID
            self._gesture_candidates = list(
                getattr(device_spec, "gesture_cids", ()) or DEFAULT_GESTURE_CIDS
            )
            self._rawxy_enabled = False
            opened_transport = None
            opened_up = int(up or 0)
            opened_usage = int(usage or 0)
            opened_path = ""
            open_attempts = []
            # On macOS, prefer IOKit (non-exclusive access) over hidapi
            # which may lock the device and freeze the cursor.
            if (
                sys.platform == "darwin"
                and _MAC_NATIVE_OK
                and _BACKEND_PREFERENCE in ("auto", "iokit")
            ):
                open_attempts.extend([
                    ("iokit-exact", info),
                    ("iokit-ble", {
                        "product_id": pid,
                        "usage_page": 0,
                        "usage": 0,
                        "transport": "Bluetooth Low Energy",
                    }),
                ])
            if _BACKEND_PREFERENCE in ("auto", "hidapi") and info.get("path"):
                open_attempts.append(("hidapi", info))

            for transport, open_info in open_attempts:
                try:
                    if transport.startswith("iokit"):
                        d = _MacNativeHidDevice(
                            pid,
                            usage_page=open_info.get("usage_page", 0),
                            usage=open_info.get("usage", 0),
                            transport=open_info.get("transport"),
                        )
                        d.open()
                    else:
                        if not HIDAPI_OK:
                            continue
                        if sys.platform.startswith("linux"):
                            path = open_info.get("path")
                            _log_once(
                                ("hid-path-access", _device_path_display(path)),
                                "[HidGesture] HID path access before open: "
                                f"{_format_linux_device_access(path)}",
                            )
                        if _HID_API_STYLE == "hidapi":
                            d = _hid.device()
                            d.open_path(open_info["path"])
                        else:
                            d = _HidDeviceCompat(open_info["path"])
                        d.set_nonblocking(False)
                    self._dev = d
                    opened_transport = open_info.get("transport") or transport
                    opened_up = int(open_info.get("usage_page", up) or 0)
                    opened_usage = int(open_info.get("usage", usage) or 0)
                    opened_path = _device_path_display(open_info.get("path"))
                    print(f"[HidGesture] Opened PID=0x{pid:04X} via {transport}")
                    break
                except Exception as exc:
                    print(f"[HidGesture] Can't open PID=0x{pid:04X} "
                          f"UP=0x{int(open_info.get('usage_page', up) or 0):04X} "
                          f"usage=0x{int(open_info.get('usage', usage) or 0):04X} "
                          f"via {transport}: {exc}")
                    self._dev = None
            if self._dev is None:
                continue

            # Enable receiver-level HID++ notifications once: needed both for
            # crown delivery AND for device arrival/departure (hot-plug) events.
            self._enable_receiver_notifications(pid)

            # A USB receiver multiplexes paired devices on slots 1-6; a direct
            # (Bluetooth) device answers only on 0xFF. Prefer probing just the
            # slots the receiver announces, so we neither stall on empty slots
            # nor miss an idle device that needs a longer wake timeout.
            if is_receiver:
                announced = self._discover_receiver_slots()
                scan_slots = tuple(announced) if announced else (1, 2, 3, 4, 5, 6)
                # Only populated slots are probed when announced, so we can give
                # an idle device a long wake timeout without stalling overall.
                scan_timeout = 3000 if announced else 1200
            else:
                scan_slots = (BT_DEV_IDX,)
                scan_timeout = 2000
            reprog_found = False
            hidpp_name = None
            sessions_before = len(self._sessions)
            for idx in scan_slots:
                self._dev_idx = idx
                fi = self._find_feature(FEAT_REPROG_V4, timeout_ms=scan_timeout)
                if fi is not None:
                    reprog_found = True
                    # Resolve this specific device-index (the HID++ name is
                    # per-device) and start from a fresh cursor so one device
                    # never inherits another's feature indexes (multiplexer).
                    idx_spec = resolve_device(product_id=pid, product_name=product)
                    self._reset_device_cursor(idx_spec)
                    self._dev_idx = idx
                    self._feat_idx = fi
                    print(f"[HidGesture] Found REPROG_V4 @0x{fi:02X}  "
                          f"PID=0x{pid:04X} devIdx=0x{idx:02X}")
                    # Query actual device name via HID++ (resolves
                    # USB receivers that report a generic PID/name).
                    hidpp_name = self._query_device_name()
                    if hidpp_name:
                        print(f"[HidGesture] HID++ device name: '{hidpp_name}'")
                        idx_spec = resolve_device(
                            product_id=pid, product_name=hidpp_name,
                        ) or idx_spec
                        self._gesture_candidates = list(
                            getattr(idx_spec, "gesture_cids", ())
                            or DEFAULT_GESTURE_CIDS
                        )
                    self._device_type = (
                        getattr(idx_spec, "device_type", "mouse") or "mouse"
                    )
                    controls = self._discover_reprog_controls()
                    self._last_controls = controls
                    self._gesture_candidates = self._choose_gesture_candidates(
                        controls,
                        device_spec=idx_spec,
                    )
                    print("[HidGesture] Gesture CID candidates: "
                          + ", ".join(_format_cid(cid) for cid in self._gesture_candidates))
                    # Also discover ADJUSTABLE_DPI and SMART_SHIFT
                    dpi_fi = self._find_feature(FEAT_ADJ_DPI)
                    if dpi_fi:
                        self._dpi_idx = dpi_fi
                        print(f"[HidGesture] Found ADJUSTABLE_DPI @0x{dpi_fi:02X}")
                    # Prefer 0x2111 (Enhanced) — used by MX Master 3/3S/4 and Logi Options+.
                    # Fall back to 0x2110 (basic) for older devices.
                    ss_fi = self._find_feature(FEAT_SMART_SHIFT_ENHANCED)
                    if ss_fi:
                        self._smart_shift_idx = ss_fi
                        self._smart_shift_enhanced = True
                        print(f"[HidGesture] Found SMART_SHIFT_ENHANCED @0x{ss_fi:02X}")
                    else:
                        ss_fi = self._find_feature(FEAT_SMART_SHIFT)
                        if ss_fi:
                            self._smart_shift_idx = ss_fi
                            self._smart_shift_enhanced = False
                            print(f"[HidGesture] Found SMART_SHIFT (basic) @0x{ss_fi:02X}")
                    for wheel_feature in (
                        FEAT_HIRES_WHEEL,
                        FEAT_HIRES_WHEEL_ENHANCED,
                        FEAT_LOWRES_WHEEL,
                        FEAT_THUMB_WHEEL,
                    ):
                        wheel_fi = self._find_feature(wheel_feature)
                        if wheel_fi:
                            self._wheel_feature_indexes[wheel_feature] = wheel_fi
                            print(
                                f"[HidGesture] Found wheel feature "
                                f"0x{wheel_feature:04X} @0x{wheel_fi:02X}"
                            )
                    batt_fi = self._find_feature(FEAT_UNIFIED_BATT)
                    if batt_fi:
                        self._battery_idx = batt_fi
                        self._battery_feature_id = FEAT_UNIFIED_BATT
                        print(f"[HidGesture] Found UNIFIED_BATT @0x{batt_fi:02X}")
                    else:
                        batt_fi = self._find_feature(FEAT_BATTERY_STATUS)
                        if batt_fi:
                            self._battery_idx = batt_fi
                            self._battery_feature_id = FEAT_BATTERY_STATUS
                            print(f"[HidGesture] Found BATTERY_STATUS @0x{batt_fi:02X}")
                    # Probe + divert the crown dial (Logitech Craft). Reliable
                    # crown delivery requires enabling the receiver's
                    # NOTIFICATIONS register first.
                    crown_ok = False
                    if self._find_crown() is not None:
                        crown_ok = self._divert_crown()
                    # Probe the keyboard backlight (BACKLIGHT2). No divert needed;
                    # just locate it so set_backlight() can drive it.
                    self._find_backlight()

                    # Bind if we can divert the gesture button OR the crown.
                    # Keyboards have no gesture CID, so gesture divert fails on
                    # them: the Craft still binds via its crown, but a plain
                    # keyboard (e.g. MX Keys) has neither a gesture button nor a
                    # crown. Classify it from its HID++ profile and bind it
                    # anyway — its top-row keys are diverted on demand once the
                    # user remaps them, so it just needs to claim a session and
                    # appear on the Keyboard page.
                    gesture_ok = self._divert()
                    device_kind = classify_device_kind(
                        product_name=hidpp_name or product,
                        discovered_features=self._discovered_feature_inventory(),
                        reprog_controls=controls,
                    )
                    keyboard_ok = device_kind == "keyboard"
                    if gesture_ok or crown_ok or keyboard_ok:
                        self._divert_extras()
                        if idx == BT_DEV_IDX:
                            actual_transport = "Bluetooth"
                        elif pid == BOLT_RECEIVER_PID:
                            actual_transport = "Logi Bolt"
                        else:
                            actual_transport = "USB Receiver"
                        self._connected_device_info = build_connected_device_info(
                            product_id=pid,
                            product_name=hidpp_name or product,
                            transport=actual_transport,
                            source=source,
                            gesture_cids=self._gesture_candidates,
                            reprog_controls=controls,
                            active_gesture_cid=self._gesture_cid,
                            gesture_rawxy_enabled=self._rawxy_enabled,
                            discovered_features=self._discovered_feature_inventory(),
                            device_identity={
                                "device_index": self._dev_idx,
                                "usage_page": opened_up,
                                "usage": opened_usage,
                                "backend": transport,
                                "hid_module": _HID_MODULE_NAME or "",
                                "device_path": opened_path,
                            },
                        )
                        # Authoritative device type: catalog when recognized,
                        # otherwise the auto-classification computed above.
                        self._device_type = (
                            self._connected_device_info.device_type
                        )
                        # Save this device under a unique session key (device
                        # indexes are not unique across Bluetooth handles, which
                        # all report on 0xFF) and keep scanning for more devices.
                        self._session_key = self._next_session_key
                        self._next_session_key += 1
                        self._sessions[self._session_key] = self._snapshot_cursor()
                        if self._primary_session is None:
                            self._primary_session = self._session_key
                        print(f"[HidGesture] Bound {self._device_type} "
                              f"'{hidpp_name or product}' @devIdx=0x{idx:02X} "
                              f"transport={actual_transport} "
                              f"crown={'y' if crown_ok else 'n'} "
                              f"backlight={'y' if self._backlight_idx else 'n'}")
                        if idx == BT_DEV_IDX:
                            # A Bluetooth HID interface represents exactly one
                            # device; additional Bluetooth keyboards/mice surface
                            # as separate interfaces handled by the outer
                            # candidate loop below.
                            break
                        continue
                    continue     # divert failed — try next receiver slot

            bound_this_iface = len(self._sessions) > sessions_before
            if bound_this_iface:
                if is_receiver:
                    # A receiver multiplexes all its devices on this one handle;
                    # its remaining collections would only rediscover the same
                    # devices, so stop scanning candidates.
                    break
                # A direct device keeps its own handle open and we keep scanning
                # the remaining candidates for additional Bluetooth devices.
                if phys_key is not None:
                    bound_direct_keys.add(phys_key)
                continue

            if not reprog_found:
                print(
                    "[HidGesture] Opened candidate but REPROG_V4 was not found "
                    f"on tested devIdx values PID=0x{int(pid or 0):04X} "
                    f"UP=0x{opened_up:04X} usage=0x{opened_usage:04X} "
                    f"transport={opened_transport or '-'} source={source}"
                )

            # Couldn't use this interface — close and try next
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

        # Activate the primary device's cursor/handle; the main loop then polls
        # every distinct session handle (receiver handle + each Bluetooth one).
        if self._sessions:
            self._load_cursor(self._sessions[self._primary_session])
            self._consecutive_request_timeouts = 0
            bound = ", ".join(
                f"{s.get('_device_type', '?')}@0x{int(s.get('_dev_idx', 0) or 0):02X}"
                for s in self._sessions.values()
            )
            print(f"[HidGesture] Bound {len(self._sessions)} device(s) across "
                  f"{len(self._distinct_session_handles())} handle(s) "
                  f"[{bound}] primary={self._primary_session}")
            return True

        return False

    def _main_loop(self):
        """Outer loop: connect → listen → reconnect on error/disconnect."""
        retry_logged = False
        while self._running:
            if not self._try_connect():
                if not retry_logged:
                    print("[HidGesture] No compatible device; retrying in 5 s…")
                    retry_logged = True
                for _ in range(50):
                    if not self._running:
                        return
                    time.sleep(0.1)
                continue
            retry_logged = False

            self._connected = True
            if self._on_connect:
                try:
                    self._on_connect()
                except Exception:
                    pass
            print("[HidGesture] Listening for gesture events…")
            _no_data_count = 0          # consecutive _rx() returning None
            _STALE_HOLD_LIMIT = 3       # force-release held buttons after this many empty reads (~3 s)
            _CONSECUTIVE_TIMEOUT_RECONNECT = 3  # force reconnect after this many request timeouts
            self._consecutive_request_timeouts = 0
            try:
                while self._running:
                    if self._reconnect_requested:
                        self._reconnect_requested = False
                        raise IOError("reconnect requested")
                    # If too many consecutive HID++ requests timed out, the
                    # device likely went to sleep or power-cycled.  Force a
                    # full reconnect so button diverts are re-applied.
                    if self._consecutive_request_timeouts >= _CONSECUTIVE_TIMEOUT_RECONNECT:
                        print(f"[HidGesture] {self._consecutive_request_timeouts} consecutive "
                              f"request timeouts — forcing reconnect")
                        raise IOError("consecutive request timeouts — device likely asleep")
                    # Apply any queued DPI command
                    if self._pending_dpi is not None:
                        if self._pending_dpi == "read":
                            self._apply_pending_read_dpi()
                        else:
                            self._apply_pending_dpi()
                    if self._pending_smart_shift is not None:
                        self._apply_pending_smart_shift()
                    if self._pending_extra_diverts is not None:
                        self._apply_pending_extra_diverts()
                    if self._pending_crown_smooth is not None:
                        self._apply_pending_crown_smooth()
                    if self._pending_backlight is not None:
                        self._apply_pending_backlight()
                    if self._pending_battery is not None:
                        if self._pending_battery == "read_all":
                            self._apply_pending_read_battery_all()
                        else:
                            self._apply_pending_read_battery()
                    self._poll_receiver_notifications()
                    # Poll every distinct session handle. A USB receiver has a
                    # single handle; multiple direct Bluetooth devices each have
                    # their own, so we read from each in turn and let _on_report
                    # route by handle. Split the ~1s budget across handles.
                    handles = self._distinct_session_handles()
                    if not handles and self._dev is not None:
                        handles = [self._dev]
                    per_handle_ms = max(50, 1000 // max(1, len(handles)))
                    got_data = False
                    for handle in handles:
                        self._dev = handle
                        raw = self._rx(per_handle_ms)
                        if raw:
                            got_data = True
                            self._on_report(raw)
                    if got_data:
                        _no_data_count = 0
                    else:
                        _no_data_count += 1
                        # Force-release buttons stuck in held state when the
                        # device stops sending reports (firmware stall / sleep).
                        if _no_data_count >= _STALE_HOLD_LIMIT:
                            self._force_release_stale_holds()
            except Exception as e:
                print(f"[HidGesture] read error: {e}")

            # Cleanup before potential reconnect: undivert + force-release every
            # device session (multiplexer), then the shared handle.
            for s in (list(self._sessions.values()) if self._sessions else [None]):
                if s is not None:
                    self._load_cursor(s)
                self._undivert()
                self._undivert_crown()
                if self._held and self._on_up:
                    try:
                        self._on_up()
                    except Exception:
                        pass
                self._held = False
                for info in self._extra_diverts.values():
                    if info.get("held"):
                        info["held"] = False
                        cb = info.get("on_up")
                        if cb:
                            try:
                                cb()
                            except Exception:
                                pass
                self._cancel_pending_touch()
            # Close every distinct session handle (receiver + each Bluetooth
            # device), then drop the sessions.
            session_handles = self._distinct_session_handles()
            self._sessions = {}
            self._primary_session = None
            self._session_key = None
            self._close_recv_handle()
            for handle in session_handles:
                try:
                    handle.close()
                except Exception:
                    pass
            try:
                if self._dev is not None and not any(
                    self._dev is h for h in session_handles
                ):
                    self._dev.close()
            except Exception:
                pass
            self._dev = None
            self._feat_idx = None
            self._dpi_idx = None
            self._smart_shift_idx = None
            self._battery_idx = None
            self._battery_feature_id = None
            self._wheel_feature_indexes = {}
            self._crown_idx = None
            self._crown_accum = 0
            self._crown_pressed = False
            self._crown_rotated_while_pressed = False
            self._crown_touch_active = False
            self._cancel_pending_touch()
            self._pending_battery = None
            self._pending_dpi = None
            self._dpi_result = None
            self._abort_pending_smart_shift()
            self._last_logged_battery = None
            self._consecutive_request_timeouts = 0
            if self._held:
                self._held = False
                print("[HidGesture] Gesture force-released on disconnect")
                if self._on_up:
                    try:
                        self._on_up()
                    except Exception:
                        pass
            for info in self._extra_diverts.values():
                if info["held"]:
                    info["held"] = False
                    cb = info.get("on_up")
                    if cb:
                        print("[HidGesture] Extra button force-released on disconnect")
                        try:
                            cb()
                        except Exception:
                            pass
            self._gesture_cid = DEFAULT_GESTURE_CID
            self._gesture_candidates = list(DEFAULT_GESTURE_CIDS)
            self._rawxy_enabled = False
            self._connected_device_info = None
            self._reconnect_requested = False
            if self._connected:
                self._connected = False
                if self._on_disconnect:
                    try:
                        self._on_disconnect()
                    except Exception:
                        pass

            if self._running:
                time.sleep(2)
