"""Cross-platform login startup: Windows HKCU Run and macOS LaunchAgent."""

import os
import plistlib
import subprocess
import sys

# Windows
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Mouser"

# macOS
MACOS_LAUNCH_AGENT_LABEL = "io.github.tombadash.mouser"
MACOS_PLIST_NAME = f"{MACOS_LAUNCH_AGENT_LABEL}.plist"


def supports_login_startup():
    return sys.platform in ("win32", "darwin")


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
    script = os.path.abspath(sys.argv[0])
    return f"{exe_q} {_quote_arg(script)}"


def _program_arguments():
    """Argv list for macOS LaunchAgent ProgramArguments."""
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return [exe]
    return [exe, os.path.abspath(sys.argv[0])]


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


def apply_login_startup(enabled: bool) -> None:
    if not supports_login_startup():
        return
    if sys.platform == "win32":
        _apply_windows(enabled)
    elif sys.platform == "darwin":
        _apply_macos(enabled)


def sync_from_config(enabled: bool) -> None:
    """Ensure OS login startup matches config."""
    apply_login_startup(enabled)
