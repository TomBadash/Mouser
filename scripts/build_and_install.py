#!/usr/bin/env python3
"""Build Mouser and install it to the platform default location."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MACOS_APP_NAME = "Mouser.app"
WINDOWS_APP_DIR = "Mouser"
DEFAULT_MACOS_INSTALL_DIR = Path("/Applications")


def fail(message: str, *, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def load_env_local() -> None:
    env_file = ROOT / ".env.local"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def resolve_command(candidate: str) -> Path | None:
    path = Path(candidate)
    if any(sep in candidate for sep in ("/", "\\", os.sep)) or path.suffix:
        if not path.is_file():
            return None
        if sys.platform == "win32":
            return path
        return path if os.access(path, os.X_OK) else None
    resolved = shutil.which(candidate)
    return Path(resolved) if resolved else None


def python_from_env_dir(env_dir: Path) -> Path | None:
    for name in ("python3", "python"):
        candidate = env_dir / "Scripts" / f"{name}.exe"
        if candidate.is_file():
            return candidate
        candidate = env_dir / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def resolve_python() -> tuple[Path, str]:
    override = os.environ.get("MOUSER_PYTHON")
    if override:
        resolved = resolve_command(override)
        if resolved is None:
            fail(f"MOUSER_PYTHON is set but is not executable: {override}")
        return resolved, "MOUSER_PYTHON"

    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        resolved = python_from_env_dir(Path(virtual_env))
        if resolved is None:
            fail(f"VIRTUAL_ENV is set but no executable Python was found in {virtual_env}")
        return resolved, "VIRTUAL_ENV"

    repo_venv = ROOT / ".venv"
    if repo_venv.is_dir():
        resolved = python_from_env_dir(repo_venv)
        if resolved is None:
            fail(
                "Repository .venv exists but no executable Python was found in "
                f"{repo_venv / ('Scripts' if sys.platform == 'win32' else 'bin')}"
            )
        return resolved, "repo .venv"

    for name in ("python3", "python"):
        resolved = resolve_command(name)
        if resolved is not None:
            return resolved, f"PATH {name}"

    fail("No Python interpreter found. Create .venv or set MOUSER_PYTHON.")


def run_command(
    args: list[str | Path],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    display = " ".join(str(arg) for arg in args)
    print(f"+ {display}")
    result = subprocess.run(
        [str(arg) for arg in args],
        cwd=ROOT,
        env=env,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        fail(f"Command failed ({result.returncode}): {display}")
    return result


def require_pyinstaller(python: Path, source: str) -> None:
    probe = subprocess.run(
        [str(python), "-c", "import PyInstaller"],
        cwd=ROOT,
        text=True,
        check=False,
    )
    if probe.returncode == 0:
        return
    fail(
        f"PyInstaller not installed in {python} (source: {source}). "
        f"Install it with: {python} -m pip install -r {ROOT / 'requirements.txt'}"
    )


def log_python_provenance(python: Path, source: str) -> None:
    version = subprocess.check_output(
        [str(python), "-c", "import platform; print(platform.python_version())"],
        cwd=ROOT,
        text=True,
    ).strip()
    machine = subprocess.check_output(
        [str(python), "-c", "import platform; print(platform.machine() or 'unknown')"],
        cwd=ROOT,
        text=True,
    ).strip()
    pyinstaller_version = subprocess.check_output(
        [str(python), "-c", "import PyInstaller; print(PyInstaller.__version__)"],
        cwd=ROOT,
        text=True,
    ).strip()
    print(f"Using Python: {python} (source: {source})")
    print(f"Python version: {version} ({machine})")
    print(f"PyInstaller version: {pyinstaller_version}")


def resolve_install_dir(default: Path | None = None) -> Path:
    override = os.environ.get("MOUSER_INSTALL_DIR")
    if override:
        return Path(override).expanduser()
    if default is not None:
        return default
    if sys.platform == "win32":
        from scripts.windows_install import default_install_root

        return default_install_root()
    fail("No install directory configured for this platform.")


def replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def resolve_macos_sign_identity() -> str:
    configured = os.environ.get("MOUSER_SIGN_IDENTITY")
    if configured:
        return configured

    team_id = os.environ.get("MOUSER_TEAM_ID", "").strip()
    if not team_id:
        fail(
            "Set MOUSER_SIGN_IDENTITY or MOUSER_TEAM_ID for macOS code signing."
        )
    try:
        output = subprocess.check_output(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        fail(
            f"No codesigning identity found for team {team_id}. "
            "Set MOUSER_SIGN_IDENTITY or MOUSER_TEAM_ID."
        )

    for line in output.splitlines():
        if f"({team_id})" not in line:
            continue
        match = re.search(r"\b([A-F0-9]{40})\b", line)
        if match:
            return match.group(1)
        break

    fail(
        f"No codesigning identity found for team {team_id}. "
        "Set MOUSER_SIGN_IDENTITY or MOUSER_TEAM_ID."
    )


def build_and_install_macos() -> None:
    build_output = ROOT / "dist" / MACOS_APP_NAME
    install_dir = resolve_install_dir(DEFAULT_MACOS_INSTALL_DIR)
    install_path = install_dir / MACOS_APP_NAME

    sign_identity = resolve_macos_sign_identity()
    env = os.environ.copy()
    env["MOUSER_SIGN_IDENTITY"] = sign_identity

    print(f"Building signed macOS app (identity: {sign_identity})")
    run_command(["/bin/zsh", ROOT / "build_macos_app.sh"], env=env)

    if not build_output.is_dir():
        fail(f"Build output not found: {build_output}")

    print(f"Installing to {install_path}")
    replace_tree(build_output, install_path)

    if shutil.which("codesign"):
        run_command(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", install_path]
        )

    print(f"Installed: {install_path}")


def build_and_install_windows() -> None:
    from scripts.windows_install import (
        cleanup_all_windows_installs,
        default_install_root,
        finalize_windows_install,
        permission_hint,
        remove_legacy_local_install,
        replace_tree,
        resolve_install_scope,
    )

    print("[*] Cleaning previous Windows installs...")
    cleanup_all_windows_installs()

    build_output = ROOT / "dist" / WINDOWS_APP_DIR
    scope = resolve_install_scope()
    install_path = (
        Path(os.environ["MOUSER_INSTALL_DIR"]).expanduser()
        if os.environ.get("MOUSER_INSTALL_DIR")
        else default_install_root(scope)
    )

    python, source = resolve_python()

    print("[*] Installing requirements...")
    run_command([python, "-m", "pip", "install", "-r", ROOT / "requirements.txt"])

    require_pyinstaller(python, source)
    log_python_provenance(python, source)

    print("[*] Verifying hidapi import...")
    probe = subprocess.run(
        [str(python), "-c", "import hid; print('[*] hidapi:', hid.__file__)"],
        cwd=ROOT,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        fail(
            "hidapi is not importable. The packaged app would not detect Logitech devices."
        )

    if build_output.exists():
        print(f"[*] Removing previous {build_output}...")
        shutil.rmtree(build_output)

    print("[*] Building with PyInstaller...")
    env = os.environ.copy()
    env.setdefault("PYTHONHASHSEED", "0")
    run_command(
        [python, "-m", "PyInstaller", ROOT / "Mouser.spec", "--noconfirm"],
        env=env,
    )

    exe_path = build_output / "Mouser.exe"
    internal_dir = build_output / "_internal"
    if not exe_path.is_file() or not internal_dir.is_dir():
        fail(f"Build output is incomplete: {build_output}")

    print(f"Installing to {install_path} ({scope} scope)")
    try:
        replace_tree(build_output, install_path)
    except PermissionError as exc:
        fail(f"{permission_hint(scope)} ({exc})")

    installed_exe = install_path / "Mouser.exe"
    if not installed_exe.is_file():
        fail(f"Install verification failed: {installed_exe}")

    remove_legacy_local_install(active_scope=scope)
    shell = finalize_windows_install(install_path, scope=scope)

    print(f"Installed: {shell['install_root']}")
    print(f"Start Menu: {shell['start_menu_shortcut']}")
    print(f"Uninstall: {shell['uninstall_script']}")


def main() -> None:
    load_env_local()

    if sys.platform == "darwin":
        build_and_install_macos()
        return
    if sys.platform == "win32":
        build_and_install_windows()
        return

    fail(
        "Unsupported platform for build-and-install. "
        "Use build_macos_app.sh, build.bat, or Mouser-linux.spec on this system."
    )


if __name__ == "__main__":
    main()
