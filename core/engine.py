"""
Engine — wires the mouse hook to the key simulator using the
current configuration.  Sits between the hook layer and the UI.
Supports per-application auto-switching of profiles.
"""

import threading
import time
from core.mouse_hook import MouseHook, MouseEvent
from core.key_simulator import (
    ACTIONS, execute_action, is_mouse_button_action,
    inject_mouse_down, inject_mouse_up,
)
from core.config import (
    load_config, get_active_mappings, get_profile_for_app,
    BUTTON_TO_EVENTS, GESTURE_DIRECTION_BUTTONS, save_config,
)
from core.app_detector import AppDetector
from core.linux_permissions import (
    linux_permission_log_message,
    linux_permission_report,
    linux_permission_status_message,
)
from core.logi_devices import clamp_dpi

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
        self._last_connection_state = bool(self.hook.device_connected)
        self._last_hid_features_ready = bool(self.hid_features_ready)
        self._hid_replay_requested_this_launch = False
        self._replay_inflight = False
        self._replay_pending_rerun = False
        self._replay_lock = threading.Lock()
        self._mouse_release_timers = {}   # action_id → Timer for safety auto-release
        self._lock = threading.Lock()
        self.hook.set_debug_callback(self._emit_debug)
        self.hook.set_gesture_callback(self._emit_gesture_event)
        self._setup_hooks()
        self.hook.set_connection_change_callback(self._on_connection_change)
        # Apply persisted DPI setting
        dpi = self.cfg.get("settings", {}).get("dpi", 1000)
        try:
            if hasattr(self.hook, "set_dpi"):
                self.hook.set_dpi(dpi)
        except Exception as e:
            print(f"[Engine] Failed to set DPI: {e}")

    # ------------------------------------------------------------------
    # Hook wiring
    # ------------------------------------------------------------------
    def _setup_hooks(self):
        """Register callbacks and block events for all mapped buttons."""
        mappings = get_active_mappings(self.cfg)

        # Apply scroll inversion settings to the hook
        settings = self.cfg.get("settings", {})
        self.hook.invert_vscroll = settings.get("invert_vscroll", False)
        self.hook.invert_hscroll = settings.get("invert_hscroll", False)
        if hasattr(self.hook, "ignore_trackpad"):
            self.hook.ignore_trackpad = settings.get("ignore_trackpad", True)
        self.hook.debug_mode = self._debug_events_enabled
        self.hook.configure_gestures(
            enabled=any(mappings.get(key, "none") != "none"
                        for key in GESTURE_DIRECTION_BUTTONS),
            threshold=settings.get("gesture_threshold", 50),
            deadzone=settings.get("gesture_deadzone", 40),
            timeout_ms=settings.get("gesture_timeout_ms", 3000),
            cooldown_ms=settings.get("gesture_cooldown_ms", 500),
        )
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

        self._emit_mapping_snapshot("Hook mappings refreshed", mappings)

        for btn_key, action_id in mappings.items():
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
                            self.hook.register(evt_type, self._make_handler(action_id))
                    else:
                        self.hook.register(evt_type, self._make_handler(action_id))

    def _make_handler(self, action_id):
        def handler(event):
            try:
                if self._enabled:
                    self._emit_debug(
                        f"Mapped {event.event_type} -> {action_id} "
                        f"({self._action_label(action_id)})"
                    )
                    if event.event_type.startswith("gesture_"):
                        self._emit_gesture_event({
                            "type": "mapped",
                            "event_name": event.event_type,
                            "action_id": action_id,
                            "action_label": self._action_label(action_id),
                        })
                    if action_id == "toggle_smart_shift":
                        self._toggle_smart_shift()
                    elif action_id == "switch_scroll_mode":
                        self._switch_scroll_mode()
                    elif action_id == "cycle_dpi":
                        self._cycle_dpi()
                    else:
                        execute_action(action_id)
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

    def _toggle_smart_shift(self):
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

    def _switch_scroll_mode(self):
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

    def _cycle_dpi(self):
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
            0.1,
            float(self.cfg.get("settings", {}).get("hscroll_threshold", 1)),
        )

    # ------------------------------------------------------------------
    # Per-app auto-switching
    # ------------------------------------------------------------------
    def _on_app_change(self, exe_name: str):
        """Called by AppDetector when foreground window changes."""
        target = get_profile_for_app(self.cfg, exe_name)
        if target == self._current_profile:
            return
        print(f"[Engine] App changed to {exe_name} -> profile '{target}'")
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
                    level = hg.read_battery()
                    if stop_event.is_set():
                        return
                    if level is not None and self._battery_read_cb:
                        try:
                            self._battery_read_cb(level)
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
        """Register ``cb(level: int)`` invoked when battery level is read (0-100)."""
        self._battery_read_cb = cb

    def set_connection_change_callback(self, cb):
        """Register ``cb(connected: bool)`` invoked on device connect/disconnect."""
        self._connection_change_cb = cb
        if cb:
            try:
                cb(bool(self.hook.device_connected))
            except Exception:
                pass

    @property
    def device_connected(self):
        return self.hook.device_connected

    @property
    def connected_device(self):
        return getattr(self.hook, "connected_device", None)

    def dump_device_info(self):
        return getattr(self.hook, "dump_device_info", lambda: None)()

    @property
    def hid_features_ready(self):
        hg = self.hook._hid_gesture
        return hg is not None and getattr(hg, "connected_device", None) is not None

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
        self._battery_poll_stop.set()
        if self._battery_poll_thread is not None:
            self._battery_poll_thread.join(timeout=5)
            self._battery_poll_thread = None
        self._app_detector.stop()
        self.hook.stop()
