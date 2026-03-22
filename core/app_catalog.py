"""
Application catalog helpers.

Provides:
- installed-app discovery for the current platform
- stable app identifiers for profile matching
- friendly labels for UI display
- alias resolution so old config values keep matching
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import sys
import threading
from pathlib import Path

if sys.platform == "win32":
    import winreg
else:
    winreg = None


# Intentionally curated list of high-value Windows apps. The goal is better
# profile switching for common apps, not exhaustive OS-wide discovery.
WINDOWS_APP_SPECS = [
    {
        "id": "msedge.exe",
        "label": "Microsoft Edge",
        "legacy_icon": "",
        "executables": ["msedge.exe"],
        "aliases": ["Microsoft Edge", "Edge"],
        "display_names": ["Microsoft Edge"],
        "path_hints": [
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        ],
    },
    {
        "id": "chrome.exe",
        "label": "Google Chrome",
        "legacy_icon": "chrom.png",
        "executables": ["chrome.exe"],
        "aliases": ["Google Chrome", "Chrome"],
        "display_names": ["Google Chrome"],
        "path_hints": [
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ],
    },
    {
        "id": "firefox.exe",
        "label": "Firefox",
        "legacy_icon": "",
        "executables": ["firefox.exe"],
        "aliases": ["Mozilla Firefox", "Firefox"],
        "display_names": ["Mozilla Firefox", "Firefox"],
        "path_hints": [
            r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
            r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
        ],
    },
    {
        "id": "Code.exe",
        "label": "Visual Studio Code",
        "legacy_icon": "VSCODE.png",
        "executables": ["Code.exe"],
        "aliases": ["Visual Studio Code", "VS Code", "Code"],
        "display_names": ["Microsoft Visual Studio Code", "Visual Studio Code"],
        "path_hints": [
            r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
            r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
        ],
    },
    {
        "id": "Cursor.exe",
        "label": "Cursor",
        "legacy_icon": "",
        "executables": ["Cursor.exe"],
        "aliases": ["Cursor"],
        "display_names": ["Cursor"],
        "path_hints": [
            r"%LocalAppData%\Programs\Cursor\Cursor.exe",
        ],
    },
    {
        "id": "Adobe Premiere Pro.exe",
        "label": "Adobe Premiere Pro",
        "legacy_icon": "",
        "executables": ["Adobe Premiere Pro.exe"],
        "aliases": ["Premiere Pro", "Adobe Premiere Pro"],
        "display_names": ["Adobe Premiere Pro"],
        "path_hints": [
            r"%ProgramFiles%\Adobe\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe",
            r"%ProgramFiles%\Adobe\Adobe Premiere Pro 2025\Adobe Premiere Pro.exe",
            r"%ProgramFiles%\Adobe\Adobe Premiere Pro 2024\Adobe Premiere Pro.exe",
            r"%ProgramFiles%\Adobe\Adobe Premiere Pro 2023\Adobe Premiere Pro.exe",
        ],
    },
    {
        "id": "AfterFX.exe",
        "label": "Adobe After Effects",
        "legacy_icon": "",
        "executables": ["AfterFX.exe"],
        "aliases": ["After Effects", "Adobe After Effects"],
        "display_names": ["Adobe After Effects"],
        "path_hints": [
            r"%ProgramFiles%\Adobe\Adobe After Effects 2026\Support Files\AfterFX.exe",
            r"%ProgramFiles%\Adobe\Adobe After Effects 2025\Support Files\AfterFX.exe",
            r"%ProgramFiles%\Adobe\Adobe After Effects 2024\Support Files\AfterFX.exe",
            r"%ProgramFiles%\Adobe\Adobe After Effects 2023\Support Files\AfterFX.exe",
        ],
    },
    {
        "id": "Photoshop.exe",
        "label": "Adobe Photoshop",
        "legacy_icon": "",
        "executables": ["Photoshop.exe"],
        "aliases": ["Photoshop", "Adobe Photoshop"],
        "display_names": ["Adobe Photoshop"],
        "path_hints": [
            r"%ProgramFiles%\Adobe\Adobe Photoshop 2026\Photoshop.exe",
            r"%ProgramFiles%\Adobe\Adobe Photoshop 2025\Photoshop.exe",
            r"%ProgramFiles%\Adobe\Adobe Photoshop 2024\Photoshop.exe",
            r"%ProgramFiles%\Adobe\Adobe Photoshop 2023\Photoshop.exe",
        ],
    },
    {
        "id": "Illustrator.exe",
        "label": "Adobe Illustrator",
        "legacy_icon": "",
        "executables": ["Illustrator.exe"],
        "aliases": ["Illustrator", "Adobe Illustrator"],
        "display_names": ["Adobe Illustrator"],
        "path_hints": [
            r"%ProgramFiles%\Adobe\Adobe Illustrator 2026\Support Files\Contents\Windows\Illustrator.exe",
            r"%ProgramFiles%\Adobe\Adobe Illustrator 2025\Support Files\Contents\Windows\Illustrator.exe",
            r"%ProgramFiles%\Adobe\Adobe Illustrator 2024\Support Files\Contents\Windows\Illustrator.exe",
            r"%ProgramFiles%\Adobe\Adobe Illustrator 2023\Support Files\Contents\Windows\Illustrator.exe",
        ],
    },
    {
        "id": "slack.exe",
        "label": "Slack",
        "legacy_icon": "",
        "executables": ["slack.exe"],
        "aliases": ["Slack"],
        "display_names": ["Slack"],
        "path_hints": [
            r"%LocalAppData%\slack\slack.exe",
            r"%ProgramFiles%\Slack\slack.exe",
        ],
    },
    {
        "id": "Discord.exe",
        "label": "Discord",
        "legacy_icon": "",
        "executables": ["Discord.exe"],
        "aliases": ["Discord"],
        "display_names": ["Discord"],
        "path_hints": [
            r"%LocalAppData%\Discord\Update.exe",
            r"%LocalAppData%\Discord\app-*\Discord.exe",
        ],
    },
    {
        "id": "Spotify.exe",
        "label": "Spotify",
        "legacy_icon": "",
        "executables": ["Spotify.exe"],
        "aliases": ["Spotify"],
        "display_names": ["Spotify"],
        "path_hints": [
            r"%AppData%\Spotify\Spotify.exe",
            r"%LocalAppData%\Microsoft\WindowsApps\Spotify.exe",
        ],
    },
    {
        "id": "vlc.exe",
        "label": "VLC Media Player",
        "legacy_icon": "VLC.png",
        "executables": ["vlc.exe"],
        "aliases": ["VLC", "VLC Media Player"],
        "display_names": ["VLC media player", "VLC Media Player"],
        "path_hints": [
            r"%ProgramFiles%\VideoLAN\VLC\vlc.exe",
            r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe",
        ],
    },
    {
        "id": "Microsoft.Media.Player.exe",
        "label": "Windows Media Player",
        "legacy_icon": "media.webp",
        "executables": ["Microsoft.Media.Player.exe", "wmplayer.exe"],
        "aliases": ["Windows Media Player", "Media Player"],
        "display_names": ["Windows Media Player", "Media Player"],
        "path_hints": [
            r"%ProgramFiles%\Windows Media Player\wmplayer.exe",
            r"%ProgramFiles(x86)%\Windows Media Player\wmplayer.exe",
        ],
    },
    {
        "id": "WindowsTerminal.exe",
        "label": "Windows Terminal",
        "legacy_icon": "",
        "executables": ["WindowsTerminal.exe", "wt.exe"],
        "aliases": ["Windows Terminal", "wt"],
        "display_names": ["Windows Terminal"],
        "path_hints": [
            r"%LocalAppData%\Microsoft\WindowsApps\wt.exe",
            r"%LocalAppData%\Microsoft\WindowsApps\WindowsTerminal.exe",
        ],
    },
    {
        "id": "explorer.exe",
        "label": "File Explorer",
        "legacy_icon": "",
        "executables": ["explorer.exe"],
        "aliases": ["File Explorer", "Explorer"],
        "display_names": ["File Explorer"],
        "path_hints": [
            r"%WINDIR%\explorer.exe",
        ],
    },
    {
        "id": "cmd.exe",
        "label": "Command Prompt",
        "legacy_icon": "",
        "executables": ["cmd.exe"],
        "aliases": ["Command Prompt", "cmd"],
        "display_names": ["Command Prompt"],
        "path_hints": [
            r"%WINDIR%\System32\cmd.exe",
        ],
    },
    {
        "id": "powershell.exe",
        "label": "Windows PowerShell",
        "legacy_icon": "",
        "executables": ["powershell.exe"],
        "aliases": ["Windows PowerShell", "PowerShell"],
        "display_names": ["Windows PowerShell"],
        "path_hints": [
            r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe",
        ],
    },
    {
        "id": "pwsh.exe",
        "label": "PowerShell",
        "legacy_icon": "",
        "executables": ["pwsh.exe"],
        "aliases": ["PowerShell 7", "PowerShell"],
        "display_names": ["PowerShell", "PowerShell 7"],
        "path_hints": [
            r"%ProgramFiles%\PowerShell\7\pwsh.exe",
            r"%ProgramFiles(x86)%\PowerShell\7\pwsh.exe",
        ],
    },
]

MAC_APP_SPECS = [
    {
        "id": "com.apple.Safari",
        "label": "Safari",
        "legacy_icon": "",
        "aliases": ["Safari"],
        "bundle_ids": ["com.apple.Safari"],
        "executables": ["Safari"],
    },
    {
        "id": "com.google.Chrome",
        "label": "Google Chrome",
        "legacy_icon": "chrom.png",
        "aliases": ["Google Chrome", "Chrome"],
        "bundle_ids": ["com.google.Chrome"],
        "executables": ["Google Chrome"],
    },
    {
        "id": "org.videolan.vlc",
        "label": "VLC Media Player",
        "legacy_icon": "VLC.png",
        "aliases": ["VLC", "VLC Media Player"],
        "bundle_ids": ["org.videolan.vlc"],
        "executables": ["VLC"],
    },
    {
        "id": "com.microsoft.VSCode",
        "label": "Visual Studio Code",
        "legacy_icon": "VSCODE.png",
        "aliases": ["Visual Studio Code", "VS Code", "Code"],
        "bundle_ids": ["com.microsoft.VSCode"],
        "executables": ["Code"],
    },
    {
        "id": "com.apple.finder",
        "label": "Finder",
        "legacy_icon": "",
        "aliases": ["Finder"],
        "bundle_ids": ["com.apple.finder"],
        "executables": ["Finder"],
    },
]

ALL_APP_SPECS = WINDOWS_APP_SPECS + MAC_APP_SPECS
WINDOWS_UNINSTALL_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]

_CATALOG_LOCK = threading.Lock()
_CATALOG_CACHE: list[dict] | None = None


def _dedupe_keep_order(values):
    result = []
    seen = set()
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _entry_sort_key(entry: dict):
    return (entry.get("label", "").casefold(), entry.get("id", "").casefold())


def _spec_aliases(spec: dict):
    return _dedupe_keep_order(
        [
            spec["id"],
            spec["label"],
            *spec.get("aliases", []),
            *spec.get("executables", []),
            *spec.get("bundle_ids", []),
        ]
    )


def _build_hint_map(specs):
    hints = {}
    for spec in specs:
        hint = {
            "id": spec["id"],
            "label": spec["label"],
            "legacy_icon": spec.get("legacy_icon", ""),
            "aliases": _spec_aliases(spec),
        }
        for key in hint["aliases"]:
            hints[key] = hint
    return hints, {key.casefold(): value for key, value in hints.items()}

WINDOWS_APP_HINTS, _WINDOWS_APP_HINTS_CASEFOLD = _build_hint_map(WINDOWS_APP_SPECS)
MAC_APP_HINTS, _MAC_APP_HINTS_CASEFOLD = _build_hint_map(MAC_APP_SPECS)
APP_HINTS = {**WINDOWS_APP_HINTS, **MAC_APP_HINTS}


def _hint_for(spec: str):
    if not spec:
        return None
    key = spec.casefold()
    if sys.platform == "win32":
        return _WINDOWS_APP_HINTS_CASEFOLD.get(key) or _MAC_APP_HINTS_CASEFOLD.get(key)
    if sys.platform == "darwin":
        return _MAC_APP_HINTS_CASEFOLD.get(key) or _WINDOWS_APP_HINTS_CASEFOLD.get(key)
    return APP_HINTS.get(spec) or _WINDOWS_APP_HINTS_CASEFOLD.get(key) or _MAC_APP_HINTS_CASEFOLD.get(key)


def _make_entry(app_id: str, label: str, *, path: str = "", aliases=None, legacy_icon: str = ""):
    if path:
        normalized_path = os.path.realpath(path) if sys.platform == "linux" else os.path.abspath(path)
    else:
        normalized_path = ""
    alias_values = list(aliases or [])
    alias_values.extend([app_id, label])
    if normalized_path:
        alias_values.extend(
            [
                normalized_path,
                os.path.basename(normalized_path),
                Path(normalized_path).stem,
            ]
        )
    return {
        "id": app_id,
        "label": label,
        "path": normalized_path,
        "aliases": _dedupe_keep_order(alias_values),
        "legacy_icon": legacy_icon,
    }


def _entry_from_spec(spec: dict, path: str = ""):
    return _make_entry(
        spec["id"],
        spec["label"],
        path=path,
        aliases=_spec_aliases(spec),
        legacy_icon=spec.get("legacy_icon", ""),
    )


def _merge_entry(entry: dict, existing: dict | None):
    if existing is None:
        return entry

    merged = dict(existing)
    merged["label"] = existing.get("label") or entry.get("label") or entry["id"]
    merged["path"] = existing.get("path") or entry.get("path") or ""
    merged["legacy_icon"] = (
        existing.get("legacy_icon") or entry.get("legacy_icon") or ""
    )
    merged["aliases"] = _dedupe_keep_order(
        list(existing.get("aliases", [])) + list(entry.get("aliases", []))
    )
    return merged


def _mac_app_dirs():
    return [
        "/Applications",
        "/System/Applications",
        "/System/Applications/Utilities",
        "/System/Library/CoreServices",
        "/Applications/Utilities",
        os.path.expanduser("~/Applications"),
    ]


def _iter_mac_app_bundles():
    seen = set()
    for root in _mac_app_dirs():
        if not os.path.isdir(root):
            continue

        for current_root, dirnames, _filenames in os.walk(root):
            dirnames.sort(key=str.casefold)
            app_dirs = [name for name in dirnames if name.endswith(".app")]
            for app_name in app_dirs:
                app_path = os.path.join(current_root, app_name)
                normalized = os.path.abspath(app_path)
                if normalized in seen:
                    continue
                seen.add(normalized)
                yield normalized

            dirnames[:] = [name for name in dirnames if not name.endswith(".app")]


def _read_mac_bundle_info(app_path: str) -> dict:
    info_path = os.path.join(app_path, "Contents", "Info.plist")
    if not os.path.exists(info_path):
        return {}
    try:
        with open(info_path, "rb") as handle:
            return plistlib.load(handle)
    except Exception:
        return {}


def _discover_macos_apps():
    entries = {}

    for app_path in _iter_mac_app_bundles():
        info = _read_mac_bundle_info(app_path)
        bundle_id = info.get("CFBundleIdentifier")
        executable = info.get("CFBundleExecutable")
        label = (
            info.get("CFBundleDisplayName")
            or info.get("CFBundleName")
            or Path(app_path).stem
        )
        hint = _hint_for(bundle_id or "") or _hint_for(executable or "")
        app_id = (hint or {}).get("id") or bundle_id or executable or Path(app_path).stem
        if not app_id:
            continue

        aliases = [Path(app_path).stem, f"{Path(app_path).stem}.app"]
        if executable:
            aliases.append(executable)
        if hint:
            aliases.extend(hint.get("aliases", []))

        entry = _make_entry(
            app_id,
            hint.get("label") if hint else label,
            path=app_path,
            aliases=aliases,
            legacy_icon=(hint or {}).get("legacy_icon", ""),
        )
        entries[app_id.casefold()] = _merge_entry(entry, entries.get(app_id.casefold()))

    for spec in MAC_APP_SPECS:
        entries[spec["id"].casefold()] = _merge_entry(
            _entry_from_spec(spec),
            entries.get(spec["id"].casefold()),
        )

    return sorted(entries.values(), key=_entry_sort_key)


def _expand_windows_path_hint(path_hint: str):
    expanded = os.path.expandvars(path_hint)
    if "*" in expanded:
        import glob

        matches = sorted(glob.glob(expanded))
        return os.path.abspath(matches[-1]) if matches else ""
    return os.path.abspath(expanded)


def _path_if_usable(path: str):
    if not path:
        return ""
    normalized = os.path.realpath(path) if sys.platform == "linux" else os.path.abspath(path)
    return normalized if os.path.exists(normalized) else ""


def _read_reg_str(key, name: str):
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return value if isinstance(value, str) else ""


def _clean_windows_icon_path(value: str):
    raw = (value or "").strip().strip('"')
    if not raw:
        return ""
    lower = raw.lower()
    exe_index = lower.find(".exe")
    if exe_index != -1:
        return os.path.abspath(raw[: exe_index + 4].strip().strip('"'))
    return ""


def _normalized_windows_name(value: str):
    return " ".join((value or "").casefold().replace("-", " ").split())


def _windows_name_has_helper_terms(value: str):
    lowered = _normalized_windows_name(value)
    helper_terms = (
        "runtime",
        "webview2",
        "installer",
        "updater",
        "update",
        "helper",
        "service",
    )
    return any(term in lowered for term in helper_terms)


def _iter_windows_uninstall_entries():
    if winreg is None:
        return []

    entries = []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    for root in roots:
        for subkey_path in WINDOWS_UNINSTALL_KEYS:
            try:
                parent = winreg.OpenKey(root, subkey_path)
            except OSError:
                continue

            with parent:
                subkey_count, _value_count, _modified = winreg.QueryInfoKey(parent)
                for index in range(subkey_count):
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        child = winreg.OpenKey(parent, child_name)
                    except OSError:
                        continue

                    with child:
                        display_name = _read_reg_str(child, "DisplayName")
                        display_icon = _clean_windows_icon_path(_read_reg_str(child, "DisplayIcon"))
                        install_location = _read_reg_str(child, "InstallLocation")
                        if not any([display_name, display_icon, install_location]):
                            continue
                        entries.append(
                            {
                                "display_name": display_name,
                                "display_icon": display_icon,
                                "install_location": install_location,
                            }
                        )
    return entries


def _windows_registry_match_score(spec: dict, entry: dict):
    display_name_raw = entry.get("display_name", "")
    display_name = _normalized_windows_name(display_name_raw)
    display_icon = entry.get("display_icon", "")
    install_location = entry.get("install_location", "")
    executables = {exe.casefold() for exe in spec.get("executables", [])}
    names = [
        _normalized_windows_name(name)
        for name in [spec["label"], *spec.get("display_names", []), *spec.get("aliases", [])]
        if name
    ]

    if display_icon and os.path.basename(display_icon).casefold() in executables:
        return 0
    if install_location:
        install_lower = install_location.casefold()
        if any(exe in install_lower for exe in executables):
            return 1

    if any(name in display_name for name in names if name):
        if _windows_name_has_helper_terms(display_name_raw):
            return -1
        if any(display_name == name for name in names):
            return 2
        if any(display_name.startswith(name + " (") for name in names):
            return 3
        if any(display_name.startswith(name + " ") for name in names):
            return 4

    return -1


def _windows_registry_matches(spec: dict, entry: dict):
    return _windows_registry_match_score(spec, entry) >= 0


def _windows_registry_path(spec: dict, registry_entries):
    executables = spec.get("executables", [])
    executable_names = {exe.casefold() for exe in executables}
    best_score = None
    best_path = ""
    for entry in registry_entries:
        score = _windows_registry_match_score(spec, entry)
        if score < 0:
            continue

        display_icon = entry.get("display_icon", "")
        if display_icon and os.path.basename(display_icon).casefold() in executable_names:
            candidate = os.path.abspath(display_icon)
            if best_score is None or score < best_score:
                best_score = score
                best_path = candidate
            continue

        install_location = entry.get("install_location", "")
        for executable in executables:
            candidate = os.path.join(install_location, executable)
            usable = _path_if_usable(candidate)
            if usable and (best_score is None or score < best_score):
                best_score = score
                best_path = usable

    return best_path


def _discover_windows_apps():
    registry_entries = _iter_windows_uninstall_entries()
    entries = []

    for spec in WINDOWS_APP_SPECS:
        path = ""
        for path_hint in spec.get("path_hints", []):
            path = _path_if_usable(_expand_windows_path_hint(path_hint))
            if path:
                break
        if not path:
            path = _windows_registry_path(spec, registry_entries)

        if path or any(_windows_registry_matches(spec, entry) for entry in registry_entries):
            entries.append(_entry_from_spec(spec, path=path))

    return sorted(entries, key=_entry_sort_key)


def _linux_app_dirs():
    data_home = os.environ.get(
        "XDG_DATA_HOME",
        os.path.join(os.path.expanduser("~"), ".local", "share"),
    )
    return [
        os.path.join(data_home, "applications"),
        os.path.join(os.path.expanduser("~"), ".local", "share", "flatpak", "exports", "share", "applications"),
        "/var/lib/flatpak/exports/share/applications",
        "/usr/local/share/applications",
        "/usr/share/applications",
    ]


def _iter_linux_desktop_files():
    seen = set()
    for root in _linux_app_dirs():
        if not os.path.isdir(root):
            continue
        for current_root, dirnames, filenames in os.walk(root):
            dirnames.sort(key=str.casefold)
            for filename in sorted(filenames, key=str.casefold):
                if not filename.endswith(".desktop"):
                    continue
                desktop_path = os.path.realpath(os.path.join(current_root, filename))
                if desktop_path in seen:
                    continue
                seen.add(desktop_path)
                yield desktop_path


def _extract_linux_exec_command(exec_value: str):
    if not exec_value:
        return ""
    try:
        tokens = shlex.split(exec_value, posix=True)
    except ValueError:
        tokens = exec_value.split()
    if not tokens:
        return ""

    index = 0
    if os.path.basename(tokens[0]) == "env":
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token.startswith("%") or "=" not in token:
                break
            index += 1

    while index < len(tokens):
        token = tokens[index]
        if token.startswith("%"):
            index += 1
            continue
        return token
    return ""


def _resolve_linux_exec_path(exec_value: str, try_exec: str = ""):
    command = (try_exec or "").strip() or _extract_linux_exec_command(exec_value)
    if not command:
        return ""

    expanded = os.path.expanduser(os.path.expandvars(command))
    if os.path.isabs(expanded):
        return _path_if_usable(expanded)

    resolved = shutil.which(expanded)
    return _path_if_usable(resolved)


def _read_linux_desktop_entry(desktop_path: str):
    try:
        lines = Path(desktop_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    in_desktop_entry = False
    fields = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_desktop_entry = (line == "[Desktop Entry]")
            continue
        if not in_desktop_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields.setdefault(key, value.strip())

    if fields.get("Type", "Application") != "Application":
        return None
    if fields.get("Hidden", "").lower() == "true":
        return None
    if fields.get("NoDisplay", "").lower() == "true":
        return None

    exec_path = _resolve_linux_exec_path(fields.get("Exec", ""), fields.get("TryExec", ""))
    if not exec_path:
        return None

    label = fields.get("Name") or Path(desktop_path).stem
    desktop_id = Path(desktop_path).name
    hint = (
        _hint_for(fields.get("StartupWMClass", ""))
        or _hint_for(os.path.basename(exec_path))
        or _hint_for(label)
    )
    aliases = [
        desktop_id,
        Path(desktop_path).stem,
        label,
        os.path.basename(exec_path),
        Path(exec_path).stem,
    ]
    startup_wm_class = fields.get("StartupWMClass", "")
    if startup_wm_class:
        aliases.append(startup_wm_class)
    if hint:
        aliases.extend(hint.get("aliases", []))

    return _make_entry(
        (hint or {}).get("id") or desktop_id,
        (hint or {}).get("label") or label,
        path=exec_path,
        aliases=aliases,
        legacy_icon=(hint or {}).get("legacy_icon", ""),
    )


def _discover_linux_apps():
    entries = {}
    for desktop_path in _iter_linux_desktop_files():
        entry = _read_linux_desktop_entry(desktop_path)
        if not entry:
            continue
        entries[entry["id"].casefold()] = _merge_entry(
            entry,
            entries.get(entry["id"].casefold()),
        )
    return sorted(entries.values(), key=_entry_sort_key)


def _build_catalog():
    if sys.platform == "darwin":
        return _discover_macos_apps()
    if sys.platform == "win32":
        return _discover_windows_apps()
    if sys.platform == "linux":
        return _discover_linux_apps()
    return []


def get_app_catalog(refresh: bool = False):
    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        if refresh or _CATALOG_CACHE is None:
            _CATALOG_CACHE = _build_catalog()
        return [dict(entry) for entry in _CATALOG_CACHE]


def _find_catalog_entry(spec: str):
    if not spec:
        return None

    key = spec.casefold()
    for entry in get_app_catalog():
        if entry["id"].casefold() == key:
            return entry
        for alias in entry.get("aliases", []):
            if alias.casefold() == key:
                return entry
    return None


def _linux_catalog_path_tokens(path: str):
    normalized = os.path.realpath(path)
    basename = os.path.basename(normalized)
    stem = Path(normalized).stem
    return normalized, basename, stem


def _linux_catalog_entry_for_path(path: str):
    normalized, basename, stem = _linux_catalog_path_tokens(path)
    entries = get_app_catalog()

    def matches_for(value: str):
        key = value.casefold()
        return [
            entry for entry in entries
            if key == entry["id"].casefold()
            or any(alias.casefold() == key for alias in entry.get("aliases", []))
        ]

    exact_matches = matches_for(normalized)
    if exact_matches:
        return exact_matches[0]

    basename_matches = matches_for(basename)
    if len(basename_matches) == 1:
        return basename_matches[0]

    stem_matches = matches_for(stem)
    if len(stem_matches) == 1:
        return stem_matches[0]

    return None


def _linux_catalog_matched_entry(catalog_entry: dict, observed_path: str):
    normalized, basename, stem = _linux_catalog_path_tokens(observed_path)
    aliases = list(catalog_entry.get("aliases", []))
    aliases.extend([normalized, basename, stem])
    return _make_entry(
        catalog_entry["id"],
        catalog_entry.get("label", catalog_entry["id"]),
        path=catalog_entry.get("path") or observed_path,
        aliases=aliases,
        legacy_icon=catalog_entry.get("legacy_icon", ""),
    )


def _resolve_path_entry(path: str):
    if not path:
        return None

    normalized = os.path.realpath(path) if sys.platform == "linux" else os.path.abspath(path)
    path_exists = os.path.exists(normalized)

    if sys.platform == "linux" and path_exists:
        catalog_entry = _linux_catalog_entry_for_path(normalized)
        if catalog_entry:
            return _linux_catalog_matched_entry(catalog_entry, normalized)

    if sys.platform == "darwin" and normalized.endswith(".app"):
        if not path_exists:
            return None
        info = _read_mac_bundle_info(normalized)
        executable = info.get("CFBundleExecutable")
        bundle_id = info.get("CFBundleIdentifier")
        label = (
            info.get("CFBundleDisplayName")
            or info.get("CFBundleName")
            or Path(normalized).stem
        )
        hint = _hint_for(bundle_id or "") or _hint_for(executable or "")
        aliases = [Path(normalized).stem, f"{Path(normalized).stem}.app"]
        if executable:
            aliases.append(executable)
        if hint:
            aliases.extend(hint.get("aliases", []))
        return _make_entry(
            (hint or {}).get("id") or bundle_id or executable or Path(normalized).stem,
            (hint or {}).get("label") or label,
            path=normalized,
            aliases=aliases,
            legacy_icon=(hint or {}).get("legacy_icon", ""),
        )

    if normalized.lower().endswith(".exe"):
        exe_name = os.path.basename(normalized)
        hint = _hint_for(exe_name)
        aliases = [exe_name, Path(normalized).stem]
        if hint:
            aliases.extend(hint.get("aliases", []))
        return _make_entry(
            (hint or {}).get("id") or exe_name,
            (hint or {}).get("label") or Path(normalized).stem,
            path=normalized,
            aliases=aliases,
            legacy_icon=(hint or {}).get("legacy_icon", ""),
        )

    if path_exists:
        return _make_entry(Path(normalized).name, Path(normalized).stem, path=normalized)

    return None


def resolve_app_spec(spec: str):
    """
    Resolve an app identifier, alias, or path into a catalog entry.

    Returns a dict with keys: id, label, path, aliases, legacy_icon.
    """
    if not spec:
        return None

    if os.path.isabs(spec) or os.path.exists(spec):
        entry = _resolve_path_entry(spec)
        if entry:
            return entry

    entry = _find_catalog_entry(spec)
    if entry:
        return entry

    hint = _hint_for(spec)
    if hint:
        return _make_entry(
            hint["id"],
            hint["label"],
            aliases=hint.get("aliases", []),
            legacy_icon=hint.get("legacy_icon", ""),
        )

    return _make_entry(spec, spec, aliases=[])


def get_app_aliases(spec: str):
    entry = resolve_app_spec(spec)
    if not entry:
        return []
    return _dedupe_keep_order([entry["id"], *entry.get("aliases", [])])


def get_app_label(spec: str):
    entry = resolve_app_spec(spec)
    return entry.get("label", spec) if entry else spec


def get_legacy_icon(spec: str):
    entry = resolve_app_spec(spec)
    return entry.get("legacy_icon", "") if entry else ""
