"""
Engine — wires the mouse hook to the key simulator using the
current configuration.  Sits between the hook layer and the UI.
Supports per-application auto-switching of profiles.
"""

import threading
from core.mouse_hook import MouseHook, MouseEvent
from core.keyboard_hook import KeyboardHook
from core.key_simulator import execute_action
from core.config import (
    load_config, get_active_mappings, get_active_keyboard_mappings,
    get_profile_for_app,
    BUTTON_TO_EVENTS, KEYBOARD_BUTTON_TO_EVENTS,
    save_config,
)
from core.app_detector import AppDetector
from core.devices import get_device_config, DEVICE_TYPE_KEYBOARD


class Engine:
    """
    Core logic: reads config, installs the mouse hook,
    dispatches actions when mapped buttons are pressed,
    and auto-switches profiles when the foreground app changes.
    """

    def __init__(self):
        self.hook = MouseHook()
        self.keyboard_hook = KeyboardHook()
        self.cfg = load_config()
        self._enabled = True
        self._hscroll_accum = 0
        self._current_profile: str = self.cfg.get("active_profile", "default")
        self._app_detector = AppDetector(self._on_app_change)
        self._profile_change_cb = None       # UI callback
        self._connection_change_cb = None   # UI callback for device status
        self._battery_read_cb = None        # UI callback for battery level
        self._device_change_cb = None       # UI callback for device type change
        self._battery_poll_stop = threading.Event()
        self._lock = threading.Lock()
        self._current_device = None         # device config dict or None
        self._setup_hooks()
        self.hook.set_connection_change_callback(self._on_connection_change)
        self.hook.set_device_detected_callback(self._on_device_detected)
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

        for btn_key, action_id in mappings.items():
            events = list(BUTTON_TO_EVENTS.get(btn_key, ()))

            for evt_type in events:
                if evt_type.endswith("_up"):
                    if action_id != "none":
                        self.hook.block(evt_type)
                    continue

                if action_id != "none":
                    self.hook.block(evt_type)

                    if "hscroll" in evt_type:
                        self.hook.register(evt_type, self._make_hscroll_handler(action_id))
                    else:
                        self.hook.register(evt_type, self._make_handler(action_id))

        # Wire keyboard key mappings
        keyboard_mappings = get_active_keyboard_mappings(self.cfg)
        for key, action_id in keyboard_mappings.items():
            events = list(KEYBOARD_BUTTON_TO_EVENTS.get(key, ()))
            for evt_type in events:
                if action_id != "none":
                    self.keyboard_hook.block(evt_type)
                    self.keyboard_hook.register(
                        evt_type, self._make_handler(action_id))

    def _make_handler(self, action_id):
        def handler(event):
            if self._enabled:
                execute_action(action_id)
        return handler

    def _make_hscroll_handler(self, action_id):
        def handler(event):
            if not self._enabled:
                return
            execute_action(action_id)
        return handler

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
            self.keyboard_hook.reset_bindings()
            self._setup_hooks()
        # Notify UI (if connected)
        if self._profile_change_cb:
            try:
                self._profile_change_cb(profile_name)
            except Exception:
                pass

    def set_profile_change_callback(self, cb):
        """Register a callback ``cb(profile_name)`` invoked on auto-switch."""
        self._profile_change_cb = cb

    def set_device_change_callback(self, cb):
        """Register ``cb(device_config: dict)`` invoked when connected device is identified."""
        self._device_change_cb = cb

    def _on_device_detected(self, pid: int):
        """Called from HidGestureListener when a device is identified."""
        device = get_device_config(pid)
        self._current_device = device
        print(f"[Engine] Detected device: {device['name']} (PID=0x{pid:04X})")
        if self._device_change_cb:
            try:
                self._device_change_cb(device)
            except Exception:
                pass

    def _on_connection_change(self, connected):
        if not connected:
            self._current_device = None
            if self._device_change_cb:
                try:
                    self._device_change_cb(None)
                except Exception:
                    pass
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass
        self._battery_poll_stop.set()   # stop any existing poll loop
        if connected:
            self._battery_poll_stop = threading.Event()
            threading.Thread(
                target=self._battery_poll_loop, daemon=True, name="BatteryPoll"
            ).start()

    def _battery_poll_loop(self):
        """Read battery on connect then every 5 minutes while connected."""
        import time
        time.sleep(1)   # brief settle after connect
        stop = self._battery_poll_stop
        while not stop.is_set():
            hg = self.hook._hid_gesture
            if hg:
                level = hg.read_battery()
                if level is not None and self._battery_read_cb:
                    try:
                        self._battery_read_cb(level)
                    except Exception:
                        pass
            if stop.wait(300):   # 5 minutes between polls; exits immediately if stopped
                break

    def set_battery_callback(self, cb):
        """Register ``cb(level: int)`` invoked when battery level is read (0-100)."""
        self._battery_read_cb = cb

    def set_connection_change_callback(self, cb):
        """Register ``cb(connected: bool)`` invoked on device connect/disconnect."""
        self._connection_change_cb = cb

    @property
    def device_connected(self):
        return self.hook.device_connected

    @property
    def current_device(self):
        """Device config dict for the currently connected device, or None."""
        return self._current_device

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_dpi(self, dpi_value):
        """Send DPI change to the mouse via HID++."""
        self.cfg.setdefault("settings", {})["dpi"] = dpi_value
        save_config(self.cfg)
        # Try via the hook's HidGestureListener
        hg = self.hook._hid_gesture
        if hg:
            return hg.set_dpi(dpi_value)
        print("[Engine] No HID++ connection — DPI not applied")
        return False

    def reload_mappings(self):
        """
        Called by the UI when the user changes a mapping.
        Re-wire callbacks without tearing down the hook or HID++.
        """
        with self._lock:
            self.cfg = load_config()
            self._current_profile = self.cfg.get("active_profile", "default")
            self.hook.reset_bindings()
            self.keyboard_hook.reset_bindings()
            self._setup_hooks()

    def set_enabled(self, enabled):
        self._enabled = enabled

    def start(self):
        self.hook.start()
        self.keyboard_hook.start()
        self._app_detector.start()
        # Read current DPI from device on startup (don't overwrite it)
        self._dpi_read_cb = None   # UI callback for initial DPI
        def _read_dpi():
            import time
            time.sleep(3)  # give HID++ time to connect
            hg = self.hook._hid_gesture
            if hg:
                current = hg.read_dpi()
                if current is not None:
                    self.cfg.setdefault("settings", {})["dpi"] = current
                    save_config(self.cfg)
                    if self._dpi_read_cb:
                        try:
                            self._dpi_read_cb(current)
                        except Exception:
                            pass
        threading.Thread(target=_read_dpi, daemon=True).start()

    def set_dpi_read_callback(self, cb):
        """Register a callback ``cb(dpi_value)`` invoked when DPI is read from device."""
        self._dpi_read_cb = cb

    def stop(self):
        self._app_detector.stop()
        self.hook.stop()
        self.keyboard_hook.stop()

