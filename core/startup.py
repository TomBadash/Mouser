"""Cross-platform login startup: Windows HKCU Run, macOS LaunchAgent, Linux autostart."""

import os
import plistlib
import shlex
import subprocess
import sys

# Windows
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Mouser"

# macOS
MACOS_LAUNCH_AGENT_LABEL = "io.github.tombadash.mouser"
MACOS_PLIST_NAME = f"{MACOS_LAUNCH_AGENT_LABEL}.plist"

# Linux
LINUX_AUTOSTART_NAME = "io.github.tombadash.mouser.desktop"


def supports_login_startup():
    return sys.platform in ("win32", "darwin", "linux")


def _quote_arg(s: str) -> str:
    if not s:
        return '""'
    if " " in s or "\t" in s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def build_run_command() -> str:
    """Windows: command line stored in the HKCU Run value."""
    exe = os.path.abspath(sys.executable)
    exe_q = _quote_arg(exe)
    if getattr(sys, "frozen", False):
        return exe_q
    script = _entry_script_path()
    return f"{exe_q} {_quote_arg(script)}"


def _program_arguments():
    """Argv list for macOS LaunchAgent ProgramArguments."""
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return [exe]
    return [exe, _entry_script_path()]


def _entry_script_path() -> str:
    raw_argv0 = (sys.argv[0] or "").strip()
    argv0 = os.path.abspath(raw_argv0)
    if raw_argv0 and os.path.basename(raw_argv0) not in {"-", "-c"}:
        return argv0
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main_qml.py"))


def _linux_autostart_dir() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_home, "autostart")


def _linux_desktop_path() -> str:
    return os.path.join(_linux_autostart_dir(), LINUX_AUTOSTART_NAME)


def _linux_exec_line() -> str:
    return " ".join(shlex.quote(arg) for arg in _program_arguments())


def _linux_desktop_entry() -> str:
    icon_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "images", "logo_icon.png")
    )
    working_dir = os.path.dirname(os.path.abspath(sys.argv[0])) or os.getcwd()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=Mouser",
        "Comment=Logitech mouse remapper",
        f"Exec={_linux_exec_line()}",
        f"Path={working_dir}",
        f"Icon={icon_path}",
        "Terminal=false",
        "StartupNotify=false",
        "Categories=Utility;",
        "X-GNOME-Autostart-enabled=true",
        "",
    ]
    return "\n".join(lines)


def _get_winreg():
    import winreg

    return winreg


def _apply_windows(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    winreg = _get_winreg()
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(
                key, RUN_VALUE_NAME, 0, winreg.REG_SZ, build_run_command()
            )
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _macos_plist_path() -> str:
    return os.path.expanduser(
        os.path.join("~/Library/LaunchAgents", MACOS_PLIST_NAME)
    )


def _launchctl_run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
    )


def _apply_macos(enabled: bool) -> None:
    if sys.platform != "darwin":
        return
    plist_path = _macos_plist_path()
    launch_agents_dir = os.path.dirname(plist_path)
    uid = os.getuid()
    domain = f"gui/{uid}"

    if enabled:
        os.makedirs(launch_agents_dir, exist_ok=True)
        if os.path.isfile(plist_path):
            _launchctl_run(["launchctl", "bootout", domain, plist_path])
        payload = {
            "Label": MACOS_LAUNCH_AGENT_LABEL,
            "ProgramArguments": _program_arguments(),
            "RunAtLoad": True,
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(payload, f, fmt=plistlib.FMT_XML)
        result = _launchctl_run(["launchctl", "bootstrap", domain, plist_path])
        if result.returncode != 0:
            print(
                f"[startup] launchctl bootstrap failed: {result.stderr.strip()}",
                file=sys.stderr,
            )
    else:
        if os.path.isfile(plist_path):
            _launchctl_run(["launchctl", "bootout", domain, plist_path])
            try:
                os.remove(plist_path)
            except OSError:
                pass
        else:
            _launchctl_run(
                ["launchctl", "bootout", domain, MACOS_LAUNCH_AGENT_LABEL]
            )


def _apply_linux(enabled: bool) -> None:
    if sys.platform != "linux":
        return
    desktop_path = _linux_desktop_path()
    if enabled:
        os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(_linux_desktop_entry())
        return
    try:
        os.remove(desktop_path)
    except FileNotFoundError:
        pass


def apply_login_startup(enabled: bool) -> None:
    if not supports_login_startup():
        return
    if sys.platform == "win32":
        _apply_windows(enabled)
    elif sys.platform == "darwin":
        _apply_macos(enabled)
    elif sys.platform == "linux":
        _apply_linux(enabled)


def sync_from_config(enabled: bool) -> None:
    """Ensure OS login startup matches config."""
    apply_login_startup(enabled)
