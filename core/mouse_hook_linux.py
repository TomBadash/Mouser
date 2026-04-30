"""
Linux mouse hook implementation.
"""

import glob
import os
import stat
import sys
import threading
import time

try:
    import select as _select_mod
    import evdev as _evdev_mod
    from evdev import InputDevice as _InputDevice
    from evdev import UInput as _UInput
    from evdev import ecodes as _ecodes

    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False
    print("[MouseHook] python-evdev not installed — pip install evdev")

from core.logi_devices import (
    build_evdev_connected_device_info,
    resolve_device as _resolve_logi_device,
)
from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import MouseEvent

_LOGI_VENDOR = 0x046D
_LOG_ONCE_KEYS = set()


def _log_once(key, message):
    if key in _LOG_ONCE_KEYS:
        return
    _LOG_ONCE_KEYS.add(key)
    print(message)


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
    if not path:
        return "path=-"
    try:
        st = os.stat(path)
    except OSError as exc:
        return f"path={path} stat_error={exc}"

    mode = stat.S_IMODE(st.st_mode)
    can_read = os.access(path, os.R_OK)
    can_write = os.access(path, os.W_OK)
    can_rw = os.access(path, os.R_OK | os.W_OK)
    return (
        f"path={path} mode={mode:04o} "
        f"owner={_owner_name(st.st_uid)}({st.st_uid}) "
        f"group={_group_name(st.st_gid)}({st.st_gid}) "
        f"access=read:{can_read} write:{can_write} read_write:{can_rw}"
    )


def _format_linux_device_access_list(paths, limit=8):
    details = [_format_linux_device_access(path) for path in list(paths)[:limit]]
    remaining = max(0, len(paths) - limit)
    if remaining:
        details.append(f"... {remaining} more")
    return "; ".join(details) if details else "-"


class MouseHook(BaseMouseHook):
    """
    Uses evdev on Linux to intercept mouse button presses and scroll events.
    Grabs the mouse device for exclusive access and forwards non-blocked events
    via a uinput virtual mouse.
    """

    def __init__(self):
        super().__init__()
        self._running = False
        self._evdev_ready = False
        self._hid_ready = False
        self._evdev_connected_device = None
        self._gesture_lock = threading.Lock()
        self._evdev_device = None
        self._uinput = None
        self._evdev_thread = None
        self._rescan_requested = threading.Event()
        self._evdev_wakeup = threading.Event()
        self._ignored_non_logitech = set()

    @property
    def evdev_ready(self):
        return self._evdev_ready

    @property
    def hid_ready(self):
        return self._hid_ready

    def _set_evdev_ready(self, ready):
        if ready == self._evdev_ready:
            return
        self._evdev_ready = ready
        self._refresh_device_state(force=True)

    def _set_device_connected(self, connected, force=False):
        changed = connected != self._device_connected
        if not changed and not force:
            return
        self._device_connected = connected
        if changed:
            state = "Connected" if connected else "Disconnected"
            print(f"[MouseHook] Device {state}")
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass

    def _build_evdev_connected_device(self, dev):
        info = getattr(dev, "info", None)
        return build_evdev_connected_device_info(
            product_id=getattr(info, "product", None) if info else None,
            product_name=getattr(dev, "name", None),
            transport="evdev",
            source="evdev",
        )

    def _refresh_device_state(self, force=False):
        previous = self._connected_device
        next_device = None
        if self._hid_ready and self._hid_gesture:
            next_device = self._hid_gesture.connected_device
        if next_device is None:
            next_device = self._evdev_connected_device
        self._connected_device = next_device

        prev_source = getattr(previous, "source", None) if previous is not None else None
        next_source = getattr(next_device, "source", None) if next_device is not None else None
        if prev_source != next_source:
            if next_source == "evdev":
                print("[MouseHook] Using evdev fallback device info")
            elif prev_source == "evdev" and next_device is not None:
                print("[MouseHook] Device info upgraded from evdev fallback to HID++")

        self._set_device_connected(self._evdev_ready, force=force)

    def _hid_gesture_available(self):
        return self._hid_gesture is not None and self._evdev_ready

    def _accumulate_gesture_delta(self, delta_x, delta_y, source):
        dispatch_event = None
        with self._gesture_lock:
            if not (self._gesture_direction_enabled and self._gesture_active):
                return
            if self._gesture_cooldown_active():
                self._emit_debug(
                    f"Gesture cooldown active source={source} "
                    f"dx={delta_x} dy={delta_y}"
                )
                self._emit_gesture_event(
                    {
                        "type": "cooldown_active",
                        "source": source,
                        "dx": delta_x,
                        "dy": delta_y,
                    }
                )
                return
            if not self._gesture_tracking:
                self._emit_debug(f"Gesture tracking started source={source}")
                self._emit_gesture_event(
                    {
                        "type": "tracking_started",
                        "source": source,
                    }
                )
                self._start_gesture_tracking()

            now = time.monotonic()
            idle_ms = (now - self._gesture_last_move_at) * 1000.0
            if idle_ms > self._gesture_timeout_ms:
                self._emit_debug(
                    f"Gesture segment reset timeout source={source} "
                    f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
                )
                self._start_gesture_tracking()

            if source == "hid_rawxy" and self._gesture_input_source == "evdev":
                self._emit_debug(
                    "Gesture source promoted from evdev to hid_rawxy "
                    f"prev_accum_x={self._gesture_delta_x} "
                    f"prev_accum_y={self._gesture_delta_y}"
                )
                self._start_gesture_tracking()

            if self._gesture_input_source not in (None, source):
                self._emit_debug(
                    f"Gesture source locked to {self._gesture_input_source}; "
                    f"ignoring {source} dx={delta_x} dy={delta_y}"
                )
                return
            self._gesture_input_source = source

            self._gesture_delta_x += delta_x
            self._gesture_delta_y += delta_y
            self._gesture_last_move_at = now
            self._emit_debug(
                f"Gesture segment source={source} "
                f"accum_x={self._gesture_delta_x} accum_y={self._gesture_delta_y}"
            )
            self._emit_gesture_event(
                {
                    "type": "segment",
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                }
            )

            gesture_event = self._detect_gesture_event()
            if not gesture_event:
                return

            self._gesture_triggered = True
            self._emit_debug(
                "Gesture detected "
                f"{gesture_event} source={source} "
                f"delta_x={self._gesture_delta_x} delta_y={self._gesture_delta_y}"
            )
            self._emit_gesture_event(
                {
                    "type": "detected",
                    "event_name": gesture_event,
                    "source": source,
                    "dx": self._gesture_delta_x,
                    "dy": self._gesture_delta_y,
                }
            )
            dispatch_event = MouseEvent(
                gesture_event,
                {
                    "delta_x": self._gesture_delta_x,
                    "delta_y": self._gesture_delta_y,
                    "source": source,
                },
            )
            self._gesture_cooldown_until = (
                time.monotonic() + self._gesture_cooldown_ms / 1000.0
            )
            self._emit_debug(
                f"Gesture cooldown started source={source} "
                f"for_ms={self._gesture_cooldown_ms}"
            )
            self._emit_gesture_event(
                {
                    "type": "cooldown_started",
                    "source": source,
                    "for_ms": self._gesture_cooldown_ms,
                }
            )
            self._finish_gesture_tracking()

        if dispatch_event:
            self._dispatch(dispatch_event)

    def _on_hid_gesture_down(self):
        with self._gesture_lock:
            if not self._gesture_active:
                self._gesture_active = True
                self._gesture_triggered = False
                self._emit_debug("HID gesture button down")
                self._emit_gesture_event({"type": "button_down"})
                if self._gesture_direction_enabled and not self._gesture_cooldown_active():
                    self._start_gesture_tracking()
                else:
                    self._gesture_tracking = False
                    self._gesture_triggered = False

    def _on_hid_gesture_up(self):
        dispatch_click = False
        with self._gesture_lock:
            if self._gesture_active:
                should_click = not self._gesture_triggered
                self._gesture_active = False
                self._finish_gesture_tracking()
                self._gesture_triggered = False
                self._emit_debug(
                    f"HID gesture button up click_candidate={str(should_click).lower()}"
                )
                self._emit_gesture_event(
                    {
                        "type": "button_up",
                        "click_candidate": should_click,
                    }
                )
                dispatch_click = should_click
        if dispatch_click:
            self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _on_hid_mode_shift_down(self):
        self._emit_debug("HID mode shift button down")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        self._emit_debug("HID mode shift button up")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        self._emit_debug("HID DPI switch button down")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._emit_debug("HID DPI switch button up")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))

    def _on_hid_gesture_move(self, delta_x, delta_y):
        self._emit_debug(f"HID rawxy move dx={delta_x} dy={delta_y}")
        self._emit_gesture_event(
            {
                "type": "move",
                "source": "hid_rawxy",
                "dx": delta_x,
                "dy": delta_y,
            }
        )
        self._accumulate_gesture_delta(delta_x, delta_y, "hid_rawxy")

    def _on_hid_connect(self):
        self._hid_ready = True
        self._refresh_device_state(force=True)
        dev = self._evdev_device
        should_wake_evdev = (
            self._running
            and _EVDEV_OK
            and (
                dev is None
                or not self._evdev_ready
                or dev.info.vendor != _LOGI_VENDOR
            )
        )
        if should_wake_evdev:
            print("[MouseHook] Logitech HID connected; waking evdev scan")
            self._rescan_requested.set()
            self._evdev_wakeup.set()

    def _on_hid_disconnect(self):
        self._hid_ready = False
        if self._gesture_active:
            self._gesture_active = False
            self._finish_gesture_tracking()
            self._gesture_triggered = False
        self._refresh_device_state(force=True)

    def _find_mouse_device(self):
        logi_mice = []
        try:
            paths = list(_evdev_mod.list_devices())
        except Exception as exc:
            _log_once(
                ("evdev-list-error", type(exc).__name__, str(exc)),
                f"[MouseHook] Cannot list evdev devices: {exc}",
            )
            return None
        if not paths:
            event_paths = sorted(glob.glob("/dev/input/event*"))
            if event_paths:
                _log_once(
                    "evdev-empty-fallback-event-nodes",
                    "[MouseHook] evdev returned no input devices; falling "
                    "back to visible /dev/input/event* nodes: "
                    f"{_format_linux_device_access_list(event_paths)}",
                )
                paths = event_paths
            else:
                _log_once(
                    "evdev-no-input-devices",
                    "[MouseHook] evdev returned no input devices and no "
                    "/dev/input/event* nodes are visible; remapping needs "
                    f"/dev/input/event* access. "
                    f"{_format_linux_device_access('/dev/input')}",
                )

        for path in paths:
            try:
                dev = _InputDevice(path)
            except PermissionError as exc:
                _log_once(
                    ("evdev-open-permission", path),
                    f"[MouseHook] Permission denied opening {path}: {exc}. "
                    f"{_format_linux_device_access(path)}. "
                    "Add the user to a group with /dev/input/event* access "
                    "or install a udev rule.",
                )
                continue
            except Exception as exc:
                _log_once(
                    ("evdev-open-error", path, type(exc).__name__, str(exc)),
                    f"[MouseHook] Cannot open evdev device {path}: {exc}",
                )
                continue
            try:
                caps = dev.capabilities(absinfo=False)
                if _ecodes.EV_REL not in caps or _ecodes.EV_KEY not in caps:
                    dev.close()
                    continue
                rel_caps = set(caps.get(_ecodes.EV_REL, []))
                key_caps = set(caps.get(_ecodes.EV_KEY, []))
                if _ecodes.REL_X not in rel_caps or _ecodes.REL_Y not in rel_caps:
                    dev.close()
                    continue
                if not key_caps.intersection(
                    {
                        _ecodes.BTN_LEFT,
                        _ecodes.BTN_RIGHT,
                        _ecodes.BTN_MIDDLE,
                    }
                ):
                    dev.close()
                    continue
                has_side = bool(
                    key_caps.intersection(
                        {
                            _ecodes.BTN_SIDE,
                            _ecodes.BTN_EXTRA,
                        }
                    )
                )
            except PermissionError as exc:
                _log_once(
                    ("evdev-capabilities-permission", dev.path),
                    f"[MouseHook] Permission denied reading capabilities for "
                    f"{dev.path}: {exc}",
                )
                dev.close()
                continue
            except Exception as exc:
                _log_once(
                    ("evdev-capabilities-error", dev.path, type(exc).__name__, str(exc)),
                    f"[MouseHook] Cannot inspect evdev device {dev.path}: {exc}",
                )
                dev.close()
                continue
            if dev.info.vendor == _LOGI_VENDOR:
                logi_mice.append((dev, has_side))
            else:
                info = getattr(dev, "info", None)
                dedupe_key = (
                    dev.path,
                    getattr(info, "vendor", 0),
                    getattr(info, "product", 0),
                    dev.name or "",
                )
                if dedupe_key not in self._ignored_non_logitech:
                    self._ignored_non_logitech.add(dedupe_key)
                    print(
                        "[MouseHook] Ignoring non-Logitech evdev candidate: "
                        f"{dev.name} ({dev.path}) "
                        f"vendor=0x{getattr(info, 'vendor', 0):04X} "
                        f"product=0x{getattr(info, 'product', 0):04X}"
                    )
                dev.close()

        def _event_num(dev):
            try:
                return int(str(dev.path).rsplit("event", 1)[1])
            except (IndexError, ValueError):
                return -1

        def _sort_key(item):
            dev, has_side = item
            info = getattr(dev, "info", None)
            spec = _resolve_logi_device(
                product_id=getattr(info, "product", None),
                product_name=getattr(dev, "name", None),
            )
            return (
                int(spec is not None),
                int(has_side),
                _event_num(dev),
            )

        ordered = sorted(logi_mice, key=_sort_key, reverse=True)
        if ordered:
            chosen = ordered[0][0]
            for dev, _ in ordered[1:]:
                dev.close()
            print(
                f"[MouseHook] Found mouse: {chosen.name} ({chosen.path}) "
                f"vendor=0x{chosen.info.vendor:04X}"
            )
            return chosen
        _log_once(
            "evdev-no-logitech-mouse",
            "[MouseHook] No Logitech evdev mouse found; UI connection state "
            "and remapping require a Logitech mouse visible under "
            "/dev/input/event* with vendor 0x046D",
        )
        return None

    def _setup_evdev(self):
        dev = self._find_mouse_device()
        if not dev:
            return False
        try:
            self._uinput = _UInput.from_device(dev, name="Mouser Virtual Mouse")
            dev.grab()
            self._evdev_device = dev
            self._evdev_connected_device = self._build_evdev_connected_device(dev)
            self._set_evdev_ready(True)
            print(f"[MouseHook] Grabbed {dev.name} ({dev.path})")
            return True
        except PermissionError:
            print(
                "[MouseHook] Permission denied — add user to 'input' group "
                "and ensure /dev/uinput is writable"
            )
            dev.close()
        except Exception as exc:
            print(f"[MouseHook] Failed to setup evdev: {exc}")
            dev.close()
        return False

    def _cleanup_evdev(self):
        if self._evdev_device:
            try:
                self._evdev_device.ungrab()
            except Exception:
                pass
            try:
                self._evdev_device.close()
            except Exception:
                pass
            self._evdev_device = None
            print("[MouseHook] evdev device released")
        if self._uinput:
            try:
                self._uinput.close()
            except Exception:
                pass
            self._uinput = None
        self._evdev_connected_device = None
        self._set_evdev_ready(False)

    def _evdev_loop(self):
        while self._running:
            self._rescan_requested.clear()
            if not self._setup_evdev():
                if self._running:
                    self._wait_for_evdev_wakeup(2)
                continue
            try:
                self._listen_loop()
            except OSError as exc:
                if self._running:
                    print(f"[MouseHook] Device disconnected: {exc}")
            except Exception as exc:
                if self._running:
                    print(f"[MouseHook] evdev error: {exc}")
            finally:
                self._cleanup_evdev()
            if self._running:
                if self._rescan_requested.is_set():
                    continue
                self._wait_for_evdev_wakeup(1)

    def _wait_for_evdev_wakeup(self, timeout):
        self._evdev_wakeup.wait(timeout)
        self._evdev_wakeup.clear()

    def _listen_loop(self):
        fd = self._evdev_device.fd
        while self._running:
            if self._rescan_requested.is_set():
                print("[MouseHook] Rescan requested; leaving listen loop")
                return
            readable, _, _ = _select_mod.select([fd], [], [], 0.5)
            if not readable:
                continue
            for event in self._evdev_device.read():
                if not self._running:
                    return
                if event.type == _ecodes.EV_SYN:
                    self._uinput.write_event(event)
                elif event.type == _ecodes.EV_KEY:
                    self._handle_button(event)
                elif event.type == _ecodes.EV_REL:
                    self._handle_rel(event)
                else:
                    self._uinput.write_event(event)

    def _handle_button(self, event):
        mouse_event = None
        should_block = False

        if event.code == _ecodes.BTN_SIDE:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.XBUTTON1_UP)
                should_block = MouseEvent.XBUTTON1_UP in self._blocked_events

        elif event.code == _ecodes.BTN_EXTRA:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.XBUTTON2_UP)
                should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

        elif event.code == _ecodes.BTN_MIDDLE:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.MIDDLE_UP)
                should_block = MouseEvent.MIDDLE_UP in self._blocked_events

        if mouse_event:
            self._dispatch(mouse_event)

        if not should_block:
            self._uinput.write_event(event)

    def _handle_rel(self, event):
        code = event.code
        value = event.value

        if code == _ecodes.REL_X or code == _ecodes.REL_Y:
            if self._gesture_direction_enabled and self._gesture_active:
                if self._gesture_input_source != "hid_rawxy":
                    if code == _ecodes.REL_X:
                        self._accumulate_gesture_delta(value, 0, "evdev")
                    else:
                        self._accumulate_gesture_delta(0, value, "evdev")
                return
            self._uinput.write_event(event)
            return

        rel_wheel_hi_res = getattr(_ecodes, "REL_WHEEL_HI_RES", 0x0B)
        if code == _ecodes.REL_WHEEL or code == rel_wheel_hi_res:
            if self.invert_vscroll:
                self._uinput.write(_ecodes.EV_REL, code, -value)
            else:
                self._uinput.write_event(event)
            return

        rel_hwheel_hi_res = getattr(_ecodes, "REL_HWHEEL_HI_RES", 0x0C)
        if code == _ecodes.REL_HWHEEL or code == rel_hwheel_hi_res:
            should_block = False
            if value > 0:
                should_block = MouseEvent.HSCROLL_RIGHT in self._blocked_events
            elif value < 0:
                should_block = MouseEvent.HSCROLL_LEFT in self._blocked_events

            if code == _ecodes.REL_HWHEEL:
                if value > 0:
                    self._dispatch(MouseEvent(MouseEvent.HSCROLL_RIGHT, abs(value)))
                elif value < 0:
                    self._dispatch(MouseEvent(MouseEvent.HSCROLL_LEFT, abs(value)))

            if should_block:
                return
            if self.invert_hscroll:
                self._uinput.write(_ecodes.EV_REL, code, -value)
            else:
                self._uinput.write_event(event)
            return

        self._uinput.write_event(event)

    def _install_crash_guard(self):
        import atexit
        import signal

        atexit.register(self._cleanup_evdev)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            prev = signal.getsignal(sig)

            def _handler(signum, frame, _prev=prev):
                self._cleanup_evdev()
                if callable(_prev) and _prev not in (signal.SIG_DFL, signal.SIG_IGN):
                    _prev(signum, frame)
                else:
                    raise SystemExit(128 + signum)

            signal.signal(sig, _handler)

    def start(self):
        self._running = True

        self._start_hid_listener()

        if _EVDEV_OK:
            self._install_crash_guard()
            self._evdev_thread = threading.Thread(
                target=self._evdev_loop,
                daemon=True,
                name="MouseHook-evdev",
            )
            self._evdev_thread.start()
        else:
            print("[MouseHook] evdev not available — button remapping disabled")

        return True

    def stop(self):
        self._running = False
        self._stop_hid_listener()
        self._hid_ready = False
        self._connected_device = None
        self._evdev_connected_device = None
        self._rescan_requested.set()
        self._evdev_wakeup.set()
        if self._evdev_thread:
            self._evdev_thread.join(timeout=2)
            self._evdev_thread = None
        self._cleanup_evdev()


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "_select_mod",
    "_evdev_mod",
    "_InputDevice",
    "_UInput",
    "_ecodes",
    "_EVDEV_OK",
    "_LOGI_VENDOR",
]
