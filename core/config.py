"""
Configuration manager — loads/saves button mappings to a JSON file.
Supports per-application profiles (for future use).
"""

import json
import os
import sys

if sys.platform == "darwin":
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "LogiControl")
elif sys.platform == "win32":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LogiControl")
else:
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".logicontrol")

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
}

# Maps config button keys to the MouseEvent types they correspond to
BUTTON_TO_EVENTS = {
    "middle":        ("middle_down", "middle_up"),
    "gesture":       ("gesture_down", "gesture_up"),
    "xbutton1":      ("xbutton1_down", "xbutton1_up"),
    "xbutton2":      ("xbutton2_down", "xbutton2_up"),
    "hscroll_left":  ("hscroll_left",),
    "hscroll_right": ("hscroll_right",),
}

DEFAULT_CONFIG = {
    "version": 2,
    "active_profile": "default",
    "profiles": {
        "default": {
            "label": "Default (All Apps)",
            "apps": [],          # empty = all apps (fallback profile)
            "mappings": {
                "middle": "none",
                "gesture": "none",
                "xbutton1": "alt_tab",
                "xbutton2": "alt_tab",
                "hscroll_left": "browser_back",
                "hscroll_right": "browser_forward",
            },
        }
    },
    "settings": {
        "start_minimized": True,
        "start_with_windows": False,
        "hscroll_threshold": 1,
        "invert_hscroll": False,  # swap horizontal scroll directions
        "invert_vscroll": False,  # swap vertical scroll directions
        "dpi": 1000,              # pointer speed / DPI setting
    },
}

# Known applications for per-app profiles
# Note: Modern UWP apps appear as their package exe (e.g. Microsoft.Media.Player.exe)
# thanks to ApplicationFrameHost child-window resolution in app_detector.py.
# icon values must match filenames in images/ (without extension for png,
# or with extension for non-png like .webp)
KNOWN_APPS = {
    # Windows executables
    "msedge.exe":                {"label": "Microsoft Edge",       "icon": ""},
    "chrome.exe":                {"label": "Google Chrome",        "icon": "chrom"},
    "Microsoft.Media.Player.exe":{"label": "Windows Media Player", "icon": "media.webp"},
    "wmplayer.exe":              {"label": "Windows Media Player (Classic)", "icon": "media.webp"},
    "vlc.exe":                   {"label": "VLC Media Player",     "icon": "VLC"},
    "Code.exe":                  {"label": "Visual Studio Code",   "icon": "VSCODE"},
    # macOS executables (basename of the bundle binary)
    "Safari":                    {"label": "Safari",               "icon": ""},
    "Google Chrome":             {"label": "Google Chrome",        "icon": "chrom"},
    "Chromium":                  {"label": "Chromium",             "icon": "chrom"},
    "Firefox":                   {"label": "Firefox",              "icon": ""},
    "VLC":                       {"label": "VLC Media Player",     "icon": "VLC"},
    "Code":                      {"label": "Visual Studio Code",   "icon": "VSCODE"},
    "Finder":                    {"label": "Finder",               "icon": ""},
    "Music":                     {"label": "Apple Music",          "icon": ""},
}


def get_icon_for_exe(exe_name: str) -> str:
    """Return the icon image filename (relative to images/) for an exe, or ''."""
    info = KNOWN_APPS.get(exe_name, {})
    icon = info.get("icon", "")
    if not icon:
        return ""
    # If icon already has extension, use as-is; otherwise assume .png
    if "." in icon:
        return icon
    return icon + ".png"


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


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
            return cfg
        except Exception as e:
            print(f"[Config] Error loading config: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy


def save_config(cfg):
    """Persist config to disk."""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


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


def get_profile_for_app(cfg, exe_name):
    """Return the profile name that matches the given executable, or 'default'."""
    for pname, pdata in cfg.get("profiles", {}).items():
        if exe_name and exe_name.lower() in [a.lower() for a in pdata.get("apps", [])]:
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
