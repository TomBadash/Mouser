"""Register a built Mouser folder as a normal Windows application install."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.update_installer import APP_ID
from core.version import APP_VERSION

WINDOWS_APP_DIR = "Mouser"
UNINSTALL_KEY_NAME = APP_ID
UNINSTALL_SCRIPT_NAME = "Uninstall Mouser.cmd"


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def resolve_install_scope() -> str:
    configured = (os.environ.get("MOUSER_INSTALL_SCOPE") or "").strip().lower()
    if configured:
        if configured not in {"machine", "user"}:
            raise ValueError(
                f"Unsupported MOUSER_INSTALL_SCOPE: {configured!r} "
                "(expected 'machine' or 'user')"
            )
        return configured
    if _can_install_machine():
        return "machine"
    print(
        "[!] Program Files is not writable from this shell; "
        "using per-user install scope."
    )
    print("    Re-run as administrator for a machine-wide install.")
    return "user"


def _can_install_machine() -> bool:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    probe = program_files / ".mouser-install-probe"
    try:
        probe.mkdir(exist_ok=True)
        probe.rmdir()
        return True
    except OSError:
        return False


def _join_win_path(base: str, *parts: str) -> Path:
    """Join Windows install path segments consistently on every platform."""
    return Path(os.path.normpath(os.path.join(base, *parts)))


def default_install_root(scope: str | None = None) -> Path:
    scope = scope or resolve_install_scope()
    if scope == "user":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return _join_win_path(base, "Programs", WINDOWS_APP_DIR)
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return _join_win_path(program_files, WINDOWS_APP_DIR)


def start_menu_dir(scope: str) -> Path:
    if scope == "machine":
        base = os.environ.get("ProgramData", r"C:\ProgramData")
    else:
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def start_menu_shortcut_path(scope: str) -> Path:
    return start_menu_dir(scope) / "Mouser.lnk"


def uninstall_registry_root(scope: str):
    import winreg

    hive = winreg.HKEY_LOCAL_MACHINE if scope == "machine" else winreg.HKEY_CURRENT_USER
    return hive, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{UNINSTALL_KEY_NAME}"


def run_powershell(command: str) -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell command failed ({result.returncode})")


def create_shortcut(shortcut_path: Path, target: Path, working_dir: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{_escape_ps(str(shortcut_path))}'); "
        f"$shortcut.TargetPath = '{_escape_ps(str(target))}'; "
        f"$shortcut.WorkingDirectory = '{_escape_ps(str(working_dir))}'; "
        f"$shortcut.IconLocation = '{_escape_ps(str(target))},0'; "
        "$shortcut.Save()"
    )
    run_powershell(command)


def write_uninstall_script(install_root: Path, scope: str) -> Path:
    script_path = install_root / UNINSTALL_SCRIPT_NAME
    shortcut = start_menu_shortcut_path(scope)
    hive_name = "HKLM" if scope == "machine" else "HKCU"
    content = f"""@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"

del /f /q "{shortcut}" 2>nul
reg delete "{hive_name}\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{UNINSTALL_KEY_NAME}" /f 2>nul

start "" /min cmd /c "ping -n 3 127.0.0.1>nul & rd /s /q \"%ROOT%\""
exit /b 0
"""
    script_path.write_text(content, encoding="utf-8", newline="\r\n")
    return script_path


def register_uninstall_entry(
    install_root: Path,
    *,
    scope: str,
    version: str,
    uninstall_command: Path,
) -> None:
    import winreg

    hive, key_path = uninstall_registry_root(scope)
    exe = install_root / "Mouser.exe"
    with winreg.CreateKey(hive, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Mouser")
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe))
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_root))
        winreg.SetValueEx(
            key,
            "UninstallString",
            0,
            winreg.REG_SZ,
            f'"{uninstall_command}"',
        )
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Tom Badash")
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def finalize_windows_install(install_root: Path, *, scope: str | None = None) -> dict[str, Path]:
    if sys.platform != "win32":
        raise RuntimeError("finalize_windows_install is Windows-only")

    scope = scope or resolve_install_scope()
    install_root = install_root.resolve()
    exe = install_root / "Mouser.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"Missing executable: {exe}")
    if not (install_root / "_internal").is_dir():
        raise FileNotFoundError(f"Missing runtime folder: {install_root / '_internal'}")

    uninstall_script = write_uninstall_script(install_root, scope)
    shortcut_path = start_menu_shortcut_path(scope)
    create_shortcut(shortcut_path, exe, install_root)
    register_uninstall_entry(
        install_root,
        scope=scope,
        version=APP_VERSION,
        uninstall_command=uninstall_script,
    )
    return {
        "install_root": install_root,
        "start_menu_shortcut": shortcut_path,
        "uninstall_script": uninstall_script,
    }


def stop_running_mouser_instances() -> None:
    if sys.platform != "win32":
        return
    result = subprocess.run(
        [
            "taskkill",
            "/IM",
            "Mouser.exe",
            "/F",
            "/T",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print("[*] Stopped running Mouser instance(s) before install")
        time.sleep(1)


def _remove_uninstall_registry(scope: str) -> None:
    if sys.platform != "win32":
        return
    import winreg

    hive, key_path = uninstall_registry_root(scope)
    try:
        winreg.DeleteKey(hive, key_path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _remove_install_tree(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError as exc:
        print(f"[!] Could not remove {path}: {exc}")
        return False


def _remove_staging_artifacts(parent: Path, app_dir: str = WINDOWS_APP_DIR) -> None:
    if not parent.is_dir():
        return
    prefix = f".{app_dir}."
    for entry in parent.iterdir():
        if entry.name.startswith(prefix) and (
            ".staging-" in entry.name or ".backup-" in entry.name
        ):
            _remove_install_tree(entry)


def remove_install_artifacts(scope: str) -> None:
    """Remove one install scope: app folder, Start Menu shortcut, uninstall key."""
    if sys.platform != "win32":
        return
    root = default_install_root(scope)
    shortcut = start_menu_shortcut_path(scope)
    if shortcut.exists():
        shortcut.unlink()
    _remove_uninstall_registry(scope)
    _remove_install_tree(root)
    if scope == "machine":
        _remove_staging_artifacts(Path(os.environ.get("ProgramFiles", r"C:\Program Files")))


def remove_stale_install_artifacts(active_scope: str) -> None:
    """Drop shortcuts/registry/install dirs from every scope except the active one."""
    for scope in ("user", "machine"):
        if scope != active_scope:
            remove_install_artifacts(scope)


def cleanup_all_windows_installs() -> None:
    """Remove every Mouser Windows install artifact (both scopes + staging folders)."""
    if sys.platform != "win32":
        return
    stop_running_mouser_instances()
    for scope in ("user", "machine"):
        remove_install_artifacts(scope)
    _remove_staging_artifacts(Path(os.environ.get("ProgramFiles", r"C:\Program Files")))


def replace_tree(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Build output not found: {source}")

    stop_running_mouser_instances()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _remove_staging_artifacts(destination.parent)

    staging = destination.with_name(f".{destination.name}.staging-{os.getpid()}")
    backup = destination.with_name(f".{destination.name}.backup-{int(time.time())}")

    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(source, staging)

    if destination.exists():
        try:
            if destination.is_dir():
                destination.rename(backup)
            else:
                destination.unlink()
        except OSError:
            shutil.rmtree(destination, ignore_errors=True)

    try:
        staging.rename(destination)
    except OSError as exc:
        raise RuntimeError(
            f"Could not activate install at {destination}. "
            f"A complete copy is at {staging}. Close Mouser and retry."
        ) from exc

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def permission_hint(scope: str) -> str:
    if scope == "machine":
        return (
            "Could not write to Program Files. Re-run the build task in an "
            "elevated terminal (Run as administrator), or set "
            "MOUSER_INSTALL_SCOPE=user for a per-user install."
        )
    return "Could not write to the selected install location."


def remove_legacy_local_install(*, active_scope: str | None = None) -> None:
    """Remove install artifacts from scopes other than the one just installed."""
    scope = active_scope or resolve_install_scope()
    print(f"[*] Removing stale install artifacts (keeping {scope} scope)")
    remove_stale_install_artifacts(scope)
