"""
hid_gesture.py -- Detect Logitech HID++ gesture controls and device features.

Many Logitech mice expose their gesture button and DPI/battery controls only
through the HID++ vendor channel instead of standard OS mouse events. This
module opens the Logitech HID interface, discovers REPROG_CONTROLS_V4 and
related features, diverts the best gesture candidate it can find, and reports
press/release or RawXY movement back to Mouser.

Requires:  pip install hidapi
Falls back gracefully if the package or device are unavailable.
"""

import atexit
import os
import stat
import sys
import queue
import threading
import time
import weakref
from dataclasses import replace as _dataclass_replace

from core.logi_devices import (
    DEFAULT_GESTURE_CIDS,
    _coerce_cid,
    build_connected_device_info,
    clamp_dpi,
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
_ATEXIT_LISTENERS = weakref.WeakSet()
_ATEXIT_REGISTERED = False
_ATEXIT_LOCK = threading.Lock()


# Last-known-good (transport, PID, dev_idx, ...) cache for sub-second
# warm-start device detection. Schema is additive: unknown keys ignored.

_CACHE_SCHEMA_VERSION = 1
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _cache_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/Mouser")
    elif sys.platform.startswith("linux"):
        base = os.environ.get(
            "XDG_CONFIG_HOME",
            os.path.expanduser("~/.config"),
        )
        base = os.path.join(base, "Mouser")
    else:
        base = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "Mouser",
        )
    return base


def _cache_path() -> str:
    return os.path.join(_cache_dir(), "last_device.json")


def _load_last_device_cache() -> dict | None:
    """Read the last-known-good device cache. Returns None on missing,
    malformed, expired, or version-mismatched cache (all treated as
    cache-miss). Never raises."""
    path = _cache_path()
    try:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("version", 0)) != _CACHE_SCHEMA_VERSION:
        return None
    saved_at = float(payload.get("saved_at", 0) or 0)
    if saved_at and (time.time() - saved_at) > _CACHE_TTL_SECONDS:
        return None
    candidate = payload.get("candidate")
    device = payload.get("device")
    if not isinstance(candidate, dict) or not isinstance(device, dict):
        return None
    return payload


def _save_last_device_cache(*, candidate: dict, device: dict) -> None:
    """Atomically persist the last-known-good device tuple. Failures are
    logged but never raised -- caching is a pure speedup."""
    path = _cache_path()
    try:
        import json, tempfile
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        payload = {
            "version": _CACHE_SCHEMA_VERSION,
            "saved_at": time.time(),
            "candidate": candidate,
            "device": device,
        }
        fd, tmp = tempfile.mkstemp(
            prefix=".last_device.", suffix=".tmp",
            dir=os.path.dirname(path),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    except Exception as exc:
        print(f"[HidGesture] Could not save device cache: {exc}")


def _candidate_signature(info) -> dict:
    """Persistent identity fields for cache matching. Path is a hint
    only -- USB ports and IOKit paths can shift between sessions."""
    pid = int(info.get("product_id", 0) or 0)
    return {
        "pid": pid,
        "usage_page": int(info.get("usage_page", 0) or 0),
        "usage": int(info.get("usage", 0) or 0),
        "transport": info.get("transport") or "",
        "source": info.get("source", "unknown"),
        "path": _device_path_display(info.get("path")) or "",
    }


def _candidate_match_score(info, cached_candidate) -> int:
    """Ranking score for a candidate against the cached identity tuple.
    0 = no match, 1 = PID+usage match, 2 = +same source backend,
    3 = +same OS path. Higher score sorts first in the connect order."""
    sig = _candidate_signature(info)
    if sig["pid"] != int(cached_candidate.get("pid", 0) or 0):
        return 0
    if sig["usage_page"] != int(cached_candidate.get("usage_page", 0) or 0):
        return 0
    if sig["usage"] != int(cached_candidate.get("usage", 0) or 0):
        return 0
    score = 1
    cached_source = cached_candidate.get("source") or ""
    if cached_source and sig["source"] == cached_source:
        score += 1
    cached_path = cached_candidate.get("path") or ""
    if cached_path and sig["path"] == cached_path:
        score += 1
    return score


def _candidate_matches_cache(info, cached_candidate) -> bool:
    return _candidate_match_score(info, cached_candidate) > 0


def _atexit_stop_listeners():
    """Best-effort undivert before interpreter exit so a Mouser crash or
    SIGTERM does not leave the device stuck in HID++ divert mode.

    Failures are logged but otherwise tolerated -- atexit runs during
    interpreter teardown when the HID stack may already be partially gone,
    so we never propagate. We do *not* silently swallow: a stuck divert is a
    user-visible bug that the next session needs to diagnose.
    """
    for listener in list(_ATEXIT_LISTENERS):
        try:
            listener.stop()
        except Exception as exc:  # noqa: BLE001 - atexit must never propagate
            print(f"[HidGesture] atexit stop failed for {listener!r}: {exc}")


def _register_atexit_listener(listener):
    global _ATEXIT_REGISTERED
    with _ATEXIT_LOCK:
        _ATEXIT_LISTENERS.add(listener)
        if not _ATEXIT_REGISTERED:
            atexit.register(_atexit_stop_listeners)
            _ATEXIT_REGISTERED = True


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
FEAT_HIRES_WHEEL          = 0x2120  # Hi-Res Wheel (basic / older devices)
FEAT_HIRES_WHEEL_ENHANCED = 0x2121  # Hi-Res Wheel Enhanced (MX Master 3/3S/4 -- divert + hi-res deltas)
FEAT_LOWRES_WHEEL         = 0x2130
FEAT_THUMB_WHEEL          = 0x2150  # Thumbwheel (horizontal thumbwheel divert)
FEAT_UNIFIED_BATT   = 0x1004      # Unified Battery (preferred)
FEAT_DEVICE_NAME    = 0x0005      # Device Name & Type
FEAT_BATTERY_STATUS = 0x1000      # Battery Status (fallback)
FEAT_HAPTIC         = 0x19B0      # Haptic Feedback (MX Master 4)
FEAT_FORCE_SENSING  = 0x19C0      # Force Sensing Button (MX Master 4)
DEFAULT_GESTURE_CID = DEFAULT_GESTURE_CIDS[0]

# REPROG_V4 ``setCidReporting`` control flags (fn 3 byte 2). The
# protocol packs four bits we ever toggle from this module:
#   bit 0 (0x01) = temporary divert    -- volatile, cleared on disconnect.
#   bit 1 (0x02) = persistent divert   -- survives sleep/wake.
#   bit 4 (0x10) = temporary rawXY     -- forward raw cursor deltas instead
#                                         of the synthesized button click.
#   bit 5 (0x20) = persistent rawXY    -- survives sleep/wake.
# We always set both the volatile and persistent bits so the firmware
# replays our divert across power-saving wake events without needing a
# re-driver round trip. The constants below name the four combinations
# this module emits so call sites no longer read like bare magic bytes.
_DIVERT_BUTTON_ONLY = 0x03  # 0x01 | 0x02       -- divert as button click
_DIVERT_RAW_XY      = 0x33  # 0x01 | 0x02 | 0x10 | 0x20 -- divert + rawXY
_UNDIVERT_BUTTON    = 0x02  # 0x02 only         -- revert button-only divert
_UNDIVERT_RAW_XY    = 0x22  # 0x02 | 0x20       -- revert rawXY divert

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
    # MX Master 4 Sense Panel; divertable rawXY-capable control
    # used as the primary gesture source on the big pad.
    0x01A0: "Sense Panel",
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



def _control_present(controls, cid: int) -> bool:
    """True when ``cid`` appears in the live REPROG_V4 ``controls`` dump.

    Centralizes the catalog-vs-runtime gating invariant: we never attempt to
    divert (or otherwise act on) a CID the firmware does not advertise on the
    current connection.
    """
    if not controls:
        return False
    for control in controls:
        if not isinstance(control, dict):
            continue
        if _coerce_cid(control.get("cid")) == cid:
            return True
    return False


# ── Listener class ────────────────────────────────────────────────

class HidGestureListener:
    """Background thread: diverts the gesture button and listens via HID++."""

    def __init__(self, on_down=None, on_up=None, on_move=None,
                 on_connect=None, on_disconnect=None, extra_diverts=None,
                 on_wheel=None, on_thumbwheel=None,
                 on_thumb_button_down=None, on_thumb_button_up=None,
                 on_thumb_button_move=None):
        self._on_down       = on_down
        self._on_up         = on_up
        self._on_move       = on_move
        self._on_connect    = on_connect
        self._on_disconnect = on_disconnect
        # Accepted for divert+inject-era callers; native-invert never
        # sees wheelMovement / thumbwheelEvent notifications.
        self._on_wheel = on_wheel
        self._on_thumbwheel = on_thumbwheel
        # Optional callbacks for devices with a dedicated thumb_button CID
        # (currently MX Master 4's small HID++ button). Wired after the
        # gesture divert succeeds, only when `LogiDeviceSpec.thumb_button_cid`
        # is set AND it is NOT the active gesture CID.
        self._on_thumb_button_down = on_thumb_button_down
        self._on_thumb_button_up = on_thumb_button_up
        # Movement callback for thumb-button swipe gestures. When enabled,
        # holding the thumb button hands the single rawXY stream from the
        # primary gesture CID over to the thumb CID so hold+move recognizes a
        # direction; released on button-up. ``_rawxy_owner`` says which
        # control the current func=1 movement reports belong to.
        self._on_thumb_button_move = on_thumb_button_move
        self._thumb_rawxy_enabled = False
        self._rawxy_owner = "gesture"   # "gesture" (primary) | "thumb"
        # Static extras (mode_shift, dpi_switch). Action ring extras are
        # added DYNAMICALLY at connect time via `_install_thumb_button_extra`
        # because the choice depends on which CID `_divert` settled on.
        self._static_extra_diverts = dict(extra_diverts or {})
        self._extra_diverts = {
            cid: {**info, "held": False}
            for cid, info in self._static_extra_diverts.items()
        }
        self._thumb_button_cid: int | None = None
        # Per-CID divert acknowledgment: a CID lives in ``_extra_diverts`` from
        # the moment it is installed, but it only joins this set after the
        # firmware acknowledges the ``setCidReporting`` call. ``thumb_button_via_hid``
        # reads off this set so callers never suppress the OS-level BTN_TASK
        # fallback while the device is still emitting it.
        self._extra_divert_acks: set[int] = set()
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
        self._extra_held_during_gesture = False
        # CIDs requiring button-only divert (0x03) instead of the default
        # rawXY-enabled divert (0x33); currently the device's thumb_button
        # CID so it stays usable on the fallback path without freezing
        # the cursor.
        self._button_only_cids: set[int] = set()
        self._pending_dpi = None        # set by set_dpi(), applied in loop
        self._dpi_result  = None        # True/False after apply
        self._dpi_event   = threading.Event()
        self._smart_shift_idx = None      # feature index of SMART_SHIFT / SMART_SHIFT_ENHANCED
        self._smart_shift_enhanced = False  # True → use fn 1/2; False → fn 0/1
        self._wheel_feature_indexes = {}
        self._pending_smart_shift = None
        self._smart_shift_result = None
        self._smart_shift_call_lock = threading.Lock()
        self._smart_shift_slot_lock = threading.Lock()
        self._smart_shift_event = threading.Event()
        self._reconnect_requested = False
        self._pending_battery = None
        self._battery_result = None
        self._battery_event = threading.Event()
        self._last_logged_battery = None
        self._connected_device_info = None
        self._last_controls = []   # REPROG_V4 controls from last connection
        self._consecutive_request_timeouts = 0
        # 0x2121 Hi-Res Wheel + 0x2150 Thumbwheel native-invert state.
        # Lock ordering: outer `_wheel_divert_call_lock` serializes
        # cross-thread callers, inner `_wheel_divert_lock` protects the
        # pending/result slot. The event signals listener-loop completion.
        self._hires_wheel_idx = None
        self._hires_wheel_multiplier = None
        self._thumbwheel_idx = None
        self._thumbwheel_multiplier = None
        self._wheel_divert_target = (False, False)
        self._wheel_divert_state = False
        self._pending_wheel_divert = None
        self._wheel_divert_event = threading.Event()
        self._wheel_divert_lock = threading.Lock()
        self._wheel_divert_call_lock = threading.Lock()
        self._wheel_divert_result = None
        self._tx_lock = threading.Lock()    # serialize concurrent HID writes
        self._haptic_idx = None             # feature index of HAPTIC (0x19B0)
        self._force_sensing_idx = None      # feature index of FORCE_SENSING (0x19C0)
        self._pending_haptic = None
        self._haptic_result = None
        self._haptic_event = threading.Event()
        self._haptic_capabilities = None    # raw bytes from getCapabilities
        self._pending_force_sensing = None
        self._force_sensing_result = None
        self._force_sensing_event = threading.Event()
        self._force_sensing_range = None    # (min_val, max_val, default_val) after probe

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
        _register_atexit_listener(self)
        self._thread = threading.Thread(
            target=self._main_loop, daemon=True, name="HidGesture")
        self._thread.start()
        return True

    def stop(self):
        # Best-effort revert to native non-inverted before tearing down, so a
        # graceful exit leaves the device in firmware default state. We log
        # failures rather than swallow them: a failed revert means the next
        # session will see an unexpected divert state and the user needs the
        # breadcrumb to debug it. We do not propagate -- ``stop`` must always
        # complete the rest of teardown (close device, join thread).
        if self._dev is not None and self._wheel_divert_state:
            try:
                self._set_native_wheel_invert_vertical(False)
            except Exception as exc:  # noqa: BLE001 - teardown must complete
                print(f"[HidGesture] stop: vertical invert revert failed: {exc}")
            try:
                self._set_native_wheel_invert_horizontal(False)
            except Exception as exc:  # noqa: BLE001 - teardown must complete
                print(f"[HidGesture] stop: horizontal invert revert failed: {exc}")
            self._wheel_divert_state = False
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
        if self._haptic_idx is not None:
            features["HAPTIC (0x19B0)"] = f"index 0x{self._haptic_idx:02X}"
        if self._force_sensing_idx is not None:
            features["FORCE_SENSING (0x19C0)"] = f"index 0x{self._force_sensing_idx:02X}"
        for feature_id, index in sorted(self._wheel_feature_indexes.items()):
            features[f"WHEEL (0x{feature_id:04X})"] = f"index 0x{index:02X}"
        if self._hires_wheel_idx is not None:
            features["HIRES_WHEEL_ENHANCED (0x2121) [divert]"] = (
                f"index 0x{self._hires_wheel_idx:02X} "
                f"mul={self._hires_wheel_multiplier}"
            )
        if self._thumbwheel_idx is not None:
            features["THUMB_WHEEL (0x2150) [divert]"] = (
                f"index 0x{self._thumbwheel_idx:02X} "
                f"divertedRes={self._thumbwheel_multiplier}"
            )

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
        with self._tx_lock:
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
        """Use IRoot (feature 0x0000) to discover a feature index.

        `timeout_ms` controls how long to wait for the IRoot response. The
        default of 2000 ms is the safe value for active sessions; during
        the REPROG_V4 discovery probe in `_try_connect` we use a much
        tighter timeout (≈400 ms) because a live HID++ device responds in
        <50 ms and waiting longer just stalls us across non-matching
        receiver slots and candidate interfaces.
        """
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

    def _divert(self):
        """Divert the selected gesture control. RawXY is requested for any
        CID not flagged as button-only in `_button_only_cids`.

        Why per-CID? On MX Master 4 the sense panel (0x01A0) is the
        primary gesture CID and benefits from rawXY (the firmware then
        delivers swipe motion over the vendor channel and pins the cursor
        on its own). The small button (0x00C3) is the thumb_button CID and
        gets diverted button-only as an extra elsewhere -- but if 0x01A0
        divert is rejected we fall back to 0x00C3 as the gesture CID, and
        then we want it button-only so the cursor doesn't freeze every
        time the user clicks the small button. A single button-only flag
        for the whole listener can't express that.

        """
        if self._feat_idx is None:
            return False
        # Fresh divert round — the primary gesture CID owns rawXY until a thumb
        # hold hands it over (guards against a stuck owner across reconnects).
        self._rawxy_owner = "gesture"
        for cid in self._gesture_candidates:
            self._gesture_cid = cid
            button_only = cid in self._button_only_cids
            if not button_only:
                resp = self._set_cid_reporting(cid, _DIVERT_RAW_XY)
                if resp is not None:
                    self._rawxy_enabled = True
                    print(f"[HidGesture] Divert {_format_cid(cid)} with RawXY: OK")
                    return True
            self._rawxy_enabled = False
            resp = self._set_cid_reporting(cid, _DIVERT_BUTTON_ONLY)
            ok = resp is not None
            mode = "button-only (catalog hint)" if button_only else "button-only fallback"
            print(f"[HidGesture] Divert {_format_cid(cid)} ({mode}): "
                  f"{'OK' if ok else 'FAILED'}")
            if ok:
                return True
        self._gesture_cid = DEFAULT_GESTURE_CID
        return False

    def _install_thumb_button_extra(self, device_spec, controls):
        """Wire ``device_spec.thumb_button_cid`` (when set) as a button-only
        extra divert so its press/release fires ``_on_thumb_button_down/up``.

        Must run between ``_divert()`` and ``_divert_extras()`` so the entry
        lands in the same setCidReporting round. Gated against the live
        REPROG_V4 ``controls`` list -- we never install an extra divert for a
        CID the firmware has not advertised, otherwise ``setCidReporting``
        hammers the device for a control that does not exist. Skipped when the
        CID is already the active gesture CID (fallback path).
        """
        if (
            self._thumb_button_cid is not None
            and self._thumb_button_cid not in self._static_extra_diverts
        ):
            self._extra_diverts.pop(self._thumb_button_cid, None)
        self._thumb_button_cid = None
        cid = _coerce_cid(getattr(device_spec, "thumb_button_cid", None))
        if cid is None:
            return
        if cid == self._gesture_cid:
            print(
                f"[HidGesture] Skip thumb_button extra {_format_cid(cid)} "
                f"-- it's already the active gesture CID (fallback path)"
            )
            return
        if not _control_present(controls, cid):
            print(
                f"[HidGesture] Skip thumb_button extra {_format_cid(cid)} "
                f"-- firmware does not advertise this CID in REPROG_V4"
            )
            return
        self._thumb_button_cid = cid
        self._extra_diverts[cid] = {
            "on_down": self._fire_thumb_button_down,
            "on_up": self._fire_thumb_button_up,
            "held": False,
        }

    def set_thumb_rawxy_enabled(self, enabled: bool) -> None:
        """Enable/disable handing the rawXY stream to the thumb button while
        held. Called by the hook when the thumb's tap action is "Do Nothing"
        and at least one thumb swipe direction is mapped."""
        self._thumb_rawxy_enabled = bool(enabled)

    def _thumb_rawxy_acquire(self):
        """Divert the thumb CID with rawXY so hold+move flows to the thumb
        recognizer. Firmware streams rawXY for one control at a time, so this
        implicitly redirects it from the primary gesture CID for the hold."""
        cid = self._thumb_button_cid
        if cid is None or not self._rawxy_enabled:
            return
        resp = self._set_cid_reporting(cid, _DIVERT_RAW_XY)
        if resp is not None:
            self._rawxy_owner = "thumb"
        else:
            print(f"[HidGesture] thumb rawXY acquire FAILED {_format_cid(cid)}")

    def _thumb_rawxy_release(self):
        """Return the thumb CID to button-only so the primary gesture CID
        reclaims the rawXY stream and the OS cursor moves normally again."""
        cid = self._thumb_button_cid
        self._rawxy_owner = "gesture"
        if cid is None:
            return
        self._set_cid_reporting(cid, _DIVERT_BUTTON_ONLY)

    def _fire_thumb_button_down(self):
        if self._thumb_rawxy_enabled:
            self._thumb_rawxy_acquire()
        cb = self._on_thumb_button_down
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            print(f"[HidGesture] thumb_button down callback error: {exc}")

    def _fire_thumb_button_up(self):
        cb = self._on_thumb_button_up
        try:
            if cb is not None:
                cb()
        except Exception as exc:
            print(f"[HidGesture] thumb_button up callback error: {exc}")
        finally:
            if self._rawxy_owner == "thumb":
                self._thumb_rawxy_release()

    @property
    def thumb_button_via_hid(self) -> bool:
        """True when the listener is delivering thumb_button events from a
        HID++ extra divert (rather than the OS-level btn=6 fallback).

        Reads off ``_extra_divert_acks``, not ``_thumb_button_cid``, so the
        property only flips after ``setCidReporting`` is acknowledged. Without
        this gate the hook layer would suppress the OS BTN_TASK path while the
        device is still emitting it, eating the press entirely.
        """
        cid = self._thumb_button_cid
        return cid is not None and cid in self._extra_divert_acks

    @property
    def extra_held_during_gesture(self) -> bool:
        return self._extra_held_during_gesture

    def _divert_extras(self):
        """Divert additional CIDs (e.g. mode shift) without raw XY.

        Tracks per-CID acknowledgment in ``_extra_divert_acks`` so callers
        know which extras the firmware actually took. CIDs that fail the
        setCidReporting call are removed from ``_extra_diverts`` so the loop
        does not later route OS events through a divert handler the firmware
        never installed.
        """
        if self._feat_idx is None:
            return
        self._extra_divert_acks.clear()
        failed: list[int] = []
        for cid in list(self._extra_diverts.keys()):
            resp = self._set_cid_reporting(cid, _DIVERT_BUTTON_ONLY)
            ok = resp is not None
            print(f"[HidGesture] Extra divert {_format_cid(cid)}: "
                  f"{'OK' if ok else 'FAILED'}")
            if ok:
                self._extra_divert_acks.add(cid)
            else:
                failed.append(cid)
        for cid in failed:
            if cid == self._thumb_button_cid:
                self._thumb_button_cid = None
            self._extra_diverts.pop(cid, None)

    def _undivert(self):
        """Restore default button behaviour (best-effort).

        Failures during teardown are logged at debug level rather than
        silently swallowed -- a stuck divert state is a user-visible bug
        and the next session needs the breadcrumb to diagnose it. We
        intentionally never raise here because callers (disconnect path,
        atexit) must complete the rest of teardown regardless.
        """
        if self._feat_idx is None or self._dev is None:
            return
        for cid in self._extra_diverts:
            hi = (cid >> 8) & 0xFF
            lo = cid & 0xFF
            try:
                self._tx(LONG_ID, self._feat_idx, 3,
                         [hi, lo, _UNDIVERT_BUTTON, 0x00, 0x00])
            except Exception as exc:  # noqa: BLE001 - teardown must complete
                print(
                    f"[HidGesture] _undivert: extra {_format_cid(cid)} "
                    f"revert failed: {exc}"
                )
        hi = (self._gesture_cid >> 8) & 0xFF
        lo = self._gesture_cid & 0xFF
        flags = _UNDIVERT_RAW_XY if self._rawxy_enabled else _UNDIVERT_BUTTON
        try:
            self._tx(LONG_ID, self._feat_idx, 3,
                     [hi, lo, flags, 0x00, 0x00])
        except Exception as exc:  # noqa: BLE001 - teardown must complete
            print(
                f"[HidGesture] _undivert: gesture {_format_cid(self._gesture_cid)} "
                f"revert failed: {exc}"
            )
        self._rawxy_enabled = False
        if self._wheel_divert_state:
            try:
                self._set_native_wheel_invert_vertical(False)
            except Exception as exc:  # noqa: BLE001 - teardown must complete
                print(f"[HidGesture] _undivert: vertical invert revert failed: {exc}")
            try:
                self._set_native_wheel_invert_horizontal(False)
            except Exception as exc:  # noqa: BLE001 - teardown must complete
                print(f"[HidGesture] _undivert: horizontal invert revert failed: {exc}")
            self._wheel_divert_state = False

    # ── DPI control ───────────────────────────────────────────────

    def set_dpi(self, dpi_value):
        """Queue a DPI change -- will be applied on the listener thread.
        Can be called from any thread.  Returns True on success."""
        dpi = clamp_dpi(dpi_value, self._connected_device_info)
        self._dpi_result = None
        self._dpi_event.clear()
        self._pending_dpi = dpi
        if not self._dpi_event.wait(3.0):
            print("[HidGesture] DPI set timed out")
            self._pending_dpi = None
            return False
        return self._dpi_result is True

    def _apply_pending_dpi(self):
        """Called from the listener thread to actually send DPI."""
        dpi = self._pending_dpi
        if dpi is None:
            return
        if self._dpi_idx is None or self._dev is None:
            print("[HidGesture] Cannot set DPI -- not connected")
            self._dpi_result = False
            self._pending_dpi = None
            self._dpi_event.set()
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
        self._dpi_event.set()

    def read_dpi(self):
        """Queue a DPI read -- will be applied on the listener thread.
        Can be called from any thread.  Returns the DPI value or None."""
        self._dpi_result = None
        self._dpi_event.clear()
        self._pending_dpi = "read"
        if not self._dpi_event.wait(3.0):
            print("[HidGesture] DPI read timed out")
            self._pending_dpi = None
            return None
        return self._dpi_result

    def _apply_pending_read_dpi(self):
        """Called from the listener thread to read current DPI."""
        if self._dpi_idx is None or self._dev is None:
            self._dpi_result = None
            self._pending_dpi = None
            self._dpi_event.set()
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
        self._dpi_event.set()

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

    @property
    def hires_wheel_supported(self):
        return self._hires_wheel_idx is not None

    @property
    def thumbwheel_supported(self):
        return self._thumbwheel_idx is not None

    @property
    def wheel_divert_active(self):
        """True iff the device acknowledged the divert ON request on the
        current connection. Mirrors the listener-thread internal state."""
        return bool(self._wheel_divert_state)

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
        if self._smart_shift_idx is None or self._dev is None:
            print("[HidGesture] Cannot set Smart Shift -- not connected")
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
            # Freespin mode means fixed free-spin -- SmartShift auto-switching is always OFF.
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

    # 0x2121 setWheelMode (fn 2) bitfield: bit0=target (0=HID, 1=divert),
    # bit1=resolution (0=low, 1=hi-res), bit2=invert. Mouser keeps target
    # and resolution at 0 and only drives bit2 -- hi-res emits fractional
    # events per detent which renders as jumpy scroll on apps without
    # trackpad-class smoothing.
    _WHEEL_MODE_BIT_TARGET     = 0x01
    _WHEEL_MODE_BIT_RESOLUTION = 0x02
    _WHEEL_MODE_BIT_INVERT     = 0x04
    # 0x2150 setThumbwheelReporting (fn 2): [reportingMode, invertDirection].
    _THUMBWHEEL_SET_REPORTING_FN = 2

    def _set_native_wheel_invert_vertical(self, invert: bool) -> bool:
        """Read-modify-write the 0x2121 wheel mode to native low-res with
        the invert bit reflecting `invert`. Listener-thread only. Returns
        True when the device acknowledges the write, or when the feature
        is absent AND no inversion was requested -- claiming success for
        an invert the firmware cannot perform would make the engine
        suppress the OS-layer fallback and lose the inversion entirely."""
        if self._hires_wheel_idx is None:
            return not invert
        if self._dev is None:
            return False
        target_mode = self._WHEEL_MODE_BIT_INVERT if invert else 0x00
        if invert:
            current_resp = self._request(self._hires_wheel_idx, 1, [])
            if current_resp is not None:
                _, _, _, _, params = current_resp
                current_mode = int(params[0]) & 0xFF if params else None
                if current_mode == target_mode:
                    return True
        resp = self._request(self._hires_wheel_idx, 2, [target_mode])
        return resp is not None

    def _set_native_wheel_invert_horizontal(self, invert: bool) -> bool:
        """Set firmware invert on the thumbwheel (0x2150 fn 2) without
        diverting. Listener-thread only. Absent feature counts as success
        only when no inversion was requested (see vertical twin)."""
        if self._thumbwheel_idx is None:
            return not invert
        if self._dev is None:
            return False
        invert_byte = 0x01 if invert else 0x00
        resp = self._request(
            self._thumbwheel_idx,
            self._THUMBWHEEL_SET_REPORTING_FN,
            [0x00, invert_byte],
        )
        return resp is not None

    def _apply_pending_native_wheel_invert(self) -> None:
        """Drain the pending native-invert slot on the listener thread.
        Mirrors the Smart-Shift pattern: on IOError the main loop's
        cleanup calls ``_abort_pending_wheel_divert`` which wakes the
        waiter, so callers never strand."""
        with self._wheel_divert_lock:
            target = self._pending_wheel_divert
        if target is None:
            return
        invert_v, invert_h = target
        no_features = (
            self._hires_wheel_idx is None and self._thumbwheel_idx is None
        )
        if no_features:
            ok_v = ok_h = False
            success = False
        else:
            ok_v = self._set_native_wheel_invert_vertical(invert_v)
            ok_h = self._set_native_wheel_invert_horizontal(invert_h)
            success = bool(ok_v and ok_h)
            if not success:
                # The engine treats failure as "fall back to OS-layer
                # inversion on BOTH axes", so any axis the firmware did
                # apply must be reverted or scrolling double-inverts.
                if ok_v and invert_v:
                    self._set_native_wheel_invert_vertical(False)
                if ok_h and invert_h:
                    self._set_native_wheel_invert_horizontal(False)
        self._wheel_divert_state = bool(success)
        with self._wheel_divert_lock:
            self._wheel_divert_result = success
            self._pending_wheel_divert = None
            self._wheel_divert_event.set()
        if no_features:
            print(
                "[HidGesture] Wheel native invert skipped -- "
                "neither 0x2121 nor 0x2150 available"
            )
        else:
            print(
                f"[HidGesture] Wheel native invert v={invert_v} h={invert_h} "
                f"vertical={'OK' if ok_v else 'FAIL'} "
                f"thumb={'OK' if ok_h else 'FAIL'}"
            )

    def _abort_pending_wheel_divert(self) -> None:
        """Wake any waiter with result=False when the connection drops
        mid-request, and clear stale post-success state so the next
        request starts cleanly. Mirrors `_abort_pending_smart_shift`."""
        with self._wheel_divert_lock:
            had_waiter = self._pending_wheel_divert is not None
            self._wheel_divert_result = False if had_waiter else None
            self._pending_wheel_divert = None
            if had_waiter:
                self._wheel_divert_event.set()

    def set_wheel_divert_active_flags(self, vertical: bool, thumb: bool) -> None:
        """Update the published ConnectedDeviceInfo so external readers
        see which axes are currently inverted at the firmware level.
        ConnectedDeviceInfo is frozen, so this swaps the reference via
        ``dataclasses.replace`` for thread safety."""
        info = self._connected_device_info
        if info is None:
            return
        try:
            self._connected_device_info = _dataclass_replace(
                info,
                hires_wheel_active=bool(vertical),
                thumbwheel_active=bool(thumb),
            )
        except Exception as exc:
            print(f"[HidGesture] set_wheel_divert_active_flags error: {exc}")

    def request_wheel_native_invert(
        self,
        invert_vertical: bool,
        invert_horizontal: bool,
        timeout_s: float = 3.0,
    ) -> bool:
        """Cross-thread API. Ask the device to flip the wheel sign at
        the firmware level (no divert). Blocks until the listener
        applies the write or ``timeout_s`` elapses. ``_wheel_divert_target``
        is cached so reconnect replays the same intent.

        The reconnect-replay cache (``_wheel_divert_target``) is mutated
        *inside* ``_wheel_divert_call_lock`` so two concurrent callers cannot
        interleave updates: whichever caller wins the lock is the one whose
        intent persists across reconnect.
        """
        target = (bool(invert_vertical), bool(invert_horizontal))
        with self._wheel_divert_call_lock:
            self._wheel_divert_target = target
            with self._wheel_divert_lock:
                self._wheel_divert_result = None
                self._pending_wheel_divert = target
                self._wheel_divert_event.clear()
            if not self._wheel_divert_event.wait(timeout_s):
                with self._wheel_divert_lock:
                    if self._pending_wheel_divert is not None:
                        self._wheel_divert_result = False
                        self._pending_wheel_divert = None
                        self._wheel_divert_event.set()
                print("[HidGesture] Wheel native-invert request timed out")
                return False
            with self._wheel_divert_lock:
                return bool(self._wheel_divert_result)

    # ── Haptic Feedback control (0x19B0) ─────────────────────────
    #
    # The HAPTIC feature on MX Master 4 supports vibration level
    # control and waveform playback.  Protocol details:
    #   Function 0: getCapabilities -- returns capability bitmask
    #   Function 1: getState        -- returns current level/mode
    #   Function 2: setState        -- sets haptic level
    #   Function 3: playWaveform    -- triggers a haptic effect
    #
    # Level values observed: 0=subtle, 1=low, 2=medium, 3=high.
    # Waveform IDs are partially unknown; 0 = default click pulse.
    #
    # Fully supported now: feature discovery, level get/set, waveform play.
    # Partial: exact payload semantics for functions 0-3.
    # TODO for future: per-event haptic routing, waveform enumeration,
    #                   Force Sensing Button (0x19C0) integration.

    HAPTIC_LEVEL_SUBTLE = 0
    HAPTIC_LEVEL_LOW    = 1
    HAPTIC_LEVEL_MEDIUM = 2
    HAPTIC_LEVEL_HIGH   = 3
    HAPTIC_WAVEFORM_DEFAULT = 0

    # Maps UI levels (0-3) to the device's 0-100 intensity scale.
    # Derived from Solaar's HapticLevel implementation (feature 0x19B0):
    # Off=0, Low=25, Medium=50, High=75, Maximum=100.
    HAPTIC_DEVICE_LEVELS = {0: 25, 1: 50, 2: 75, 3: 100}

    @property
    def haptic_supported(self):
        return self._haptic_idx is not None

    @property
    def force_sensing_detected(self):
        return self._force_sensing_idx is not None

    @property
    def force_sensing_supported(self):
        return self._force_sensing_idx is not None and self._force_sensing_range is not None

    @property
    def force_sensing_range(self):
        return self._force_sensing_range

    def get_force_sensing(self):
        """Queue a force sensing read. Returns current value (int) or None."""
        self._force_sensing_result = None
        self._force_sensing_event.clear()
        self._pending_force_sensing = "read"
        if not self._force_sensing_event.wait(3.0):
            print("[HidGesture] Force sensing read timed out")
            self._pending_force_sensing = None
            return None
        return self._force_sensing_result

    def set_force_sensing(self, value):
        """Queue a force sensing level change. Returns True on success."""
        rng = self._force_sensing_range
        if rng:
            value = max(rng[0], min(rng[1], int(value)))
        else:
            value = int(value)
        self._force_sensing_result = None
        self._force_sensing_event.clear()
        self._pending_force_sensing = ("set", value)
        if not self._force_sensing_event.wait(3.0):
            print("[HidGesture] Force sensing set timed out")
            self._pending_force_sensing = None
            return False
        return self._force_sensing_result is True

    def _apply_pending_force_sensing(self):
        """Process queued force sensing commands on the listener thread."""
        import struct as _struct
        cmd = self._pending_force_sensing
        if cmd is None:
            return
        if self._force_sensing_idx is None or self._dev is None:
            print("[HidGesture] Cannot process force sensing -- not connected or unsupported")
            self._force_sensing_result = None if isinstance(cmd, str) else False
            self._pending_force_sensing = None
            self._force_sensing_event.set()
            return

        try:
            if cmd == "read":
                resp = self._request(self._force_sensing_idx, 2, [0])
                if resp:
                    _, _, _, _, p = resp
                    current = _struct.unpack("!H", bytes(p[:2]))[0]
                    self._force_sensing_result = current
                    print(f"[HidGesture] Force sensing current: {current}")
                else:
                    self._force_sensing_result = None
                    print("[HidGesture] Force sensing read FAILED")
            elif isinstance(cmd, tuple) and cmd[0] == "set":
                value = cmd[1]
                payload = list(_struct.pack("!BH", 0, value))
                resp = self._request(self._force_sensing_idx, 3, payload)
                self._force_sensing_result = resp is not None
                print(f"[HidGesture] Force sensing set value={value}: "
                      f"{'OK' if self._force_sensing_result else 'FAILED'}")
            else:
                print(f"[HidGesture] Unknown force sensing command: {cmd}")
                self._force_sensing_result = False
        except Exception as exc:
            print(f"[HidGesture] Force sensing command error: {exc}")
            self._force_sensing_result = False
        self._pending_force_sensing = None
        self._force_sensing_event.set()

    def get_haptic_state(self):
        """Queue a haptic state read.  Returns dict or None."""
        self._haptic_result = None
        self._haptic_event.clear()
        self._pending_haptic = "read_state"
        if not self._haptic_event.wait(3.0):
            print("[HidGesture] Haptic state read timed out")
            self._pending_haptic = None
            return None
        return self._haptic_result

    def set_haptic_level(self, level):
        """Queue a haptic level change (0-3).  Returns True on success."""
        level = max(0, min(3, int(level)))
        self._haptic_result = None
        self._haptic_event.clear()
        self._pending_haptic = ("set_level", level)
        if not self._haptic_event.wait(3.0):
            print("[HidGesture] Haptic set level timed out")
            self._pending_haptic = None
            return False
        return self._haptic_result is True

    def play_haptic_waveform(self, waveform_id=0):
        """Queue a haptic waveform play command.  Returns True on success."""
        self._haptic_result = None
        self._haptic_event.clear()
        self._pending_haptic = ("play", int(waveform_id))
        if not self._haptic_event.wait(3.0):
            print("[HidGesture] Haptic play timed out")
            self._pending_haptic = None
            return False
        return self._haptic_result is True

    def queue_haptic_waveform(self, waveform_id=0):
        """Set the pending haptic command without blocking.

        Safe to call from the listener thread itself (e.g. from inside an
        event callback).  The listener loop will pick it up at the top of
        the next iteration, before the next _rx() call, so the pulse fires
        with minimal latency.  Does not wait for a result."""
        if self._haptic_idx is not None and self._dev is not None:
            self._pending_haptic = ("play", int(waveform_id))

    def play_haptic_immediate(self, waveform_id=0):
        """Write a playWaveform command right away, from any thread.

        Unlike queue_haptic_waveform(), this does not wait for the listener
        loop to finish its (up to 1s) blocking read, so a pulse triggered
        off the listener thread -- e.g. an Actions Ring hover from the UI
        thread -- fires immediately instead of lagging behind _rx().  Writes
        are serialized by _tx_lock, so this is safe alongside the listener's
        reads and requests.  Fire-and-forget: the device's response is left
        for the listener to read and ignore."""
        if self._haptic_idx is None or self._dev is None:
            return
        try:
            self._tx(LONG_ID, self._haptic_idx, 4, [int(waveform_id)])
        except Exception as exc:
            print(f"[HidGesture] immediate haptic failed: {exc}")
            self._pending_haptic = ("play", int(waveform_id))

    def _apply_pending_haptic(self):
        """Process queued haptic commands on the listener thread."""
        cmd = self._pending_haptic
        if cmd is None:
            return
        if self._haptic_idx is None or self._dev is None:
            print("[HidGesture] Cannot process haptic -- not connected or unsupported")
            self._haptic_result = None if isinstance(cmd, str) else False
            self._pending_haptic = None
            self._haptic_event.set()
            return

        try:
            if cmd == "read_state":
                resp = self._request(self._haptic_idx, 1, [])
                if resp:
                    _, _, _, _, p = resp
                    # Byte 0: enable flag (bit 0 = enabled/disabled).
                    # Byte 1: device-scale level (0-100).
                    enabled = bool(p[0] & 0x01) if p else False
                    device_level = p[1] if len(p) > 1 else 0
                    # Reverse-map device level to UI level (closest match).
                    ui_level = min(
                        self.HAPTIC_DEVICE_LEVELS,
                        key=lambda k: abs(self.HAPTIC_DEVICE_LEVELS[k] - device_level),
                    )
                    self._haptic_result = {
                        "raw": list(p),
                        "enabled": enabled,
                        "device_level": device_level,
                        "level": ui_level,
                    }
                    print(f"[HidGesture] Haptic state: [{_hex_bytes(p)}] "
                          f"enabled={enabled} device_level={device_level} "
                          f"ui_level={ui_level}")
                else:
                    self._haptic_result = None
                    print("[HidGesture] Haptic state read FAILED")
            elif isinstance(cmd, tuple) and cmd[0] == "set_level":
                level = cmd[1]
                # Function 2: setState.
                # Byte 0: enable flag (0x01 = on).
                # Byte 1: intensity on the 0-100 device scale.
                device_level = self.HAPTIC_DEVICE_LEVELS.get(level, 50)
                resp = self._request(self._haptic_idx, 2, [0x01, device_level])
                self._haptic_result = resp is not None
                print(f"[HidGesture] Haptic set level={level} "
                      f"(device={device_level}): "
                      f"{'OK' if self._haptic_result else 'FAILED'}")
                if resp:
                    _, _, _, _, p = resp
                    print(f"[HidGesture] Haptic set response: [{_hex_bytes(p)}]")
            elif isinstance(cmd, tuple) and cmd[0] == "play":
                waveform = cmd[1]
                # Function 4: playWaveform.  Byte 0 = waveform ID.
                resp = self._request(self._haptic_idx, 4, [waveform])
                self._haptic_result = resp is not None
                print(f"[HidGesture] Haptic play waveform={waveform}: "
                      f"{'OK' if self._haptic_result else 'FAILED'}")
                if resp:
                    _, _, _, _, p = resp
                    print(f"[HidGesture] Haptic play response: [{_hex_bytes(p)}]")
            else:
                print(f"[HidGesture] Unknown haptic command: {cmd}")
                self._haptic_result = False
        except Exception as exc:
            print(f"[HidGesture] Haptic command error: {exc}")
            self._haptic_result = False
        self._pending_haptic = None
        self._haptic_event.set()

    def read_battery(self):
        """Queue a battery read and wait for the listener thread result."""
        self._battery_result = None
        self._battery_event.clear()
        self._pending_battery = "read"
        if not self._battery_event.wait(3.0):
            print("[HidGesture] Battery read timed out")
            self._pending_battery = None
            return None
        return self._battery_result

    def _apply_pending_read_battery(self):
        """Called from the listener thread to read current battery level."""
        if self._battery_idx is None or self._dev is None:
            self._battery_result = None
            self._pending_battery = None
            self._battery_event.set()
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
        self._battery_event.set()

    # ── notification handling ─────────────────────────────────────

    @staticmethod
    def _decode_s16(hi, lo):
        value = ((hi & 0xFF) << 8) | (lo & 0xFF)
        if value & 0x8000:
            value -= 0x10000
        return value

    def _drain_pending_requests(self):
        """Abort all pending HID++ requests, unblocking waiting threads."""
        self._pending_battery = None
        self._battery_event.set()
        self._pending_dpi = None
        self._dpi_result = None
        self._dpi_event.set()
        self._abort_pending_smart_shift()
        self._abort_pending_wheel_divert()
        self._pending_haptic = None
        self._haptic_event.set()
        self._pending_force_sensing = None
        self._force_sensing_event.set()

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
            if len(params) < 4:
                return
            dx = self._decode_s16(params[0], params[1])
            dy = self._decode_s16(params[2], params[3])
            if not (dx or dy):
                return
            if self._rawxy_owner == "thumb":
                # Movement belongs to the thumb Gesture button's swipe hold.
                cb = self._on_thumb_button_move
                if cb:
                    try:
                        cb(dx, dy)
                    except Exception as e:
                        print(f"[HidGesture] thumb move callback error: {e}")
                return
            if not self._held:
                return
            if self._on_move:
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
            self._extra_held_during_gesture = False
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

        for cid, info in self._extra_diverts.items():
            btn_now = cid in cids
            if btn_now and not info["held"]:
                info["held"] = True
                if self._held:
                    self._extra_held_during_gesture = True
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
        """Open the vendor HID collection, discover features, divert.

        Warm path: a cached ``last_device.json`` biases candidate and
        dev_idx ordering so the previously-working interface is probed
        first with a tight 400 ms REPROG_V4 timeout. Cold path falls
        back to the default direct-then-receiver scan with the same
        per-slot timeout. On divert success the working tuple is
        persisted so the next launch hits the warm path."""
        infos = self._vendor_hid_infos()
        if not infos:
            return False

        cached = _load_last_device_cache()
        cached_candidate = (
            cached.get("candidate") if isinstance(cached, dict) else None
        )
        cached_device = (
            cached.get("device") if isinstance(cached, dict) else None
        )

        def _default_priority(info):
            name = (info.get("product_string") or "").lower()
            return (1 if "receiver" in name else 0, name)

        # Negate the score so higher match (cached interface) sorts first.
        def _priority(info):
            score = (
                _candidate_match_score(info, cached_candidate)
                if cached_candidate is not None else 0
            )
            return (-score,) + _default_priority(info)

        infos.sort(key=_priority)

        print(f"[HidGesture] Backend preference: {_BACKEND_PREFERENCE}")
        print(f"[HidGesture] Candidate HID interfaces: {len(infos)}")
        if cached_candidate:
            print(
                f"[HidGesture] Cached last-known device: "
                f"PID=0x{int(cached_candidate.get('pid', 0)):04X} "
                f"devIdx=0x{int((cached_device or {}).get('dev_idx', 0)):02X} "
                f"name='{(cached_device or {}).get('name', '?')}' "
                f"(warm-path probe will run first)"
            )
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

        for info in infos:
            pid = info.get("product_id", 0)
            up = info.get("usage_page", 0)
            usage = info.get("usage", 0)
            product = info.get("product_string")
            source = info.get("source", "unknown")
            # Snapshot before inner branches rebind `info` to HID++ responses.
            candidate_signature = _candidate_signature(info)
            device_spec = resolve_device(product_id=pid, product_name=product)
            self._feat_idx = None
            self._dpi_idx = None
            self._smart_shift_idx = None
            self._battery_idx = None
            self._battery_feature_id = None
            self._haptic_idx = None
            self._force_sensing_idx = None
            self._force_sensing_range = None
            self._haptic_capabilities = None
            self._wheel_feature_indexes = {}
            self._gesture_cid = DEFAULT_GESTURE_CID
            self._gesture_candidates = list(
                getattr(device_spec, "gesture_cids", ()) or DEFAULT_GESTURE_CIDS
            )
            # thumb_button CID must be diverted button-only (no rawXY) so
            # firmware doesn't suppress OS cursor motion while it's held.
            self._button_only_cids = set()
            ar_cid = getattr(device_spec, "thumb_button_cid", None)
            if ar_cid is not None:
                self._button_only_cids.add(int(ar_cid))
            self._rawxy_enabled = False
            self._hires_wheel_idx = None
            self._hires_wheel_multiplier = None
            self._thumbwheel_idx = None
            self._thumbwheel_multiplier = None
            self._wheel_divert_state = False
            opened_transport = None
            opened_up = int(up or 0)
            opened_usage = int(usage or 0)
            opened_path = ""
            open_attempts = []
            candidate_transport = (info.get("transport") or "").lower()
            is_bt_candidate = "bluetooth" in candidate_transport
            # On macOS, prefer IOKit (non-exclusive access) over hidapi
            # which may lock the device and freeze the cursor.
            if (
                sys.platform == "darwin"
                and _MAC_NATIVE_OK
                and _BACKEND_PREFERENCE in ("auto", "iokit")
            ):
                if not is_bt_candidate:
                    open_attempts.append(("iokit-exact", info))
                if is_bt_candidate or not candidate_transport:
                    open_attempts.append(("iokit-ble", {
                        "product_id": pid,
                        "usage_page": 0,
                        "usage": 0,
                        "transport": "Bluetooth Low Energy",
                    }))
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

            # Narrow the device-index search based on transport:
            #  - BT candidates only use BT_DEV_IDX (0xFF)
            #  - Bolt receivers only use slots 1-6
            #  - Unknown: try all (BT first, then receiver slots)
            bt_opened = "bluetooth" in (opened_transport or "").lower()
            if bt_opened:
                default_idx_order = (BT_DEV_IDX,)
            elif pid == BOLT_RECEIVER_PID:
                default_idx_order = (1, 2, 3, 4, 5, 6)
            else:
                default_idx_order = (BT_DEV_IDX, 1, 2, 3, 4, 5, 6)
            cached_dev_idx = None
            if (
                cached_candidate is not None
                and cached_device is not None
                and _candidate_matches_cache(info, cached_candidate)
            ):
                try:
                    cached_dev_idx = int(cached_device.get("dev_idx"))
                except (TypeError, ValueError):
                    cached_dev_idx = None
            if cached_dev_idx is not None and cached_dev_idx in default_idx_order:
                idx_order = (cached_dev_idx,) + tuple(
                    i for i in default_idx_order if i != cached_dev_idx
                )
            else:
                idx_order = default_idx_order
            reprog_found = False
            hidpp_name = None
            for idx in idx_order:
                self._dev_idx = idx
                fi = self._find_feature(FEAT_REPROG_V4, timeout_ms=400)
                if fi is not None:
                    reprog_found = True
                    self._feat_idx = fi
                    print(f"[HidGesture] Found REPROG_V4 @0x{fi:02X}  "
                          f"PID=0x{pid:04X} devIdx=0x{idx:02X}")
                    # Query actual device name via HID++ (resolves
                    # USB receivers that report a generic PID/name).
                    hidpp_name = self._query_device_name()
                    if hidpp_name:
                        print(f"[HidGesture] HID++ device name: '{hidpp_name}'")
                        device_spec = resolve_device(
                            product_id=pid, product_name=hidpp_name,
                        ) or device_spec
                        self._gesture_candidates = list(
                            getattr(device_spec, "gesture_cids", ())
                            or DEFAULT_GESTURE_CIDS
                        )
                        # Re-evaluate hints when HID++ name resolves a more
                        # specific spec than the receiver PID alone.
                        self._button_only_cids = set()
                        ar_cid = getattr(device_spec, "thumb_button_cid", None)
                        if ar_cid is not None:
                            self._button_only_cids.add(int(ar_cid))
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
                    # Prefer 0x2111 (Enhanced) -- used by MX Master 3/3S/4 and Logi Options+.
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
                    # Haptic Feedback (MX Master 4)
                    haptic_fi = self._find_feature(FEAT_HAPTIC)
                    if haptic_fi:
                        self._haptic_idx = haptic_fi
                        print(f"[HidGesture] Found HAPTIC @0x{haptic_fi:02X}")
                        try:
                            cap_resp = self._request(haptic_fi, 0, [])
                            if cap_resp:
                                _, _, _, _, cap_params = cap_resp
                                self._haptic_capabilities = bytes(cap_params)
                                print(f"[HidGesture] Haptic capabilities: "
                                      f"[{_hex_bytes(cap_params)}]")
                        except Exception as exc:
                            print(f"[HidGesture] Haptic capabilities probe "
                                  f"failed: {exc}")
                    # Force Sensing Button (MX Master 4)
                    fs_fi = self._find_feature(FEAT_FORCE_SENSING)
                    if fs_fi:
                        self._force_sensing_idx = fs_fi
                        try:
                            import struct as _struct
                            count_resp = self._request(fs_fi, 0, [])
                            if count_resp:
                                _, _, _, _, cp = count_resp
                                fs_count = cp[0] if cp else 0
                                if fs_count >= 1:
                                    cfg_resp = self._request(fs_fi, 1, [0])
                                    cur_resp = self._request(fs_fi, 2, [0])
                                    if cfg_resp and cur_resp:
                                        _, _, _, _, cfg_p = cfg_resp
                                        changeable = _struct.unpack("!H", bytes(cfg_p[:2]))[0] & 0x01
                                        default_val = _struct.unpack("!H", bytes(cfg_p[2:4]))[0]
                                        max_val = _struct.unpack("!H", bytes(cfg_p[4:6]))[0]
                                        min_val = _struct.unpack("!H", bytes(cfg_p[6:8]))[0]
                                        _, _, _, _, cur_p = cur_resp
                                        current = _struct.unpack("!H", bytes(cur_p[:2]))[0]
                                        self._force_sensing_range = (min_val, max_val, default_val, current)
                                        print(f"[HidGesture] Found FORCE_SENSING @0x{fs_fi:02X} "
                                              f"count={fs_count} changeable={changeable} "
                                              f"min={min_val} max={max_val} default={default_val} "
                                              f"current={current}")
                                    else:
                                        print(f"[HidGesture] Found FORCE_SENSING @0x{fs_fi:02X} "
                                              f"(probe failed)")
                                else:
                                    print(f"[HidGesture] Found FORCE_SENSING @0x{fs_fi:02X} "
                                          f"(no buttons)")
                            else:
                                print(f"[HidGesture] Found FORCE_SENSING @0x{fs_fi:02X} "
                                      f"(count query failed)")
                        except Exception as exc:
                            print(f"[HidGesture] FORCE_SENSING probe failed: {exc}")
                    hw_fi = self._wheel_feature_indexes.get(FEAT_HIRES_WHEEL_ENHANCED)
                    if hw_fi:
                        self._hires_wheel_idx = hw_fi
                        cap = self._request(hw_fi, 0, [])
                        if cap:
                            _, _, _, _, p = cap
                            mul = p[0] if p else None
                            self._hires_wheel_multiplier = (
                                int(mul) if mul not in (None, 0) else None
                            )
                        print(
                            f"[HidGesture] HIRES_WHEEL_ENHANCED @0x{hw_fi:02X} "
                            f"mul={self._hires_wheel_multiplier}"
                        )
                    tw_fi = self._wheel_feature_indexes.get(FEAT_THUMB_WHEEL)
                    if tw_fi:
                        self._thumbwheel_idx = tw_fi
                        tw_info = self._request(tw_fi, 0, [])
                        if tw_info:
                            _, _, _, _, p = tw_info
                            if len(p) >= 4:
                                self._thumbwheel_multiplier = (
                                    (p[2] << 8) | p[3]
                                ) or None
                        print(
                            f"[HidGesture] THUMB_WHEEL @0x{tw_fi:02X} "
                            f"divertedRes={self._thumbwheel_multiplier}"
                        )
                    if self._divert():
                        # Install BEFORE _divert_extras so it lands in the
                        # same setCidReporting round. Pass the live REPROG_V4
                        # controls so the helper can refuse to divert CIDs the
                        # firmware does not advertise.
                        self._install_thumb_button_extra(device_spec, controls)
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
                            has_hires_wheel=bool(self._hires_wheel_idx is not None),
                            has_thumbwheel=bool(self._thumbwheel_idx is not None),
                            hires_wheel_active=False,
                            thumbwheel_active=False,
                            thumb_button_via_hid=self.thumb_button_via_hid,
                        )
                        # Replay the last desired native-invert state on
                        # reconnect; listener loop drains this next iter.
                        if (
                            any(self._wheel_divert_target)
                            and (
                                self._hires_wheel_idx is not None
                                or self._thumbwheel_idx is not None
                            )
                        ):
                            with self._wheel_divert_lock:
                                self._wheel_divert_result = None
                                self._pending_wheel_divert = self._wheel_divert_target
                                self._wheel_divert_event.clear()
                        try:
                            _save_last_device_cache(
                                candidate=candidate_signature,
                                device={
                                    "name": hidpp_name or product,
                                    "dev_idx": int(idx),
                                    "transport": actual_transport,
                                    "feat_idx_reprog": int(fi),
                                },
                            )
                        except Exception as exc:
                            print(f"[HidGesture] Cache write skipped: {exc}")
                        return True
                    continue     # divert failed -- try next receiver slot
            if not reprog_found:
                print(
                    "[HidGesture] Opened candidate but REPROG_V4 was not found "
                    f"on tested devIdx values PID=0x{int(pid or 0):04X} "
                    f"UP=0x{opened_up:04X} usage=0x{opened_usage:04X} "
                    f"transport={opened_transport or '-'} source={source}"
                )

            # Couldn't use this interface -- close and try next
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
                    print("[HidGesture] No compatible device; retrying in 1.5 s…")
                    retry_logged = True
                for _ in range(15):
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
            _SLEEP_TIMEOUT_S = 300      # abandon handle after 5 min asleep
            self._consecutive_request_timeouts = 0
            _device_asleep = False
            _device_sleep_time = None
            try:
                while self._running:
                    if self._reconnect_requested:
                        self._reconnect_requested = False
                        raise IOError("reconnect requested")

                    if self._consecutive_request_timeouts >= _CONSECUTIVE_TIMEOUT_RECONNECT:
                        if not _device_asleep:
                            _device_asleep = True
                            _device_sleep_time = time.monotonic()
                            print("[HidGesture] Device appears asleep "
                                  "— suppressing requests, listening for wake")
                            self._force_release_stale_holds()
                            self._drain_pending_requests()
                            self._consecutive_request_timeouts = 0
                            if self._connected:
                                self._connected = False
                                if self._on_disconnect:
                                    try:
                                        self._on_disconnect()
                                    except Exception:
                                        pass

                    if _device_asleep:
                        if (time.monotonic() - _device_sleep_time
                                >= _SLEEP_TIMEOUT_S):
                            print("[HidGesture] Sleep timeout "
                                  "— falling back to full reconnect")
                            raise IOError("sleep timeout — device may be gone")
                        self._drain_pending_requests()
                        raw = self._rx(1000)
                        if raw:
                            _device_asleep = False
                            _device_sleep_time = None
                            _no_data_count = 0
                            self._consecutive_request_timeouts = 0
                            self._connected = True
                            if self._on_connect:
                                try:
                                    self._on_connect()
                                except Exception:
                                    pass
                            print("[HidGesture] Device woke from sleep")
                            self._on_report(raw)
                        continue

                    # Apply any queued DPI command
                    if self._pending_dpi is not None:
                        if self._pending_dpi == "read":
                            self._apply_pending_read_dpi()
                        else:
                            self._apply_pending_dpi()
                    if self._pending_smart_shift is not None:
                        self._apply_pending_smart_shift()
                    if self._pending_wheel_divert is not None:
                        self._apply_pending_native_wheel_invert()
                    if self._pending_battery is not None:
                        self._apply_pending_read_battery()
                    if self._pending_haptic is not None:
                        self._apply_pending_haptic()
                    if self._pending_force_sensing is not None:
                        self._apply_pending_force_sensing()
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
            self._wheel_feature_indexes = {}
            self._drain_pending_requests()
            self._hires_wheel_idx = None
            self._hires_wheel_multiplier = None
            self._thumbwheel_idx = None
            self._thumbwheel_multiplier = None
            self._wheel_divert_state = False
            self._last_logged_battery = None
            self._consecutive_request_timeouts = 0
            self._haptic_idx = None
            self._force_sensing_idx = None
            self._force_sensing_range = None
            self._haptic_capabilities = None
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
