"""
QML Backend Bridge — connects the QML UI to the engine and config.
Exposes properties, signals, and slots for two-way data binding.
"""

import os
import sys

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt

from core.config import (
    BUTTON_NAMES, load_config, save_config, get_active_mappings,
    set_mapping, create_profile, delete_profile, KNOWN_APPS, get_icon_for_exe,
)
from core.key_simulator import ACTIONS


def _action_label(action_id):
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
    mouseConnectedChanged = Signal()
    batteryLevelChanged = Signal()

    # Internal cross-thread signals
    _profileSwitchRequest = Signal(str)
    _dpiReadRequest = Signal(int)
    _connectionChangeRequest = Signal(bool)
    _batteryChangeRequest = Signal(int)

    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._cfg = load_config()
        self._mouse_connected = False
        self._battery_level = -1

        # Cross-thread signal connections
        self._profileSwitchRequest.connect(
            self._handleProfileSwitch, Qt.QueuedConnection)
        self._dpiReadRequest.connect(
            self._handleDpiRead, Qt.QueuedConnection)
        self._connectionChangeRequest.connect(
            self._handleConnectionChange, Qt.QueuedConnection)
        self._batteryChangeRequest.connect(
            self._handleBatteryChange, Qt.QueuedConnection)

        # Wire engine callbacks
        if engine:
            engine.set_profile_change_callback(self._onEngineProfileSwitch)
            engine.set_dpi_read_callback(self._onEngineDpiRead)
            engine.set_connection_change_callback(self._onEngineConnectionChange)
            if hasattr(engine, "set_battery_callback"):
                engine.set_battery_callback(self._onEngineBatteryRead)
            if hasattr(engine, "set_debug_enabled"):
                engine.set_debug_enabled(self.debugMode)

    # ── Properties ─────────────────────────────────────────────

    @Property(list, notify=mappingsChanged)
    def buttons(self):
        """List of button dicts for the active profile."""
        mappings = get_active_mappings(self._cfg)
        result = []
        for i, (key, name) in enumerate(BUTTON_NAMES.items()):
            aid = mappings.get(key, "none")
            result.append({
                "key": key,
                "name": name,
                "actionId": aid,
                "actionLabel": _action_label(aid),
                "index": i + 1,
            })
        return result

    @Property(list, constant=True)
    def actionCategories(self):
        """Actions grouped by category — for the action picker chips."""
        from collections import OrderedDict
        cats = OrderedDict()
        for aid in sorted(
            ACTIONS,
            key=lambda a: (
                "0" if ACTIONS[a]["category"] == "Other" else "1" + ACTIONS[a]["category"],
                ACTIONS[a]["label"],
            ),
        ):
            data = ACTIONS[aid]
            cat = data["category"]
            cats.setdefault(cat, []).append({"id": aid, "label": data["label"]})
        return [{"category": c, "actions": a} for c, a in cats.items()]

    @Property(list, constant=True)
    def allActions(self):
        """Flat sorted action list (Do Nothing first) — for ComboBoxes."""
        result = []
        none_data = ACTIONS.get("none")
        if none_data:
            result.append({"id": "none", "label": none_data["label"],
                           "category": "Other"})
        for aid in sorted(
            ACTIONS,
            key=lambda a: (ACTIONS[a]["category"], ACTIONS[a]["label"]),
        ):
            if aid == "none":
                continue
            data = ACTIONS[aid]
            result.append({"id": aid, "label": data["label"],
                           "category": data["category"]})
        return result

    @Property(int, notify=settingsChanged)
    def dpi(self):
        return self._cfg.get("settings", {}).get("dpi", 1000)

    @Property(bool, notify=settingsChanged)
    def invertVScroll(self):
        return self._cfg.get("settings", {}).get("invert_vscroll", False)

    @Property(bool, notify=settingsChanged)
    def invertHScroll(self):
        return self._cfg.get("settings", {}).get("invert_hscroll", False)

    @Property(int, notify=settingsChanged)
    def gestureThreshold(self):
        return int(self._cfg.get("settings", {}).get("gesture_threshold", 50))

    @Property(bool, notify=settingsChanged)
    def debugMode(self):
        return bool(self._cfg.get("settings", {}).get("debug_mode", False))

    @Property(bool, constant=True)
    def supportsGestureDirections(self):
        return sys.platform in ("darwin", "win32")

    @Property(str, notify=activeProfileChanged)
    def activeProfile(self):
        return self._cfg.get("active_profile", "default")

    @Property(bool, notify=mouseConnectedChanged)
    def mouseConnected(self):
        return self._mouse_connected

    @Property(int, notify=batteryLevelChanged)
    def batteryLevel(self):
        return self._battery_level

    @Property(list, notify=profilesChanged)
    def profiles(self):
        result = []
        active = self._cfg.get("active_profile", "default")
        for pname, pdata in self._cfg.get("profiles", {}).items():
            # Collect icons for all apps in this profile
            apps = pdata.get("apps", [])
            app_icons = [get_icon_for_exe(ex) for ex in apps]
            result.append({
                "name": pname,
                "label": pdata.get("label", pname),
                "apps": apps,
                "appIcons": app_icons,
                "isActive": pname == active,
            })
        return result

    @Property(list, constant=True)
    def knownApps(self):
        return [{"exe": ex, "label": info["label"], "icon": get_icon_for_exe(ex)}
                for ex, info in KNOWN_APPS.items()]

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

    @Slot(int)
    def setDpi(self, value):
        self._cfg.setdefault("settings", {})["dpi"] = value
        save_config(self._cfg)
        if self._engine:
            self._engine.set_dpi(value)
        self.settingsChanged.emit()

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

    @Slot(bool)
    def setDebugMode(self, value):
        enabled = bool(value)
        self._cfg.setdefault("settings", {})["debug_mode"] = enabled
        save_config(self._cfg)
        if self._engine and hasattr(self._engine, "set_debug_enabled"):
            self._engine.set_debug_enabled(enabled)
        self.settingsChanged.emit()

    @Slot(str)
    def addProfile(self, appLabel):
        """Create a new per-app profile from the known-apps label."""
        exe = None
        for ex, info in KNOWN_APPS.items():
            if info["label"] == appLabel:
                exe = ex
                break
        if not exe:
            return
        for pdata in self._cfg.get("profiles", {}).values():
            if exe.lower() in [a.lower() for a in pdata.get("apps", [])]:
                self.statusMessage.emit("Profile already exists")
                return
        safe_name = exe.replace(".exe", "").lower()
        self._cfg = create_profile(
            self._cfg, safe_name, label=appLabel, apps=[exe])
        if self._engine:
            self._engine.cfg = self._cfg
        self.profilesChanged.emit()
        self.statusMessage.emit("Profile created")

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
        """Return button mappings for a specific profile."""
        profiles = self._cfg.get("profiles", {})
        pdata = profiles.get(profileName, {})
        mappings = pdata.get("mappings", {})
        result = []
        for key, name in BUTTON_NAMES.items():
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
        self._mouse_connected = connected
        if not connected and self._battery_level != -1:
            self._battery_level = -1
            self.batteryLevelChanged.emit()
        self.mouseConnectedChanged.emit()

    @Slot(int)
    def _handleBatteryChange(self, level):
        """Runs on Qt main thread."""
        self._battery_level = level
        self.batteryLevelChanged.emit()
