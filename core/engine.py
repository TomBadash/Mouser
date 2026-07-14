"""
Engine — wires the mouse hook to the key simulator using the
current configuration.  Sits between the hook layer and the UI.
Supports per-application auto-switching of profiles.
"""

import sys
import threading
import time
from core.mouse_hook import MouseHook, MouseEvent
from core.key_simulator import (
    ACTIONS, execute_action, is_mouse_button_action,
    inject_mouse_down, inject_mouse_up,
)
from core.config import (
    load_config, get_active_mappings, get_profile_for_app_identity,
    BUTTON_TO_EVENTS, BUTTON_HOLD_EVENTS, SWIPE_SET_FOR_TAP,
    save_config, action_haptic_enabled, button_haptic_enabled,
    WHEEL_DIVERT_OFF, coerce_wheel_divert_setting,
)
from core.app_detector import AppDetector
from core.mouse_hook_types import HidRuntimeState
from core.linux_permissions import (
    linux_permission_log_message,
    linux_permission_report,
    linux_permission_status_message,
)
from core.logi_devices import clamp_dpi
from core.actions_ring import ActionsRingController

HSCROLL_ACTION_COOLDOWN_S = 0.35
HSCROLL_VOLUME_COOLDOWN_S = 0.06
_VOLUME_ACTIONS = {"volume_up", "volume_down"}


class Engine:
    """
    Core logic: reads config, installs the mouse hook,
    dispatches actions when mapped buttons are pressed,
    and auto-switches profiles when the foreground app changes.
    """

    def __init__(self):
        self.hook = MouseHook()
        self.cfg = load_config()
        self._enabled = True
        self._last_haptic_time = 0.0
        self._hscroll_state = {
            MouseEvent.HSCROLL_LEFT: {"accum": 0.0, "last_fire_at": 0.0},
            MouseEvent.HSCROLL_RIGHT: {"accum": 0.0, "last_fire_at": 0.0},
        }
        self._current_profile: str = self.cfg.get("active_profile", "default")
        self._app_detector = AppDetector(self._on_app_change)
        self._profile_change_cb = None       # UI callback
        self._connection_change_cb = None   # UI callback for device status
        self._status_cb = None             # UI callback for status messages
        self._battery_read_cb = None        # UI callback for battery level
        self._dpi_read_cb = None            # UI callback for current DPI
        self._smart_shift_read_cb = None   # UI callback for Smart Shift mode
        self._debug_cb = None               # UI callback for debug messages
        self._gesture_event_cb = None       # UI callback for structured gesture events
        self._debug_events_enabled = bool(
            self.cfg.get("settings", {}).get("debug_mode", False)
        )
        self._battery_poll_stop = threading.Event()
        self._battery_poll_thread = None          # track the poller thread
        self._last_connection_state = bool(self._hid_runtime_state().input_ready)
        self._wheel_divert_change_cb = None
        self._wheel_divert_active_local = False
        self._last_native_invert_target = (False, False)
        self._last_hid_features_ready = bool(self.hid_features_ready)
        self._hid_replay_requested_this_launch = False
        self._desktop_info_cache = None
        self._desktop_info_ts = 0.0
        self._desktop_direction = "right"
        self._replay_inflight = False
        self._replay_pending_rerun = False
        self._replay_lock = threading.Lock()
        self._mouse_release_timers = {}   # action_id → Timer for safety auto-release
        self._ring = None                 # ActionsRingController (created in _setup_hooks)
        self._ring_show_cb = None         # UI callback for showing ring overlay
        self._ring_hide_cb = None         # UI callback for hiding ring overlay
        self._ring_sector_cb = None       # UI callback to get current overlay sector
        self._ring_move_cb = None         # UI callback for rawXY deltas → overlay
        self._lock = threading.Lock()
        self.hook.set_debug_callback(self._emit_debug)
        self.hook.set_gesture_callback(self._emit_gesture_event)
        self.hook.set_status_callback(self._emit_status)
        self._setup_hooks()
        self.hook.set_connection_change_callback(self._on_connection_change)
        self.hook.set_battery_notify_callback(self._on_hid_battery_notification)
        # Apply persisted DPI setting
        dpi = self.cfg.get("settings", {}).get("dpi", 1000)
        try:
            if hasattr(self.hook, "set_dpi"):
                self.hook.set_dpi(dpi)
        except Exception as e:
            print(f"[Engine] Failed to set DPI: {e}")

    def _hid_runtime_state(self):
        state = getattr(self.hook, "hid_runtime_state", None)
        if state is not None:
            return state
        hg = getattr(self.hook, "_hid_gesture", None)
        hid_device = getattr(hg, "connected_device", None) if hg else None
        return HidRuntimeState(
            input_ready=bool(getattr(self.hook, "device_connected", False)),
            hid_ready=hid_device is not None,
            connected_device=getattr(self.hook, "connected_device", None),
        )

    # ------------------------------------------------------------------
    # Hook wiring
    # ------------------------------------------------------------------
    def _setup_hooks(self, *, defer_wheel_invert=False):
        """Register callbacks and block events for all mapped buttons.

        When ``defer_wheel_invert`` is True the blocking native wheel-invert
        write is skipped; the caller is responsible for applying it off the
        HID listener thread (see ``_on_connection_change``).
        """
        mappings = get_active_mappings(self.cfg)

        # Apply scroll inversion settings to the hook
        settings = self.cfg.get("settings", {})
        self.hook.invert_vscroll = settings.get("invert_vscroll", False)
        self.hook.invert_hscroll = settings.get("invert_hscroll", False)
        if hasattr(self.hook, "ignore_trackpad"):
            self.hook.ignore_trackpad = settings.get("ignore_trackpad", True)
        self.hook.debug_mode = self._debug_events_enabled
        ring_btn_key = next(
            (k for k, v in mappings.items()
             if isinstance(v, str) and v == "activate_actions_ring"),
            None,
        )

        # Map the two swipe-capable tap buttons to the hook's two recognizers.
        # The hook's *primary* recognizer is whichever control emits the
        # device's primary gesture events: the Sense Panel ("actions_ring") on
        # the MX Master 4, else the Gesture button ("gesture"). The MX4's thumb
        # ("gesture") drives the *thumb* recognizer.
        via_sense = bool(
            getattr(self.connected_device, "gesture_via_sense_panel", False)
        )
        primary_tap_key = "actions_ring" if via_sense else "gesture"
        thumb_tap_key = "gesture" if via_sense else None

        g_threshold = settings.get("gesture_threshold", 25)
        g_commit = settings.get("gesture_commit_window_ms", 400)
        g_settle = settings.get("gesture_settle_ms", 90)
        g_cross = settings.get("gesture_cross_ratio", 0.5)

        def _swipe_enabled(tap_key):
            # A button's swipe set is active only when its tap is "Do Nothing"
            # and at least one direction is mapped.
            if mappings.get(tap_key, "none") != "none":
                return False
            return any(mappings.get(k, "none") != "none"
                       for k in SWIPE_SET_FOR_TAP.get(tap_key, ()))

        primary_ring = mappings.get(primary_tap_key) == "activate_actions_ring"
        self.hook.configure_gestures(
            enabled=_swipe_enabled(primary_tap_key),
            threshold=g_threshold, commit_window_ms=g_commit,
            settle_ms=g_settle, cross_ratio=g_cross,
        )
        if hasattr(self.hook, "set_gesture_os_passthrough"):
            self.hook.set_gesture_os_passthrough(
                primary_ring,
                move_callback=self._on_gesture_rawxy if primary_ring else None,
            )

        if thumb_tap_key and hasattr(self.hook, "configure_thumb_gestures"):
            thumb_ring = mappings.get(thumb_tap_key) == "activate_actions_ring"
            self.hook.configure_thumb_gestures(
                enabled=_swipe_enabled(thumb_tap_key),
                threshold=g_threshold, commit_window_ms=g_commit,
                settle_ms=g_settle, cross_ratio=g_cross,
            )
            if hasattr(self.hook, "set_thumb_os_passthrough"):
                self.hook.set_thumb_os_passthrough(
                    thumb_ring,
                    move_callback=self._on_gesture_rawxy if thumb_ring else None,
                )
        elif hasattr(self.hook, "configure_thumb_gestures"):
            # No secondary control on this device — keep it disabled.
            self.hook.configure_thumb_gestures(enabled=False)

        # Swipe-direction keys whose owning tap button is set to the Actions
        # Ring: their movement drives the ring, so the swipe events never fire
        # and we must not block them.
        ring_suppressed_swipes = set()
        for tap_key, swipe_keys in SWIPE_SET_FOR_TAP.items():
            if mappings.get(tap_key) == "activate_actions_ring":
                ring_suppressed_swipes.update(swipe_keys)
        if not defer_wheel_invert:
            self._apply_wheel_invert_setting()
        # Divert mode shift CID only when the device has the button and
        # at least one profile maps it to an action.  When no device is
        # connected yet, assume the button exists (safe: if the device
        # turns out not to have it, the divert simply has no effect).
        device = getattr(self, "connected_device", None)
        device_buttons = getattr(device, "supported_buttons", None)
        has_mode_shift = device_buttons is None or "mode_shift" in device_buttons
        self.hook.divert_mode_shift = (
            has_mode_shift
            and any(
                pdata.get("mappings", {}).get("mode_shift", "none") != "none"
                for pdata in self.cfg.get("profiles", {}).values()
            )
        )

        # Divert DPI switch CID (0x00FD) on MX Vertical when mapped.
        has_dpi_switch = device_buttons is None or "dpi_switch" in device_buttons
        self.hook.divert_dpi_switch = (
            has_dpi_switch
            and any(
                pdata.get("mappings", {}).get("dpi_switch", "none") != "none"
                for pdata in self.cfg.get("profiles", {}).values()
            )
        )

        # Actions Ring controller — create/recreate on every hook setup so
        # profile switches pick up the new slot list automatically.
        if self._ring:
            self._ring.shutdown()
            self._ring = None

        any_ring = any(
            v == "activate_actions_ring"
            for v in mappings.values() if isinstance(v, str)
        )
        if any_ring:
            # Ring slot contents are global (shared by every app) unless the
            # user opts into per-app rings.  Global mode ignores any per-app
            # actions_ring_slots; per-app mode falls back to the global list
            # when the active profile has none.
            if settings.get("actions_ring_use_global", True):
                slots = settings.get("actions_ring_slots", [])
            else:
                slots = (mappings.get("actions_ring_slots")
                         or settings.get("actions_ring_slots", []))
            hold_ms = settings.get("actions_ring_hold_ms", 250)
            ring_btn = ring_btn_key or ""
            self._ring = ActionsRingController(
                slots=slots,
                hold_ms=hold_ms,
                execute_cb=self._execute_ring_action,
                play_haptic_cb=lambda wf, _b=ring_btn: (
                    self._play_haptic_async(wf)
                    if button_haptic_enabled(self.cfg, _b) else None
                ),
                show_ring_cb=self._on_ring_show,
                hide_ring_cb=self._on_ring_hide,
                move_cb=self._on_ring_move,
            )

        self._emit_mapping_snapshot("Hook mappings refreshed", mappings)

        for btn_key, action_id in mappings.items():
            if not isinstance(action_id, str):
                continue
            # Actions Ring — route through controller when mapped to the ring action.
            if action_id == "activate_actions_ring" and self._ring is not None:
                ring = self._ring
                events = list(BUTTON_TO_EVENTS.get(btn_key, ()))
                has_down = any(e.endswith("_down") for e in events)
                has_up = any(e.endswith("_up") for e in events)
                if has_down and has_up:
                    down_evt = next(e for e in events if e.endswith("_down"))
                    up_evt = next(e for e in events if e.endswith("_up"))
                    self.hook.block(down_evt)
                    self.hook.block(up_evt)
                    self.hook.register(down_evt,
                                       lambda e, r=ring: r.on_button_down())
                    self.hook.register(up_evt,
                                       lambda e, r=ring: self._on_ring_button_up(r))
                else:
                    hold_events = BUTTON_HOLD_EVENTS.get(btn_key)
                    if hold_events:
                        down_evt, up_evt = hold_events
                        self.hook.block(down_evt)
                        self.hook.block(up_evt)
                        self.hook.register(down_evt,
                                           lambda e, r=ring: r.on_button_down())
                        self.hook.register(up_evt,
                                           lambda e, r=ring: self._on_ring_button_up(r))
                        for evt_type in events:
                            self.hook.block(evt_type)
                    else:
                        for evt_type in events:
                            self.hook.block(evt_type)
                            self.hook.register(evt_type,
                                               lambda e, r=ring: r.on_click())
                continue

            if btn_key in ring_suppressed_swipes:
                continue

            events = list(BUTTON_TO_EVENTS.get(btn_key, ()))
            has_paired_down = any(e.endswith("_down") for e in events)
            has_up = any(e.endswith("_up") for e in events)

            for evt_type in events:
                if has_paired_down and evt_type.endswith("_up"):
                    if action_id != "none":
                        self.hook.block(evt_type)
                        if is_mouse_button_action(action_id):
                            self.hook.register(evt_type, self._make_mouse_up_handler(action_id))
                    continue

                if action_id != "none":
                    self.hook.block(evt_type)

                    if "hscroll" in evt_type:
                        self.hook.register(evt_type, self._make_hscroll_handler(action_id))
                    elif is_mouse_button_action(action_id):
                        if has_up:
                            # Button has a matching _up event → split press/release
                            self.hook.register(evt_type, self._make_mouse_down_handler(action_id))
                        else:
                            # Single-fire event (gesture, swipe) → full click
                            self.hook.register(evt_type, self._make_handler(action_id, btn_key))
                    else:
                        self.hook.register(evt_type, self._make_handler(action_id, btn_key))
                elif (not evt_type.endswith("_up")
                      and button_haptic_enabled(self.cfg, btn_key)):
                    # "Do Nothing" but button has haptic enabled — observe without
                    # consuming the event so the click still passes through normally.
                    self.hook.register(evt_type, self._make_handler("none", btn_key))

    def _make_handler(self, action_id, btn_key=""):
        def handler(event):
            try:
                if self._enabled:
                    self._emit_debug(
                        f"Mapped {event.event_type} -> {action_id} "
                        f"({self._action_label(action_id)})"
                    )
                    if event.event_type.startswith(("gesture_", "sense_")):
                        self._emit_gesture_event({
                            "type": "mapped",
                            "event_name": event.event_type,
                            "action_id": action_id,
                            "action_label": self._action_label(action_id),
                        })
                        # Gesture resolved — same OR gate as regular presses.
                        if (action_haptic_enabled(self.cfg, action_id)
                                or button_haptic_enabled(self.cfg, btn_key)):
                            self._play_haptic_async(7)  # COMPLETED
                    elif not event.event_type.endswith("_up"):
                        # Regular press — fires when EITHER action OR button gate passes.
                        if (action_haptic_enabled(self.cfg, action_id)
                                or button_haptic_enabled(self.cfg, btn_key)):
                            wf = 3 if action_id == "cycle_dpi" else 1
                            self._play_haptic_async(wf)
                    self._dispatch_action(action_id, btn_key)
            except Exception as exc:
                print(f"[Engine] _make_handler EXCEPTION for {action_id}: {exc}")
                import traceback; traceback.print_exc()
        return handler

    def _make_mouse_down_handler(self, action_id):
        def _safety_release():
            """Auto-release if the UP event never fires."""
            try:
                print(f"[Engine] SAFETY RELEASE fired for {action_id} (UP never received)")
                self._mouse_release_timers.pop(action_id, None)
                inject_mouse_up(action_id)
            except Exception as exc:
                print(f"[Engine] _safety_release EXCEPTION for {action_id}: {exc}")
                import traceback; traceback.print_exc()

        def handler(event):
            try:
                if self._enabled:
                    self._emit_debug(
                        f"Mapped {event.event_type} -> {action_id} (mouse down)"
                    )
                    inject_mouse_down(action_id)
                    # Safety: auto-release after 20s if UP event is never received
                    old = self._mouse_release_timers.pop(action_id, None)
                    if old is not None:
                        old.cancel()
                    t = threading.Timer(20.0, _safety_release)
                    t.daemon = True
                    self._mouse_release_timers[action_id] = t
                    t.start()
            except Exception as exc:
                print(f"[Engine] mouse_down_handler EXCEPTION for {action_id}: {exc}")
                import traceback; traceback.print_exc()
        return handler

    def _make_mouse_up_handler(self, action_id):
        def handler(event):
            try:
                if self._enabled:
                    self._emit_debug(
                        f"Mapped {event.event_type} -> {action_id} (mouse up)"
                    )
                    # Cancel safety timer
                    old = self._mouse_release_timers.pop(action_id, None)
                    if old is not None:
                        old.cancel()
                    inject_mouse_up(action_id)
            except Exception as exc:
                print(f"[Engine] mouse_up_handler EXCEPTION for {action_id}: {exc}")
                import traceback; traceback.print_exc()
        return handler

    def _toggle_smart_shift(self, btn_key=""):
        """Toggle SmartShift auto-switching on/off.

        IMPORTANT: this is called from a HID event callback which runs on the HID
        loop thread.  Calling hg.set_smart_shift() directly would block waiting for
        the same loop to process the pending request — a deadlock that causes the
        3-second timeout seen in the logs.  Config and UI are updated synchronously;
        the device write is dispatched to a separate thread.
        """
        settings = self.cfg.get("settings", {})
        new_enabled = not settings.get("smart_shift_enabled", False)
        mode = settings.get("smart_shift_mode", "ratchet")
        threshold = settings.get("smart_shift_threshold", 25)
        print(f"[Engine] toggle_smart_shift -> enabled={new_enabled}")
        settings["smart_shift_enabled"] = new_enabled
        save_config(self.cfg)
        if self._smart_shift_read_cb:
            try:
                self._smart_shift_read_cb({"mode": mode, "enabled": new_enabled, "threshold": threshold})
            except Exception:
                pass
        hg = self.hook._hid_gesture
        if hg:
            def _write():
                ok = hg.set_smart_shift(mode, new_enabled, threshold)
                print(f"[Engine] toggle_smart_shift device write -> {'OK' if ok else 'FAILED'}")
            threading.Thread(target=_write, daemon=True, name="ToggleSmartShift").start()

    def _switch_scroll_mode(self, btn_key=""):
        """Switch between ratchet and free-spin (Logi Options+ physical button behaviour).

        SmartShift auto-switching is disabled so the chosen fixed mode takes effect.
        Same deadlock caveat as _toggle_smart_shift — device write runs off-thread.
        """
        settings = self.cfg.get("settings", {})
        current_mode = settings.get("smart_shift_mode", "ratchet")
        new_mode = "freespin" if current_mode == "ratchet" else "ratchet"
        threshold = settings.get("smart_shift_threshold", 25)
        print(f"[Engine] switch_scroll_mode -> {new_mode}")
        settings["smart_shift_mode"] = new_mode
        settings["smart_shift_enabled"] = False
        save_config(self.cfg)
        if self._smart_shift_read_cb:
            try:
                self._smart_shift_read_cb({"mode": new_mode, "enabled": False, "threshold": threshold})
            except Exception:
                pass
        hg = self.hook._hid_gesture
        if hg:
            def _write():
                ok = hg.set_smart_shift(new_mode, False, threshold)
                print(f"[Engine] switch_scroll_mode device write -> {'OK' if ok else 'FAILED'}")
            threading.Thread(target=_write, daemon=True, name="SwitchScrollMode").start()

    _DEFAULT_DPI_PRESETS = [800, 1200, 1600, 2400]

    def _cycle_dpi(self, btn_key=""):
        """Cycle through user-configured DPI presets.

        Advances to the next preset in the list.  If the current DPI doesn't
        match any preset, jumps to the first one.  Updates config, notifies
        the UI, and writes to the device off-thread.
        """
        settings = self.cfg.setdefault("settings", {})
        presets = settings.get("dpi_presets") or list(self._DEFAULT_DPI_PRESETS)
        if not presets:
            return
        current_dpi = settings.get("dpi", 1000)
        try:
            idx = presets.index(current_dpi)
            next_idx = (idx + 1) % len(presets)
        except ValueError:
            next_idx = 0
        new_dpi = clamp_dpi(presets[next_idx], self.connected_device)
        print(f"[Engine] cycle_dpi {current_dpi} -> {new_dpi} (preset {next_idx + 1}/{len(presets)})")
        settings["dpi"] = new_dpi
        save_config(self.cfg)
        if self._dpi_read_cb:
            try:
                self._dpi_read_cb(new_dpi)
            except Exception:
                pass
        hg = self.hook._hid_gesture
        if hg:
            def _write():
                hg.set_dpi(new_dpi)
            threading.Thread(target=_write, daemon=True, name="CycleDPI").start()

    def _apply_wheel_invert_setting(self, *, force: bool = False) -> None:
        settings = self.cfg.get("settings", {})
        kill_switch_off = (
            coerce_wheel_divert_setting(settings.get("wheel_divert")) == WHEEL_DIVERT_OFF
        )
        invert_v = bool(settings.get("invert_vscroll", False))
        invert_h = bool(settings.get("invert_hscroll", False))
        device = self.connected_device
        capable = bool(device and (
            getattr(device, "has_hires_wheel", False)
            or getattr(device, "has_thumbwheel", False)
        ))
        target_active = bool(capable and not kill_switch_off)
        hg = self.hook._hid_gesture
        if (
            not force
            and target_active == self._wheel_divert_active_local
            and target_active == bool(getattr(self.hook, "wheel_native_invert_active", False))
            and (not target_active or self._last_native_invert_target == (invert_v, invert_h))
        ):
            return
        ack = False
        if target_active and hg is not None and hasattr(hg, "request_wheel_native_invert"):
            try:
                ack = bool(hg.request_wheel_native_invert(invert_v, invert_h))
            except Exception as exc:
                print(f"[Engine] wheel native-invert request failed: {exc}")
                ack = False
        elif not target_active and hg is not None and hasattr(hg, "request_wheel_native_invert"):
            try:
                hg.request_wheel_native_invert(False, False)
            except Exception as exc:
                print(f"[Engine] wheel native-invert release failed: {exc}")
        new_active = bool(target_active and ack)
        prev_active = self._wheel_divert_active_local
        self._wheel_divert_active_local = new_active
        self.hook.wheel_native_invert_active = new_active
        self._last_native_invert_target = (invert_v, invert_h) if new_active else (False, False)
        if hg is not None and hasattr(hg, "set_wheel_divert_active_flags"):
            try:
                hg.set_wheel_divert_active_flags(
                    bool(new_active and invert_v
                         and getattr(hg, "_hires_wheel_idx", None) is not None),
                    bool(new_active and invert_h
                         and getattr(hg, "_thumbwheel_idx", None) is not None),
                )
            except Exception as exc:
                print(f"[Engine] set_wheel_divert_active_flags failed: {exc}")
        if new_active != prev_active:
            print(
                f"[Engine] wheel native-invert -> "
                f"{'ON (HID++)' if new_active else 'OFF (OS fallback)'} "
                f"capable={capable} kill_switch_off={kill_switch_off} "
                f"invert_v={invert_v} invert_h={invert_h} ack={ack}"
            )
            if not new_active and target_active:
                self._emit_status(
                    "Firmware wheel invert FAILED on a capable device -- "
                    "falling back to OS-level inversion."
                )
            self._notify_wheel_divert_change(new_active)

    def _notify_wheel_divert_change(self, active: bool) -> None:
        if self._wheel_divert_change_cb is None:
            return
        try:
            self._wheel_divert_change_cb(bool(active))
        except Exception as exc:
            print(f"[Engine] wheel divert change callback raised: {exc}")

    def set_wheel_divert_change_callback(self, cb) -> None:
        self._wheel_divert_change_cb = cb
        if cb is None:
            return
        try:
            cb(bool(self._wheel_divert_active_local))
        except Exception as exc:
            print(f"[Engine] wheel divert change callback (initial) raised: {exc}")

    @property
    def wheel_native_invert_active(self) -> bool:
        return bool(self._wheel_divert_active_local)

    @staticmethod
    def _get_macos_desktop_info():
        """Get macOS desktop count and current position (1-indexed).

        Returns (desktop_count, current_position) for the display that
        currently has the cursor.

        Uses CGSGetActiveSpace to get the current space id64, then finds
        which display's Spaces list contains that id64.  Only id64 values
        inside the Spaces array are counted (not from "Current Space" or
        "Collapsed Space" blocks).

        Only works on macOS; returns (4, 1) on other platforms.
        """
        if sys.platform != "darwin":
            return 4, 1

        import ctypes
        import subprocess
        import re

        try:
            # CGSGetActiveSpace returns the current space id64 of the
            # display where the cursor is located.
            cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
            cg.CGSMainConnectionID.restype = ctypes.c_uint32
            cg.CGSGetActiveSpace.restype = ctypes.c_int64
            cg.CGSGetActiveSpace.argtypes = [ctypes.c_uint32]
            conn = cg.CGSMainConnectionID()
            current_id64 = cg.CGSGetActiveSpace(conn)

            # Read spaces config
            result = subprocess.run(
                ['defaults', 'read', 'com.apple.spaces', 'SpacesDisplayConfiguration'],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout

            # Split by Display Identifier to get per-monitor sections
            sections = re.split(r'"Display Identifier"\s*=\s*', output)

            def _extract_spaces_id64_list(section_text):
                """Extract id64 values only from the Spaces array block."""
                spaces_match = re.search(r'Spaces\s*=\s*\(', section_text)
                if not spaces_match:
                    return []
                # Find the matching closing paren
                text = section_text[spaces_match.start():]
                depth = 0
                end = 0
                for i, c in enumerate(text):
                    if c == '(':
                        depth += 1
                    elif c == ')':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end == 0:
                    return []
                spaces_block = text[:end]
                return [int(x) for x in re.findall(r'id64 = (\d+)', spaces_block)]

            # Find the display whose Spaces list contains current_id64
            active_display_id = None
            active_id64_list = None

            for section in sections[1:]:  # skip text before first identifier
                display_id = section.split(';')[0].strip().strip('"')
                id64_list = _extract_spaces_id64_list(section)
                if current_id64 in id64_list:
                    active_display_id = display_id
                    active_id64_list = id64_list
                    break

            # Fallback: use Main display
            if active_id64_list is None:
                for section in sections[1:]:
                    display_id = section.split(';')[0].strip().strip('"')
                    if display_id == 'Main':
                        active_display_id = 'Main'
                        active_id64_list = _extract_spaces_id64_list(section)
                        break

            if not active_id64_list:
                print("[Engine] No desktops found for active monitor")
                return 4, 1

            desktop_count = len(active_id64_list)

            # Find current position (1-indexed)
            if current_id64 in active_id64_list:
                current_position = active_id64_list.index(current_id64) + 1
            else:
                current_position = 1

            print(f"[Engine] macOS desktop info: display={active_display_id}, count={desktop_count}, "
                  f"position={current_position}, id64={current_id64}, list={active_id64_list}")
            return desktop_count, current_position

        except Exception as e:
            print(f"[Engine] Error getting macOS desktop info: {e}")
            return 4, 1

    def _cycle_desktops(self):
        """Ping-pong cycle through desktops (macOS only).

        Switches right until the last desktop, then left until the first,
        then right again, etc.  Uses CGSGetActiveSpace and com.apple.spaces
        to detect desktop count and current position.
        """
        if sys.platform != "darwin":
            print("[Engine] cycle_desktops only supported on macOS")
            return

        # Get desktop info (cached for 5 seconds to avoid subprocess per press)
        now = time.time()
        if self._desktop_info_cache is None or (now - self._desktop_info_ts) > 5.0:
            self._desktop_info_cache = self._get_macos_desktop_info()
            self._desktop_info_ts = now
        desktop_count, current = self._desktop_info_cache

        # Only one desktop — nothing to cycle
        if desktop_count <= 1:
            print(f"[Engine] cycle_desktops: only {desktop_count} desktop, skipping")
            return

        direction = self._desktop_direction

        # Calculate next position
        if direction == "right":
            if current >= desktop_count:
                direction = "left"
                next_pos = current - 1
            else:
                next_pos = current + 1
        else:  # left
            if current <= 1:
                direction = "right"
                next_pos = current + 1
            else:
                next_pos = current - 1

        # Execute switch
        print(f"[Engine] cycle_desktops: {current} -> {next_pos} (direction={direction})")
        if next_pos > current:
            execute_action("space_right")
        else:
            execute_action("space_left")

        self._desktop_direction = direction
        self._desktop_info_cache = (desktop_count, next_pos)

    def _make_hscroll_handler(self, action_id):
        def handler(event):
            if not self._enabled:
                return
            state = self._hscroll_state.setdefault(
                event.event_type,
                {"accum": 0.0, "last_fire_at": 0.0},
            )
            step = self._hscroll_step(event.raw_data)
            threshold = self._hscroll_threshold()
            now = getattr(event, "timestamp", None) or time.time()

            cooldown = HSCROLL_VOLUME_COOLDOWN_S if action_id in _VOLUME_ACTIONS else HSCROLL_ACTION_COOLDOWN_S
            if now - state["last_fire_at"] < cooldown:
                state["accum"] = 0.0
                return

            state["accum"] += step
            if state["accum"] < threshold:
                return

            state["accum"] = 0.0
            state["last_fire_at"] = now
            self._emit_debug(
                f"Mapped {event.event_type} -> {action_id} "
                f"({self._action_label(action_id)})"
            )
            execute_action(action_id)
        return handler

    def _hscroll_step(self, raw_value):
        if not isinstance(raw_value, (int, float)):
            return 1.0

        # Treat large wheel deltas as a single logical step while preserving
        # sub-step deltas from macOS event tap scrolling.
        return min(abs(float(raw_value)), 1.0)

    def _hscroll_threshold(self):
        return max(
            0.01,
            float(self.cfg.get("settings", {}).get("hscroll_threshold", 1)),
        )

    # ------------------------------------------------------------------
    # Per-app auto-switching
    # ------------------------------------------------------------------
    def _on_app_change(self, app_identity: tuple[str, ...]):
        """Called by AppDetector when foreground window changes."""
        target = get_profile_for_app_identity(self.cfg, app_identity)
        if target == self._current_profile:
            return
        app_label = app_identity[0] if app_identity else ""
        print(f"[Engine] App changed to {app_label} -> profile '{target}'")
        self._switch_profile(target)

    def _switch_profile(self, profile_name: str):
        with self._lock:
            self.cfg["active_profile"] = profile_name
            self._current_profile = profile_name
            # Lightweight: just re-wire callbacks, keep hook + HID++ alive
            self.hook.reset_bindings()
            self._setup_hooks()
            self._emit_debug(f"Active profile -> {profile_name}")
        # Notify UI (if connected)
        if self._profile_change_cb:
            try:
                self._profile_change_cb(profile_name)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Actions Ring
    # ------------------------------------------------------------------

    def set_ring_show_callback(self, cb):
        """Register ``cb(slots)`` invoked when the ring overlay should appear."""
        self._ring_show_cb = cb

    def set_ring_hide_callback(self, cb):
        """Register ``cb()`` invoked when the ring overlay should disappear."""
        self._ring_hide_cb = cb

    def set_ring_sector_callback(self, cb):
        """Register ``cb() -> int`` that returns the overlay's current sector."""
        self._ring_sector_cb = cb

    def set_ring_move_callback(self, cb):
        """Register ``cb(dx, dy)`` invoked for rawXY deltas during held ring."""
        self._ring_move_cb = cb

    def _on_ring_move(self, dx, dy):
        """Called by the ring controller to forward rawXY deltas to the UI."""
        if self._ring_move_cb:
            try:
                self._ring_move_cb(dx, dy)
            except Exception as exc:
                print(f"[Engine] ring move callback error: {exc}")

    def _on_gesture_rawxy(self, dx, dy):
        """Hook callback — forward rawXY deltas to the ring controller."""
        ring = self._ring
        if ring:
            ring.on_move(dx, dy)

    def _on_ring_show(self, slots, interactive=False):
        """Called by the controller when the ring should appear."""
        if self._ring_show_cb:
            try:
                self._ring_show_cb(slots, interactive)
            except Exception as exc:
                print(f"[Engine] ring show callback error: {exc}")

    def _on_ring_hide(self):
        """Called by the controller when the ring should disappear."""
        if self._ring_hide_cb:
            try:
                self._ring_hide_cb()
            except Exception as exc:
                print(f"[Engine] ring hide callback error: {exc}")

    def _on_ring_button_up(self, ring=None):
        """Handle actions_ring_up — pass current sector from overlay to controller."""
        ring = ring or self._ring
        if not ring:
            return
        sector = None
        if self._ring_sector_cb:
            try:
                sector = self._ring_sector_cb()
            except Exception:
                pass
        ring.on_button_up(sector_override=sector)

    def ring_toggle_select(self, sector):
        """Called from the UI when user clicks a sector in toggle mode."""
        if self._ring:
            self._ring.on_toggle_select(sector)

    def ring_toggle_dismiss(self):
        """Called from the UI when user clicks center X or outside in toggle mode."""
        if self._ring:
            self._ring.on_toggle_dismiss()

    def ring_hover(self, sector):
        """Called from the UI when the hovered ring slot changes.

        Fires one haptic pulse per newly entered slot using the default
        waveform, so it plays at the user's globally configured haptic level.
        Gated on the dedicated Actions Ring hover setting; the global haptic
        toggle and dedup are enforced inside _play_haptic_async."""
        if sector is None or sector < 0:
            return
        if not self.cfg.get("settings", {}).get("actions_ring_hover_haptic", True):
            return
        self._play_haptic_async(immediate=True)

    def _dispatch_action(self, action_id, source_key=""):
        """Route an action to the appropriate engine handler or system executor."""
        if action_id == "activate_actions_ring":
            return
        elif action_id == "toggle_smart_shift":
            self._toggle_smart_shift(source_key)
        elif action_id == "switch_scroll_mode":
            self._switch_scroll_mode(source_key)
        elif action_id == "cycle_dpi":
            self._cycle_dpi(source_key)
        elif action_id == "cycle_desktops":
            self._cycle_desktops()
        else:
            execute_action(action_id)

    def _execute_ring_action(self, action_id):
        """Execute an action from the ring."""
        if not self._enabled or action_id == "none":
            return
        self._emit_debug(f"Ring action -> {action_id} ({self._action_label(action_id)})")
        self._dispatch_action(action_id, "actions_ring")

    def set_profile_change_callback(self, cb):
        """Register a callback ``cb(profile_name)`` invoked on auto-switch."""
        self._profile_change_cb = cb

    def set_debug_callback(self, cb):
        """Register ``cb(message: str)`` invoked for debug events."""
        self._debug_cb = cb

    def set_status_callback(self, cb):
        """Register ``cb(message: str)`` invoked for status messages."""
        self._status_cb = cb

    def set_gesture_event_callback(self, cb):
        """Register ``cb(event: dict)`` invoked for structured gesture debug events."""
        self._gesture_event_cb = cb

    def set_debug_enabled(self, enabled):
        enabled = bool(enabled)
        self.cfg.setdefault("settings", {})["debug_mode"] = enabled
        self._debug_events_enabled = enabled
        self.hook.debug_mode = enabled
        if enabled:
            self._emit_debug(f"Debug enabled on profile {self._current_profile}")
            self._emit_mapping_snapshot(
                "Current mappings", get_active_mappings(self.cfg)
            )

    def set_debug_events_enabled(self, enabled):
        self._debug_events_enabled = bool(enabled)
        self.hook.debug_mode = self._debug_events_enabled

    def _action_label(self, action_id):
        return ACTIONS.get(action_id, {}).get("label", action_id)

    def _emit_debug(self, message):
        if not self._debug_events_enabled:
            return
        if self._debug_cb:
            try:
                self._debug_cb(message)
            except Exception:
                pass

    def _emit_status(self, message):
        if self._status_cb:
            try:
                self._status_cb(message)
            except Exception:
                pass

    def _emit_gesture_event(self, event):
        if not self._debug_events_enabled:
            return
        if self._gesture_event_cb:
            try:
                self._gesture_event_cb(event)
            except Exception:
                pass

    def _emit_mapping_snapshot(self, prefix, mappings):
        if not self._debug_events_enabled:
            return
        interesting = [
            "gesture",
            "gesture_left",
            "gesture_right",
            "gesture_up",
            "gesture_down",
            "xbutton1",
            "xbutton2",
        ]
        summary = ", ".join(f"{key}={mappings.get(key, 'none')}" for key in interesting)
        self._emit_debug(f"{prefix}: {summary}")

    def _saved_smart_shift_state(self):
        settings = self.cfg.get("settings", {})
        return {
            "mode": settings.get("smart_shift_mode", "ratchet"),
            "enabled": settings.get("smart_shift_enabled", False),
            "threshold": settings.get("smart_shift_threshold", 25),
        }

    def _run_saved_settings_replay(self):
        hg = self.hook._hid_gesture
        if hg is None:
            return False
        if hasattr(hg, "connected_device") and hg.connected_device is None:
            return False

        replay_ok = True
        retry_dpi = False
        retry_smart_shift = False
        saved_dpi = self.cfg.get("settings", {}).get("dpi")

        saved_ss_state = self._saved_smart_shift_state()
        saved_ss = saved_ss_state["mode"]
        ss_enabled = saved_ss_state["enabled"]
        ss_threshold = saved_ss_state["threshold"]

        # Phase A: apply Smart Shift immediately so the physical wheel mode
        # converges before the settled replay.
        if saved_ss and getattr(hg, "smart_shift_supported", False):
            if not hasattr(hg, "set_smart_shift"):
                replay_ok = False
            else:
                if not hg.set_smart_shift(saved_ss, ss_enabled, ss_threshold):
                    replay_ok = False
                if self._smart_shift_read_cb:
                    try:
                        self._smart_shift_read_cb(saved_ss_state)
                    except Exception:
                        pass

        time.sleep(3)
        hg = self.hook._hid_gesture
        if hg is None or getattr(hg, "connected_device", None) is None:
            return False

        if saved_dpi is not None:
            if not hasattr(hg, "set_dpi"):
                replay_ok = False
            elif hg.set_dpi(saved_dpi):
                if self._dpi_read_cb:
                    try:
                        self._dpi_read_cb(saved_dpi)
                    except Exception:
                        pass
            else:
                replay_ok = False
                retry_dpi = True

        if saved_ss and getattr(hg, "smart_shift_supported", False):
            if not hasattr(hg, "set_smart_shift"):
                replay_ok = False
            elif hg.set_smart_shift(saved_ss, ss_enabled, ss_threshold):
                if self._smart_shift_read_cb:
                    try:
                        self._smart_shift_read_cb(saved_ss_state)
                    except Exception:
                        pass
            else:
                replay_ok = False
                retry_smart_shift = True

        if retry_dpi or retry_smart_shift:
            time.sleep(5)
            hg = self.hook._hid_gesture
            if hg is None or getattr(hg, "connected_device", None) is None:
                return False
            if retry_dpi:
                if not hasattr(hg, "set_dpi") or not hg.set_dpi(saved_dpi):
                    replay_ok = False
                elif self._dpi_read_cb:
                    try:
                        self._dpi_read_cb(saved_dpi)
                    except Exception:
                        pass
            if retry_smart_shift and getattr(hg, "smart_shift_supported", False):
                if not hasattr(hg, "set_smart_shift") or not hg.set_smart_shift(
                    saved_ss, ss_enabled, ss_threshold
                ):
                    replay_ok = False
                elif self._smart_shift_read_cb:
                    try:
                        self._smart_shift_read_cb(saved_ss_state)
                    except Exception:
                        pass

        saved_haptic = self.cfg.get("settings", {}).get("haptic_level")
        if saved_haptic is not None and getattr(hg, "haptic_supported", False):
            if hasattr(hg, "set_haptic_level"):
                hg.set_haptic_level(saved_haptic)

        saved_force = self.cfg.get("settings", {}).get("force_sensitivity")
        if saved_force is not None and getattr(hg, "force_sensing_supported", False):
            hg.set_force_sensing(saved_force)

        return replay_ok

    def _replay_saved_settings_worker(self):
        while True:
            with self._replay_lock:
                self._replay_pending_rerun = False
            replay_ok = self._run_saved_settings_replay()
            should_emit_failure = False
            with self._replay_lock:
                if self._replay_pending_rerun:
                    continue
                self._replay_inflight = False
                should_emit_failure = not replay_ok
            if should_emit_failure:
                self._emit_status(
                    "Mouse reconnected, but saved device settings could not be restored yet."
                )
            return

    def _request_saved_settings_replay(self, *, startup_fallback=False):
        with self._replay_lock:
            if startup_fallback and self._hid_replay_requested_this_launch:
                return
            if self._replay_inflight:
                self._replay_pending_rerun = True
                return
            self._hid_replay_requested_this_launch = True
            self._replay_inflight = True
        if startup_fallback:
            self._emit_status("Using startup fallback to replay saved device settings")
        threading.Thread(
            target=self._replay_saved_settings_worker,
            daemon=True,
            name="SavedSettingsReplay",
        ).start()

    def _on_connection_change(self, connected):
        connection_changed = connected != self._last_connection_state
        hid_features_ready = self.hid_features_ready
        hid_features_changed = hid_features_ready != self._last_hid_features_ready
        if connection_changed:
            self._last_connection_state = connected
            if connected:
                # Re-wire hooks now that the device (and its
                # gesture_via_sense_panel / supported_buttons) is known, so the
                # per-device gesture recognizers and rawXY hand-off are applied.
                with self._lock:
                    self.hook.reset_bindings()
                    self._setup_hooks(defer_wheel_invert=True)
                # This callback runs ON the HID listener thread. The native
                # wheel-invert write blocks until that same thread services the
                # queued request from its main loop, so applying it here would
                # deadlock until the request times out. Defer it to a worker so
                # the listener can return to its loop and complete the write.
                hg = getattr(self.hook, "_hid_gesture", None)
                if hg is not None and hasattr(hg, "request_wheel_native_invert"):
                    threading.Thread(
                        target=self._apply_wheel_invert_setting,
                        daemon=True,
                        name="WheelInvertApply",
                    ).start()
            self._battery_poll_stop.set()
            if self._battery_poll_thread is not None:
                self._battery_poll_thread.join(timeout=5)
                self._battery_poll_thread = None
        self._last_hid_features_ready = hid_features_ready
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass
        if connected and connection_changed:
            self._battery_poll_stop = threading.Event()
            self._battery_poll_thread = threading.Thread(
                target=self._battery_poll_loop,
                args=(self._battery_poll_stop,),
                daemon=True,
                name="BatteryPoll",
            )
            self._battery_poll_thread.start()
        if hid_features_ready and hid_features_changed:
            self._request_saved_settings_replay()

    def _battery_poll_loop(self, stop_event):
        """Read battery and smart shift mode periodically until disconnected."""
        _battery_poll_interval = 300   # seconds between battery reads
        _ss_poll_interval = 15         # seconds between scroll-mode reads
        _last_battery = time.time() - _battery_poll_interval  # fire immediately
        _last_ss = time.time() - _ss_poll_interval            # fire immediately
        _last_ss_mode = None

        while not stop_event.is_set():
            now = time.time()
            hg = self.hook._hid_gesture
            if hg and hg.connected_device is not None:
                if now - _last_battery >= _battery_poll_interval:
                    _last_battery = now
                    result = hg.read_battery()
                    if stop_event.is_set():
                        return
                    if result is not None and self._battery_read_cb:
                        level, charging = result
                        try:
                            self._battery_read_cb(level, charging)
                        except Exception:
                            pass

                if (
                    not self._replay_inflight
                    and now - _last_ss >= _ss_poll_interval
                    and hg.smart_shift_supported
                ):
                    _last_ss = now
                    ss_mode = hg.read_smart_shift()
                    if stop_event.is_set():
                        return
                    if ss_mode is not None:
                        if ss_mode != _last_ss_mode:
                            print(f"[Engine] Scroll mode: {ss_mode}"
                                  + (" (changed)" if _last_ss_mode is not None else ""))
                            _last_ss_mode = ss_mode
                        if self._smart_shift_read_cb:
                            try:
                                self._smart_shift_read_cb(ss_mode)
                            except Exception:
                                pass

            if stop_event.wait(5):
                return

    def set_battery_callback(self, cb):
        """Register ``cb(level: int, charging: bool)`` invoked when battery is read.

        ``level`` is 0-100; ``charging`` is True while the device reports it is
        plugged in / recharging.
        """
        self._battery_read_cb = cb

    def _on_hid_battery_notification(self, level, charging):
        """Forward an unsolicited HID++ battery event to the UI (instant)."""
        if self._battery_read_cb:
            try:
                self._battery_read_cb(level, charging)
            except Exception:
                pass

    def set_connection_change_callback(self, cb):
        """Register ``cb(connected: bool)`` invoked on device connect/disconnect."""
        self._connection_change_cb = cb
        if cb:
            try:
                cb(bool(self._hid_runtime_state().input_ready))
            except Exception:
                pass

    @property
    def device_connected(self):
        return self._hid_runtime_state().input_ready

    @property
    def connected_device(self):
        return self._hid_runtime_state().connected_device

    def dump_device_info(self):
        return getattr(self.hook, "dump_device_info", lambda: None)()

    @property
    def hid_features_ready(self):
        return self._hid_runtime_state().hid_ready

    @property
    def enabled(self):
        return self._enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_dpi(self, dpi_value):
        """Send DPI change to the mouse via HID++."""
        dpi = clamp_dpi(dpi_value, self.connected_device)
        self.cfg.setdefault("settings", {})["dpi"] = dpi
        save_config(self.cfg)
        # Try via the hook's HidGestureListener
        hg = self.hook._hid_gesture
        if hg:
            return hg.set_dpi(dpi)
        print("[Engine] No HID++ connection — DPI not applied")
        return False

    def set_smart_shift(self, mode, smart_shift_enabled=False, threshold=25):
        """Send Smart Shift settings to device.
        mode: 'ratchet' or 'freespin' (fixed mode when smart_shift_enabled=False)
        smart_shift_enabled: True to enable auto SmartShift
        threshold: 1-50 sensitivity when SmartShift is enabled"""
        print(f"[Engine] set_smart_shift({mode}, enabled={smart_shift_enabled}, threshold={threshold}) called")
        settings = self.cfg.setdefault("settings", {})
        settings["smart_shift_mode"] = mode
        settings["smart_shift_enabled"] = smart_shift_enabled
        settings["smart_shift_threshold"] = threshold
        save_config(self.cfg)
        hg = self.hook._hid_gesture
        if hg:
            result = hg.set_smart_shift(mode, smart_shift_enabled, threshold)
            print(f"[Engine] set_smart_shift -> {'OK' if result else 'FAILED'}")
            return result
        print("[Engine] set_smart_shift: No HID++ connection — not applied")
        return False

    @property
    def smart_shift_supported(self):
        hg = self.hook._hid_gesture
        return hg.smart_shift_supported if hg else False

    @property
    def haptic_supported(self):
        hg = self.hook._hid_gesture
        return hg.haptic_supported if hg else False

    def set_haptic_level(self, level):
        """Send haptic level to the mouse and persist to config."""
        level = max(0, min(3, int(level)))
        settings = self.cfg.setdefault("settings", {})
        settings["haptic_level"] = level
        save_config(self.cfg)
        hg = self.hook._hid_gesture
        if hg:
            return hg.set_haptic_level(level)
        print("[Engine] No HID++ connection -- haptic level not applied")
        return False

    @property
    def force_sensing_supported(self):
        hg = self.hook._hid_gesture
        return getattr(hg, "force_sensing_supported", False) if hg else False

    @property
    def force_sensing_range(self):
        hg = self.hook._hid_gesture
        return getattr(hg, "force_sensing_range", None) if hg else None

    def set_force_sensitivity(self, value):
        """Send force sensitivity to the mouse and persist to config."""
        value = int(value)
        settings = self.cfg.setdefault("settings", {})
        settings["force_sensitivity"] = value
        save_config(self.cfg)
        hg = self.hook._hid_gesture
        if hg:
            return hg.set_force_sensing(value)
        print("[Engine] No HID++ connection -- force sensitivity not applied")
        return False

    def play_haptic_waveform(self, waveform_id=0):
        """Trigger a haptic waveform on the mouse."""
        hg = self.hook._hid_gesture
        if hg:
            return hg.play_haptic_waveform(waveform_id)
        return False

    def _play_haptic_async(self, waveform_id=0, immediate=False):
        """Queue a haptic pulse with minimal latency.

        Calls queue_haptic_waveform() which sets _pending_haptic directly on
        the HidGestureListener.  Because HID++ event callbacks are dispatched
        synchronously on the listener thread, this flag is set before _on_report
        returns, so the listener loop picks it up at the very next iteration
        (before the next _rx() call) rather than waiting for an incoming event.

        When ``immediate`` is True the pulse is written straight to the device
        instead of queued.  Use it for pulses triggered off the listener
        thread (e.g. an Actions Ring hover from the UI thread), where the
        listener would otherwise be parked in its blocking read for up to a
        second before draining the queue."""
        if not self.cfg.get("settings", {}).get("haptic_enabled", True):
            return
        if self.cfg.get("settings", {}).get("haptic_dedup", True):
            now = time.monotonic()
            if now - self._last_haptic_time < 0.1:
                return
            self._last_haptic_time = now
        hg = self.hook._hid_gesture
        if hg and hg.haptic_supported:
            if immediate:
                hg.play_haptic_immediate(waveform_id)
            else:
                hg.queue_haptic_waveform(waveform_id)

    def reload_mappings(self):
        """
        Called by the UI when the user changes a mapping.
        Re-wire callbacks without tearing down the hook or HID++.
        """
        with self._lock:
            self.cfg = load_config()
            self._current_profile = self.cfg.get("active_profile", "default")
            self.hook.reset_bindings()
            self._setup_hooks()
            self._emit_debug(f"reload_mappings profile={self._current_profile}")

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

    def set_ui_passthrough(self, enabled):
        if hasattr(self.hook, "set_ui_passthrough"):
            self.hook.set_ui_passthrough(enabled)

    def _emit_linux_permission_warning(self):
        report = linux_permission_report()
        log_message = linux_permission_log_message(report)
        if log_message:
            print(log_message)
        status_message = linux_permission_status_message(report)
        if status_message:
            self._emit_status(status_message)

    def start(self):
        self._emit_linux_permission_warning()
        self.hook.start()
        self._app_detector.start()
        # Temporary safety-net: keep the old delayed replay path until the
        # hid-ready transition path has proven out in the field.
        def _startup_replay_fallback():
            time.sleep(3)
            if not self.hid_features_ready:
                return
            self._request_saved_settings_replay(startup_fallback=True)
        threading.Thread(target=_startup_replay_fallback, daemon=True).start()

    def set_dpi_read_callback(self, cb):
        """Register a callback ``cb(dpi_value)`` invoked when DPI is read from device."""
        self._dpi_read_cb = cb

    def set_smart_shift_read_callback(self, cb):
        """Register a callback ``cb(state)`` invoked when Smart Shift is read."""
        self._smart_shift_read_cb = cb

    def stop(self):
        if self._ring:
            self._ring.shutdown()
            self._ring = None
        self._battery_poll_stop.set()
        if self._battery_poll_thread is not None:
            self._battery_poll_thread.join(timeout=5)
            self._battery_poll_thread = None
        self._app_detector.stop()
        self.hook.stop()
