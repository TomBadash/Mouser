"""
QML Backend Bridge — connects the QML UI to the engine and config.
Exposes properties, signals, and slots for two-way data binding.
"""

import os
import json
import re
import shutil
import sys
import threading
import time
import urllib.error
import webbrowser
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QMetaObject, QObject, Property, QTimer, Signal, Slot, Qt, QUrl

from core.accessibility import is_process_trusted
from core.config import (
    BUTTON_NAMES, load_config, save_config, get_active_mappings,
    PROFILE_BUTTON_NAMES, set_mapping, create_profile, delete_profile,
    get_icon_for_exe, HAPTIC_ELIGIBLE_ACTIONS, set_action_haptic,
    set_button_haptic,
)
from core import app_catalog
from core.device_layouts import get_device_layout, get_manual_layout_choices
from core.key_registry import (
    ShortcutParseError,
    canonical_shortcut_text,
    is_reserved_risky_shortcut,
    pretty_key_name,
)
from core.logi_devices import (
    DEFAULT_DPI_MAX,
    DEFAULT_DPI_MIN,
    build_evdev_connected_device_info,
    clamp_dpi,
    get_buttons_for_layout,
)
from core.key_simulator import (
    ACTIONS,
    custom_action_label,
    normalize_captured_shortcut_parts,
    valid_custom_key_names,
)
from core.startup import (
    apply_login_startup,
    supports_login_startup,
    sync_from_config as sync_login_startup_from_config,
)
from core.updater import (
    DEFAULT_AUTO_CHECK_INTERVAL_SECONDS,
    DEFAULT_RELEASE_REPO,
    UpdateCheckState,
    check_latest_release,
    is_newer,
)
from core.update_installer import (
    ArchiveRequirements,
    UpdateInstallError,
    WindowsUpdatePlan,
    cleanup_stale_update_state,
    extract_validated_zip,
    fetch_update_manifest_for_release,
    launch_windows_update_helper,
    locate_runtime,
    plan_install_for_platform,
    prepare_downloaded_asset,
    read_update_result,
    same_volume_windows_stage_dir,
    write_windows_update_plan,
)
from core.version import APP_VERSION
from ui.screenshot_common import screenshot_file_path, screenshot_file_paths, screenshots_dir


def _action_label(action_id):
    if action_id.startswith("custom:"):
        return custom_action_label(action_id)
    return ACTIONS.get(action_id, {}).get("label", "Do Nothing")


def _qt_shortcut_modifier_name(name):
    """Return the raw Qt semantic name for a modifier."""
    return (name or "").strip().lower()


def _qt_enum_int(value):
    """Coerce Qt enum and flag values from QML into plain integers."""
    if hasattr(value, "value"):
        return int(value.value)
    return int(value)


def _qt_shortcut_key_name(key, text=""):
    """Translate a Qt key value into a raw Qt semantic shortcut name."""
    key = _qt_enum_int(key)
    text = text or ""

    if key == _qt_enum_int(Qt.Key_Shift):
        return "shift"
    if key == _qt_enum_int(Qt.Key_Control):
        return "ctrl"
    if key == _qt_enum_int(Qt.Key_Alt):
        return "alt"
    if key == _qt_enum_int(Qt.Key_Meta):
        return "super"
    if key == _qt_enum_int(Qt.Key_Escape):
        return "esc"
    if key == _qt_enum_int(Qt.Key_Tab):
        return "tab"
    if key == _qt_enum_int(Qt.Key_Space):
        return "space"
    if key in (_qt_enum_int(Qt.Key_Return), _qt_enum_int(Qt.Key_Enter)):
        return "enter"
    if key == _qt_enum_int(Qt.Key_Backspace):
        return "backspace"
    if key == _qt_enum_int(Qt.Key_Delete):
        return "delete"
    if key == _qt_enum_int(Qt.Key_Left):
        return "left"
    if key == _qt_enum_int(Qt.Key_Right):
        return "right"
    if key == _qt_enum_int(Qt.Key_Up):
        return "up"
    if key == _qt_enum_int(Qt.Key_Down):
        return "down"
    if key == _qt_enum_int(Qt.Key_Home):
        return "home"
    if key == _qt_enum_int(Qt.Key_End):
        return "end"
    if key == _qt_enum_int(Qt.Key_PageUp):
        return "pageup"
    if key == _qt_enum_int(Qt.Key_PageDown):
        return "pagedown"
    if key == _qt_enum_int(Qt.Key_Insert):
        return "insert"

    for n in range(1, 25):
        qt_key = getattr(Qt, f"Key_F{n}", None)
        if qt_key is not None and key == _qt_enum_int(qt_key):
            return f"f{n}"

    if _qt_enum_int(Qt.Key_A) <= key <= _qt_enum_int(Qt.Key_Z):
        return chr(ord("a") + (key - _qt_enum_int(Qt.Key_A)))
    if _qt_enum_int(Qt.Key_0) <= key <= _qt_enum_int(Qt.Key_9):
        return chr(ord("0") + (key - _qt_enum_int(Qt.Key_0)))

    if len(text) == 1:
        lowered = text.lower()
        try:
            canonical_shortcut_text(lowered, allow_modifier_only=False)
        except ShortcutParseError:
            pass
        else:
            return lowered
    return ""


def _qt_shortcut_combo(key, modifiers, text=""):
    """Build the stored custom-shortcut string from Qt event parts."""
    modifiers = _qt_enum_int(modifiers)
    parts = []
    if modifiers & _qt_enum_int(Qt.ControlModifier):
        parts.append(_qt_shortcut_modifier_name("ctrl"))
    if modifiers & _qt_enum_int(Qt.ShiftModifier):
        parts.append("shift")
    if modifiers & _qt_enum_int(Qt.AltModifier):
        parts.append("alt")
    if modifiers & _qt_enum_int(Qt.MetaModifier):
        parts.append(_qt_shortcut_modifier_name("super"))

    key_name = _qt_shortcut_key_name(key, text)
    return normalize_captured_shortcut_parts(parts, key_name)


def _open_url(url: str) -> bool:
    """Open a URL without importing QtGui during backend module import."""
    if not url:
        return False
    qurl = QUrl(url)
    try:
        from PySide6.QtGui import QDesktopServices

        if QDesktopServices.openUrl(qurl):
            return True
    except Exception:
        pass
    return bool(webbrowser.open(qurl.toString()))


def _update_install_enabled() -> bool:
    value = os.environ.get("MOUSER_ENABLE_UPDATE_INSTALL", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_directory_path(path: str) -> str:
    expanded = os.path.expanduser((path or "").strip())
    if not expanded:
        return ""
    if sys.platform == "linux":
        return os.path.realpath(expanded)
    return os.path.normpath(expanded)


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
    batteryChargingChanged = Signal()
    debugLogChanged = Signal()
    debugEventsEnabledChanged = Signal()
    gestureStateChanged = Signal()
    gestureRecordsChanged = Signal()
    deviceInfoChanged = Signal()
    deviceLayoutChanged = Signal()
    hapticChanged = Signal()
    forceSensingChanged = Signal()
    knownAppsChanged = Signal()
    updateAvailable = Signal(str, str)
    updateInstallChanged = Signal()

    # Internal cross-thread signals
    _profileSwitchRequest = Signal(str)
    _dpiReadRequest = Signal(int)
    _connectionChangeRequest = Signal(bool)
    _batteryChangeRequest = Signal(int, bool)
    _debugMessageRequest = Signal(str)
    _gestureEventRequest = Signal(object)
    _smartShiftReadRequest = Signal()
    _statusMessageRequest = Signal(str)
    _updateAvailableRequest = Signal(str, str, bool, object)
    _updateCheckFinishedRequest = Signal(bool, bool, object)
    _updateInstallStateRequest = Signal(str, str, bool)
    _updateInstallProgressRequest = Signal(int)
    _showRingRequest = Signal(list, bool)
    _hideRingRequest = Signal()

    def __init__(self, engine=None, parent=None, root_dir=None):
        super().__init__(parent)
        self._engine = engine
        self._root_dir = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._cfg = load_config()
        self._mouse_connected = False
        self._device_display_name = "Logitech mouse"
        self._connected_device_key = ""
        self._device_layout_override_key = ""
        self._device_layout = get_device_layout("generic_mouse")
        self._device_dpi_min = DEFAULT_DPI_MIN
        self._device_dpi_max = DEFAULT_DPI_MAX
        self._connected_device_source = ""
        self._connected_device_transport = ""
        self._battery_level = -1
        self._battery_charging = False
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
        self._latest_update_url = ""
        self._latest_update_version = ""
        self._update_check_in_progress = False
        self._update_install_status = "idle"
        self._update_install_message = ""
        self._update_install_can_install = False
        self._update_install_progress = 0
        self._update_cancel = threading.Event()
        self._pending_update_plan = None
        self._pending_update_plan_path = None
        self._pending_update_helper_dir = None
        self._update_state = UpdateCheckState.from_dict(
            self._cfg.get("settings", {}).get("update_check_state", {})
        )
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(DEFAULT_AUTO_CHECK_INTERVAL_SECONDS * 1000)
        self._update_timer.timeout.connect(lambda: self._startUpdateCheck(manual=False))

        # Lazily-computed list snapshots for QML bindings. Every read of a
        # ``@Property(list, ...)`` returns the cached value until the
        # property's notify signal (or a structurally-dependent signal)
        # fires and clears it. Without these caches QML repaints rebuild
        # the lists on every binding evaluation -- profiles re-runs
        # ``app_catalog`` lookups, knownApps walks the catalog, etc.
        self._buttons_cache: list | None = None
        self._profiles_cache: list | None = None
        self._known_apps_cache: list | None = None
        self._action_categories_cache: list | None = None
        self._all_actions_cache: list | None = None

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
        self._updateAvailableRequest.connect(
            self._handleUpdateAvailable, Qt.QueuedConnection)
        self._updateCheckFinishedRequest.connect(
            self._handleUpdateCheckFinished, Qt.QueuedConnection)
        self._updateInstallStateRequest.connect(
            self._handleUpdateInstallState, Qt.QueuedConnection)
        self._updateInstallProgressRequest.connect(
            self._handleUpdateInstallProgress, Qt.QueuedConnection)
        self._showRingRequest.connect(
            self._handleShowRing, Qt.QueuedConnection)
        self._hideRingRequest.connect(
            self._handleHideRing, Qt.QueuedConnection)

        self._ring_overlay = None  # created lazily on first show
        self._ring_visible = False  # thread-safe flag (avoids Qt isVisible() off main thread)
        self._ring_edit_profile = ""  # profile targeted by the ring editor (per-app mode)

        # List-property cache invalidation. Each notify signal maps to the
        # subset of caches that depends on it; reads after the next emit
        # rebuild lazily.
        self.mappingsChanged.connect(self._invalidate_buttons_cache)
        self.profilesChanged.connect(self._invalidate_profiles_cache)
        self.activeProfileChanged.connect(self._invalidate_profiles_cache)
        self.knownAppsChanged.connect(self._invalidate_known_apps_cache)
        self.deviceLayoutChanged.connect(self._invalidate_device_dependent_caches)

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
            if hasattr(engine, "set_ring_show_callback"):
                engine.set_ring_show_callback(self._onEngineShowRing)
                engine.set_ring_hide_callback(self._onEngineHideRing)
                engine.set_ring_sector_callback(self._getRingCurrentSector)
            if hasattr(engine, "set_ring_move_callback"):
                engine.set_ring_move_callback(self._onEngineRingMove)
            self._mouse_connected = bool(getattr(engine, "device_connected", False))
            self._hid_features_ready = bool(
                getattr(engine, "hid_features_ready", False)
            )
        if supports_login_startup():
            try:
                sync_login_startup_from_config(self.startAtLogin)
            except Exception as exc:
                print(f"[startup] Failed to sync desktop integration: {exc}", file=sys.stderr)
                if self.startAtLogin:
                    self._cfg.setdefault("settings", {})["start_at_login"] = False
                    try:
                        save_config(self._cfg)
                    except Exception as save_exc:
                        print(
                            "[startup] Failed to save start-at-login recovery state: "
                            f"{save_exc}",
                            file=sys.stderr,
                        )
                    self.settingsChanged.emit()
                    self.statusMessage.emit(
                        "Start at login could not be enabled. Please try again."
                    )
        else:
            self._cfg.setdefault("settings", {})["start_at_login"] = False
        self._sync_connected_device_info()
        self._configureUpdateChecks()
        self._consumeUpdateResultMarker()
        self._cleanupStaleUpdatePreparation()

    # ── Properties ─────────────────────────────────────────────

    @Property(list, notify=mappingsChanged)
    def buttons(self):
        """List of button dicts for the active profile, filtered by device.

        Cached -- invalidated by ``mappingsChanged`` (active-profile
        mappings) and ``deviceLayoutChanged`` (effective supported-button
        set). The QML mappings list binds to ``backend.buttons`` and
        re-evaluates on every paint of the row delegate, so without the
        cache this rebuilt a list of ~10 dicts and a per-button
        ``_action_label`` lookup on every frame the user scrolled.
        """
        if self._buttons_cache is None:
            self._buttons_cache = self._compute_buttons()
        return self._buttons_cache

    def _compute_buttons(self):
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

    def _invalidate_buttons_cache(self) -> None:
        self._buttons_cache = None

    def _invalidate_profiles_cache(self) -> None:
        self._profiles_cache = None

    def _invalidate_known_apps_cache(self) -> None:
        self._known_apps_cache = None

    def _invalidate_device_dependent_caches(self) -> None:
        # ``buttons`` depends on ``_effective_supported_buttons`` and
        # ``actionCategories`` / ``allActions`` depend on the hidden-action
        # filter that is itself derived from the layout. A device swap
        # invalidates all three at once.
        self._buttons_cache = None
        self._action_categories_cache = None
        self._all_actions_cache = None

    def _hidden_actions(self):
        """Return set of action IDs to hide based on effective device buttons."""
        btns = self._effective_supported_buttons
        hidden = set()
        if btns and "mode_shift" not in btns:
            hidden.add("toggle_smart_shift")
            hidden.add("switch_scroll_mode")
        if sys.platform == "darwin":
            hidden.update(("win_d", "task_view"))
        return hidden

    @Property(list, notify=deviceLayoutChanged)
    def actionCategories(self):
        """Actions grouped by category, filtered by device capabilities.

        Cached -- invalidated by ``deviceLayoutChanged``. The grouped
        structure is rebuilt across the whole ``ACTIONS`` registry on
        every read; the QML action picker binds to this property and
        rebuilt it on every focus/visibility change before the cache.
        """
        if self._action_categories_cache is None:
            self._action_categories_cache = self._compute_action_categories()
        return self._action_categories_cache

    def _compute_action_categories(self):
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
        """Flat sorted action list (Do Nothing first), filtered by device.

        Cached -- invalidated by ``deviceLayoutChanged``.
        """
        if self._all_actions_cache is None:
            self._all_actions_cache = self._compute_all_actions()
        return self._all_actions_cache

    def _compute_all_actions(self):
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

    @Property(bool, notify=deviceLayoutChanged)
    def deviceHasActionsRing(self):
        """Whether the effective device has an Actions Ring button."""
        btns = self._effective_supported_buttons
        return btns is not None and "actions_ring" in btns

    @Property(bool, notify=mappingsChanged)
    def actionsRingActive(self):
        """Whether the current profile has the ring action assigned to any button."""
        mappings = get_active_mappings(self._cfg)
        return any(
            v == "activate_actions_ring"
            for v in mappings.values() if isinstance(v, str)
        )

    @Property(int, notify=settingsChanged)
    def actionsRingHoldMs(self):
        return int(self._cfg.get("settings", {}).get("actions_ring_hold_ms", 250))

    @Slot(int)
    def setActionsRingHoldMs(self, ms):
        ms = max(100, min(500, ms))
        self._cfg.setdefault("settings", {})["actions_ring_hold_ms"] = ms
        save_config(self._cfg)
        self.settingsChanged.emit()
        if self._engine:
            self._engine.reload_mappings()

    @Property(bool, notify=mappingsChanged)
    def actionsRingUseGlobal(self):
        """True when one shared ring is used for every app (default)."""
        return bool(self._cfg.get("settings", {}).get(
            "actions_ring_use_global", True))

    @Slot(bool)
    def setActionsRingUseGlobal(self, use_global):
        self._cfg.setdefault("settings", {})["actions_ring_use_global"] = bool(use_global)
        save_config(self._cfg)
        self.mappingsChanged.emit()
        if self._engine:
            self._engine.reload_mappings()

    @Property(str, notify=mappingsChanged)
    def ringEditProfile(self):
        """Profile the ring editor targets in per-app mode (defaults to active)."""
        return self._ring_edit_profile or self._cfg.get("active_profile", "default")

    @Slot(str)
    def setRingEditProfile(self, name):
        self._ring_edit_profile = name or ""
        self.mappingsChanged.emit()

    def _ring_slots_target_mappings(self):
        """Mappings dict the ring editor reads/writes in per-app mode (the
        selected profile, falling back to Default), created if absent."""
        name = self._ring_edit_profile or self._cfg.get("active_profile", "default")
        prof = self._cfg.get("profiles", {}).get(name)
        if prof is None:
            prof = self._cfg.get("profiles", {}).setdefault("default", {})
        return prof.setdefault("mappings", {})

    @Property(list, notify=mappingsChanged)
    def actionsRingSlots(self):
        if self.actionsRingUseGlobal:
            return list(self._cfg.get("settings", {}).get("actions_ring_slots", []))
        return list(self._ring_slots_target_mappings().get("actions_ring_slots", []))

    @Slot(list)
    def setActionsRingSlots(self, slots):
        if self.actionsRingUseGlobal:
            self._cfg.setdefault("settings", {})["actions_ring_slots"] = list(slots)
        else:
            self._ring_slots_target_mappings()["actions_ring_slots"] = list(slots)
        save_config(self._cfg)
        self.mappingsChanged.emit()
        if self._engine:
            self._engine.reload_mappings()

    @Property(bool, notify=hidFeaturesReadyChanged)
    def hapticSupported(self):
        return self._engine.haptic_supported if self._engine else False

    @Property(int, notify=hapticChanged)
    def hapticLevel(self):
        return int(self._cfg.get("settings", {}).get("haptic_level", 2))

    @Property(bool, notify=hapticChanged)
    def hapticEnabled(self):
        return bool(self._cfg.get("settings", {}).get("haptic_enabled", True))

    @Property(list, notify=hapticChanged)
    def hapticEnabledActions(self):
        """Actions in the user's haptic allowlist, in stored order."""
        enabled = self._cfg.get("settings", {}).get("action_haptic", [])
        result = []
        for aid in enabled:
            data = ACTIONS.get(aid)
            if data:
                result.append({"id": aid, "label": data["label"]})
        return result

    @Property(list, notify=hapticChanged)
    def hapticAvailableActions(self):
        """Eligible haptic actions the user has NOT yet enabled."""
        enabled = set(self._cfg.get("settings", {}).get("action_haptic", []))
        result = []
        for aid in HAPTIC_ELIGIBLE_ACTIONS:
            if aid in enabled:
                continue
            data = ACTIONS.get(aid)
            if data:
                result.append({"id": aid, "label": data["label"]})
        return result

    _HAPTIC_BUTTON_EXCLUDE = {"hscroll_left", "hscroll_right"}

    @Property(list, notify=hapticChanged)
    def hapticEnabledButtons(self):
        """Buttons in the per-button haptic allowlist, in stored order."""
        enabled = self._cfg.get("settings", {}).get("button_haptic", [])
        result = []
        for key in enabled:
            if key in self._HAPTIC_BUTTON_EXCLUDE:
                continue
            label = BUTTON_NAMES.get(key)
            if label:
                result.append({"key": key, "label": label})
        return result

    @Property(list, notify=hapticChanged)
    def hapticAvailableButtons(self):
        """Device buttons the user has NOT yet added to the haptic allowlist."""
        enabled = set(self._cfg.get("settings", {}).get("button_haptic", []))
        supported = self._effective_supported_buttons or set(BUTTON_NAMES.keys())
        result = []
        for key, label in BUTTON_NAMES.items():
            if key in enabled or key not in supported or key in self._HAPTIC_BUTTON_EXCLUDE:
                continue
            result.append({"key": key, "label": label})
        return result

    @Property(bool, notify=hapticChanged)
    def hapticDedup(self):
        return bool(self._cfg.get("settings", {}).get("haptic_dedup", True))

    @Property(bool, notify=hapticChanged)
    def actionsRingHoverHaptic(self):
        return bool(self._cfg.get("settings", {}).get(
            "actions_ring_hover_haptic", True))

    @Property(bool, notify=hidFeaturesReadyChanged)
    def forceSensingSupported(self):
        return self._engine.force_sensing_supported if self._engine else False

    @Property(int, notify=hidFeaturesReadyChanged)
    def forceSensingMin(self):
        if self._engine:
            rng = self._engine.force_sensing_range
            if rng:
                return rng[0]
        return 0

    @Property(int, notify=hidFeaturesReadyChanged)
    def forceSensingMax(self):
        if self._engine:
            rng = self._engine.force_sensing_range
            if rng:
                return rng[1]
        return 100

    @Property(int, notify=hidFeaturesReadyChanged)
    def forceSensingDefault(self):
        if self._engine:
            rng = self._engine.force_sensing_range
            if rng:
                return rng[2]
        return 50

    @Property(int, notify=forceSensingChanged)
    def forceSensitivity(self):
        saved = self._cfg.get("settings", {}).get("force_sensitivity")
        if saved is not None:
            return int(saved)
        if self._engine:
            rng = self._engine.force_sensing_range
            if rng and len(rng) >= 4:
                return rng[3]
        return 50

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

    @Property(bool, notify=settingsChanged)
    def ignoreTrackpad(self):
        return self._cfg.get("settings", {}).get("ignore_trackpad", True)

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

    @Property(bool, notify=settingsChanged)
    def checkForUpdates(self):
        return bool(self._cfg.get("settings", {}).get("check_for_updates", True))

    @Property(str, notify=settingsChanged)
    def screenshotDirectory(self):
        return self._configured_screenshot_directory()

    @Property(str, notify=settingsChanged)
    def screenshotDirectoryLabel(self):
        return self._configured_screenshot_directory()

    @Property(bool, notify=settingsChanged)
    def hasCustomScreenshotDirectory(self):
        return self.has_custom_screenshot_directory()

    @Property(bool, constant=True)
    def isWindows(self):
        return sys.platform.startswith("win")

    @Property(bool, constant=True)
    def isLinux(self):
        return sys.platform.startswith("linux")

    @Property(str, notify=updateInstallChanged)
    def latestUpdateVersion(self):
        return self._latest_update_version

    @Property(str, notify=updateInstallChanged)
    def updateInstallStatus(self):
        return self._update_install_status

    @Property(str, notify=updateInstallChanged)
    def updateInstallMessage(self):
        return self._update_install_message

    @Property(int, notify=updateInstallChanged)
    def updateInstallProgress(self):
        return int(self._update_install_progress)

    @Property(bool, notify=updateInstallChanged)
    def updateInstallCanInstall(self):
        return self._update_install_can_install

    @Property(bool, constant=True)
    def updateInstallEnabled(self):
        return _update_install_enabled()

    @Property(bool, notify=updateInstallChanged)
    def updateInstallInProgress(self):
        return self._update_install_status in {
            "checking",
            "downloading",
            "verifying",
            "installing",
        }

    @Property(bool, notify=debugEventsEnabledChanged)
    def debugEventsEnabled(self):
        return self._debug_events_enabled

    @Property(bool, constant=True)
    def supportsGestureDirections(self):
        return sys.platform in ("darwin", "win32", "linux")

    @Property(bool, constant=True)
    def isMacOS(self):
        return sys.platform == "darwin"

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

    @Property(str, notify=deviceInfoChanged)
    def connectionType(self):
        return self._connected_device_transport

    @Property(int, notify=deviceInfoChanged)
    def deviceDpiMin(self):
        return self._device_dpi_min

    @Property(int, notify=deviceInfoChanged)
    def deviceDpiMax(self):
        return self._device_dpi_max

    @Property(str, notify=deviceLayoutChanged)
    def deviceImageAsset(self):
        return self._device_layout.get("image_asset", "mouse.png")

    @Property(str, notify=deviceLayoutChanged)
    def deviceImageSource(self):
        asset = self._device_layout.get("image_asset", "mouse.png")
        path = os.path.join(self._root_dir, "images", asset)
        return QUrl.fromLocalFile(os.path.abspath(path)).toString()

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

    @Property(bool, notify=batteryChargingChanged)
    def batteryCharging(self):
        return self._battery_charging

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
        """Profile snapshots for the QML profile selector.

        Cached -- invalidated by ``profilesChanged`` (catalog churn) and
        ``activeProfileChanged`` (the ``isActive`` flag per row). The
        compute path walks every profile's apps and resolves each through
        ``get_icon_for_exe`` and ``app_catalog.get_app_label`` -- both
        non-trivial in a profile with several apps, so rebuilding on
        every QML read was the worst per-paint allocator in this file.
        """
        if self._profiles_cache is None:
            self._profiles_cache = self._compute_profiles()
        return self._profiles_cache

    def _compute_profiles(self):
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
        """Catalog snapshot for the QML known-apps picker.

        Cached -- invalidated by ``knownAppsChanged``. The catalog itself
        is essentially static for a session, so this is the highest-hit
        memoization target of the five.
        """
        if self._known_apps_cache is None:
            self._known_apps_cache = self._compute_known_apps()
        return self._known_apps_cache

    def _compute_known_apps(self):
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

    def _configured_screenshot_directory(self) -> str:
        settings = self._cfg.setdefault("settings", {})
        return _normalize_directory_path(settings.get("screenshot_directory", ""))

    def has_custom_screenshot_directory(self) -> bool:
        return bool(self._configured_screenshot_directory())

    def next_screenshot_file_path(self) -> Path:
        custom_directory = self._configured_screenshot_directory()
        if custom_directory:
            return screenshot_file_path(directory=Path(custom_directory))
        return screenshot_file_path()

    def next_screenshot_file_paths(self, count: int) -> list[Path]:
        custom_directory = self._configured_screenshot_directory()
        if custom_directory:
            return screenshot_file_paths(count, directory=Path(custom_directory))
        return screenshot_file_paths(count)

    def _configureUpdateChecks(self):
        if self.checkForUpdates:
            if not self._update_timer.isActive():
                self._update_timer.start()
            QTimer.singleShot(3000, lambda: self._startUpdateCheck(manual=False))
        else:
            self._update_timer.stop()

    def _startUpdateCheck(self, manual=False):
        if not manual and not self.checkForUpdates:
            return
        if self._update_check_in_progress:
            if manual:
                self.statusMessage.emit("Update check already running")
            return
        self._update_check_in_progress = True
        if manual:
            self.statusMessage.emit("Checking for updates...")

        thread = threading.Thread(
            target=self._runUpdateCheck,
            args=(bool(manual), self._update_state),
            name="MouserUpdateCheck",
            daemon=True,
        )
        thread.start()

    def _runUpdateCheck(self, manual=False, state=None):
        result = check_latest_release(
            DEFAULT_RELEASE_REPO,
            timeout=5.0,
            state=state,
            manual=bool(manual),
        )
        release = result.release
        state_data = result.state.to_dict()
        if release and is_newer(APP_VERSION, release.tag_name):
            version = (
                release.tag_name[1:]
                if release.tag_name.startswith("v")
                else release.tag_name
            )
            self._updateAvailableRequest.emit(
                version, release.html_url, bool(manual), state_data
            )
            return
        self._updateCheckFinishedRequest.emit(
            bool(manual),
            bool(result.reachable or result.not_modified or result.throttled),
            state_data,
        )

    def _persistUpdateCheckState(self, state_data):
        self._update_state = UpdateCheckState.from_dict(state_data)
        self._cfg.setdefault("settings", {})["update_check_state"] = (
            self._update_state.to_dict()
        )
        save_config(self._cfg)

    @Slot(str, str, bool, object)
    def _handleUpdateAvailable(self, version, url, manual, state_data):
        self._update_check_in_progress = False
        self._persistUpdateCheckState(state_data)
        self._latest_update_version = str(version or "")
        self._latest_update_url = str(url or "")
        self._update_install_status = "available"
        self._update_install_message = ""
        self._update_install_can_install = False
        self._pending_update_plan = None
        self._pending_update_plan_path = None
        self.updateInstallChanged.emit()
        self.updateAvailable.emit(self._latest_update_version, self._latest_update_url)
        self.statusMessage.emit(f"Mouser {self._latest_update_version} is available")

    @Slot(bool, bool, object)
    def _handleUpdateCheckFinished(self, manual, reachable, state_data):
        self._update_check_in_progress = False
        self._persistUpdateCheckState(state_data)
        if manual:
            if reachable:
                self.statusMessage.emit("Mouser is up to date")
            else:
                self.statusMessage.emit("Could not check for updates")

    def _setUpdateInstallState(self, status, message="", can_install=False):
        self._update_install_status = str(status or "idle")
        self._update_install_message = str(message or "")
        self._update_install_can_install = bool(can_install)
        if status not in {"downloading", "verifying", "ready_to_install"}:
            self._update_install_progress = 0
        self.updateInstallChanged.emit()

    @Slot(str, str, bool)
    def _handleUpdateInstallState(self, status, message, can_install):
        self._setUpdateInstallState(status, message, can_install)

    @Slot(int)
    def _handleUpdateInstallProgress(self, value):
        self._update_install_progress = max(0, min(100, int(value)))
        self.updateInstallChanged.emit()

    def _trustedBuildNumber(self):
        try:
            return int(self._update_state.highest_trusted_build or 0)
        except (TypeError, ValueError):
            return 0

    def _updateErrorCode(self, exc):
        if isinstance(exc, UpdateInstallError):
            return exc.code
        if isinstance(exc, urllib.error.HTTPError):
            return "metadata_missing" if exc.code == 404 else "network_error"
        if isinstance(exc, (urllib.error.URLError, TimeoutError)):
            return "network_error"
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
            return "metadata_invalid"
        if isinstance(exc, PermissionError):
            return "permission_denied"
        if isinstance(exc, OSError):
            return "file_error"
        return "error"

    def _updateProgressCallback(self, expected_size):
        def _progress(downloaded):
            if expected_size:
                self._updateInstallProgressRequest.emit(
                    int(min(100, max(0, downloaded * 100 / expected_size)))
                )

        return _progress

    def _raiseIfUpdateCancelled(self):
        if self._update_cancel.is_set():
            raise UpdateInstallError("cancelled", "Update cancelled.")

    def _cleanupUpdatePreparation(self, stage_dir=None):
        try:
            cleanup_stale_update_state(locate_runtime().app_data_dir)
        except Exception:
            pass
        if stage_dir is not None:
            try:
                shutil.rmtree(stage_dir, ignore_errors=True)
            except Exception:
                pass

    def _consumeUpdateResultMarker(self):
        try:
            runtime = locate_runtime()
            marker = runtime.app_data_dir / "last-update-result.txt"
            result = read_update_result(marker)
            if not result:
                return
            try:
                marker.unlink()
            except OSError:
                pass
            status = str(result.get("status") or "")
            version = str(result.get("version") or "")
            build_number = int(result.get("build_number") or 0)
            if status == "installed":
                if build_number > self._trustedBuildNumber():
                    next_state = UpdateCheckState(
                        **{
                            **self._update_state.to_dict(),
                            "highest_trusted_build": build_number,
                        }
                    )
                    self._persistUpdateCheckState(next_state.to_dict())
                self._setUpdateInstallState("installed", version, False)
                self.statusMessage.emit(
                    f"Updated to {version}" if version else "Update installed"
                )
            elif status == "failed":
                self._setUpdateInstallState("error", "install_failed", False)
        except Exception as exc:
            print(f"[update] failed to consume update result marker: {exc}")

    def _cleanupStaleUpdatePreparation(self):
        try:
            cleanup_stale_update_state(locate_runtime().app_data_dir)
        except Exception:
            pass

    def _runPrepareLatestUpdate(self):
        stage_dir = None
        try:
            version = self._latest_update_version
            if not version:
                self._updateInstallStateRequest.emit(
                    "error", "check_first", False
                )
                return
            tag = version if version.startswith("v") else f"v{version}"
            self._raiseIfUpdateCancelled()
            self._updateInstallStateRequest.emit("checking", "", False)
            self._raiseIfUpdateCancelled()
            manifest = fetch_update_manifest_for_release(
                tag,
                repo=DEFAULT_RELEASE_REPO,
                highest_trusted_build=self._trustedBuildNumber(),
            )
            self._raiseIfUpdateCancelled()
            runtime = locate_runtime()
            self._raiseIfUpdateCancelled()
            asset = manifest.assets.get(runtime.platform_key)
            if asset is None:
                self._raiseIfUpdateCancelled()
                self._updateInstallStateRequest.emit(
                    "manual_fallback",
                    "no_asset",
                    False,
                )
                return
            if not runtime.platform_key.startswith("windows"):
                plan_install_for_platform(manifest, runtime=runtime)
                self._raiseIfUpdateCancelled()
                platform_message = (
                    "macos" if runtime.platform_key.startswith("macos") else "linux"
                )
                self._updateInstallStateRequest.emit(
                    "manual_fallback", platform_message, False
                )
                return
            if not self.updateInstallEnabled:
                self._raiseIfUpdateCancelled()
                self._updateInstallStateRequest.emit(
                    "manual_fallback", "windows", False
                )
                return
            if not runtime.update_supported:
                self._raiseIfUpdateCancelled()
                self._updateInstallStateRequest.emit(
                    "manual_fallback", "windows", False
                )
                return

            self._updateInstallStateRequest.emit("downloading", "", False)
            archive_path = prepare_downloaded_asset(
                asset,
                download_dir=runtime.app_data_dir / "downloads" / tag,
                cancel_event=self._update_cancel,
                progress_callback=self._updateProgressCallback(asset.size),
            )
            self._raiseIfUpdateCancelled()
            self._updateInstallStateRequest.emit("verifying", "", False)
            stage_dir = same_volume_windows_stage_dir(runtime.install_root, tag)
            staged = extract_validated_zip(
                archive_path,
                stage_dir,
                requirements=ArchiveRequirements(require_windows_app=True),
            )
            self._raiseIfUpdateCancelled()
            plan = plan_install_for_platform(manifest, runtime=runtime, staged=staged)
            if not plan.can_install or not plan.staged:
                self._updateInstallStateRequest.emit(
                    plan.status, plan.message, plan.can_install
                )
                return
            backup_root = runtime.install_root.with_name(
                f"{runtime.install_root.name}.backup-{int(time.time())}"
            )
            result_marker = runtime.app_data_dir / "last-update-result.txt"
            state_path = runtime.app_data_dir / "pending-update.json"
            windows_plan = WindowsUpdatePlan(
                current_pid=os.getpid(),
                install_root=str(runtime.install_root),
                staged_root=str(plan.staged.app_root),
                backup_root=str(backup_root),
                result_marker=str(result_marker),
                target_version=manifest.version,
                target_build_number=manifest.build_number,
            )
            write_windows_update_plan(windows_plan, state_path)
            self._pending_update_plan = windows_plan
            self._pending_update_plan_path = state_path
            self._pending_update_helper_dir = runtime.app_data_dir / "helper" / tag
            self._updateInstallStateRequest.emit("ready_to_install", "", True)
        except Exception as exc:
            code = self._updateErrorCode(exc)
            self._cleanupUpdatePreparation(stage_dir)
            if code == "cancelled":
                self._updateInstallStateRequest.emit("cancelled", "", False)
                return
            self._updateInstallStateRequest.emit("error", code, False)

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
    def setCheckForUpdates(self, value):
        enabled = bool(value)
        if self.checkForUpdates == enabled:
            return
        self._cfg.setdefault("settings", {})["check_for_updates"] = enabled
        save_config(self._cfg)
        self.settingsChanged.emit()
        self._configureUpdateChecks()
        self.statusMessage.emit("Saved")

    @Slot()
    def chooseScreenshotDirectory(self):
        from PySide6.QtWidgets import QFileDialog

        current = self._configured_screenshot_directory() or str(screenshots_dir())
        selected = QFileDialog.getExistingDirectory(
            None,
            "Choose Screenshot Folder",
            current,
        )
        normalized = _normalize_directory_path(selected)
        if not normalized:
            return
        if not os.path.isdir(normalized):
            self.statusMessage.emit("Choose a valid screenshot folder")
            return
        settings = self._cfg.setdefault("settings", {})
        if settings.get("screenshot_directory", "") == normalized:
            return
        settings["screenshot_directory"] = normalized
        save_config(self._cfg)
        self.settingsChanged.emit()
        self.statusMessage.emit("Saved")

    @Slot()
    def resetScreenshotDirectory(self):
        settings = self._cfg.setdefault("settings", {})
        if not settings.get("screenshot_directory", ""):
            return
        settings["screenshot_directory"] = ""
        save_config(self._cfg)
        self.settingsChanged.emit()
        self.statusMessage.emit("Saved")

    @Slot()
    def manualCheckForUpdates(self):
        self._startUpdateCheck(manual=True)

    @Slot()
    def openLatestReleasePage(self):
        url = self._latest_update_url or (
            f"https://github.com/{DEFAULT_RELEASE_REPO}/releases/latest"
        )
        _open_url(url)

    @Slot()
    def prepareLatestUpdate(self):
        if self.updateInstallInProgress:
            self.statusMessage.emit("Update is already in progress")
            return
        self._update_cancel.clear()
        self._setUpdateInstallState("checking")
        thread = threading.Thread(
            target=self._runPrepareLatestUpdate,
            name="MouserPrepareUpdate",
            daemon=True,
        )
        thread.start()

    @Slot()
    def cancelUpdatePreparation(self):
        if self._update_install_status not in {"checking", "downloading", "verifying"}:
            return
        self._update_cancel.set()
        self._setUpdateInstallState("cancelled")

    @Slot()
    def installPreparedUpdate(self):
        if not self.updateInstallEnabled:
            self.statusMessage.emit("Open the release page to install manually")
            return
        if not self._pending_update_plan_path or not self._update_install_can_install:
            self.statusMessage.emit("Update is not ready to install")
            return
        self._setUpdateInstallState("installing")
        engine_stopped = False
        try:
            if self._engine:
                # Release mouse hooks and HID grabs before replacing binaries.
                self._engine.stop()
                engine_stopped = True
            launch_windows_update_helper(
                self._pending_update_plan_path,
                helper_dir=self._pending_update_helper_dir,
            )
        except Exception as exc:
            if engine_stopped and self._engine:
                try:
                    self._engine.start()
                except Exception as restart_exc:
                    print(
                        f"[update] failed to restart remapping after update error: {restart_exc}",
                        file=sys.stderr,
                    )
            self._setUpdateInstallState("error", self._updateErrorCode(exc), False)
            return
        QCoreApplication.quit()

    @Slot(bool)
    def setStartAtLogin(self, value):
        enabled = bool(value)
        if not supports_login_startup():
            self.statusMessage.emit("Start at login is not available on this platform")
            return
        settings = self._cfg.setdefault("settings", {})
        old_enabled = bool(settings.get("start_at_login", False))
        if old_enabled == enabled:
            return
        try:
            apply_login_startup(enabled)
        except Exception as exc:
            self.settingsChanged.emit()
            self.statusMessage.emit(f"Failed to update login item: {exc}")
            return
        settings["start_at_login"] = enabled
        try:
            save_config(self._cfg)
        except Exception as exc:
            settings["start_at_login"] = old_enabled
            rollback_error = None
            try:
                apply_login_startup(old_enabled)
            except Exception as rollback_exc:
                rollback_error = rollback_exc
                print(
                    "[Backend] Failed to roll back start-at-login OS state "
                    f"after config save failure: {rollback_exc}"
                )
            self.settingsChanged.emit()
            if rollback_error is not None:
                self.statusMessage.emit(
                    "Start-at-login state is inconsistent; please restart Mouser to recover."
                )
            else:
                self.statusMessage.emit(f"Failed to save login item setting: {exc}")
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
        current_mode = settings.get("smart_shift_mode", "ratchet")
        current_enabled = settings.get("smart_shift_enabled", False)
        current_threshold = settings.get("smart_shift_threshold", 25)
        next_mode = current_mode if mode is None else mode
        next_enabled = current_enabled if enabled is None else enabled
        next_threshold = current_threshold if threshold is None else threshold
        if (
            next_mode == current_mode
            and next_enabled == current_enabled
            and next_threshold == current_threshold
        ):
            return
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

    @Slot(int)
    def setHapticLevel(self, level):
        level = max(0, min(3, int(level)))
        self._cfg.setdefault("settings", {})["haptic_level"] = level
        save_config(self._cfg)
        self.hapticChanged.emit()
        if self._engine:
            import threading
            threading.Thread(
                target=lambda: self._engine.set_haptic_level(level),
                daemon=True, name="SetHapticLevel"
            ).start()

    @Slot(bool)
    def setHapticEnabled(self, enabled):
        self._cfg.setdefault("settings", {})["haptic_enabled"] = bool(enabled)
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
        self.hapticChanged.emit()

    @Slot()
    def playHapticTest(self):
        if self._engine:
            import threading
            threading.Thread(
                target=lambda: self._engine.play_haptic_waveform(0),
                daemon=True, name="HapticTest"
            ).start()

    @Slot(str, bool)
    def setActionHaptic(self, action_id, enabled):
        """Toggle whether an action fires haptic feedback on button press."""
        self._cfg = set_action_haptic(self._cfg, action_id, bool(enabled))
        if self._engine:
            self._engine.cfg = self._cfg
        self.hapticChanged.emit()

    @Slot(str, bool)
    def setButtonHaptic(self, button_key, enabled):
        """Toggle whether a physical button fires haptic feedback on press."""
        self._cfg = set_button_haptic(self._cfg, button_key, bool(enabled))
        if self._engine:
            self._engine.cfg = self._cfg
        self.hapticChanged.emit()

    @Slot(bool)
    def setHapticDedup(self, enabled):
        """Set whether overlapping haptic pulses are deduplicated."""
        self._cfg.setdefault("settings", {})["haptic_dedup"] = bool(enabled)
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
        self.hapticChanged.emit()

    @Slot(bool)
    def setActionsRingHoverHaptic(self, enabled):
        """Set whether landing on a ring slot fires haptic feedback."""
        self._cfg.setdefault("settings", {})["actions_ring_hover_haptic"] = bool(enabled)
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
        self.hapticChanged.emit()

    @Slot(int)
    def setForceSensitivity(self, value):
        value = int(value)
        self._cfg.setdefault("settings", {})["force_sensitivity"] = value
        save_config(self._cfg)
        self.forceSensingChanged.emit()
        if self._engine:
            import threading
            threading.Thread(
                target=lambda: self._engine.set_force_sensitivity(value),
                daemon=True, name="SetForceSensitivity"
            ).start()

    @Slot(bool)
    def setInvertVScroll(self, value):
        value = bool(value)
        if self.invertVScroll == value:
            return
        self._cfg.setdefault("settings", {})["invert_vscroll"] = value
        save_config(self._cfg)
        if self._engine:
            self._engine.reload_mappings()
        self.settingsChanged.emit()

    @Slot(bool)
    def setInvertHScroll(self, value):
        value = bool(value)
        if self.invertHScroll == value:
            return
        self._cfg.setdefault("settings", {})["invert_hscroll"] = value
        save_config(self._cfg)
        if self._engine:
            self._engine.reload_mappings()
        self.settingsChanged.emit()

    @Slot(bool)
    def setIgnoreTrackpad(self, value):
        self._cfg.setdefault("settings", {})["ignore_trackpad"] = value
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

    @Slot(int, int, str, result=str)
    def shortcutComboFromQtEvent(self, key, modifiers, text):
        return _qt_shortcut_combo(key, modifiers, text)

    @Slot(str, result=str)
    def canonicalizeCustomShortcut(self, text):
        try:
            return canonical_shortcut_text(
                text,
                allow_modifier_only=False,
                platform_name=sys.platform,
            )
        except ShortcutParseError:
            return ""

    @Slot(str, result="QVariantMap")
    def customShortcutValidationErrorInfo(self, text):
        try:
            canonical_shortcut_text(
                text,
                allow_modifier_only=False,
                platform_name=sys.platform,
            )
        except ShortcutParseError as exc:
            return {
                "code": getattr(exc, "code", "") or "unsupported",
                "detail": getattr(exc, "detail", "") or "",
            }
        return {}

    @Slot(str, result=bool)
    def isReservedCustomShortcut(self, text):
        try:
            return is_reserved_risky_shortcut(text, allow_modifier_only=False)
        except ShortcutParseError:
            return False

    @Slot(str, result=str)
    def displayShortcutKeyName(self, name):
        try:
            return pretty_key_name(name, platform_name=sys.platform)
        except ShortcutParseError:
            return name

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

    def _onEngineBatteryRead(self, level, charging):
        """Called from engine thread — posts to Qt main thread."""
        self._batteryChangeRequest.emit(level, charging)

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
        if not isinstance(state, dict):
            return
        settings = self._cfg.setdefault("settings", {})
        mode = state.get("mode", "ratchet")
        enabled = bool(state.get("enabled", False))
        settings["smart_shift_enabled"] = enabled
        # Hardware reads cannot report the user's saved fixed-mode fallback while
        # SmartShift auto-switching is enabled: the device only exposes ratchet +
        # threshold in that state. Preserve the existing fallback mode unless the
        # callback explicitly carries free-spin (the engine's saved-state replay).
        if not enabled or mode == "freespin":
            settings["smart_shift_mode"] = mode
        # Only accept the device-reported threshold when SmartShift is
        # enabled (device returns the real value 1-50).  When disabled the
        # device returns 0xFF which the read code maps to a hardcoded 25,
        # overwriting whatever the user chose in the UI.
        if enabled:
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

    # ── Actions Ring overlay ────────────────────────────────────

    def _onEngineShowRing(self, slots, interactive=False):
        """Called from hook/timer thread — posts to Qt main thread."""
        from core.key_simulator import ACTIONS
        from ui.actions_ring_overlay import _resolve_ring_label
        labels = [_resolve_ring_label(s, ACTIONS.get(s, {}).get("label", s))
                  for s in slots]
        self._showRingRequest.emit(labels, bool(interactive))

    def _onEngineHideRing(self):
        """Called from hook/timer thread — posts to Qt main thread."""
        self._hideRingRequest.emit()

    def _onEngineRingMove(self, dx, dy):
        """Called from HID thread — forward rawXY deltas to overlay."""
        overlay = self._ring_overlay
        if overlay and self._ring_visible:
            overlay.accumulate_rawxy(dx, dy)

    def _getRingCurrentSector(self):
        """Called from hook thread at button-up — reads Python attr, not Qt C++."""
        overlay = self._ring_overlay
        if overlay and self._ring_visible:
            return overlay._highlighted_sector
        return -1

    @Slot(list, bool)
    def _handleShowRing(self, labels, interactive):
        """Runs on Qt main thread — create/show overlay."""
        from PySide6.QtGui import QCursor
        from ui.actions_ring_overlay import ActionsRingOverlay
        if self._ring_overlay is None:
            self._ring_overlay = ActionsRingOverlay()
            self._ring_overlay.action_selected.connect(self._onRingActionSelected)
            self._ring_overlay.cancelled.connect(self._onRingCancelled)
            self._ring_overlay.sector_changed.connect(self._onRingSectorChanged)
        pos = QCursor.pos()
        self._ring_overlay.show_ring(pos.x(), pos.y(), labels, interactive=interactive)
        self._ring_visible = True

    @Slot()
    def _handleHideRing(self):
        """Runs on Qt main thread — hide overlay."""
        self._ring_visible = False
        if self._ring_overlay:
            self._ring_overlay.hide_ring()

    @Slot(int)
    def _onRingActionSelected(self, sector):
        """Overlay click on a sector in toggle mode."""
        if self._engine:
            self._engine.ring_toggle_select(sector)

    @Slot()
    def _onRingCancelled(self):
        """Overlay click on center X or outside ring in toggle mode."""
        if self._engine:
            self._engine.ring_toggle_dismiss()

    @Slot(int)
    def _onRingSectorChanged(self, sector):
        """Cursor moved onto a new ring slot -- fire hover haptic."""
        if self._engine:
            self._engine.ring_hover(sector)

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
        """Runs on Qt main thread.

        A device-reported DPI is authoritative for "what the hardware is
        currently set to" -- the user expects Mouser to keep showing the
        same value across restarts rather than reverting to a stale
        preference whenever the engine reads the device. Clamp the
        incoming value, persist it, and keep the engine's cached config
        in sync so subsequent reads do not loop through a stale picture.

        Skip the engine push (``set_dpi``) here: this handler is reacting
        to a value the device already reports, so echoing it back would
        be a redundant HID round-trip.
        """
        device = self._resolved_connected_device()
        clamped = clamp_dpi(dpi, device)
        settings = self._cfg.setdefault("settings", {})
        if settings.get("dpi") == clamped:
            self.dpiFromDevice.emit(clamped)
            return
        settings["dpi"] = clamped
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
        self.settingsChanged.emit()
        self.dpiFromDevice.emit(clamped)

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
        if (not connected or device_source == "evdev") and self._battery_charging:
            self._battery_charging = False
            self.batteryChargingChanged.emit()
        if self._hid_features_ready != previous_hid_features_ready:
            self.hidFeaturesReadyChanged.emit()
            self.forceSensingChanged.emit()
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
        previous_hid_features_ready = self._hid_features_ready
        self._hid_features_ready = bool(
            getattr(self._engine, "hid_features_ready", False)
        ) if self._engine else False
        if self._hid_features_ready != previous_hid_features_ready:
            self.hidFeaturesReadyChanged.emit()
            self.forceSensingChanged.emit()
        self._connected_device_refresh_attempts += 1
        self._sync_connected_device_info()

    def _apply_device_layout(self, device):
        device_key = getattr(device, "key", "") or ""
        display_name = getattr(device, "display_name", "") or "Logitech mouse"
        source = getattr(device, "source", "") or ""
        transport = getattr(device, "transport", "") or ""
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
        if transport != self._connected_device_transport:
            self._connected_device_transport = transport
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

    @Slot(int, bool)
    def _handleBatteryChange(self, level, charging):
        """Runs on Qt main thread."""
        if level != self._battery_level:
            self._battery_level = level
            self.batteryLevelChanged.emit()
        if charging != self._battery_charging:
            self._battery_charging = charging
            self.batteryChargingChanged.emit()

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
