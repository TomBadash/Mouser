"""Cross-platform login startup helpers for Windows, macOS, and Linux."""

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

# Linux
LINUX_DESKTOP_ENTRY_NAME = "io.github.tombadash.mouser.desktop"
LINUX_DESKTOP_TEMPLATE_NAME = f"{LINUX_DESKTOP_ENTRY_NAME}.in"
LINUX_AUTOSTART_DELAY_SECONDS = 15
APP_DISPLAY_NAME = "Mouser"


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
    script = os.path.abspath(sys.argv[0])
    return f"{exe_q} {_quote_arg(script)}"


def _program_arguments():
    """Argv list for macOS LaunchAgent ProgramArguments."""
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return [exe]
    return [exe, os.path.abspath(sys.argv[0])]


def _runtime_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    script_path = os.path.abspath(sys.argv[0]) if sys.argv else os.path.abspath(__file__)
    return os.path.dirname(script_path)


def _source_checkout_python() -> str | None:
    root_dir = _runtime_root_dir()
    if sys.platform == "win32":
        candidate = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
    else:
        candidate = os.path.join(root_dir, ".venv", "bin", "python")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


def _desktop_exec_parts(*, force_show: bool = False):
    if getattr(sys, "frozen", False):
        args = [os.path.abspath(sys.executable)]
        if force_show:
            args.append("--show-window")
        return args
    script_path = os.path.abspath(sys.argv[0]) if sys.argv else os.path.abspath(__file__)
    exe = _source_checkout_python() or os.path.abspath(sys.executable)
    args = [exe, script_path]
    if force_show:
        args.append("--show-window")
    return args


def _desktop_exec_arg(arg: str) -> str:
    if not arg:
        return '""'
    if all(ch not in arg for ch in ' \t\n"\\`$'):
        return arg
    escaped = (
        arg.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _desktop_exec_string(args: list[str]) -> str:
    return " ".join(_desktop_exec_arg(arg) for arg in args)


def _repo_root_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _linux_template_path() -> str:
    candidates = []
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            candidates.append(os.path.join(bundle_root, "linux", LINUX_DESKTOP_TEMPLATE_NAME))
        candidates.append(
            os.path.join(_runtime_root_dir(), "linux", LINUX_DESKTOP_TEMPLATE_NAME)
        )
    candidates.append(
        os.path.join(
            _repo_root_dir(),
            "packaging",
            "linux",
            LINUX_DESKTOP_TEMPLATE_NAME,
        )
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def _linux_desktop_path() -> str:
    return os.path.expanduser(
        os.path.join("~", ".local", "share", "applications", LINUX_DESKTOP_ENTRY_NAME)
    )


def _linux_autostart_path() -> str:
    return os.path.expanduser(
        os.path.join("~", ".config", "autostart", LINUX_DESKTOP_ENTRY_NAME)
    )


def _linux_icon_path() -> str:
    runtime_icon = os.path.join(_runtime_root_dir(), "images", "logo_icon.png")
    if os.path.isfile(runtime_icon):
        return runtime_icon
    return os.path.join(_repo_root_dir(), "images", "logo_icon.png")


def _linux_source_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    if sys.argv:
        return os.path.abspath(sys.argv[0])
    return os.path.join(_repo_root_dir(), "main_qml.py")


def _linux_template_text() -> str:
    with open(_linux_template_path(), "r", encoding="utf-8") as fh:
        return fh.read()


def _render_linux_desktop_entry(*, autostart: bool) -> str:
    autostart_lines = ""
    if autostart:
        autostart_lines = "\n".join(
            [
                "X-GNOME-Autostart-enabled=true",
                f"X-GNOME-Autostart-Delay={LINUX_AUTOSTART_DELAY_SECONDS}",
                "Hidden=false",
            ]
        )
    entry = _linux_template_text()
    exec_parts = _desktop_exec_parts(force_show=not autostart)
    replacements = {
        "@APP_NAME@": APP_DISPLAY_NAME,
        "@EXEC@": _desktop_exec_string(exec_parts),
        "@TRY_EXEC@": exec_parts[0],
        "@WORKDIR@": _runtime_root_dir(),
        "@ICON@": _linux_icon_path(),
        "@SOURCE_PATH@": _linux_source_path(),
        "@AUTOSTART_LINES@": autostart_lines,
    }
    for placeholder, value in replacements.items():
        entry = entry.replace(placeholder, value)
    return entry.rstrip() + "\n"


def _write_linux_desktop_entry(path: str, *, autostart: bool) -> None:
    entry = _render_linux_desktop_entry(autostart=autostart)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def ensure_linux_launcher() -> str:
    launcher_path = _linux_desktop_path()
    _write_linux_desktop_entry(launcher_path, autostart=False)
    return launcher_path


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
    autostart_path = _linux_autostart_path()
    if enabled:
        ensure_linux_launcher()
        _write_linux_desktop_entry(autostart_path, autostart=True)
        return
    try:
        os.remove(autostart_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[startup] failed to remove Linux autostart entry: {exc}", file=sys.stderr)
    try:
        ensure_linux_launcher()
    except Exception as exc:
        print(f"[startup] failed to refresh Linux launcher on disable: {exc}", file=sys.stderr)


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
