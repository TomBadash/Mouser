"""
QML Backend Bridge — connects the QML UI to the engine and config.
Exposes properties, signals, and slots for two-way data binding.
"""

import os
import re
import sys
import time

from PySide6.QtCore import QMetaObject, QObject, Property, QTimer, Signal, Slot, Qt

from core.accessibility import is_process_trusted
from core.config import (
    BUTTON_NAMES, load_config, save_config, get_active_mappings,
    PROFILE_BUTTON_NAMES, set_mapping, create_profile, delete_profile,
    get_icon_for_exe,
)
from core import app_catalog
from core.device_layouts import get_device_layout, get_manual_layout_choices
from core.logi_devices import (
    DEFAULT_DPI_MAX,
    DEFAULT_DPI_MIN,
    build_evdev_connected_device_info,
    clamp_dpi,
    get_buttons_for_layout,
)
from core.key_simulator import ACTIONS, custom_action_label, valid_custom_key_names
from core.startup import (
    apply_login_startup,
    supports_login_startup,
    sync_from_config as sync_login_startup_from_config,
)


def _action_label(action_id):
    if action_id.startswith("custom:"):
        return custom_action_label(action_id)
    return ACTIONS.get(action_id, {}).get("label", "Do Nothing")


class Backend(QObject):
    """QML-exposed backend that bridges the engine and configuration."""

    # ── Signals ────────────────────────────────────────────────
    mappingsChanged = Signal()
    settingsChanged = Signal()
    profilesChanged = Signal()
    activeProfileChanged = Signal()
    statusMessage = Signal(str)
    dpiFromDevice = Signal(int)
    smartShiftChanged = Signal()
    mouseConnectedChanged = Signal()
    hidFeaturesReadyChanged = Signal()
    batteryLevelChanged = Signal()
    debugLogChanged = Signal()
    debugEventsEnabledChanged = Signal()
    gestureStateChanged = Signal()
    gestureRecordsChanged = Signal()
    deviceInfoChanged = Signal()
    deviceLayoutChanged = Signal()
    knownAppsChanged = Signal()

    # Internal cross-thread signals
    _profileSwitchRequest = Signal(str)
    _dpiReadRequest = Signal(int)
    _connectionChangeRequest = Signal(bool)
    _batteryChangeRequest = Signal(int)
    _debugMessageRequest = Signal(str)
    _gestureEventRequest = Signal(object)
    _smartShiftReadRequest = Signal()
    _statusMessageRequest = Signal(str)

    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._cfg = load_config()
        self._mouse_connected = False
        self._device_display_name = "Logitech mouse"
        self._connected_device_key = ""
        self._device_layout_override_key = ""
        self._device_layout = get_device_layout("generic_mouse")
        self._device_dpi_min = DEFAULT_DPI_MIN
        self._device_dpi_max = DEFAULT_DPI_MAX
        self._connected_device_source = ""
        self._battery_level = -1
        self._hid_features_ready = False
        self._debug_lines = []
        self._debug_events_enabled = bool(
            self._cfg.get("settings", {}).get("debug_mode", False)
        )
        self._record_mode = False
        self._gesture_records = []
        self._gesture_active = False
        self._gesture_move_seen = False
        self._gesture_move_source = ""
        self._gesture_move_dx = 0
        self._gesture_move_dy = 0
        self._gesture_status = "Idle"
        self._current_attempt = None
        self._pending_smart_shift_state = None  # thread-safe staging area
        self._effective_supported_buttons = None  # set by _apply_device_layout
        self._connected_device_refresh_pending = False
        self._connected_device_refresh_attempts = 0

        # Cross-thread signal connections
        self._profileSwitchRequest.connect(
            self._handleProfileSwitch, Qt.QueuedConnection)
        self._dpiReadRequest.connect(
            self._handleDpiRead, Qt.QueuedConnection)
        self._connectionChangeRequest.connect(
            self._handleConnectionChange, Qt.QueuedConnection)
        self._batteryChangeRequest.connect(
            self._handleBatteryChange, Qt.QueuedConnection)
        self._debugMessageRequest.connect(
            self._handleDebugMessage, Qt.QueuedConnection)
        self._gestureEventRequest.connect(
            self._handleGestureEvent, Qt.QueuedConnection)
        self._smartShiftReadRequest.connect(
            self._handleSmartShiftRead, Qt.QueuedConnection)
        self._statusMessageRequest.connect(
            self._handleStatusMessage, Qt.QueuedConnection)

        # Wire engine callbacks
        if engine:
            engine.set_profile_change_callback(self._onEngineProfileSwitch)
            engine.set_dpi_read_callback(self._onEngineDpiRead)
            engine.set_connection_change_callback(self._onEngineConnectionChange)
            if hasattr(engine, "set_battery_callback"):
                engine.set_battery_callback(self._onEngineBatteryRead)
            if hasattr(engine, "set_debug_callback"):
                engine.set_debug_callback(self._onEngineDebugMessage)
            if hasattr(engine, "set_gesture_event_callback"):
                engine.set_gesture_event_callback(self._onEngineGestureEvent)
            if hasattr(engine, "set_smart_shift_read_callback"):
                engine.set_smart_shift_read_callback(self._onEngineSmartShiftRead)
            if hasattr(engine, "set_status_callback"):
                engine.set_status_callback(self._onEngineStatusMessage)
            if hasattr(engine, "set_debug_enabled"):
                engine.set_debug_enabled(self.debugMode)
            self._mouse_connected = bool(getattr(engine, "device_connected", False))
            self._hid_features_ready = bool(
                getattr(engine, "hid_features_ready", False)
            )
        if supports_login_startup():
            sync_login_startup_from_config(self.startAtLogin)
        else:
            self._cfg.setdefault("settings", {})["start_at_login"] = False
        self._sync_connected_device_info()

    # ── Properties ─────────────────────────────────────────────

    @Property(list, notify=mappingsChanged)
    def buttons(self):
        """List of button dicts for the active profile, filtered by device."""
        mappings = get_active_mappings(self._cfg)
        device_buttons = set(
            self._effective_supported_buttons or BUTTON_NAMES.keys()
        )
        result = []
        idx = 0
        for key, name in BUTTON_NAMES.items():
            if key not in device_buttons:
                continue
            aid = mappings.get(key, "none")
            idx += 1
            result.append({
                "key": key,
                "name": name,
                "actionId": aid,
                "actionLabel": _action_label(aid),
                "index": idx,
            })
        return result

    def _hidden_actions(self):
        """Return set of action IDs to hide based on effective device buttons."""
        btns = self._effective_supported_buttons
        hidden = set()
        if btns and "mode_shift" not in btns:
            hidden.add("toggle_smart_shift")
            hidden.add("switch_scroll_mode")
        return hidden

    @Property(list, notify=deviceLayoutChanged)
    def actionCategories(self):
        """Actions grouped by category, filtered by device capabilities."""
        from collections import OrderedDict
        hidden = self._hidden_actions()
        cats = OrderedDict()
        for aid in sorted(
            ACTIONS,
            key=lambda a: (
                "0" if ACTIONS[a]["category"] == "Other" else "1" + ACTIONS[a]["category"],
                ACTIONS[a]["label"],
            ),
        ):
            if aid in hidden:
                continue
            data = ACTIONS[aid]
            cat = data["category"]
            cats.setdefault(cat, []).append({"id": aid, "label": data["label"]})
        result = [{"category": c, "actions": a} for c, a in cats.items()]
        result.append({"category": "Custom", "actions": [
            {"id": "__custom__", "label": "Custom Shortcut\u2026"}
        ]})
        return result

    @Property(list, notify=deviceLayoutChanged)
    def allActions(self):
        """Flat sorted action list (Do Nothing first), filtered by device."""
        hidden = self._hidden_actions()
        result = []
        none_data = ACTIONS.get("none")
        if none_data:
            result.append({"id": "none", "label": none_data["label"],
                           "category": "Other"})
        for aid in sorted(
            ACTIONS,
            key=lambda a: (ACTIONS[a]["category"], ACTIONS[a]["label"]),
        ):
            if aid == "none" or aid in hidden:
                continue
            data = ACTIONS[aid]
            result.append({"id": aid, "label": data["label"],
                           "category": data["category"]})
        result.append({"id": "__custom__", "label": "Custom Shortcut\u2026",
                        "category": "Custom"})
        return result

    @Property(list, constant=True)
    def validKeyNames(self):
        """List of valid key names for custom shortcuts."""
        return valid_custom_key_names()

    @Property(int, notify=settingsChanged)
    def dpi(self):
        return self._cfg.get("settings", {}).get("dpi", 1000)

    _DEFAULT_DPI_PRESETS = [800, 1200, 1600, 2400]

    @Property(list, notify=settingsChanged)
    def dpiPresets(self):
        return self._cfg.get("settings", {}).get(
            "dpi_presets", list(self._DEFAULT_DPI_PRESETS)
        )

    @Slot(int, int)
    def setDpiPreset(self, index, value):
        """Set a single DPI preset slot (0-3) to *value*."""
        device = getattr(self._engine, "connected_device", None) if self._engine else None
        clamped = clamp_dpi(value, device)
        presets = list(self._cfg.get("settings", {}).get(
            "dpi_presets", list(self._DEFAULT_DPI_PRESETS)
        ))
        while len(presets) < 4:
            presets.append(self._DEFAULT_DPI_PRESETS[len(presets) % 4])
        if 0 <= index < len(presets):
            presets[index] = clamped
        self._cfg.setdefault("settings", {})["dpi_presets"] = presets
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
        self.settingsChanged.emit()

    @Property(str, notify=smartShiftChanged)
    def smartShiftMode(self):
        return self._cfg.get("settings", {}).get("smart_shift_mode", "ratchet")

    @Property(bool, notify=smartShiftChanged)
    def smartShiftEnabled(self):
        return bool(self._cfg.get("settings", {}).get("smart_shift_enabled", False))

    @Property(int, notify=smartShiftChanged)
    def smartShiftThreshold(self):
        return int(self._cfg.get("settings", {}).get("smart_shift_threshold", 25))

    @Property(bool, notify=hidFeaturesReadyChanged)
    def smartShiftSupported(self):
        return self._engine.smart_shift_supported if self._engine else False

    @Property(bool, notify=deviceLayoutChanged)
    def deviceHasSmartShift(self):
        """Whether the effective device has a mode_shift button (SmartShift)."""
        btns = self._effective_supported_buttons
        return btns is None or "mode_shift" in btns

    @Property(bool, notify=settingsChanged)
    def startMinimized(self):
        return bool(self._cfg.get("settings", {}).get("start_minimized", True))

    @Property(bool, notify=settingsChanged)
    def startAtLogin(self):
        return bool(self._cfg.get("settings", {}).get("start_at_login", False))

    @Property(bool, constant=True)
    def supportsStartAtLogin(self):
        return supports_login_startup()

    @Property(bool, notify=settingsChanged)
    def invertVScroll(self):
        return self._cfg.get("settings", {}).get("invert_vscroll", False)

    @Property(bool, notify=settingsChanged)
    def invertHScroll(self):
        return self._cfg.get("settings", {}).get("invert_hscroll", False)

    @Property(int, notify=settingsChanged)
    def gestureThreshold(self):
        return int(self._cfg.get("settings", {}).get("gesture_threshold", 50))

    @Property(str, notify=settingsChanged)
    def appearanceMode(self):
        mode = self._cfg.get("settings", {}).get("appearance_mode", "system")
        return mode if mode in {"system", "light", "dark"} else "system"

    @Property(bool, notify=settingsChanged)
    def debugMode(self):
        return bool(self._cfg.get("settings", {}).get("debug_mode", False))

    @Property(bool, notify=debugEventsEnabledChanged)
    def debugEventsEnabled(self):
        return self._debug_events_enabled

    @Property(bool, constant=True)
    def supportsGestureDirections(self):
        return sys.platform in ("darwin", "win32", "linux")

    @Property(bool, constant=True)
    def accessibilityGranted(self):
        """Whether macOS Accessibility permission is granted (always True on other platforms)."""
        if sys.platform != "darwin":
            return True
        try:
            return bool(is_process_trusted())
        except Exception:
            return True

    @Property(str, notify=activeProfileChanged)
    def activeProfile(self):
        return self._cfg.get("active_profile", "default")

    @Property(bool, notify=mouseConnectedChanged)
    def mouseConnected(self):
        return self._mouse_connected

    @Property(bool, notify=hidFeaturesReadyChanged)
    def hidFeaturesReady(self):
        return self._hid_features_ready

    @Property(str, notify=deviceInfoChanged)
    def deviceDisplayName(self):
        return self._device_display_name

    @Property(str, notify=deviceInfoChanged)
    def connectedDeviceKey(self):
        return self._connected_device_key

    @Property(int, notify=deviceInfoChanged)
    def deviceDpiMin(self):
        return self._device_dpi_min

    @Property(int, notify=deviceInfoChanged)
    def deviceDpiMax(self):
        return self._device_dpi_max

    @Property(str, notify=deviceLayoutChanged)
    def deviceImageAsset(self):
        return self._device_layout.get("image_asset", "mouse.png")

    @Property(int, notify=deviceLayoutChanged)
    def deviceImageWidth(self):
        return int(self._device_layout.get("image_width", 460))

    @Property(int, notify=deviceLayoutChanged)
    def deviceImageHeight(self):
        return int(self._device_layout.get("image_height", 360))

    @Property(bool, notify=deviceLayoutChanged)
    def hasInteractiveDeviceLayout(self):
        return bool(self._device_layout.get("interactive", True))

    @Property(str, notify=deviceLayoutChanged)
    def deviceLayoutNote(self):
        return self._device_layout.get("note", "")

    @Property(list, notify=deviceLayoutChanged)
    def deviceHotspots(self):
        return list(self._device_layout.get("hotspots", []))

    @Property(list, constant=True)
    def manualLayoutChoices(self):
        return get_manual_layout_choices()

    @Property(str, notify=deviceLayoutChanged)
    def deviceLayoutOverrideKey(self):
        return self._device_layout_override_key

    @Property(str, notify=deviceLayoutChanged)
    def effectiveDeviceLayoutKey(self):
        return self._device_layout.get("key", "generic_mouse")

    @Property(int, notify=batteryLevelChanged)
    def batteryLevel(self):
        return self._battery_level

    @Property(str, notify=debugLogChanged)
    def debugLog(self):
        return "\n".join(self._debug_lines)

    @Property(bool, notify=gestureStateChanged)
    def recordMode(self):
        return self._record_mode

    @Property(bool, notify=gestureStateChanged)
    def gestureActive(self):
        return self._gesture_active

    @Property(bool, notify=gestureStateChanged)
    def gestureMoveSeen(self):
        return self._gesture_move_seen

    @Property(str, notify=gestureStateChanged)
    def gestureMoveSource(self):
        return self._gesture_move_source

    @Property(int, notify=gestureStateChanged)
    def gestureMoveDx(self):
        return self._gesture_move_dx

    @Property(int, notify=gestureStateChanged)
    def gestureMoveDy(self):
        return self._gesture_move_dy

    @Property(str, notify=gestureStateChanged)
    def gestureStatus(self):
        return self._gesture_status

    @Property(str, notify=gestureRecordsChanged)
    def gestureRecords(self):
        return "\n\n".join(self._gesture_records)

    @Property(list, notify=profilesChanged)
    def profiles(self):
        result = []
        active = self._cfg.get("active_profile", "default")
        for pname, pdata in self._cfg.get("profiles", {}).items():
            apps = pdata.get("apps", [])
            result.append({
                "name": pname,
                "label": pdata.get("label", pname),
                "apps": apps,
                "appIcons": [get_icon_for_exe(ex) for ex in apps],
                "displayApps": [app_catalog.get_app_label(ex) for ex in apps],
                "isActive": pname == active,
            })
        return result

    @Property(list, notify=knownAppsChanged)
    def knownApps(self):
        result = []
        for entry in app_catalog.get_app_catalog():
            icon = get_icon_for_exe(entry.get("path", ""))
            result.append({
                "id": entry["id"],
                "label": entry.get("label", entry["id"]),
                "aliases": entry.get("aliases", []),
                "path": entry.get("path", ""),
                "iconSource": icon,
            })
        return result

    def _catalog_app_id(self, spec):
        entry = app_catalog.resolve_app_spec(spec)
        if not entry:
            return ""
        entry_id = entry.get("id", "")
        for catalog_entry in app_catalog.get_app_catalog():
            if catalog_entry.get("id", "").lower() == entry_id.lower():
                return catalog_entry["id"]
        return ""

    def _profile_app_identity(self, spec):
        catalog_id = self._catalog_app_id(spec)
        if catalog_id:
            return ("catalog", catalog_id.lower())

        entry = app_catalog.resolve_app_spec(spec)
        path = entry.get("path", "") if entry else ""
        if not path:
            path = spec or ""
        if not path:
            return ("", "")
        if sys.platform == "linux":
            normalized = os.path.realpath(path)
        else:
            normalized = os.path.normpath(path)
        return ("path", normalized.lower())

    def _profile_has_app(self, spec):
        target_kind, target_value = self._profile_app_identity(spec)
        if not target_value:
            return False

        for pdata in self._cfg.get("profiles", {}).values():
            for existing in pdata.get("apps", []):
                existing_kind, existing_value = self._profile_app_identity(existing)
                if existing_kind == target_kind and existing_value == target_value:
                    return True
        return False

    def _stored_profile_app_spec(self, entry, fallback_spec):
        catalog_id = self._catalog_app_id(entry.get("id", ""))
        if catalog_id:
            return catalog_id
        return entry.get("path") or fallback_spec

    # ── Slots ──────────────────────────────────────────────────

    @Slot(str, str)
    def setMapping(self, button, actionId):
        """Set a button mapping in the active profile."""
        self._cfg = set_mapping(self._cfg, button, actionId)
        if self._engine:
            self._engine.reload_mappings()
        self.mappingsChanged.emit()
        self.statusMessage.emit("Saved")

    @Slot(str, str, str)
    def setProfileMapping(self, profileName, button, actionId):
        """Set a button mapping in a specific profile."""
        self._cfg = set_mapping(self._cfg, button, actionId,
                                profile=profileName)
        if self._engine:
            self._engine.reload_mappings()
        self.profilesChanged.emit()
        self.mappingsChanged.emit()
        self.statusMessage.emit("Saved")

    @Slot(bool)
    def setStartMinimized(self, value):
        hidden = bool(value)
        if self.startMinimized == hidden:
            return
        self._cfg.setdefault("settings", {})["start_minimized"] = hidden
        save_config(self._cfg)
        self.settingsChanged.emit()
        self.statusMessage.emit("Saved")

    @Slot(bool)
    def setStartAtLogin(self, value):
        enabled = bool(value)
        if not supports_login_startup():
            self.statusMessage.emit(
                "Start at login is only available on Windows and macOS"
            )
            return
        if self.startAtLogin == enabled:
            return
        self._cfg.setdefault("settings", {})["start_at_login"] = enabled
        save_config(self._cfg)
        try:
            apply_login_startup(enabled)
        except Exception as exc:
            self.settingsChanged.emit()
            self.statusMessage.emit(f"Failed to update login item: {exc}")
            return
        self.settingsChanged.emit()
        self.statusMessage.emit(
            "Start at login enabled" if enabled else "Start at login disabled"
        )

    @Slot(int)
    def setDpi(self, value):
        device = self._resolved_connected_device()
        dpi = clamp_dpi(value, device)
        self._cfg.setdefault("settings", {})["dpi"] = dpi
        save_config(self._cfg)
        if self._engine:
            self._engine.set_dpi(dpi)
        self.settingsChanged.emit()

    def _applySmartShift(self, mode=None, enabled=None, threshold=None):
        """Update one or more SmartShift settings, persist config, and push to device."""
        settings = self._cfg.setdefault("settings", {})
        if mode is not None:
            settings["smart_shift_mode"] = mode
        if enabled is not None:
            settings["smart_shift_enabled"] = enabled
        if threshold is not None:
            settings["smart_shift_threshold"] = threshold
        save_config(self._cfg)
        if self._engine:
            self._engine.set_smart_shift(
                settings.get("smart_shift_mode", "ratchet"),
                settings.get("smart_shift_enabled", False),
                settings.get("smart_shift_threshold", 25),
            )
        self.smartShiftChanged.emit()

    @Slot(str)
    def setSmartShift(self, mode):
        self._applySmartShift(mode=mode)

    @Slot(bool)
    def setSmartShiftEnabled(self, enabled):
        self._applySmartShift(enabled=enabled)

    @Slot(int)
    def setSmartShiftThreshold(self, threshold):
        self._applySmartShift(threshold=threshold)

    @Slot(bool)
    def setInvertVScroll(self, value):
        self._cfg.setdefault("settings", {})["invert_vscroll"] = value
        save_config(self._cfg)
        if self._engine:
            self._engine.reload_mappings()
        self.settingsChanged.emit()

    @Slot(bool)
    def setInvertHScroll(self, value):
        self._cfg.setdefault("settings", {})["invert_hscroll"] = value
        save_config(self._cfg)
        if self._engine:
            self._engine.reload_mappings()
        self.settingsChanged.emit()

    @Slot(int)
    def setGestureThreshold(self, value):
        snapped = max(20, min(400, int(round(value / 5.0) * 5)))
        self._cfg.setdefault("settings", {})["gesture_threshold"] = snapped
        save_config(self._cfg)
        if self._engine:
            self._engine.reload_mappings()
        self.settingsChanged.emit()

    @Slot(str)
    def setAppearanceMode(self, mode):
        normalized = mode if mode in {"system", "light", "dark"} else "system"
        if self.appearanceMode == normalized:
            return
        self._cfg.setdefault("settings", {})["appearance_mode"] = normalized
        save_config(self._cfg)
        self.settingsChanged.emit()

    @Slot(bool)
    def setDebugMode(self, value):
        enabled = bool(value)
        self._cfg.setdefault("settings", {})["debug_mode"] = enabled
        save_config(self._cfg)
        self._debug_events_enabled = enabled
        if self._engine and hasattr(self._engine, "set_debug_enabled"):
            self._engine.set_debug_enabled(enabled)
        if enabled:
            self._append_debug_line("Debug mode enabled")
        else:
            self._append_debug_line("Debug mode disabled")
        self.settingsChanged.emit()
        self.debugEventsEnabledChanged.emit()

    @Slot(bool)
    def setDebugEventsEnabled(self, value):
        value = bool(value)
        if self._debug_events_enabled == value:
            return
        self._debug_events_enabled = value
        if self._engine and hasattr(self._engine, "set_debug_events_enabled"):
            self._engine.set_debug_events_enabled(value)
        self._append_debug_line(
            "Debug event capture enabled" if value else "Debug event capture paused"
        )
        self.debugEventsEnabledChanged.emit()

    @Slot()
    def clearDebugLog(self):
        self._debug_lines = []
        self.debugLogChanged.emit()

    @Slot(bool)
    def setRecordMode(self, value):
        self._record_mode = bool(value)
        if not self._record_mode:
            self._current_attempt = None
        self.gestureStateChanged.emit()
        self._append_debug_line(
            "Gesture recording enabled" if self._record_mode else "Gesture recording disabled"
        )

    @Slot()
    def clearGestureRecords(self):
        self._gesture_records = []
        self._current_attempt = None
        self.gestureRecordsChanged.emit()

    @Slot(str)
    def addProfile(self, appId):
        """Create a new per-app profile from an app catalog ID."""
        entry = app_catalog.resolve_app_spec(appId)
        if not entry:
            return
        app_spec = self._stored_profile_app_spec(entry, appId)
        label = entry.get("label", appId)
        if self._profile_has_app(app_spec):
            self.statusMessage.emit("Profile already exists")
            return
        safe_name = re.sub(r"[^a-z0-9_]", "_", label.lower())[:32].strip("_")
        self._cfg = create_profile(self._cfg, safe_name, label=label, apps=[app_spec])
        if self._engine:
            self._engine.cfg = self._cfg
        self.profilesChanged.emit()
        self.statusMessage.emit("Profile created")

    @Slot()
    def browseForAppProfile(self):
        """Open a file picker, then create a profile for the selected app."""
        from PySide6.QtWidgets import QFileDialog
        if sys.platform == "darwin":
            path, _ = QFileDialog.getOpenFileName(
                None, "Select Application", "/Applications", "Apps (*.app)")
        elif sys.platform == "linux":
            path, _ = QFileDialog.getOpenFileName(
                None, "Select Application",
                os.path.expanduser("~"),
                "Applications (*)")
        else:
            path, _ = QFileDialog.getOpenFileName(
                None, "Select Application",
                os.environ.get("ProgramFiles", "C:\\Program Files"),
                "Executables (*.exe)")
        if not path:
            return
        if sys.platform == "linux":
            path = os.path.realpath(path)
        else:
            path = os.path.normpath(path)
        entry = app_catalog.resolve_app_spec(path)
        label = entry.get("label") if entry else os.path.splitext(os.path.basename(path))[0]
        app_spec = self._stored_profile_app_spec(entry, path) if entry else path
        if self._profile_has_app(app_spec):
            self.statusMessage.emit("Profile already exists")
            return
        safe_name = re.sub(r"[^a-z0-9_]", "_", label.lower())[:32].strip("_")
        self._cfg = create_profile(self._cfg, safe_name, label=label, apps=[app_spec])
        if self._engine:
            self._engine.cfg = self._cfg
        self.profilesChanged.emit()
        self.statusMessage.emit("Profile created")

    @Slot()
    def refreshKnownAppsSilently(self):
        app_catalog.get_app_catalog(refresh=True)
        self.knownAppsChanged.emit()

    @Slot(str)
    def deleteProfile(self, name):
        if name == "default":
            return
        self._cfg = delete_profile(self._cfg, name)
        if self._engine:
            self._engine.cfg = self._cfg
            self._engine.reload_mappings()
        self.profilesChanged.emit()
        self.statusMessage.emit("Profile deleted")

    @Slot(str, result=list)
    def getProfileMappings(self, profileName):
        """Return button mappings for a specific profile, filtered by device."""
        profiles = self._cfg.get("profiles", {})
        pdata = profiles.get(profileName, {})
        mappings = pdata.get("mappings", {})
        device_buttons = set(
            self._effective_supported_buttons or PROFILE_BUTTON_NAMES.keys()
        )
        result = []
        for key, name in PROFILE_BUTTON_NAMES.items():
            if key not in device_buttons:
                continue
            aid = mappings.get(key, "none")
            result.append({
                "key": key,
                "name": name,
                "actionId": aid,
                "actionLabel": _action_label(aid),
            })
        return result

    @Slot(str, result=str)
    def actionLabelFor(self, actionId):
        return _action_label(actionId)

    @Slot(result=str)
    def dumpDeviceInfo(self):
        """Return JSON describing the connected device for contributor use."""
        import json
        if not self._engine:
            return ""
        info = self._engine.dump_device_info()
        if not info:
            return ""
        return json.dumps(info, indent=2)

    @Slot(str)
    def copyToClipboard(self, text):
        """Copy text to the system clipboard."""
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    @Slot(str)
    def setDeviceLayoutOverride(self, layoutKey):
        normalized = (layoutKey or "").strip()
        device_key = self._connected_device_key
        if not self._mouse_connected or not device_key:
            self.statusMessage.emit("Connect a device first")
            return
        valid_choices = {choice["key"] for choice in get_manual_layout_choices()}
        if normalized not in valid_choices:
            self.statusMessage.emit("Unknown layout option")
            return

        overrides = self._cfg.setdefault("settings", {}).setdefault(
            "device_layout_overrides",
            {},
        )
        if normalized:
            overrides[device_key] = normalized
        else:
            overrides.pop(device_key, None)
        save_config(self._cfg)

        device = getattr(self._engine, "connected_device", None) if self._engine else None
        self._apply_device_layout(device)
        if normalized:
            self.statusMessage.emit("Experimental layout applied")
        else:
            self.statusMessage.emit("Layout reset to auto-detect")

    # ── Engine thread callbacks (cross-thread safe) ────────────

    def _onEngineProfileSwitch(self, profile_name):
        """Called from engine thread — posts to Qt main thread."""
        self._profileSwitchRequest.emit(profile_name)

    def _onEngineDpiRead(self, dpi):
        """Called from engine thread — posts to Qt main thread."""
        self._dpiReadRequest.emit(dpi)

    def _onEngineConnectionChange(self, connected):
        """Called from engine/hook thread — posts to Qt main thread."""
        self._connectionChangeRequest.emit(connected)

    def _onEngineBatteryRead(self, level):
        """Called from engine thread — posts to Qt main thread."""
        self._batteryChangeRequest.emit(level)

    def _onEngineDebugMessage(self, message):
        """Called from engine/hook thread — posts to Qt main thread."""
        self._debugMessageRequest.emit(message)

    def _onEngineGestureEvent(self, event):
        """Called from engine/hook thread — posts to Qt main thread."""
        self._gestureEventRequest.emit(event)

    def _onEngineSmartShiftRead(self, state):
        """Called from engine/hook thread — posts to Qt main thread.

        Uses QMetaObject.invokeMethod instead of a signal because the call may
        originate on the Windows LL hook thread, whose message pump context can
        prevent PySide6 signal queuing from working reliably.
        """
        self._pending_smart_shift_state = state
        QMetaObject.invokeMethod(
            self, "_handleSmartShiftRead", Qt.QueuedConnection
        )

    @Slot()
    def _handleSmartShiftRead(self):
        """Runs on Qt main thread — updates config and notifies QML."""
        state = self._pending_smart_shift_state
        if isinstance(state, dict):
            settings = self._cfg.setdefault("settings", {})
            settings["smart_shift_mode"] = state.get("mode", "ratchet")
            settings["smart_shift_enabled"] = state.get("enabled", False)
            # Only accept the device-reported threshold when SmartShift is
            # enabled (device returns the real value 1-50).  When disabled the
            # device returns 0xFF which the read code maps to a hardcoded 25,
            # overwriting whatever the user chose in the UI.
            if state.get("enabled", False):
                settings["smart_shift_threshold"] = state.get("threshold", 25)
        self.smartShiftChanged.emit()

    def _onEngineStatusMessage(self, message):
        """Called from engine thread — posts to Qt main thread."""
        self._statusMessageRequest.emit(str(message or ""))

    @Slot(str)
    def _handleStatusMessage(self, message):
        """Runs on Qt main thread."""
        if message:
            self.statusMessage.emit(message)

    @Slot(str)
    def _handleProfileSwitch(self, profile_name):
        """Runs on Qt main thread."""
        self._cfg["active_profile"] = profile_name
        self.activeProfileChanged.emit()
        self.mappingsChanged.emit()
        self.profilesChanged.emit()
        self.statusMessage.emit(f"Profile: {profile_name}")

    @Slot(int)
    def _handleDpiRead(self, dpi):
        """Runs on Qt main thread."""
        self._cfg.setdefault("settings", {})["dpi"] = dpi
        self.settingsChanged.emit()
        self.dpiFromDevice.emit(dpi)

    @Slot(bool)
    def _handleConnectionChange(self, connected):
        """Runs on Qt main thread."""
        previous_connected = self._mouse_connected
        previous_hid_features_ready = self._hid_features_ready
        self._mouse_connected = connected
        self._hid_features_ready = bool(
            getattr(self._engine, "hid_features_ready", False)
        ) if self._engine else False
        self._connected_device_refresh_attempts = 0
        device = None
        if connected:
            self._sync_connected_device_info()
            device = self._resolved_connected_device()
        else:
            self._apply_device_layout(None)
        device_source = getattr(device, "source", "") if device is not None else ""
        if (not connected or device_source == "evdev") and self._battery_level != -1:
            self._battery_level = -1
            self.batteryLevelChanged.emit()
        if self._hid_features_ready != previous_hid_features_ready:
            self.hidFeaturesReadyChanged.emit()
        if connected != previous_connected:
            self.mouseConnectedChanged.emit()
            self._append_debug_line(
                f"Mouse {'connected' if connected else 'disconnected'}"
            )

    def _resolved_connected_device(self):
        device = getattr(self._engine, "connected_device", None) if self._engine else None
        if device is not None:
            return device
        if sys.platform != "linux" or not self._engine:
            return None
        hook = getattr(self._engine, "hook", None)
        hook_connected = bool(
            getattr(self._engine, "device_connected", False)
            or getattr(hook, "evdev_ready", False)
            or getattr(hook, "_device_connected", False)
        )
        if not (self._mouse_connected or hook_connected):
            return None
        evdev_device = getattr(hook, "_evdev_device", None) if hook else None
        if not evdev_device:
            return None
        info = getattr(evdev_device, "info", None)
        return build_evdev_connected_device_info(
            product_id=getattr(info, "product", None) if info else None,
            product_name=getattr(evdev_device, "name", None),
            transport="evdev",
            source="evdev",
        )

    def _sync_connected_device_info(self):
        device = self._resolved_connected_device()
        self._apply_device_layout(device)
        if self._should_retry_device_info(device):
            self._schedule_connected_device_info_refresh()

    def _should_retry_device_info(self, device):
        if sys.platform != "linux" or not self._engine:
            return False
        hook = getattr(self._engine, "hook", None)
        hook_connected = bool(
            self._mouse_connected
            or getattr(self._engine, "device_connected", False)
            or getattr(hook, "evdev_ready", False)
            or getattr(hook, "_device_connected", False)
        )
        if not hook_connected:
            return False
        if getattr(self._engine, "connected_device", None) is not None:
            return False
        if getattr(device, "source", "") != "evdev":
            return False
        return self._connected_device_refresh_attempts < 20

    def _schedule_connected_device_info_refresh(self):
        if self._connected_device_refresh_pending:
            return
        self._connected_device_refresh_pending = True
        QTimer.singleShot(250, self._refresh_connected_device_info)

    def _refresh_connected_device_info(self):
        self._connected_device_refresh_pending = False
        if not self._mouse_connected:
            return
        self._connected_device_refresh_attempts += 1
        self._sync_connected_device_info()

    def _apply_device_layout(self, device):
        device_key = getattr(device, "key", "") or ""
        display_name = getattr(device, "display_name", "") or "Logitech mouse"
        source = getattr(device, "source", "") or ""
        dpi_min = getattr(device, "dpi_min", DEFAULT_DPI_MIN) or DEFAULT_DPI_MIN
        dpi_max = getattr(device, "dpi_max", DEFAULT_DPI_MAX) or DEFAULT_DPI_MAX
        info_changed = False
        if display_name != self._device_display_name:
            self._device_display_name = display_name
            info_changed = True
        if device_key != self._connected_device_key:
            self._connected_device_key = device_key
            info_changed = True
        if source != self._connected_device_source:
            self._connected_device_source = source
            info_changed = True
        if dpi_min != self._device_dpi_min:
            self._device_dpi_min = dpi_min
            info_changed = True
        if dpi_max != self._device_dpi_max:
            self._device_dpi_max = dpi_max
            info_changed = True
        if info_changed:
            self.deviceInfoChanged.emit()

        current_dpi = self._cfg.get("settings", {}).get("dpi", DEFAULT_DPI_MIN)
        if device is not None:
            clamped_dpi = clamp_dpi(current_dpi, device)
            if clamped_dpi != current_dpi:
                self._cfg.setdefault("settings", {})["dpi"] = clamped_dpi
                save_config(self._cfg)
                if self._engine:
                    self._engine.set_dpi(clamped_dpi)
                self.settingsChanged.emit()

        overrides = self._cfg.get("settings", {}).get("device_layout_overrides", {})
        valid_override_keys = {choice["key"] for choice in get_manual_layout_choices()}
        override_key = overrides.get(device_key, "") if device_key else ""
        if override_key not in valid_override_keys:
            override_key = ""
        layout_key = override_key or getattr(device, "ui_layout", None) or "generic_mouse"
        layout = get_device_layout(layout_key)
        layout_changed = False
        if override_key != self._device_layout_override_key:
            self._device_layout_override_key = override_key
            layout_changed = True
        if layout != self._device_layout:
            self._device_layout = layout
            layout_changed = True
        if layout_changed:
            self.deviceLayoutChanged.emit()

        # Compute effective supported buttons (override wins over physical).
        if override_key:
            eff = get_buttons_for_layout(override_key)
        else:
            eff = getattr(device, "supported_buttons", None)
        old_eff = self._effective_supported_buttons
        self._effective_supported_buttons = eff

        # Refresh button list -- different devices have different buttons.
        if info_changed or layout_changed:
            self.mappingsChanged.emit()

        # If the effective button set changed, action lists may need updating.
        if eff != old_eff:
            self.deviceLayoutChanged.emit()

    @Slot(int)
    def _handleBatteryChange(self, level):
        """Runs on Qt main thread."""
        self._battery_level = level
        self.batteryLevelChanged.emit()

    @Slot(str)
    def _handleDebugMessage(self, message):
        """Runs on Qt main thread."""
        self._append_debug_line(message)

    @Slot(str)
    def _handleStatusMessage(self, message):
        """Runs on Qt main thread."""
        if message:
            self.statusMessage.emit(message)

    def _append_debug_line(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self._debug_lines.append(f"[{timestamp}] {message}")
        self._debug_lines = self._debug_lines[-200:]
        self.debugLogChanged.emit()

    def _new_attempt(self):
        self._current_attempt = {
            "started_at": time.strftime("%H:%M:%S"),
            "moves": [],
            "detected": None,
            "click_candidate": None,
            "dispatch": None,
            "mapped": None,
            "notes": [],
        }

    def _ensure_record_attempt(self, note=None):
        if not (self._record_mode and self._gesture_active):
            return None
        if self._current_attempt is None:
            self._new_attempt()
            if note:
                self._current_attempt["notes"].append(note)
        return self._current_attempt

    def _finalize_attempt(self):
        attempt = self._current_attempt
        if not attempt:
            return
        parts = [f"[{attempt['started_at']}]"]
        if attempt["detected"]:
            parts.append(f"detected={attempt['detected']}")
        if attempt["click_candidate"] is not None:
            parts.append(f"click_candidate={attempt['click_candidate']}")
        if attempt["dispatch"]:
            parts.append(f"dispatch={attempt['dispatch']}")
        if attempt["mapped"]:
            parts.append(f"mapped={attempt['mapped']}")
        if attempt["moves"]:
            move_preview = ", ".join(attempt["moves"][:8])
            if len(attempt["moves"]) > 8:
                move_preview += f", ... (+{len(attempt['moves']) - 8} more)"
            parts.append(f"moves={move_preview}")
        if attempt["notes"]:
            parts.append("notes=" + "; ".join(attempt["notes"]))
        self._gesture_records.append("\n".join(parts))
        self._gesture_records = self._gesture_records[-80:]
        self.gestureRecordsChanged.emit()
        self._current_attempt = None

    @Slot(object)
    def _handleGestureEvent(self, event):
        """Runs on Qt main thread."""
        if not isinstance(event, dict):
            return
        event_type = event.get("type")

        if event_type == "button_down":
            if self._record_mode and self._current_attempt:
                self._finalize_attempt()
            if self._record_mode:
                self._new_attempt()
            else:
                self._current_attempt = None
            self._gesture_active = True
            self._gesture_move_seen = False
            self._gesture_move_source = ""
            self._gesture_move_dx = 0
            self._gesture_move_dy = 0
            self._gesture_status = "Gesture button held"
            self.gestureStateChanged.emit()
            return

        if event_type == "move":
            source = event.get("source", "")
            dx = int(event.get("dx", 0))
            dy = int(event.get("dy", 0))
            attempt = self._ensure_record_attempt()
            self._gesture_move_seen = True
            self._gesture_move_source = source
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = (
                f"RawXY seen dx={dx} dy={dy}"
                if source == "hid_rawxy"
                else f"Movement seen dx={dx} dy={dy}"
            )
            if attempt is not None:
                attempt["moves"].append(f"{source}({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if event_type == "segment":
            source = event.get("source", "")
            dx = int(float(event.get("dx", 0)))
            dy = int(float(event.get("dy", 0)))
            attempt = self._ensure_record_attempt()
            self._gesture_move_seen = True
            self._gesture_move_source = source
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"Segment {source} accum=({dx},{dy})"
            if attempt is not None:
                attempt["notes"].append(f"segment {source} ({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if event_type == "tracking_started":
            source = event.get("source", "")
            attempt = self._ensure_record_attempt()
            self._gesture_move_source = source
            self._gesture_move_dx = 0
            self._gesture_move_dy = 0
            self._gesture_status = f"Tracking {source}"
            if attempt is not None:
                attempt["notes"].append(f"tracking {source}")
            self.gestureStateChanged.emit()
            return

        if event_type == "cooldown_started":
            source = event.get("source", "")
            for_ms = str(event.get("for_ms", "0"))
            attempt = self._ensure_record_attempt()
            self._gesture_move_source = source
            self._gesture_status = f"Cooldown {for_ms} ms"
            if attempt is not None:
                attempt["notes"].append(f"cooldown {source} {for_ms}ms")
            self.gestureStateChanged.emit()
            return

        if event_type == "cooldown_active":
            source = event.get("source", "")
            dx = int(event.get("dx", 0))
            dy = int(event.get("dy", 0))
            attempt = self._ensure_record_attempt()
            self._gesture_move_source = source
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"Cooldown ignore {source} ({dx},{dy})"
            if attempt is not None:
                attempt["notes"].append(f"cooldown-ignore {source} ({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if event_type == "detected":
            detected = event.get("event_name", "")
            source = event.get("source", "")
            dx = str(event.get("dx", 0))
            dy = str(event.get("dy", 0))
            attempt = self._ensure_record_attempt()
            self._gesture_move_seen = True
            self._gesture_move_source = source
            self._gesture_move_dx = int(float(dx))
            self._gesture_move_dy = int(float(dy))
            self._gesture_status = f"Detected {detected}"
            if attempt is not None:
                attempt["detected"] = f"{detected} via {source} ({dx},{dy})"
            self.gestureStateChanged.emit()
            return

        if event_type == "button_up":
            click_candidate = str(event.get("click_candidate", False)).lower()
            self._gesture_active = False
            self._gesture_status = f"Released click_candidate={click_candidate}"
            if self._current_attempt is not None:
                self._current_attempt["click_candidate"] = click_candidate
            self.gestureStateChanged.emit()
            return

        if event_type == "dispatch":
            event_name = event.get("event_name", "")
            callbacks = str(event.get("callbacks", 0))
            self._gesture_status = f"Dispatch {event_name} callbacks={callbacks}"
            if self._current_attempt is not None:
                self._current_attempt["dispatch"] = f"{event_name} callbacks={callbacks}"
            self.gestureStateChanged.emit()
            return

        if event_type == "mapped":
            action = (
                f"{event.get('event_name', '')} -> {event.get('action_id', '')} "
                f"({event.get('action_label', '')})"
            )
            self._gesture_status = f"Mapped {action}"
            if self._current_attempt is not None:
                self._current_attempt["mapped"] = action
                if self._record_mode:
                    self._finalize_attempt()
            self.gestureStateChanged.emit()
            return

        if event_type == "unmapped":
            message = f"No mapped action for {event.get('event_name', '')}"
            self._gesture_status = message
            if self._current_attempt is not None:
                self._current_attempt["notes"].append(message)
                if self._record_mode:
                    self._finalize_attempt()
            self.gestureStateChanged.emit()
