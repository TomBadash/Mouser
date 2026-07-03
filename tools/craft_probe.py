"""
craft_probe.py — full HID++ feature/control discovery probe.

Mouser's built-in "Copy device info" dump only reports the handful of HID++
features it already knows how to drive (REPROG_V4, DPI, Smart Shift, battery,
wheels). To add support for new control surfaces — notably the Logitech Craft
*Crown* (HID++ feature 0x4540) and any divertable top-row keys — we first need
to see the device's **complete** feature table.

This standalone script enumerates every Logitech vendor HID interface, walks the
full HID++ FEATURE_SET (0x0001), lists every feature index, and dumps the
REPROG_CONTROLS_V4 table when present. It does NOT divert anything or change
device state beyond read-only queries, so it is safe to run while the keyboard
is in normal use.

Usage:
    python tools/craft_probe.py            # probe all Logitech HID++ interfaces
    python tools/craft_probe.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Allow running as `python tools/craft_probe.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Make console output robust to non-ASCII device names on Windows (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Reuse Mouser's HID enumeration, parser, and protocol constants so this probe
# stays faithful to how the app actually talks to the device.
from core.hid_gesture import (  # noqa: E402
    HIDAPI_OK,
    HIDAPI_IMPORT_ERROR,
    LOGI_VID,
    LONG_ID,
    LONG_LEN,
    MY_SW,
    HIDPP_ERROR_NAMES,
    HidGestureListener,
    _hid,
    _parse,
    _hex_bytes,
)

FEAT_IROOT = 0x0000
FEAT_FEATURE_SET = 0x0001
FEAT_DEVICE_NAME = 0x0005
FEAT_CROWN = 0x4600
FEAT_REPROG_V4 = 0x1B04

# Curated Logitech HID++ 2.0 feature-id → name map (subset of Solaar's table,
# focused on what's relevant for keyboards + the Craft crown).
FEATURE_NAMES = {
    0x0000: "ROOT",
    0x0001: "FEATURE_SET",
    0x0002: "FEATURE_INFO",
    0x0003: "DEVICE_FW_VERSION",
    0x0005: "DEVICE_NAME",
    0x0007: "DEVICE_FRIENDLY_NAME",
    0x0008: "KEEP_ALIVE",
    0x0020: "CONFIG_CHANGE",
    0x0021: "UNIQUE_IDENTIFIER",
    0x1000: "BATTERY_STATUS",
    0x1001: "BATTERY_VOLTAGE",
    0x1004: "UNIFIED_BATTERY",
    0x1814: "CHANGE_HOST",
    0x1815: "HOSTS_INFO",
    0x1981: "BACKLIGHT",
    0x1982: "BACKLIGHT2",
    0x1B04: "REPROG_CONTROLS_V4",
    0x1BC0: "PERSISTENT_REMAPPABLE_ACTION",
    0x1D4B: "WIRELESS_DEVICE_STATUS",
    0x1DF3: "EQUAD_DJ_DEVICE_PAIRING_INFO",
    0x1E00: "ENABLE_HIDDEN_FEATURES",
    0x2110: "SMART_SHIFT",
    0x2111: "SMART_SHIFT_ENHANCED",
    0x2120: "HIRES_WHEEL",
    0x2121: "HIRES_WHEEL_ENHANCED",
    0x2130: "LOWRES_WHEEL",
    0x2150: "THUMB_WHEEL",
    0x2201: "ADJUSTABLE_DPI",
    0x40A3: "FN_INVERSION_FOR_MULTI_HOST",
    0x4220: "LOCK_KEY_STATE",
    0x4520: "KEYBOARD_LAYOUT",
    0x4521: "KEYBOARD_DISABLE_KEYS",
    0x4522: "KEYBOARD_DISABLE_BY_USAGE",
    0x4523: "DUALPLATFORM",
    0x4530: "MULTIPLATFORM",
    0x4531: "MULTIPLATFORM_2",
    0x4540: "KEYBOARD_LAYOUT_2",
    0x4600: "CROWN",
    0x6010: "TOUCHPAD_FW_ITEMS",
    0x6100: "TOUCHPAD_RAW_XY",
}


def feat_name(fid: int) -> str:
    return FEATURE_NAMES.get(fid, "UNKNOWN")


class Probe:
    """Minimal read-only HID++ 2.0 client over an already-open hid device."""

    def __init__(self, dev):
        self._dev = dev
        self.dev_idx = 0xFF

    def _tx(self, feat_idx, func, params):
        buf = [0] * LONG_LEN
        buf[0] = LONG_ID
        buf[1] = self.dev_idx
        buf[2] = feat_idx
        buf[3] = ((func & 0x0F) << 4) | (MY_SW & 0x0F)
        for i, b in enumerate(params):
            if 4 + i < LONG_LEN:
                buf[4 + i] = b & 0xFF
        self._dev.write(buf)

    def _rx(self, timeout_ms):
        # Windows refuses reads on the reserved keyboard/mouse top-level
        # collections (UP 0x0001); hidapi surfaces that as OSError. Treat any
        # read failure as "no data" so one un-probeable collection does not
        # abort the whole scan — the caller just times out and moves on.
        try:
            d = self._dev.read(64, timeout_ms)
        except Exception:
            return None
        return list(d) if d else None

    def request(self, feat_idx, func, params, timeout_ms=900):
        try:
            self._tx(feat_idx, func, params)
        except Exception as exc:
            return None, f"tx-error: {exc}"
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            raw = self._rx(min(300, timeout_ms))
            if raw is None:
                continue
            msg = _parse(raw)
            if msg is None:
                continue
            dev, r_feat, r_func, r_sw, r_params = msg
            if r_feat == 0xFF:
                code = r_params[1] if len(r_params) > 1 else 0
                return None, f"hidpp-error 0x{code:02X} ({HIDPP_ERROR_NAMES.get(code, '?')})"
            expected = {func, (func + 1) & 0x0F}
            if r_feat == feat_idx and r_sw == MY_SW and r_func in expected:
                return r_params, None
            # Ignore unrelated diverted-event traffic and keep waiting.
        return None, "timeout"

    def root_get_feature(self, feature_id):
        hi, lo = (feature_id >> 8) & 0xFF, feature_id & 0xFF
        params, err = self.request(FEAT_IROOT, 0, [hi, lo, 0x00])
        if err or not params:
            return None
        idx = params[0]
        return idx if idx else None


def probe_device_index(probe: Probe):
    """Find a device index that responds to HID++ FEATURE_SET discovery."""
    for idx in (0xFF, 1, 2, 3, 4, 5, 6):
        probe.dev_idx = idx
        fs_idx = probe.root_get_feature(FEAT_FEATURE_SET)
        if fs_idx:
            return idx, fs_idx
    return None, None


def enumerate_features(probe: Probe, feature_set_idx: int):
    """Walk FEATURE_SET (0x0001): getCount (func 0), getFeatureId (func 1)."""
    out = []
    params, err = probe.request(feature_set_idx, 0, [])
    if err or not params:
        return out, f"getCount failed: {err}"
    count = params[0]
    for i in range(count + 1):  # index 0 is ROOT; include it
        params, err = probe.request(feature_set_idx, 1, [i])
        if err or not params or len(params) < 2:
            out.append({"index": i, "error": err or "short"})
            continue
        fid = (params[0] << 8) | params[1]
        type_flags = params[2] if len(params) > 2 else 0
        out.append({
            "index": i,
            "feature_id": f"0x{fid:04X}",
            "name": feat_name(fid),
            "type_flags": f"0x{type_flags:02X}",
            "obsolete": bool(type_flags & 0x80),
            "hidden": bool(type_flags & 0x40),
            "engineering": bool(type_flags & 0x20),
        })
    return out, None


# REPROG_V4 control flag bits (matches CONTRIBUTING_DEVICES.md).
KEY_FLAG_BITS = [
    (0x0001, "mouse"), (0x0002, "fkey"), (0x0004, "hotkey"),
    (0x0008, "fn_toggle"), (0x0010, "reprog"), (0x0020, "divert"),
    (0x0040, "persist"), (0x0080, "virtual"),
    (0x0100, "raw_xy"), (0x0200, "force_raw_xy"),
]


def fmt_flags(value):
    return ",".join(n for b, n in KEY_FLAG_BITS if value & b) or "none"


def discover_reprog_controls(probe: Probe, reprog_idx: int):
    controls = []
    params, err = probe.request(reprog_idx, 0, [])
    if err or not params:
        return controls, f"count failed: {err}"
    count = params[0]
    for index in range(count):
        params, err = probe.request(reprog_idx, 1, [index], timeout_ms=600)
        if err or not params or len(params) < 9:
            controls.append({"index": index, "error": err or "short"})
            continue
        cid = (params[0] << 8) | params[1]
        task = (params[2] << 8) | params[3]
        flags = params[4] | (params[8] << 8)
        controls.append({
            "index": index,
            "cid": f"0x{cid:04X}",
            "task": f"0x{task:04X}",
            "flags": f"0x{flags:04X}",
            "flag_names": fmt_flags(flags),
            "pos": params[5],
            "group": params[6],
            "gmask": f"0x{params[7]:02X}",
        })
    return controls, None


def query_name(probe: Probe):
    name_idx = probe.root_get_feature(FEAT_DEVICE_NAME)
    if not name_idx:
        return None
    params, err = probe.request(name_idx, 0, [0, 0, 0])
    if err or not params:
        return None
    length = params[0]
    chunks = bytearray()
    offset = 0
    while offset < length:
        params, err = probe.request(name_idx, 1, [offset, 0, 0])
        if err or not params:
            break
        chunks.extend(params[: length - offset])
        offset += len(params)
        if not params:
            break
    return chunks.decode("ascii", errors="replace").strip("\x00").strip() or None


def open_hid(info):
    path = info.get("path")
    if not path:
        return None
    if isinstance(path, str):
        path = path.encode()
    if hasattr(_hid, "device"):
        d = _hid.device()
        d.open_path(path)
    else:  # "pip install hid" style
        d = _hid.Device(path=path)
    try:
        d.set_nonblocking(False)
    except Exception:
        pass
    return d


def set_cid_reporting(probe: Probe, reprog_idx: int, cid: int, flags: int):
    """REPROG_V4 setCidReporting (func 3): cid(2) + flags + remap(2)."""
    hi, lo = (cid >> 8) & 0xFF, cid & 0xFF
    return probe.request(reprog_idx, 3, [hi, lo, flags, 0x00, 0x00])


def listen_mode(args):
    """Divert the Crown + keys on the Craft and print raw HID++ notifications.

    This is the empirical capture used to design the Crown parser: run it, then
    rotate the crown left/right (slowly and quickly), press the crown, and tap
    the top-row keys. Each unsolicited report is printed with its source
    feature so we can decode the rotation/tap byte layout.
    """
    if not HIDAPI_OK:
        print(f"hidapi not available: {HIDAPI_IMPORT_ERROR}", file=sys.stderr)
        return 2

    target = None
    for info in HidGestureListener._vendor_hid_infos():
        try:
            dev = open_hid(info)
        except Exception:
            dev = None
        if dev is None:
            continue
        probe = Probe(dev)
        dev_idx, fs_idx = probe_device_index(probe)
        if dev_idx is None:
            dev.close()
            continue
        probe.dev_idx = dev_idx
        features, _ = enumerate_features(probe, fs_idx)
        feat_ids = {int(f["feature_id"], 16): f["index"]
                    for f in features if "feature_id" in f}
        if FEAT_CROWN in feat_ids:
            target = (info, dev, probe, feat_ids, features)
            break
        dev.close()

    if target is None:
        print("No connected device exposes the CROWN (0x4600) feature.",
              file=sys.stderr)
        return 1

    info, dev, probe, feat_ids, features = target
    name = query_name(probe) or info.get("product_string") or "?"
    crown_idx = feat_ids[FEAT_CROWN]
    reprog_idx = feat_ids.get(FEAT_REPROG_V4)
    idx_to_name = {f["index"]: f["name"] for f in features if "feature_id" in f}

    print(f"Listening on {name!r}  dev_idx=0x{probe.dev_idx:02X}  "
          f"CROWN @0x{crown_idx:02X}"
          + (f"  REPROG_V4 @0x{reprog_idx:02X}" if reprog_idx else ""))

    # 1) Read current crown mode. Per Solaar, CROWN (0x4600) get = fnid 0x10
    #    (function index 1), set = fnid 0x20 (function index 2).
    params, err = probe.request(crown_idx, 1, [])
    print(f"  getCrownMode (func1) -> "
          f"{_hex_bytes(params) if params else f'<{err}>'}")

    # 2) Enable crown diversion via setCrownMode (function 2). Solaar's
    #    DivertCrown writes 0x02 to enable HID++ notifications, 0x01 to disable.
    crown_param = [int(b, 16) for b in args.crown_param.split()] if args.crown_param else [0x02]
    params, err = probe.request(crown_idx, 2, crown_param)
    print(f"  setCrownMode (func2) param=[{_hex_bytes(crown_param)}] -> "
          f"{_hex_bytes(params) if params else f'<{err}>'}")

    # 2b) Optionally enable receiver-level HID++ notifications (Solaar writes
    #     receiver register 0x00 NOTIFICATIONS with wireless|software_present =
    #     0x000900). Sent as a SHORT report (0x10) on the FF00/0x0001 collection.
    recv_handle = None
    if args.enable_recv:
        for o in _hid.enumerate(LOGI_VID, 0):
            if (int(o.get("usage_page", 0) or 0) == 0xFF00
                    and int(o.get("usage", 0) or 0) == 0x0001):
                try:
                    recv_handle = open_hid(o)
                except Exception as exc:
                    print(f"  enable-recv: open short iface failed: {exc}")
                break
        if recv_handle is not None:
            try:
                recv_handle.write([0x10, 0xFF, 0x80, 0x00, 0x00, 0x09, 0x00])
                print("  enable-recv: wrote NOTIFICATIONS reg 0x00 = 00 09 00")
            except Exception as exc:
                print(f"  enable-recv: write failed: {exc}")

    # 3) Divert divertable REPROG controls so key presses also surface.
    diverted = []
    if reprog_idx and not args.no_keys:
        controls, _ = discover_reprog_controls(probe, reprog_idx)
        for c in controls:
            if "cid" not in c:
                continue
            flags = int(c["flags"], 16)
            if flags & 0x0020:  # divert-capable
                cid = int(c["cid"], 16)
                resp, e = set_cid_reporting(probe, reprog_idx, cid, 0x03)
                if resp is not None:
                    diverted.append(cid)
        print(f"  diverted {len(diverted)} key control(s): "
              + ", ".join(f"0x{c:04X}" for c in diverted))

    # Open every Logitech HID++ (UP >= 0xFF00) interface for reading. The
    # Unifying receiver may route crown notifications (short 0x10 reports) to a
    # different collection than the long 0x11 reports we send requests on, so we
    # poll them all and label which interface each report arrives on.
    control_path = info.get("path")
    if isinstance(control_path, str):
        control_path = control_path.encode()
    handles = [(f"UP=0x{int(info.get('usage_page',0) or 0):04X} "
                f"usage=0x{int(info.get('usage',0) or 0):04X} [ctrl]", dev)]
    # Default: only the vendor HID++ (0xFF00) interfaces. With --all-interfaces
    # we open EVERY Logitech HID interface (keyboard, consumer, etc.) to catch a
    # crown that might report on a standard channel instead of HID++.
    # --open PAGE:USAGE[,...] opens only the named extra collections (bisection).
    open_filter = None
    if args.open:
        open_filter = set()
        for tok in args.open.split(","):
            pg, _, us = tok.strip().partition(":")
            open_filter.add((int(pg, 16), int(us, 16) if us else 0))
    if args.all_interfaces or open_filter is not None:
        scan = list(_hid.enumerate(LOGI_VID, 0))
    else:
        scan = HidGestureListener._vendor_hid_infos()
    for other in scan:
        up = int(other.get("usage_page", 0) or 0)
        us = int(other.get("usage", 0) or 0)
        if open_filter is not None:
            if (up, us) not in open_filter:
                continue
        elif not args.all_interfaces and up < 0xFF00:
            continue
        opath = other.get("path")
        if isinstance(opath, str):
            opath = opath.encode()
        if opath == control_path:
            continue
        try:
            h = open_hid(other)
        except Exception as exc:
            print(f"  (could not open UP=0x{up:04X} "
                  f"usage=0x{int(other.get('usage',0) or 0):04X}: {exc})")
            continue
        if h is None:
            continue
        handles.append((f"UP=0x{up:04X} "
                        f"usage=0x{int(other.get('usage',0) or 0):04X}", h))
    for _label, h in handles:
        try:
            h.set_nonblocking(True)
        except Exception:
            pass
    print(f"  polling {len(handles)} HID++ interface(s)")

    print(f"\n>>> Now use the device for {args.seconds}s: rotate the crown both "
          "ways (slow + fast), press the crown, tap the top-row keys.\n"
          "    (Ctrl+C to stop early)\n")

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            got = False
            for hlabel, h in handles:
                try:
                    d = h.read(64, 0)
                except Exception:
                    d = None
                if not d:
                    continue
                got = True
                raw = list(d)
                msg = _parse(raw)
                label = ""
                if msg:
                    d_idx, feat_i, func, sw, p = msg
                    src = idx_to_name.get(feat_i, "?")
                    tag = ("CROWN" if feat_i == crown_idx
                           else "KEY" if feat_i == reprog_idx else src)
                    label = (f"  [dev=0x{d_idx:02X} featIdx=0x{feat_i:02X} {tag} "
                             f"func=0x{func:X} sw=0x{sw:X}] params={_hex_bytes(p)}")
                print(f"{time.strftime('%H:%M:%S')} {hlabel}  "
                      f"raw={_hex_bytes(raw)}{label}")
            if not got:
                time.sleep(0.005)
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        # Best-effort restore: undivert keys, reset crown.
        try:
            dev.set_nonblocking(False)
        except Exception:
            pass
        for cid in diverted:
            set_cid_reporting(probe, reprog_idx, cid, 0x02)
        try:
            probe.request(crown_idx, 2, [0x01])  # divert off
        except Exception:
            pass
        for _label, h in handles:
            try:
                h.close()
            except Exception:
                pass
        if recv_handle is not None:
            try:
                recv_handle.close()
            except Exception:
                pass
    return 0


def test_shared(args):
    """Open TWO handles to the receiver's HID++ long interface and verify both
    receive notifications (so a two-listener multi-device design is viable)."""
    if not HIDAPI_OK:
        print(f"hidapi not available: {HIDAPI_IMPORT_ERROR}", file=sys.stderr)
        return 2
    target_info = None
    for info in HidGestureListener._vendor_hid_infos():
        if (int(info.get("usage_page", 0) or 0) == 0xFF00
                and int(info.get("usage", 0) or 0) == 0x0002):
            target_info = info
            break
    if target_info is None:
        print("No FF00/0x0002 interface found.", file=sys.stderr)
        return 1
    h1 = open_hid(target_info)
    try:
        h2 = open_hid(target_info)
    except Exception as exc:
        print(f"Second handle open FAILED -> shared handles NOT possible: {exc}")
        h1.close()
        return 1
    if h2 is None:
        print("Second handle open returned None -> shared handles NOT possible.")
        h1.close()
        return 1
    print("Opened TWO handles to FF00/0x0002 OK.")

    # Use handle 1 to set up the Craft crown (dev_idx 0x02) so notifications flow.
    p1 = Probe(h1)
    p1.dev_idx = 0x02
    crown = p1.root_get_feature(FEAT_CROWN)
    # Enable receiver notifications (short report on FF00/0x0001).
    for o in _hid.enumerate(LOGI_VID, 0):
        if (int(o.get("usage_page", 0) or 0) == 0xFF00
                and int(o.get("usage", 0) or 0) == 0x0001):
            try:
                rh = open_hid(o)
                rh.write([0x10, 0xFF, 0x80, 0x00, 0x00, 0x09, 0x00])
            except Exception:
                pass
            break
    if crown:
        p1.request(crown, 2, [0x02])  # divert crown
        print(f"Diverted Craft crown @0x{crown:02X} via handle 1.")
    for h in (h1, h2):
        try:
            h.set_nonblocking(True)
        except Exception:
            pass
    counts = {"H1": 0, "H2": 0}
    print(f"\n>>> For {args.seconds}s: spin the crown and move/click the mouse. "
          "Counting reports per handle.\n")
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        got = False
        for tag, h in (("H1", h1), ("H2", h2)):
            try:
                d = h.read(64, 0)
            except Exception:
                d = None
            if d:
                got = True
                counts[tag] += 1
                msg = _parse(list(d))
                if msg:
                    print(f"[{tag}] devIdx=0x{msg[0]:02X} featIdx=0x{msg[1]:02X} "
                          f"data={_hex_bytes(msg[4])[:20]}")
        if not got:
            time.sleep(0.005)
    print(f"\nTotals: {counts}")
    print("Shared delivery WORKS" if counts["H1"] and counts["H2"]
          else "Shared delivery did NOT deliver to both handles")
    for h in (h1, h2):
        try:
            h.close()
        except Exception:
            pass
    return 0


def scan_devices(args):
    """Scan every HID++ device index behind a receiver and report which devices
    are present (name + REPROG/CROWN), to ground multi-device design."""
    if not HIDAPI_OK:
        print(f"hidapi not available: {HIDAPI_IMPORT_ERROR}", file=sys.stderr)
        return 2
    seen_paths = set()
    for info in HidGestureListener._vendor_hid_infos():
        up = int(info.get("usage_page", 0) or 0)
        if up < 0xFF00:
            continue
        path = info.get("path")
        key = bytes(path) if isinstance(path, (bytes, bytearray)) else str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        try:
            dev = open_hid(info)
        except Exception as exc:
            print(f"open failed UP=0x{up:04X} usage=0x{int(info.get('usage',0) or 0):04X}: {exc}")
            continue
        if dev is None:
            continue
        pid = int(info.get("product_id", 0) or 0)
        usage = int(info.get("usage", 0) or 0)
        print("=" * 70)
        print(f"Interface PID=0x{pid:04X} UP=0x{up:04X} usage=0x{usage:04X}")
        probe = Probe(dev)
        try:
            for idx in (0xFF, 1, 2, 3, 4, 5, 6):
                probe.dev_idx = idx
                fs = probe.root_get_feature(FEAT_FEATURE_SET)
                if not fs:
                    continue
                name = query_name(probe) or "?"
                reprog = probe.root_get_feature(FEAT_REPROG_V4)
                crown = probe.root_get_feature(FEAT_CROWN)
                feats, _ = enumerate_features(probe, fs)
                fids = {f.get("feature_id") for f in feats if "feature_id" in f}
                kind = ("keyboard/crown" if crown else
                        "mouse?" if reprog else "other")
                print(f"  devIdx=0x{idx:02X}  name={name!r}  "
                      f"REPROG_V4={'@0x%02X' % reprog if reprog else '-'}  "
                      f"CROWN={'@0x%02X' % crown if crown else '-'}  "
                      f"features={len(feats)}  -> {kind}")
        finally:
            try:
                dev.close()
            except Exception:
                pass
    return 0


def keys_capture(args):
    """Guided per-key capture: divert every top-row control and print one line
    per physical key press (the CID), so CID → physical key can be mapped."""
    if not HIDAPI_OK:
        print(f"hidapi not available: {HIDAPI_IMPORT_ERROR}", file=sys.stderr)
        return 2

    # With several REPROG_V4 devices connected (e.g. an MX mouse AND an MX Keys
    # over Bluetooth), enumeration order is arbitrary, so target the intended
    # device explicitly: --pid selects by product id, --match by product-string
    # substring. Otherwise the first REPROG_V4 interface wins.
    want_pid = int(args.pid, 16) if args.pid else None
    want_match = (args.match or "").lower()

    target = None
    for info in HidGestureListener._vendor_hid_infos():
        pid = int(info.get("product_id", 0) or 0)
        product = (info.get("product_string") or "").lower()
        if want_pid is not None and pid != want_pid:
            continue
        if want_match and want_match not in product:
            continue
        try:
            dev = open_hid(info)
        except Exception:
            dev = None
        if dev is None:
            continue
        probe = Probe(dev)
        dev_idx, fs_idx = probe_device_index(probe)
        if dev_idx is None:
            dev.close()
            continue
        probe.dev_idx = dev_idx
        features, _ = enumerate_features(probe, fs_idx)
        feat_ids = {int(f["feature_id"], 16): f["index"]
                    for f in features if "feature_id" in f}
        if FEAT_REPROG_V4 in feat_ids:
            target = (info, dev, probe, feat_ids)
            break
        dev.close()

    if target is None:
        print("No connected device exposes REPROG_CONTROLS_V4 (0x1B04).",
              file=sys.stderr)
        return 1

    info, dev, probe, feat_ids = target
    name = query_name(probe) or info.get("product_string") or "?"
    reprog_idx = feat_ids[FEAT_REPROG_V4]
    controls, _ = discover_reprog_controls(probe, reprog_idx)
    task_by_cid = {}
    diverted = []
    for c in controls:
        if "cid" not in c:
            continue
        flags = int(c["flags"], 16)
        if flags & 0x0020:  # divert-capable
            cid = int(c["cid"], 16)
            task_by_cid[cid] = c.get("task", "?")
            resp, _ = set_cid_reporting(probe, reprog_idx, cid, 0x03)
            if resp is not None:
                diverted.append(cid)
    print(f"Key capture on {name!r}  dev_idx=0x{probe.dev_idx:02X}  "
          f"REPROG_V4 @0x{reprog_idx:02X}")
    print(f"  diverted {len(diverted)} control(s)\n")
    print(f">>> Press the top-row keys ONE AT A TIME for {args.seconds}s, "
          "pausing between each. Each press prints its CID.\n"
          "    (Ctrl+C to stop early)\n")

    try:
        dev.set_nonblocking(True)
    except Exception:
        pass

    held = set()
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            try:
                d = dev.read(64, 0)
            except Exception:
                d = None
            if not d:
                time.sleep(0.005)
                continue
            msg = _parse(list(d))
            if not msg:
                continue
            _, feat_i, func, _sw, p = msg
            if feat_i != reprog_idx or func != 0:
                continue
            now = set()
            i = 0
            while i + 1 < len(p):
                cid = (p[i] << 8) | p[i + 1]
                if cid == 0:
                    break
                now.add(cid)
                i += 2
            for cid in sorted(now - held):
                print(f"{time.strftime('%H:%M:%S')}  PRESS cid=0x{cid:04X}  "
                      f"task={task_by_cid.get(cid, '?')}")
            held = now
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        try:
            dev.set_nonblocking(False)
        except Exception:
            pass
        for cid in diverted:
            set_cid_reporting(probe, reprog_idx, cid, 0x02)
        try:
            dev.close()
        except Exception:
            pass
    return 0


def main():
    ap = argparse.ArgumentParser(description="Logitech HID++ full discovery probe")
    ap.add_argument("--json", help="write the full report to this file")
    ap.add_argument("--keys", action="store_true",
                    help="guided per-key capture (press keys one at a time)")
    ap.add_argument("--pid", default="",
                    help="target only this product id (hex, e.g. 'B35B') for "
                         "--keys, when several REPROG_V4 devices are connected")
    ap.add_argument("--match", default="",
                    help="target only interfaces whose product string contains "
                         "this substring (case-insensitive) for --keys")
    ap.add_argument("--scan-devices", action="store_true",
                    help="scan all HID++ device indices behind a receiver")
    ap.add_argument("--test-shared", action="store_true",
                    help="verify two handles to the receiver both get reports")
    ap.add_argument("--listen", action="store_true",
                    help="divert Crown + keys and stream raw HID++ notifications")
    ap.add_argument("--seconds", type=int, default=30,
                    help="listen duration (with --listen)")
    ap.add_argument("--crown-param", default="",
                    help="hex bytes for setCrownMode, e.g. '02' (with --listen)")
    ap.add_argument("--no-keys", action="store_true",
                    help="do not divert keyboard controls (with --listen)")
    ap.add_argument("--all-interfaces", action="store_true",
                    help="poll every Logitech HID interface, not just 0xFF00 "
                         "(with --listen) — catches non-HID++ crown reports")
    ap.add_argument("--enable-recv", action="store_true",
                    help="write receiver NOTIFICATIONS register 0x00 to enable "
                         "HID++ notifications (with --listen)")
    ap.add_argument("--open", default="",
                    help="additionally open only these collections as "
                         "PAGE:USAGE hex pairs, comma-separated, e.g. "
                         "'000C:0001' (Consumer). For bisecting which extra "
                         "interface unlocks crown delivery.")
    args = ap.parse_args()

    if args.test_shared:
        return test_shared(args)

    if args.scan_devices:
        return scan_devices(args)

    if args.keys:
        return keys_capture(args)

    if args.listen:
        return listen_mode(args)

    if not HIDAPI_OK:
        print(f"hidapi not available: {HIDAPI_IMPORT_ERROR}", file=sys.stderr)
        return 2

    infos = HidGestureListener._vendor_hid_infos()
    print(f"Found {len(infos)} Logitech vendor HID interface(s)\n")
    report = {"interfaces": []}

    for info in infos:
        pid = int(info.get("product_id", 0) or 0)
        up = int(info.get("usage_page", 0) or 0)
        usage = int(info.get("usage", 0) or 0)
        product = info.get("product_string") or "?"
        transport = info.get("transport") or "-"
        header = (f"PID=0x{pid:04X} UP=0x{up:04X} usage=0x{usage:04X} "
                  f"transport={transport} product={product!r}")
        print("=" * 78)
        print(header)
        entry = {
            "product_id": f"0x{pid:04X}",
            "usage_page": f"0x{up:04X}",
            "usage": f"0x{usage:04X}",
            "transport": transport,
            "product_string": product,
            "source": info.get("source"),
        }

        dev = None
        try:
            dev = open_hid(info)
        except Exception as exc:
            print(f"  open failed: {exc}")
            entry["error"] = f"open failed: {exc}"
            report["interfaces"].append(entry)
            continue
        if dev is None:
            entry["error"] = "no path / could not open"
            report["interfaces"].append(entry)
            continue

        try:
            probe = Probe(dev)
            dev_idx, fs_idx = probe_device_index(probe)
            if dev_idx is None:
                print("  no responsive HID++ device index (not HID++ 2.0?)")
                entry["error"] = "no responsive HID++ device index"
                continue
            probe.dev_idx = dev_idx
            entry["device_index"] = f"0x{dev_idx:02X}"
            print(f"  device_index=0x{dev_idx:02X}  FEATURE_SET @0x{fs_idx:02X}")

            name = query_name(probe)
            if name:
                entry["hidpp_name"] = name
                print(f"  HID++ name: {name!r}")

            features, ferr = enumerate_features(probe, fs_idx)
            entry["features"] = features
            if ferr:
                print(f"  feature enumeration: {ferr}")
            print(f"  features ({len(features)}):")
            for f in features:
                if "error" in f:
                    print(f"    [{f['index']:>2}] <error: {f['error']}>")
                else:
                    print(f"    [{f['index']:>2}] {f['feature_id']} {f['name']}"
                          f"  ({f['type_flags']})")

            feat_ids = {
                int(f["feature_id"], 16): f["index"]
                for f in features if "feature_id" in f
            }
            entry["has_crown"] = FEAT_CROWN in feat_ids
            entry["has_reprog_v4"] = FEAT_REPROG_V4 in feat_ids
            print(f"  >>> CROWN (0x4600): {'YES @0x%02X' % feat_ids[FEAT_CROWN] if FEAT_CROWN in feat_ids else 'no'}")
            print(f"  >>> REPROG_V4 (0x1B04): {'YES @0x%02X' % feat_ids[FEAT_REPROG_V4] if FEAT_REPROG_V4 in feat_ids else 'no'}")

            if FEAT_REPROG_V4 in feat_ids:
                controls, cerr = discover_reprog_controls(probe, feat_ids[FEAT_REPROG_V4])
                entry["reprog_controls"] = controls
                if cerr:
                    print(f"  reprog controls: {cerr}")
                print(f"  reprog controls ({len(controls)}):")
                for c in controls:
                    if "error" in c:
                        print(f"    [{c['index']:>2}] <error: {c['error']}>")
                    else:
                        print(f"    [{c['index']:>2}] cid={c['cid']} task={c['task']} "
                              f"flags={c['flags']} [{c['flag_names']}]")
        except Exception as exc:
            print(f"  probe error on this interface: {exc}")
            entry["error"] = f"probe error: {exc}"
        finally:
            try:
                dev.close()
            except Exception:
                pass
            report["interfaces"].append(entry)
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nWrote JSON report to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
