"""
hid_gesture.py — Detect MX Master 3S gesture button via Logitech HID++.

The gesture button on a Bluetooth-connected MX Master 3S (without Logi Options+)
often produces NO standard OS-level mouse event.  This module uses the HID++
protocol (over hidapi) to:

  1. Open the Logitech vendor-specific HID collection (UP 0xFF43).
  2. Discover the REPROG_CONTROLS_V4 (0x1B04) feature via IRoot.
  3. Divert the gesture button (CID 0x00C3) so we receive notifications.
  4. Fire callbacks on gesture press / release.

Requires:  pip install hidapi
Falls back gracefully if the package or device are unavailable.
"""

import sys
import threading
import time

try:
    import hid as _hid
    HIDAPI_OK = True

    # On macOS, hidapi opens HID devices with kIOHIDOptionsTypeSeizeDevice by
    # default, grabbing exclusive access.  For Bluetooth devices this seizes the
    # entire transport, blocking the system mouse driver from reading movement
    # data and freezing the cursor.  Disable exclusive open so the OS mouse
    # input continues to work alongside our vendor-page HID++ communication.
    if sys.platform == "darwin":
        try:
            import ctypes as _ct
            _hidlib = _ct.CDLL(_hid.__file__)
            _hidlib.hid_darwin_set_open_exclusive.argtypes = [_ct.c_int]
            _hidlib.hid_darwin_set_open_exclusive.restype = _ct.c_int
            _hidlib.hid_darwin_set_open_exclusive(0)
            print("[HidGesture] macOS: disabled exclusive HID device open")
        except Exception as exc:
            print(f"[HidGesture] macOS: could not disable exclusive open: {exc}")
except ImportError:
    HIDAPI_OK = False

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
CID_GESTURE    = 0x00C3      # "Mouse Gesture Button"

MY_SW          = 0x0A        # arbitrary software-id used in our requests


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


# ── Listener class ────────────────────────────────────────────────

class HidGestureListener:
    """Background thread: diverts the gesture button and listens via HID++."""

    def __init__(self, on_down=None, on_up=None):
        self._on_down   = on_down
        self._on_up     = on_up
        self._dev       = None          # hid.device()
        self._thread    = None
        self._running   = False
        self._feat_idx  = None          # feature index of REPROG_V4
        self._dpi_idx   = None          # feature index of ADJUSTABLE_DPI
        self._dev_idx   = BT_DEV_IDX
        self._held      = False
        self._pending_dpi = None        # set by set_dpi(), applied in loop
        self._dpi_result  = None        # True/False after apply

    # ── public API ────────────────────────────────────────────────

    def start(self):
        if not HIDAPI_OK:
            print("[HidGesture] 'hidapi' not installed — pip install hidapi")
            return False
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
        if self._thread:
            self._thread.join(timeout=3)

    # ── device discovery ──────────────────────────────────────────

    @staticmethod
    def _vendor_hid_infos():
        """Return list of device-info dicts for Logitech vendor-page TLCs."""
        out = []
        try:
            for info in _hid.enumerate(LOGI_VID, 0):
                if info.get("usage_page", 0) >= 0xFF00:
                    out.append(info)
        except Exception as exc:
            print(f"[HidGesture] enumerate error: {exc}")
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
        """Read one HID input report using non-blocking poll."""
        dev = self._dev
        if dev is None:
            return None
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                d = dev.read(64)
                if d:
                    return list(d)
            except Exception:
                return None
            time.sleep(0.005)   # 5 ms poll — stays on daemon thread, never blocks main run loop
        return None

    def _request(self, feat, func, params, timeout_ms=2000):
        """Send a long HID++ request, wait for matching response."""
        try:
            self._tx(LONG_ID, feat, func, params)
        except Exception:
            return None
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            raw = self._rx(min(500, timeout_ms))
            if raw is None:
                continue
            msg = _parse(raw)
            if msg is None:
                continue
            _, r_feat, r_func, r_sw, r_params = msg

            # HID++ error (feature-index 0xFF)
            if r_feat == 0xFF:
                code = r_params[1] if len(r_params) > 1 else 0
                print(f"[HidGesture] HID++ error 0x{code:02X} "
                      f"for feat=0x{feat:02X} func={func}")
                return None

            if r_feat == feat and r_sw == MY_SW:
                return msg
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

    def _divert(self):
        """Divert gesture button CID 0x00C3 so we get press/release
        notifications instead of the device's default action."""
        if self._feat_idx is None:
            return False
        hi = (CID_GESTURE >> 8) & 0xFF
        lo = CID_GESTURE & 0xFF
        # flags: divert=1 (bit 0), dvalid=1 (bit 1) → 0x03
        resp = self._request(self._feat_idx, 3, [hi, lo, 0x03])
        ok = resp is not None
        print(f"[HidGesture] Divert CID 0x{CID_GESTURE:04X}: "
              f"{'OK' if ok else 'FAILED'}")
        return ok

    def _undivert(self):
        """Restore default button behaviour (best-effort)."""
        if self._feat_idx is None or self._dev is None:
            return
        hi = (CID_GESTURE >> 8) & 0xFF
        lo = CID_GESTURE & 0xFF
        try:
            self._tx(LONG_ID, self._feat_idx, 3,
                     [hi, lo, 0x02])          # dvalid=1, divert=0
        except Exception:
            pass

    # ── DPI control ───────────────────────────────────────────────

    def set_dpi(self, dpi_value):
        """Queue a DPI change — will be applied on the listener thread.
        Can be called from any thread.  Returns True on success."""
        dpi = max(200, min(8200, int(dpi_value)))  # MX Master 3S max is 8000
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

    # ── notification handling ─────────────────────────────────────

    def _on_report(self, raw):
        """Inspect an incoming HID++ report for a divertedButtonsEvent."""
        msg = _parse(raw)
        if msg is None:
            return
        _, feat, func, _sw, params = msg

        # Only care about notifications from REPROG_CONTROLS_V4, event 0
        if feat != self._feat_idx or func != 0:
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

        gesture_now = CID_GESTURE in cids

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

    # ── connect / main loop ───────────────────────────────────────

    def _try_connect(self):
        """Open the vendor HID collection, discover features, divert."""
        infos = self._vendor_hid_infos()
        if not infos:
            return False

        for info in infos:
            pid = info.get("product_id", 0)
            up  = info.get("usage_page", 0)
            try:
                d = _hid.device()
                d.open_path(info["path"])
                d.set_nonblocking(True)   # non-blocking: don't touch main run loop
                self._dev = d
            except Exception as exc:
                print(f"[HidGesture] Can't open PID=0x{pid:04X} "
                      f"UP=0x{up:04X}: {exc}")
                continue

            # Try Bluetooth direct (0xFF) first, then Bolt receiver slots
            for idx in (0xFF, 1, 2, 3, 4, 5, 6):
                self._dev_idx = idx
                fi = self._find_feature(FEAT_REPROG_V4)
                if fi is not None:
                    self._feat_idx = fi
                    print(f"[HidGesture] Found REPROG_V4 @0x{fi:02X}  "
                          f"PID=0x{pid:04X} devIdx=0x{idx:02X}")
                    # Also discover ADJUSTABLE_DPI
                    dpi_fi = self._find_feature(FEAT_ADJ_DPI)
                    if dpi_fi:
                        self._dpi_idx = dpi_fi
                        print(f"[HidGesture] Found ADJUSTABLE_DPI @0x{dpi_fi:02X}")
                    if self._divert():
                        return True
                    break        # right device but divert failed

            # Couldn't use this interface — close and try next
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

        return False

    def _main_loop(self):
        """Outer loop: connect → listen → reconnect on error/disconnect."""
        while self._running:
            if not self._try_connect():
                print("[HidGesture] No compatible device; retrying in 5 s…")
                for _ in range(50):
                    if not self._running:
                        return
                    time.sleep(0.1)
                continue

            print("[HidGesture] Listening for gesture events…")
            try:
                while self._running:
                    # Apply any queued DPI command
                    if self._pending_dpi is not None:
                        if self._pending_dpi == "read":
                            self._apply_pending_read_dpi()
                        else:
                            self._apply_pending_dpi()
                    raw = self._rx(1000)
                    if raw:
                        self._on_report(raw)
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
            self._held = False

            if self._running:
                time.sleep(2)
