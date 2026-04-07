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
BUTTON_NAMES = {
    "middle":        "Middle button",
    "gesture":       "Gesture button",
    "xbutton1":      "Back button",
    "xbutton2":      "Forward button",
    "hscroll_left":  "Horizontal scroll left",
    "hscroll_right": "Horizontal scroll right",
    "mode_shift":    "Mode shift button",
    "dpi_switch":    "DPI switch button",
}

GESTURE_DIRECTION_BUTTONS = (
    "gesture_left",
    "gesture_right",
    "gesture_up",
    "gesture_down",
)

PROFILE_BUTTON_NAMES = {
    **BUTTON_NAMES,
    "gesture_left":  "Gesture swipe left",
    "gesture_right": "Gesture swipe right",
    "gesture_up":    "Gesture swipe up",
    "gesture_down":  "Gesture swipe down",
}

# Maps config button keys to the MouseEvent types they correspond to
BUTTON_TO_EVENTS = {
    "middle":        ("middle_down", "middle_up"),
    "gesture":       ("gesture_click",),
    "gesture_left":  ("gesture_swipe_left",),
    "gesture_right": ("gesture_swipe_right",),
    "gesture_up":    ("gesture_swipe_up",),
    "gesture_down":  ("gesture_swipe_down",),
    "xbutton1":      ("xbutton1_down", "xbutton1_up"),
    "xbutton2":      ("xbutton2_down", "xbutton2_up"),
    "hscroll_left":  ("hscroll_left",),
    "hscroll_right": ("hscroll_right",),
    "mode_shift":    ("mode_shift_down", "mode_shift_up"),
    "dpi_switch":    ("dpi_switch_down", "dpi_switch_up"),
}

DEFAULT_CONFIG = {
    "version": 8,
    "active_profile": "default",
    "profiles": {
        "default": {
            "label": "Default (All Apps)",
            "apps": [],          # empty = all apps (fallback profile)
            "mappings": {
                "middle": "none",
                "gesture": "none",
                "gesture_left": "none",
                "gesture_right": "none",
                "gesture_up": "none",
                "gesture_down": "none",
                "xbutton1": "alt_tab",
                "xbutton2": "alt_tab",
                "hscroll_left": "browser_back",
                "hscroll_right": "browser_forward",
                "mode_shift": "switch_scroll_mode",
            },
        }
    },
    "settings": {
        "start_minimized": True,
        "start_at_login": False,
        "hscroll_threshold": 1,
        "invert_hscroll": False,  # swap horizontal scroll directions
        "invert_vscroll": False,  # swap vertical scroll directions
        "dpi": 1000,              # pointer speed / DPI setting
        "smart_shift_mode": "ratchet",
        "smart_shift_enabled": False,
        "smart_shift_threshold": 25,
        "gesture_threshold": 50,
        "gesture_deadzone": 40,
        "gesture_timeout_ms": 3000,
        "gesture_cooldown_ms": 500,
        "appearance_mode": "system",
        "debug_mode": False,
        "device_layout_overrides": {},
        "language": "en",
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


def save_config(cfg):
    """Persist config to disk via atomic write with restrictive permissions."""
    ensure_config_dir()
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform != "win32":
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, CONFIG_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    }
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


def get_profile_for_app(cfg, exe_name):
    """Return the profile name that matches the given executable, or 'default'."""
    if not exe_name:
        return "default"
    entry = resolve_app_for_config(exe_name)
    aliases = {a.lower() for a in ([entry["id"]] + entry.get("aliases", []))} if entry else {exe_name.lower()}
    for pname, pdata in cfg.get("profiles", {}).items():
        for app in pdata.get("apps", []):
            if app.lower() in aliases:
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
        settings.setdefault("gesture_threshold", 50)
        settings.setdefault("gesture_deadzone", 40)
        settings.setdefault("gesture_timeout_ms", 3000)
        settings.setdefault("gesture_cooldown_ms", 500)
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

    cfg.setdefault("settings", {})
    cfg["settings"].setdefault("appearance_mode", "system")
    cfg["settings"].setdefault("debug_mode", False)
    cfg["settings"].setdefault("device_layout_overrides", {})
    cfg["settings"].setdefault("language", "en")

    # Always migrate old wmplayer.exe → Microsoft.Media.Player.exe in profile apps
    for pdata in cfg.get("profiles", {}).values():
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


def _validate_types(cfg, defaults, path=""):
    """Reset values whose type doesn't match the defaults template."""
    for key, default_val in defaults.items():
        if key not in cfg:
            continue
        if isinstance(default_val, dict):
            if isinstance(cfg[key], dict):
                _validate_types(cfg[key], default_val, f"{path}.{key}")
            else:
                print(f"[Config] Type mismatch at {path}.{key}: "
                      f"expected dict, got {type(cfg[key]).__name__}")
                cfg[key] = json.loads(json.dumps(default_val))
        elif not isinstance(cfg[key], type(default_val)):
            print(f"[Config] Type mismatch at {path}.{key}: "
                  f"expected {type(default_val).__name__}, "
                  f"got {type(cfg[key]).__name__}")
            cfg[key] = default_val
    return cfg
