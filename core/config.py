"""
Configuration manager — loads/saves button mappings to a JSON file.
Supports per-application profiles (for future use).
"""

import json
import os
import stat
import sys
import tempfile
from urllib.parse import quote
from core import app_catalog

if sys.platform == "darwin":
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Mouser")
elif sys.platform == "linux":
    CONFIG_DIR = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")),
        "Mouser",
    )
else:
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Mouser")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Which mouse events map to which friendly button names
# Order matches the Logi Options+ diagram (top view then side view)
# Config keys are tied to *physical buttons*, not to which control happens to
# be the "primary" gesture surface on a given device:
#   "gesture"      = the physical Gesture button (thumb). It is the primary
#                    gesture control on the MX Master 3/3S/classic, and the
#                    small thumb-area button (CID 0x00C3) on the MX Master 4.
#   "actions_ring" = the MX Master 4 Sense Panel (CID 0x01A0), labeled
#                    "Actions Ring". MX Master 4 only.
# The HID layer emits a device-appropriate event family (gesture_* vs sense_*)
# so the same key means the same physical button everywhere -- see
# BUTTON_TO_EVENTS below and core/mouse_hook_base.py.
BUTTON_NAMES = {
    "middle":        "Middle button",
    "gesture":       "Gesture button",
    "xbutton1":      "Back button",
    "xbutton2":      "Forward button",
    "hscroll_left":  "Horizontal scroll",
    "hscroll_right": "Horizontal scroll right",
    "mode_shift":    "Mode shift button",
    "dpi_switch":    "DPI switch button",
    "actions_ring":  "Actions Ring",
    "thumb_button":  "Thumb button",
}

# Whole-mouse-movement swipe directions for the Gesture button (thumb).
GESTURE_SWIPE_BUTTONS = (
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
)
# Swipe directions for the Sense Panel ("Actions Ring") -- MX Master 4 only.
ACTIONS_RING_SWIPE_BUTTONS = (
    "actions_ring_left",
    "actions_ring_right",
    "actions_ring_up",
    "actions_ring_down",
)
# Union of both swipe sets (order: Gesture button first, then Sense Panel).
GESTURE_DIRECTION_BUTTONS = GESTURE_SWIPE_BUTTONS + ACTIONS_RING_SWIPE_BUTTONS

# Maps a swipe-set's tap button key -> its four direction keys.
SWIPE_SET_FOR_TAP = {
    "gesture": GESTURE_SWIPE_BUTTONS,
    "actions_ring": ACTIONS_RING_SWIPE_BUTTONS,
}

GESTURE_SENSITIVITY_PX = (18, 25, 33, 44, 56)
GESTURE_DEFAULT_SENSITIVITY_INDEX = 1


def gesture_sensitivity_index_for(threshold_px):
    """Return the sensitivity preset index nearest to a stored px threshold."""
    return min(
        range(len(GESTURE_SENSITIVITY_PX)),
        key=lambda i: abs(GESTURE_SENSITIVITY_PX[i] - int(threshold_px)),
    )


WHEEL_DIVERT_AUTO = "auto"
WHEEL_DIVERT_OFF = "off"
WHEEL_DIVERT_VALID_VALUES: frozenset[str] = frozenset((WHEEL_DIVERT_AUTO, WHEEL_DIVERT_OFF))
WHEEL_DIVERT_DEFAULT = WHEEL_DIVERT_AUTO

_WHEEL_DIVERT_WARNED: set[str] = set()


def coerce_wheel_divert_setting(value: object) -> str:
    """Normalize a stored wheel_divert value to a valid constant."""
    if isinstance(value, str) and value in WHEEL_DIVERT_VALID_VALUES:
        return value
    key = repr(value)
    if key not in _WHEEL_DIVERT_WARNED:
        _WHEEL_DIVERT_WARNED.add(key)
        print(f"[Config] wheel_divert={key!s} is not valid; using {WHEEL_DIVERT_DEFAULT!r}")
    return WHEEL_DIVERT_DEFAULT

PROFILE_BUTTON_NAMES = {
    **BUTTON_NAMES,
    "gesture_left":       "Gesture swipe left",
    "gesture_right":      "Gesture swipe right",
    "gesture_up":         "Gesture swipe up",
    "gesture_down":       "Gesture swipe down",
    "actions_ring_left":  "Actions Ring swipe left",
    "actions_ring_right": "Actions Ring swipe right",
    "actions_ring_up":    "Actions Ring swipe up",
    "actions_ring_down":  "Actions Ring swipe down",
}

# Maps config button keys to the MouseEvent types they correspond to.
# The Gesture button (thumb) uses the gesture_* family; the Sense Panel
# ("Actions Ring", MX4 only) uses the sense_* family. See BUTTON_NAMES for
# why the key names differ from the historical "primary gesture" wiring.
BUTTON_TO_EVENTS = {
    "middle":             ("middle_down", "middle_up"),
    # Gesture button (thumb)
    "gesture":            ("gesture_click",),
    "gesture_left":       ("gesture_swipe_left",),
    "gesture_right":      ("gesture_swipe_right",),
    "gesture_up":         ("gesture_swipe_up",),
    "gesture_down":       ("gesture_swipe_down",),
    "xbutton1":           ("xbutton1_down", "xbutton1_up"),
    "xbutton2":           ("xbutton2_down", "xbutton2_up"),
    "hscroll_left":       ("hscroll_left",),
    "hscroll_right":      ("hscroll_right",),
    "mode_shift":         ("mode_shift_down", "mode_shift_up"),
    "dpi_switch":         ("dpi_switch_down", "dpi_switch_up"),
    # Sense Panel ("Actions Ring", MX Master 4)
    "actions_ring":       ("sense_click",),
    "actions_ring_left":  ("sense_swipe_left",),
    "actions_ring_right": ("sense_swipe_right",),
    "actions_ring_up":    ("sense_swipe_up",),
    "actions_ring_down":  ("sense_swipe_down",),
    "thumb_button":       ("thumb_button_down", "thumb_button_up"),
}

# Hold (press-and-hold) events, used to drive the Actions Ring overlay when a
# button's tap action is "activate_actions_ring".
BUTTON_HOLD_EVENTS = {
    "gesture":      ("gesture_button_down", "gesture_button_up"),
    "actions_ring": ("sense_button_down", "sense_button_up"),
}

DEFAULT_CONFIG = {
    "version": 21,
    "active_profile": "default",
    "profiles": {
        "default": {
            "label": "Default (All Apps)",
            "apps": [],          # empty = all apps (fallback profile)
            "mappings": {
                "middle": "none",
                # Gesture button (thumb) — App Exposé by default on the MX4.
                "gesture": "app_expose",
                "gesture_left": "none",
                "gesture_right": "none",
                "gesture_up": "none",
                "gesture_down": "none",
                "xbutton1": "mouse_back_click",     # Back (Mouse Button 4)
                "xbutton2": "mouse_forward_click",  # Forward (Mouse Button 5)
                "hscroll_left": "none",             # pass-through
                "hscroll_right": "none",            # pass-through
                "mode_shift": "switch_scroll_mode",
                # Sense Panel ("Actions Ring", MX4) — activates the ring.
                "actions_ring": "activate_actions_ring",
                "actions_ring_left": "none",
                "actions_ring_right": "none",
                "actions_ring_up": "none",
                "actions_ring_down": "none",
                "thumb_button": "none",
                "actions_ring_slots": [
                    "mission_control", "play_pause",
                    "show_desktop", "launchpad",
                ],
            },
            "button_haptic": {},  # per-button haptic override; absent key = enabled (True)
        }
    },
    "settings": {
        "start_minimized": True,
        "start_at_login": False,
        "hscroll_threshold": 0.1,
        "invert_hscroll": False,  # swap horizontal scroll directions
        "invert_vscroll": False,  # swap vertical scroll directions
        "dpi": 1000,              # pointer speed / DPI setting
        "smart_shift_mode": "ratchet",
        "smart_shift_enabled": False,
        "smart_shift_threshold": 25,
        "gesture_threshold": GESTURE_SENSITIVITY_PX[GESTURE_DEFAULT_SENSITIVITY_INDEX],
        "gesture_commit_window_ms": 400,
        "gesture_settle_ms": 90,
        "gesture_cross_ratio": 0.5,
        "appearance_mode": "system",
        "debug_mode": False,
        "device_layout_overrides": {},
        "language": "en",
        "haptic_level": 2,          # 0=subtle, 1=low, 2=medium, 3=high
        "haptic_enabled": True,     # global haptic on/off
        "action_haptic": [],        # action IDs that fire haptic on press; empty = opt-in
        "button_haptic": [],        # button keys that fire haptic on press; empty = opt-in
        "haptic_dedup": True,       # True = deduplicate pulses within 100ms window
        "ignore_trackpad": True,
        "screenshot_directory": "",
        "wheel_divert": WHEEL_DIVERT_DEFAULT,
        "check_for_updates": True,
        "update_check_state": {},
        "force_sensitivity": None,
        "actions_ring_hold_ms": 250,
        "close_action": "ask",      # "ask" | "quit" | "minimize" — window close-button behavior
    },
}

# Known applications for per-app profiles
# Note: Modern UWP apps appear as their package exe (e.g. Microsoft.Media.Player.exe)
# thanks to ApplicationFrameHost child-window resolution in app_detector.py.
# icon values must match filenames in images/ (without extension for png,
# or with extension for non-png like .webp)
KNOWN_APPS = {
    # Windows apps
    "msedge.exe":                {"label": "Microsoft Edge",       "icon": ""},
    "chrome.exe":                {"label": "Google Chrome",        "icon": "chrom"},
    "Microsoft.Media.Player.exe":{"label": "Windows Media Player", "icon": "media.webp"},
    "wmplayer.exe":              {"label": "Windows Media Player (Classic)", "icon": "media.webp"},
    "vlc.exe":                   {"label": "VLC Media Player",     "icon": "VLC"},
    "Code.exe":                  {"label": "Visual Studio Code",   "icon": "VSCODE"},
    # macOS apps (executable names from NSWorkspace)
    "Safari":                    {"label": "Safari",               "icon": ""},
    "Google Chrome":             {"label": "Google Chrome",        "icon": "chrom"},
    "VLC":                       {"label": "VLC Media Player",     "icon": "VLC"},
    "Code":                      {"label": "Visual Studio Code",   "icon": "VSCODE"},
    "Finder":                    {"label": "Finder",               "icon": ""},
}


def get_icon_for_exe(exe_name: str) -> str:
    """Return an image:// URL for the app icon, or '' if unavailable."""
    if not exe_name:
        return ""
    # Full path on disk → extract icon via SystemIconProvider
    if os.path.isabs(exe_name) and os.path.exists(exe_name):
        encoded = quote(exe_name.replace("\\", "/"), safe="/:")
        return f"image://systemicons/{encoded}"
    # Exe name / label → look up installed path via app catalog
    entry = app_catalog.resolve_app_spec(exe_name)
    if entry:
        path = entry.get("path", "")
        if path and os.path.exists(path):
            encoded = quote(path.replace("\\", "/"), safe="/:")
            return f"image://systemicons/{encoded}"
    return ""


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)


def load_config():
    """Load config from disk, or return defaults if none exists."""
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge any missing keys from default
            cfg = _migrate(cfg)
            cfg = _merge_defaults(cfg, DEFAULT_CONFIG)
            cfg = _validate_types(cfg, DEFAULT_CONFIG)
            return cfg
        except Exception as e:
            print(f"[Config] Error loading config: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy


def _atomic_write_json(path, obj):
    """Write a JSON object to *path* atomically with restrictive permissions."""
    ensure_config_dir()
    target_path = os.path.realpath(path)
    target_dir = os.path.dirname(target_path) or CONFIG_DIR
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform != "win32":
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_config(cfg):
    """Persist config to disk via atomic write with restrictive permissions."""
    _atomic_write_json(CONFIG_FILE, cfg)



def get_active_mappings(cfg):
    """Return the mappings dict for the currently active profile."""
    profile_name = cfg.get("active_profile", "default")
    profiles = cfg.get("profiles", {})
    profile = profiles.get(profile_name, profiles.get("default", {}))
    return profile.get("mappings", DEFAULT_CONFIG["profiles"]["default"]["mappings"])


def set_mapping(cfg, button, action_id, profile=None):
    """Set a mapping for a button in the given profile (or active profile)."""
    if profile is None:
        profile = cfg.get("active_profile", "default")
    cfg["profiles"].setdefault(profile, {
        "label": profile,
        "mappings": dict(DEFAULT_CONFIG["profiles"]["default"]["mappings"]),
    })
    cfg["profiles"][profile]["mappings"][button] = action_id
    save_config(cfg)
    return cfg


def create_profile(cfg, name, label=None, copy_from="default", apps=None):
    """Create a new profile, optionally copying from an existing one."""
    if label is None:
        label = name
    source = cfg["profiles"].get(copy_from, cfg["profiles"].get("default", {}))
    cfg["profiles"][name] = {
        "label": label,
        "apps": apps if apps is not None else [],
        "mappings": dict(source.get("mappings", {})),
        "button_haptic": dict(source.get("button_haptic", {})),
    }
    save_config(cfg)
    return cfg


# Curated list of actions that may fire haptic feedback on button press.
# Other actions (text editing, raw scroll, mouse buttons, etc.) never trigger
# haptic regardless of mapping. Order here is the order shown in the picker UI.
HAPTIC_ELIGIBLE_ACTIONS = [
    "switch_scroll_mode",
    "toggle_smart_shift",
    "cycle_dpi",
    "volume_up",
    "volume_down",
    "volume_up_continuous",
    "volume_down_continuous",
    "brightness_up",
    "brightness_down",
    "brightness_up_continuous",
    "brightness_down_continuous",
    "volume_mute",
    "play_pause",
    "next_track",
    "prev_track",
    "task_view",
    "alt_tab",
    "alt_shift_tab",
    "win_d",
]


def action_haptic_enabled(cfg, action_id):
    """True if haptic should fire when action_id executes via a button press."""
    return action_id in cfg.get("settings", {}).get("action_haptic", [])


def set_action_haptic(cfg, action_id, enabled):
    """Add or remove action_id from the global per-action haptic allowlist."""
    lst = cfg.setdefault("settings", {}).setdefault("action_haptic", [])
    if enabled:
        if action_id not in lst:
            lst.append(action_id)
    else:
        if action_id in lst:
            lst.remove(action_id)
    save_config(cfg)
    return cfg


def button_haptic_enabled(cfg, button_key):
    """True if haptic should fire when button_key is pressed."""
    return button_key in cfg.get("settings", {}).get("button_haptic", [])


def set_button_haptic(cfg, button_key, enabled):
    """Add or remove button_key from the global per-button haptic allowlist."""
    lst = cfg.setdefault("settings", {}).setdefault("button_haptic", [])
    if enabled:
        if button_key not in lst:
            lst.append(button_key)
    else:
        if button_key in lst:
            lst.remove(button_key)
    save_config(cfg)
    return cfg


def delete_profile(cfg, name):
    """Delete a profile (cannot delete 'default')."""
    if name == "default":
        return cfg
    cfg["profiles"].pop(name, None)
    if cfg["active_profile"] == name:
        cfg["active_profile"] = "default"
    save_config(cfg)
    return cfg


def resolve_app_for_config(spec: str):
    """Resolve an app identifier/path into a catalog entry with aliases."""
    return app_catalog.resolve_app_spec(spec)


def _dedupe_specs(candidates) -> list[str]:
    result = []
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        candidate = str(candidate)
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _identity_specs(app_identity: tuple[str, ...] | None) -> list[str]:
    return _dedupe_specs(app_identity or ())


def _configured_app_specs(app_spec: str | None) -> list[str]:
    return _dedupe_specs((app_spec,) if app_spec else ())


def _app_identity_aliases(spec: str) -> set[str]:
    if not spec:
        return set()
    entry = resolve_app_for_config(spec)
    if not entry:
        return {spec.casefold()}
    aliases = [entry.get("id", ""), *entry.get("aliases", [])]
    return {alias.casefold() for alias in aliases if alias}


def get_profile_for_app_identity(cfg, app_identity: tuple[str, ...] | None) -> str:
    """
    Return the profile name that matches an app identity, or 'default'.

    ``app_identity`` is an ordered tuple of identifiers. Identifiers are matched
    most-specific first, allowing a nested app profile to win before falling
    back to its host app profile.
    """
    identities = _identity_specs(app_identity)
    if not identities:
        return "default"

    alias_cache = {}

    def aliases_for(spec: str) -> set[str]:
        key = spec.casefold()
        if key not in alias_cache:
            alias_cache[key] = _app_identity_aliases(spec)
        return alias_cache[key]

    profiles = list(cfg.get("profiles", {}).items())
    for identity in identities:
        aliases = aliases_for(identity)
        for pname, pdata in profiles:
            for app in pdata.get("apps", []):
                for app_spec in _configured_app_specs(app):
                    if aliases & aliases_for(app_spec):
                        return pname
    return "default"


def _migrate(cfg):
    """Migrate config from older versions to current."""
    version = cfg.get("version", 1)
    if version < 2:
        # v1 → v2:  add 'apps' list to each profile, new settings keys
        for pdata in cfg.get("profiles", {}).values():
            pdata.setdefault("apps", [])
        cfg.setdefault("settings", {})
        cfg["settings"].setdefault("invert_hscroll", False)
        cfg["settings"].setdefault("invert_vscroll", False)
        cfg["settings"].setdefault("dpi", 1000)
        cfg["version"] = 2

    if version < 3:
        settings = cfg.setdefault("settings", {})
        settings.setdefault(
            "gesture_threshold",
            GESTURE_SENSITIVITY_PX[GESTURE_DEFAULT_SENSITIVITY_INDEX],
        )
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            mappings.setdefault("gesture", "none")
            for key in GESTURE_DIRECTION_BUTTONS:
                mappings.setdefault(key, "none")
        cfg["version"] = 3

    if version < 4:
        settings = cfg.setdefault("settings", {})
        settings.setdefault("device_layout_overrides", {})
        cfg["version"] = 4

    if version < 5:
        settings = cfg.setdefault("settings", {})
        if "start_at_login" not in settings and "start_with_windows" in settings:
            settings["start_at_login"] = bool(settings["start_with_windows"])
        else:
            settings.setdefault("start_at_login", False)
        settings.pop("start_with_windows", None)
        cfg["version"] = 5

    if version < 6:
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            mappings.setdefault("mode_shift", "none")
        cfg["version"] = 6

    if version < 7:
        # v6 defaulted mode_shift to "none"; remap to "toggle_smart_shift" so the
        # physical SmartShift button behind the scroll wheel works out of the box.
        # Users who explicitly want no action can set it back to "none" in the UI.
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            if mappings.get("mode_shift") == "none":
                mappings["mode_shift"] = "toggle_smart_shift"
        cfg["version"] = 7

    if version < 8:
        # v7 defaulted mode_shift to "toggle_smart_shift" (SmartShift on/off toggle).
        # The better default matches Logi Options+: switch ratchet ↔ free-spin.
        # Upgrade "toggle_smart_shift" → "switch_scroll_mode" for all profiles.
        # Users who prefer the old toggle can reassign it in the UI.
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            if mappings.get("mode_shift") == "toggle_smart_shift":
                mappings["mode_shift"] = "switch_scroll_mode"
        cfg["version"] = 8

    if version < 9:
        # v8 -> v9: add Actions Ring button mapping for MX Master 4,
        # add haptic feedback level setting, and add ignore_trackpad setting.
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            mappings.setdefault("actions_ring", "none")
        settings = cfg.setdefault("settings", {})
        settings.setdefault("haptic_level", 2)
        settings.setdefault("ignore_trackpad", True)
        cfg["version"] = 9

    if version < 10:
        # v9 -> v10: gesture recognizer rewrite — add stroke-aware params.
        settings = cfg.setdefault("settings", {})
        settings.setdefault("gesture_commit_window_ms", 400)
        settings.setdefault("gesture_settle_ms", 90)
        settings.setdefault("gesture_cross_ratio", 0.5)
        cfg["version"] = 10

    if version < 11:
        # v10 -> v11: MX4 dual-CID model — wheel_divert + thumb_button.
        settings = cfg.setdefault("settings", {})
        settings.setdefault("wheel_divert", WHEEL_DIVERT_DEFAULT)
        for pdata in cfg.get("profiles", {}).values():
            mappings = pdata.setdefault("mappings", {})
            mappings.setdefault("thumb_button", "none")
        cfg["version"] = 11

    if version < 12:
        # v11 -> v12: add per-button haptic override dict to each profile.
        for pdata in cfg.get("profiles", {}).values():
            pdata.setdefault("button_haptic", {})
        cfg["version"] = 12

    if version < 13:
        # v12 -> v13: add global haptic enabled flag.
        cfg.setdefault("settings", {}).setdefault("haptic_enabled", True)
        cfg["version"] = 13

    if version < 14:
        # v13 -> v14: add per-action haptic allowlist (empty = opt-in).
        cfg.setdefault("settings", {}).setdefault("action_haptic", [])
        cfg["version"] = 14

    if version < 15:
        # v14 -> v15: add per-button haptic allowlist and dedup flag.
        s = cfg.setdefault("settings", {})
        s.setdefault("button_haptic", [])
        s.setdefault("haptic_dedup", True)
        cfg["version"] = 15

    if version < 16:
        # v15 -> v16: add force sensing button sensitivity (None = device default).
        cfg.setdefault("settings", {}).setdefault("force_sensitivity", None)
        cfg["version"] = 16

    if version < 17:
        # v16 -> v17: migrate hscroll_threshold from old default (int 1) to 0.1.
        s = cfg.setdefault("settings", {})
        if s.get("hscroll_threshold") == 1:
            s["hscroll_threshold"] = 0.1
        cfg["version"] = 17

    if version < 18:
        # v17 -> v18: Actions Ring radial overlay — mode, hold threshold, slots.
        s = cfg.setdefault("settings", {})
        s.setdefault("actions_ring_mode", "ring")
        s.setdefault("actions_ring_hold_ms", 250)
        for prof in cfg.get("profiles", {}).values():
            m = prof.get("mappings", {})
            m.setdefault("actions_ring_slots", [
                "screenshot_fullscreen", "play_pause",
                "show_desktop", "lock_screen",
            ])
        cfg["version"] = 18

    if version < 19:
        # v18 -> v19: Actions Ring is now an assignable action.
        s = cfg.setdefault("settings", {})
        old_mode = s.pop("actions_ring_mode", "ring")
        for prof in cfg.get("profiles", {}).values():
            m = prof.get("mappings", {})
            if old_mode == "ring":
                m["actions_ring"] = "activate_actions_ring"
            elif old_mode == "disabled":
                m["actions_ring"] = "none"
            # "simple": keep existing mapping (already a real action ID)
        cfg["version"] = 19

    if version < 20:
        # v19 -> v20: dual gesture-swipe sets. Config keys now track physical
        # buttons, so no mapping move is required here.
        cfg["version"] = 20

    if version < 21:
        # v20 briefly migrated the MX4 Sense Panel's default Actions Ring
        # action onto "gesture". Move only that legacy default back to the
        # physical "actions_ring" key; leave custom mappings alone.
        for prof in cfg.get("profiles", {}).values():
            m = prof.get("mappings", {})
            if (m.get("gesture") == "activate_actions_ring"
                    and m.get("actions_ring", "none") == "none"):
                m["actions_ring"] = "activate_actions_ring"
                m["gesture"] = "none"
        cfg["version"] = 21

    cfg.setdefault("settings", {})
    cfg["settings"].setdefault("appearance_mode", "system")
    cfg["settings"].setdefault("debug_mode", False)
    cfg["settings"].setdefault("device_layout_overrides", {})
    cfg["settings"].setdefault("language", "en")
    cfg["settings"].setdefault("ignore_trackpad", True)
    cfg["settings"].setdefault("screenshot_directory", "")
    cfg["settings"].setdefault("check_for_updates", True)
    cfg["settings"].setdefault("update_check_state", {})
    cfg["settings"].setdefault("close_action", "ask")
    cfg["settings"]["wheel_divert"] = coerce_wheel_divert_setting(
        cfg["settings"].get("wheel_divert", WHEEL_DIVERT_DEFAULT)
    )

    # Always migrate old wmplayer.exe → Microsoft.Media.Player.exe in profile apps
    for pdata in cfg.get("profiles", {}).values():
        mappings = pdata.setdefault("mappings", {})
        default_mappings = DEFAULT_CONFIG["profiles"]["default"]["mappings"]
        for key in (
            "gesture",
            "gesture_left",
            "gesture_right",
            "gesture_up",
            "gesture_down",
            "actions_ring",
            "actions_ring_left",
            "actions_ring_right",
            "actions_ring_up",
            "actions_ring_down",
        ):
            mappings.setdefault(key, default_mappings.get(key, "none"))
        apps = pdata.get("apps", [])
        for i, a in enumerate(apps):
            if a.lower() == "wmplayer.exe":
                apps[i] = "Microsoft.Media.Player.exe"

    return cfg


def _merge_defaults(cfg, defaults):
    """Recursively merge missing keys from defaults into cfg."""
    for key, val in defaults.items():
        if key not in cfg:
            cfg[key] = val
        elif isinstance(val, dict) and isinstance(cfg.get(key), dict):
            _merge_defaults(cfg[key], val)
    return cfg



def _is_compatible_type(value, default_val):
    """Return True for values that are safe despite differing exact types."""
    return (
        isinstance(default_val, float)
        and isinstance(value, int)
        and not isinstance(value, bool)
    )


def _validate_types(cfg, defaults, path=""):
    """Reset values whose type doesn't match the defaults template."""
    for key, default_val in defaults.items():
        if key not in cfg:
            continue
        if default_val is None:
            continue
        if isinstance(default_val, dict):
            if isinstance(cfg[key], dict):
                _validate_types(cfg[key], default_val, f"{path}.{key}")
            else:
                print(f"[Config] Type mismatch at {path}.{key}: "
                      f"expected dict, got {type(cfg[key]).__name__}")
                cfg[key] = json.loads(json.dumps(default_val))
        elif _is_compatible_type(cfg[key], default_val):
            continue
        elif not isinstance(cfg[key], type(default_val)):
            print(f"[Config] Type mismatch at {path}.{key}: "
                  f"expected {type(default_val).__name__}, "
                  f"got {type(cfg[key]).__name__}")
            cfg[key] = default_val
    return cfg
