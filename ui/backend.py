"""
QML Backend Bridge — connects the QML UI to the engine and config.
Exposes properties, signals, and slots for two-way data binding.
"""

import re
import sys
import time

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt

from core.config import (
    BUTTON_NAMES, load_config, save_config, get_active_mappings,
    PROFILE_BUTTON_NAMES, set_mapping, create_profile, delete_profile,
    KNOWN_APPS, get_icon_for_exe,
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
    debugLogChanged = Signal()
    debugEventsEnabledChanged = Signal()
    gestureStateChanged = Signal()
    gestureRecordsChanged = Signal()

    # Internal cross-thread signals
    _profileSwitchRequest = Signal(str)
    _dpiReadRequest = Signal(int)
    _connectionChangeRequest = Signal(bool)
    _batteryChangeRequest = Signal(int)
    _debugMessageRequest = Signal(str)

    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._cfg = load_config()
        self._mouse_connected = False
        self._battery_level = -1
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

        # Wire engine callbacks
        if engine:
            engine.set_profile_change_callback(self._onEngineProfileSwitch)
            engine.set_dpi_read_callback(self._onEngineDpiRead)
            engine.set_connection_change_callback(self._onEngineConnectionChange)
            if hasattr(engine, "set_battery_callback"):
                engine.set_battery_callback(self._onEngineBatteryRead)
            if hasattr(engine, "set_debug_callback"):
                engine.set_debug_callback(self._onEngineDebugMessage)
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

    @Property(bool, notify=debugEventsEnabledChanged)
    def debugEventsEnabled(self):
        return self._debug_events_enabled

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
        for key, name in PROFILE_BUTTON_NAMES.items():
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

    def _onEngineDebugMessage(self, message):
        """Called from engine/hook thread — posts to Qt main thread."""
        self._debugMessageRequest.emit(message)

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
        self._append_debug_line(
            f"Mouse {'connected' if connected else 'disconnected'}"
        )

    @Slot(int)
    def _handleBatteryChange(self, level):
        """Runs on Qt main thread."""
        self._battery_level = level
        self.batteryLevelChanged.emit()

    @Slot(str)
    def _handleDebugMessage(self, message):
        """Runs on Qt main thread."""
        self._append_debug_line(message)
        self._consume_gesture_debug(message)

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

    def _consume_gesture_debug(self, message):
        move_match = re.search(r"Gesture move event type=(\d+) dx=(-?\d+) dy=(-?\d+)", message)
        rawxy_match = re.search(r"HID rawxy move dx=(-?\d+) dy=(-?\d+)", message)
        segment_match = re.search(
            r"Gesture segment source=([a-z_]+) accum_x=([-0-9.]+) accum_y=([-0-9.]+)",
            message,
        )
        tracking_started_match = re.search(
            r"Gesture tracking started source=([a-z_]+)",
            message,
        )
        cooldown_started_match = re.search(
            r"Gesture cooldown started source=([a-z_]+) for_ms=(\d+)",
            message,
        )
        cooldown_active_match = re.search(
            r"Gesture cooldown active source=([a-z_]+) dx=(-?\d+) dy=(-?\d+)",
            message,
        )
        detect_match = re.search(
            r"Gesture detected ([a-z_]+) source=([a-z_]+) delta_x=([-0-9.]+) delta_y=([-0-9.]+)",
            message,
        )
        dispatch_match = re.search(r"Dispatch ([a-z_]+).*callbacks=(\d+)", message)
        mapped_match = re.search(r"Mapped ([a-z_]+) -> ([a-z0-9_]+) \((.+)\)", message)
        click_match = re.search(r"HID gesture button up click_candidate=(true|false)", message)

        if message == "HID gesture button down":
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

        if move_match:
            dx = int(move_match.group(2))
            dy = int(move_match.group(3))
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_seen = True
            self._gesture_move_source = "event_tap"
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"Movement seen dx={dx} dy={dy}"
            if attempt is not None:
                attempt["moves"].append(f"event_tap({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if rawxy_match:
            dx = int(rawxy_match.group(1))
            dy = int(rawxy_match.group(2))
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_seen = True
            self._gesture_move_source = "hid_rawxy"
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"RawXY seen dx={dx} dy={dy}"
            if attempt is not None:
                attempt["moves"].append(f"hid_rawxy({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if segment_match:
            source = segment_match.group(1)
            dx = int(float(segment_match.group(2)))
            dy = int(float(segment_match.group(3)))
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_seen = True
            self._gesture_move_source = source
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"Segment {source} accum=({dx},{dy})"
            if attempt is not None:
                attempt["notes"].append(f"segment {source} ({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if tracking_started_match:
            source = tracking_started_match.group(1)
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_source = source
            self._gesture_move_dx = 0
            self._gesture_move_dy = 0
            self._gesture_status = f"Tracking {source}"
            if attempt is not None:
                attempt["notes"].append(f"tracking {source}")
            self.gestureStateChanged.emit()
            return

        if cooldown_started_match:
            source = cooldown_started_match.group(1)
            for_ms = cooldown_started_match.group(2)
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_source = source
            self._gesture_status = f"Cooldown {for_ms} ms"
            if attempt is not None:
                attempt["notes"].append(f"cooldown {source} {for_ms}ms")
            self.gestureStateChanged.emit()
            return

        if cooldown_active_match:
            source = cooldown_active_match.group(1)
            dx = int(cooldown_active_match.group(2))
            dy = int(cooldown_active_match.group(3))
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_source = source
            self._gesture_move_dx = dx
            self._gesture_move_dy = dy
            self._gesture_status = f"Cooldown ignore {source} ({dx},{dy})"
            if attempt is not None:
                attempt["notes"].append(f"cooldown-ignore {source} ({dx},{dy})")
            self.gestureStateChanged.emit()
            return

        if detect_match:
            detected = detect_match.group(1)
            source = detect_match.group(2)
            dx = detect_match.group(3)
            dy = detect_match.group(4)
            attempt = self._ensure_record_attempt("continuing hold")
            self._gesture_move_seen = True
            self._gesture_move_source = source
            self._gesture_move_dx = int(float(dx))
            self._gesture_move_dy = int(float(dy))
            self._gesture_status = f"Detected {detected}"
            if attempt is not None:
                attempt["detected"] = f"{detected} via {source} ({dx},{dy})"
            self.gestureStateChanged.emit()
            return

        if click_match:
            click_candidate = click_match.group(1)
            self._gesture_active = False
            self._gesture_status = f"Released click_candidate={click_candidate}"
            if self._current_attempt is not None:
                self._current_attempt["click_candidate"] = click_candidate
            self.gestureStateChanged.emit()
            return

        if dispatch_match:
            event_name = dispatch_match.group(1)
            callbacks = dispatch_match.group(2)
            self._gesture_status = f"Dispatch {event_name} callbacks={callbacks}"
            if self._current_attempt is not None:
                self._current_attempt["dispatch"] = f"{event_name} callbacks={callbacks}"
            self.gestureStateChanged.emit()
            return

        if mapped_match:
            action = (
                f"{mapped_match.group(1)} -> {mapped_match.group(2)} "
                f"({mapped_match.group(3)})"
            )
            self._gesture_status = f"Mapped {action}"
            if self._current_attempt is not None:
                self._current_attempt["mapped"] = action
                if self._record_mode:
                    self._finalize_attempt()
            self.gestureStateChanged.emit()
            return

        if message.startswith("No mapped action for "):
            self._gesture_status = message
            if self._current_attempt is not None:
                self._current_attempt["notes"].append(message)
                if self._record_mode:
                    self._finalize_attempt()
            self.gestureStateChanged.emit()
