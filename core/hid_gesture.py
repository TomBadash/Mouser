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

import sys
import queue
import threading
import time

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    build_connected_device_info,
    clamp_dpi,
    resolve_device,
)

try:
    import hid as _hid
    HIDAPI_OK = True
    # On macOS, allow non-exclusive HID access so the mouse keeps working
    if sys.platform == "darwin" and hasattr(_hid, "hid_darwin_set_open_exclusive"):
        _hid.hid_darwin_set_open_exclusive(0)
except ImportError:
    HIDAPI_OK = False

# Support both "pip install hidapi" (hid.device) and "pip install hid" (hid.Device)
_HID_API_STYLE = None
if HIDAPI_OK:
    if hasattr(_hid, 'device'):
        _HID_API_STYLE = "hidapi"
    elif hasattr(_hid, 'Device'):
        _HID_API_STYLE = "hid"


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
    if platform_name == "darwin":
        return "iokit"
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

SHORT_ID       = 0x10        # HID++ short report (7 bytes total)
LONG_ID        = 0x11        # HID++ long  report (20 bytes total)
SHORT_LEN      = 7
LONG_LEN       = 20

BT_DEV_IDX     = 0xFF        # device-index for direct Bluetooth
FEAT_IROOT     = 0x0000
FEAT_REPROG_V4 = 0x1B04      # Reprogrammable Controls V4
FEAT_ADJ_DPI   = 0x2201      # Adjustable DPI
FEAT_SMART_SHIFT          = 0x2110  # Smart Shift basic
FEAT_SMART_SHIFT_ENHANCED = 0x2111  # Smart Shift Enhanced (MX Master 3/3S, MX Master 4)
FEAT_UNIFIED_BATT   = 0x1004      # Unified Battery (preferred)
FEAT_BATTERY_STATUS = 0x1000      # Battery Status (fallback)
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
                 on_connect=None, on_disconnect=None, extra_diverts=None):
        self._on_down       = on_down
        self._on_up         = on_up
        self._on_move       = on_move
        self._on_connect    = on_connect
        self._on_disconnect = on_disconnect
        self._extra_diverts = {
            cid: {**info, "held": False}
            for cid, info in (extra_diverts or {}).items()
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
        self._pending_smart_shift = None
        self._smart_shift_result = None
        self._reconnect_requested = False
        self._pending_battery = None
        self._battery_result = None
        self._last_logged_battery = None
        self._connected_device_info = None
        self._last_controls = []   # REPROG_V4 controls from last connection
        self._consecutive_request_timeouts = 0

    # ── public API ────────────────────────────────────────────────

    def start(self):
        if not HIDAPI_OK and not _MAC_NATIVE_OK:
            print("[HidGesture] no HID backend available; install hidapi")
            return False
        if not HIDAPI_OK and _MAC_NATIVE_OK:
            print("[HidGesture] hidapi unavailable; using native macOS HID backend only")
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
        self._connected_device_info = None
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def connected_device(self):
        return self._connected_device_info

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

        controls = []
        for c in self._last_controls:
            controls.append({
                "index": c["index"],
                "cid": f"0x{c['cid']:04X}",
                "task": f"0x{c['task']:04X}",
                "flags": f"0x{c['flags']:04X}",
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
                for info in _hid.enumerate(LOGI_VID, 0):
                    if info.get("usage_page", 0) >= 0xFF00:
                        add_info(dict(info, source="hidapi-enumerate"))
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
            return None
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                raw = self._rx(min(500, timeout_ms))
            except Exception as exc:
                print(f"[HidGesture] request rx failed feat=0x{feat:02X} func=0x{func:X} "
                      f"params=[{_hex_bytes(req_params)}]: {exc}")
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

    def _find_feature(self, feature_id):
        """Use IRoot (feature 0x0000) to discover a feature index."""
        hi = (feature_id >> 8) & 0xFF
        lo = feature_id & 0xFF
        resp = self._request(0x00, 0, [hi, lo, 0x00])
        if resp:
            _, _, _, _, p = resp
            if p and p[0] != 0:
                return p[0]
        return None

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

    def _divert(self):
        """Divert the selected gesture control and enable raw XY when supported."""
        if self._feat_idx is None:
            return False
        for cid in self._gesture_candidates:
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
            resp = self._set_cid_reporting(cid, 0x03)
            ok = resp is not None
            print(f"[HidGesture] Extra divert {_format_cid(cid)}: "
                  f"{'OK' if ok else 'FAILED'}")

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
        if self._dpi_idx is None or self._dev is None:
            print("[HidGesture] Cannot set DPI — not connected")
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
        return self._smart_shift_idx is not None

    def set_smart_shift(self, mode, smart_shift_enabled=False, threshold=25):
        """Queue a Smart Shift settings change.
        mode: 'ratchet' or 'freespin' (fixed mode when smart_shift_enabled=False)
        smart_shift_enabled: True to enable auto SmartShift (auto-switching)
        threshold: 1-50 sensitivity when SmartShift is enabled
        Can be called from any thread.  Returns True on success."""
        self._smart_shift_result = None
        self._pending_smart_shift = (mode, smart_shift_enabled, threshold)
        for _ in range(30):
            if self._pending_smart_shift is None:
                return self._smart_shift_result is True
            time.sleep(0.1)
        print("[HidGesture] Smart Shift set timed out")
        return False

    def _apply_pending_smart_shift(self):
        pending = self._pending_smart_shift
        if pending is None:
            return
        if self._smart_shift_idx is None or self._dev is None:
            print("[HidGesture] Cannot set Smart Shift — not connected")
            self._smart_shift_result = None if pending == "read" else False
            self._pending_smart_shift = None
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
            self._smart_shift_result = True
        else:
            print("[HidGesture] Smart Shift set FAILED")
            self._smart_shift_result = False
        self._pending_smart_shift = None

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
        self._smart_shift_result = None
        self._pending_smart_shift = "read"
        for _ in range(30):
            if self._pending_smart_shift is None:
                return self._smart_shift_result
            time.sleep(0.1)
        print("[HidGesture] Smart Shift read timed out")
        self._pending_smart_shift = None   # prevent stale processing
        return None

    def _apply_pending_read_smart_shift(self):
        if self._smart_shift_idx is None or self._dev is None:
            self._smart_shift_result = None
            self._pending_smart_shift = None
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
            self._smart_shift_result = result
        else:
            print("[HidGesture] Smart Shift read FAILED")
            self._smart_shift_result = None
        self._pending_smart_shift = None

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

    def _apply_pending_read_battery(self):
        """Called from the listener thread to read current battery level."""
        if self._battery_idx is None or self._dev is None:
            self._battery_result = None
            self._pending_battery = None
            return

        if self._battery_feature_id == FEAT_UNIFIED_BATT:
            resp = self._request(self._battery_idx, 1, [])
            if resp:
                _, _, _, _, params = resp
                level = params[0] if params else None
                if level is not None and 0 <= level <= 100:
                    if level != self._last_logged_battery:
                        print(f"[HidGesture] Battery (unified): {level}%")
                        self._last_logged_battery = level
                    self._battery_result = level
                else:
                    self._battery_result = None
            else:
                self._battery_result = None
        else:
            resp = self._request(self._battery_idx, 0, [])
            if resp:
                _, _, _, _, params = resp
                level = params[0] if params else None
                if level is not None and 0 <= level <= 100:
                    if level != self._last_logged_battery:
                        print(f"[HidGesture] Battery (status): {level}%")
                        self._last_logged_battery = level
                    self._battery_result = level
                else:
                    self._battery_result = None
            else:
                self._battery_result = None

        self._pending_battery = None

    # ── notification handling ─────────────────────────────────────

    @staticmethod
    def _decode_s16(hi, lo):
        value = (hi << 8) | lo
        if value & 0x8000:
            value -= 0x10000
        return value

    def _force_release_stale_holds(self):
        """Synthesize UP events for any buttons stuck in the held state.

        Called from the main loop when consecutive _rx() calls return no data,
        indicating the device may have stalled or gone to sleep while a
        button was physically held.
        """
        if self._held:
            self._held = False
            print("[HidGesture] Gesture force-released (stale hold)")
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
                    print("[HidGesture] Extra button force-released (stale hold)")
                    try:
                        cb()
                    except Exception:
                        pass

    def _on_report(self, raw):
        """Inspect an incoming HID++ report for diverted button / raw XY events."""
        msg = _parse(raw)
        if msg is None:
            return
        _, feat, func, _sw, params = msg

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

    def _try_connect(self):
        """Open the vendor HID collection, discover features, divert."""
        infos = self._vendor_hid_infos()
        if not infos:
            return False

        print(f"[HidGesture] Backend preference: {_BACKEND_PREFERENCE}")
        print(f"[HidGesture] Candidate HID interfaces: {len(infos)}")
        for info in infos:
            pid = int(info.get("product_id", 0) or 0)
            up = int(info.get("usage_page", 0) or 0)
            usage = int(info.get("usage", 0) or 0)
            transport = info.get("transport")
            source = info.get("source", "unknown")
            product = info.get("product_string") or "?"
            print(f"[HidGesture] Candidate PID=0x{pid:04X} UP=0x{up:04X} "
                  f"usage=0x{usage:04X} transport={transport or '-'} "
                  f"source={source} product={product}")

        for info in infos:
            pid = info.get("product_id", 0)
            up = info.get("usage_page", 0)
            usage = info.get("usage", 0)
            product = info.get("product_string")
            source = info.get("source", "unknown")
            device_spec = resolve_device(product_id=pid, product_name=product)
            self._feat_idx = None
            self._dpi_idx = None
            self._smart_shift_idx = None
            self._battery_idx = None
            self._battery_feature_id = None
            self._gesture_cid = DEFAULT_GESTURE_CID
            self._gesture_candidates = list(
                getattr(device_spec, "gesture_cids", ()) or DEFAULT_GESTURE_CIDS
            )
            self._rawxy_enabled = False
            opened_transport = None
            opened_up = int(up or 0)
            opened_usage = int(usage or 0)
            open_attempts = []
            if _BACKEND_PREFERENCE in ("auto", "hidapi") and info.get("path"):
                open_attempts.append(("hidapi", info))
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

            # Try Bluetooth direct (0xFF) first, then Bolt receiver slots
            reprog_found = False
            for idx in (0xFF, 1, 2, 3, 4, 5, 6):
                self._dev_idx = idx
                fi = self._find_feature(FEAT_REPROG_V4)
                if fi is not None:
                    reprog_found = True
                    self._feat_idx = fi
                    print(f"[HidGesture] Found REPROG_V4 @0x{fi:02X}  "
                          f"PID=0x{pid:04X} devIdx=0x{idx:02X}")
                    controls = self._discover_reprog_controls()
                    self._last_controls = controls
                    self._gesture_candidates = self._choose_gesture_candidates(
                        controls,
                        device_spec=device_spec,
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
                    if self._divert():
                        self._divert_extras()
                        self._connected_device_info = build_connected_device_info(
                            product_id=pid,
                            product_name=product,
                            transport=open_info.get("transport") or transport,
                            source=source,
                            gesture_cids=self._gesture_candidates,
                        )
                        return True
                    break        # right device but divert failed
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
                    if self._pending_battery is not None:
                        self._apply_pending_read_battery()
                    raw = self._rx(1000)
                    if raw:
                        _no_data_count = 0
                        self._on_report(raw)
                    else:
                        _no_data_count += 1
                        # Force-release buttons stuck in held state when the
                        # device stops sending reports (firmware stall / sleep).
                        if _no_data_count >= _STALE_HOLD_LIMIT:
                            self._force_release_stale_holds()
            except Exception as e:
                print(f"[HidGesture] read error: {e}")

            # Cleanup before potential reconnect
            self._undivert()
            try:
                if self._dev:
                    self._dev.close()
            except Exception:
                pass
            self._dev = None
            self._feat_idx = None
            self._dpi_idx = None
            self._smart_shift_idx = None
            self._battery_idx = None
            self._battery_feature_id = None
            self._pending_battery = None
            self._pending_dpi = None
            self._pending_smart_shift = None
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
