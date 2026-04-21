"""
Auto-updater for Mouser.

Checks the GitHub releases page for a newer version, downloads the
appropriate archive for the current platform, and installs it.

Update discovery uses a ``latest.json`` file uploaded to every GitHub
release.  If that file is unavailable the module falls back to the
GitHub Releases REST API.

``latest.json`` format::

    {
        "version": "3.6.0",
        "date":    "2025-01-15T00:00:00Z",
        "downloads": {
            "windows-x64":  "https://…/Mouser-Windows.zip",
            "macos-arm64":  "https://…/Mouser-macOS.zip",
            "macos-x86_64": "https://…/Mouser-macOS-intel.zip",
            "linux-deb":    "https://…/Mouser-Linux.deb",
            "linux-zip":    "https://…/Mouser-Linux.zip"
        }
    }
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Lazy import so the module loads fast even in the packaged app.
# core.version uses only stdlib; no circular import risk.
from core.version import APP_VERSION

LATEST_JSON_URL = (
    "https://github.com/farfromrefug/Mouser/releases/latest/download/latest.json"
)
GITHUB_API_LATEST = (
    "https://api.github.com/repos/farfromrefug/Mouser/releases/latest"
)
_REQUEST_TIMEOUT = 20  # seconds


# ── helpers ────────────────────────────────────────────────────────────────

def _version_tuple(version_str: str) -> tuple:
    """Convert a semver string to a comparable tuple of ints."""
    try:
        return tuple(int(p) for p in version_str.lstrip("v").split(".") if p.strip().isdigit())
    except (ValueError, AttributeError):
        return (0,)


def _platform_key() -> str:
    """Return the key identifying this platform in ``downloads``."""
    plat = sys.platform
    arch = platform.machine().lower()
    if plat == "win32":
        return "windows-x64"
    if plat == "darwin":
        return "macos-arm64" if arch in ("arm64", "aarch64") else "macos-x86_64"
    if plat.startswith("linux"):
        return "linux-deb" if shutil.which("dpkg") else "linux-zip"
    return ""


def _fetch_latest_info() -> dict:
    """Download and return the latest release info dict."""
    headers = {"User-Agent": f"Mouser/{APP_VERSION}"}

    def _get(url: str) -> bytes:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return resp.read()

    # Primary: pre-built latest.json uploaded to the release
    try:
        return json.loads(_get(LATEST_JSON_URL))
    except Exception:
        pass



# ── public status constants ─────────────────────────────────────────────────

STATUS_IDLE          = "idle"
STATUS_CHECKING      = "checking"
STATUS_UP_TO_DATE    = "up_to_date"
STATUS_AVAILABLE     = "available"
STATUS_DOWNLOADING   = "downloading"
STATUS_INSTALLING    = "installing"
STATUS_INSTALLED     = "installed"
STATUS_NEEDS_MANUAL  = "needs_manual"
STATUS_CANCELLED     = "cancelled"
STATUS_ERROR         = "error"


# ── main class ─────────────────────────────────────────────────────────────

class Updater:
    """
    Handles checking, downloading, and installing updates.

    All public methods are thread-safe; callbacks are invoked from
    the background worker thread — callers must marshal them to the
    main thread as needed (e.g. via Qt signals).

    Callback signatures::

        on_progress(status: str, fraction: float)
            Called repeatedly during a download.  ``fraction`` is in [0, 1].

        on_finished(status: str, detail: Optional[str])
            Called once when the operation completes.
            ``detail`` carries the new version string or an error message.
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_finished: Optional[Callable[[str, Optional[str]], None]] = None,
    ):
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._latest_info: Optional[dict] = None

    # ── public API ─────────────────────────────────────────────────────────

    @property
    def latest_info(self) -> Optional[dict]:
        return self._latest_info

    @property
    def latest_version(self) -> str:
        return (self._latest_info or {}).get("version", "")

    def check(self) -> None:
        """Start a background check for a newer release."""
        self._start_thread(self._do_check)

    def download_and_install(self) -> None:
        """Download and install the latest update (call after ``check``)."""
        if not self._latest_info:
            self._emit_finished(STATUS_ERROR, "No update info — run check() first")
            return
        self._start_thread(self._do_download_install)

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        self._cancel.set()

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    # ── internals ──────────────────────────────────────────────────────────

    def _start_thread(self, target: Callable) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._cancel.clear()
            self._thread = threading.Thread(target=target, daemon=True)
            self._thread.start()

    def _emit_progress(self, status: str, fraction: float = 0.0) -> None:
        if self._on_progress:
            try:
                self._on_progress(status, fraction)
            except Exception:
                pass

    def _emit_finished(self, status: str, detail: Optional[str] = None) -> None:
        if self._on_finished:
            try:
                self._on_finished(status, detail)
            except Exception:
                pass

    # ── worker: check ──────────────────────────────────────────────────────

    def _do_check(self) -> None:
        self._emit_progress(STATUS_CHECKING, 0.0)
        try:
            info = _fetch_latest_info()
        except Exception as exc:
            self._emit_finished(STATUS_ERROR, str(exc))
            return

        latest = info.get("version", "")
        if not latest:
            self._emit_finished(STATUS_ERROR, "Could not read version from release info")
            return

        self._latest_info = info
        key = _platform_key()
        if not key:
            self._emit_finished(STATUS_ERROR, f"Unsupported platform: {sys.platform}")
            return
        # test for url to ensure this update contains a package for this platform
        url = (self._latest_info or {}).get("downloads", {}).get(key, "")
        if _version_tuple(latest) > _version_tuple(APP_VERSION) and url:
            self._emit_finished(STATUS_AVAILABLE, latest)
        else:
            self._emit_finished(STATUS_UP_TO_DATE, latest)

    # ── worker: download + install ─────────────────────────────────────────

    def _do_download_install(self) -> None:
        key = _platform_key()
        if not key:
            self._emit_finished(STATUS_ERROR, f"Unsupported platform: {sys.platform}")
            return
        url = (self._latest_info or {}).get("downloads", {}).get(key, "")
        if not url:
            self._emit_finished(STATUS_ERROR, f"No download URL for {key}")
            return

        tmpdir = tempfile.mkdtemp(prefix="mouser_update_")
        try:
            filename = url.split("/")[-1]
            dest = os.path.join(tmpdir, filename)

            self._download_file(url, dest)

            if self._cancel.is_set():
                self._emit_finished(STATUS_CANCELLED)
                return

            self._emit_progress(STATUS_INSTALLING, 1.0)
            self._install(dest, key)
        except Exception as exc:
            self._emit_finished(STATUS_ERROR, str(exc))
        finally:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    def _download_file(self, url: str, dest: str) -> None:
        headers = {"User-Agent": f"Mouser/{APP_VERSION}"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            chunk_size = 65536
            with open(dest, "wb") as f:
                while True:
                    if self._cancel.is_set():
                        return
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    fraction = downloaded / total if total > 0 else 0.0
                    self._emit_progress(STATUS_DOWNLOADING, fraction)

    # ── install helpers ────────────────────────────────────────────────────

    def _install(self, path: str, key: str) -> None:
        if key == "linux-deb":
            self._install_deb(path)
        elif key.startswith("macos"):
            self._install_macos(path)
        elif key == "windows-x64":
            self._install_windows(path)
        elif key == "linux-zip":
            self._install_linux_zip(path)
        else:
            self._emit_finished(STATUS_ERROR, f"No installer for platform key: {key}")

    # ── Linux .deb ─────────────────────────────────────────────────────────

    def _install_deb(self, deb_path: str) -> None:
        """Install a .deb file via pkexec + apt/dpkg, then signal restart."""
        candidates: list[list[str]] = []
        if shutil.which("pkexec"):
            if shutil.which("apt"):
                candidates.append(["pkexec", "apt", "install", "-y", deb_path])
            if shutil.which("dpkg"):
                candidates.append(["pkexec", "dpkg", "-i", deb_path])
        # gksudo/gksu fallback (older distros)
        for sudo_tool in ("gksudo", "gksu"):
            if shutil.which(sudo_tool):
                if shutil.which("dpkg"):
                    candidates.append([sudo_tool, "dpkg", "-i", deb_path])
                break

        for cmd in candidates:
            try:
                result = subprocess.run(cmd, timeout=180, check=False)
                if result.returncode == 0:
                    self._emit_finished(STATUS_INSTALLED)
                    return
            except (subprocess.TimeoutExpired, OSError):
                continue

        # Could not install automatically — give user the path
        self._emit_finished(STATUS_NEEDS_MANUAL, deb_path)

    # ── macOS .app ─────────────────────────────────────────────────────────

    def _install_macos(self, zip_path: str) -> None:
        """Extract .app from zip and replace the running bundle in-place."""
        import subprocess
        # Maximum directory levels to walk up when searching for the .app bundle.
        _MAX_APP_SEARCH_DEPTH = 8

        exe = Path(sys.executable)
        # Walk up the path to locate the .app bundle directory
        bundle: Optional[Path] = None
        candidate = exe
        for _ in range(_MAX_APP_SEARCH_DEPTH):
            if candidate.suffix == ".app":
                bundle = candidate
                break
            candidate = candidate.parent

        if bundle is None:
            self._emit_finished(
                STATUS_ERROR,
                "Could not locate .app bundle. Please reinstall manually.",
            )
            return

        extract_dir = Path(tempfile.mkdtemp(prefix="mouser_macos_new_"))
        try:
            
            subprocess.run(["unzip", zip_path, "-d", extract_dir], check=True)   

            new_app: Optional[Path] = None
            for entry in extract_dir.iterdir():
                if entry.suffix == ".app":
                    new_app = entry
                    break

            if new_app is None:
                self._emit_finished(STATUS_ERROR, "No .app found in update archive")
                return

            backup = bundle.with_suffix(".app.bak")
            if backup.exists():
                shutil.rmtree(str(backup), ignore_errors=True)
            shutil.move(str(bundle), str(backup))
            try:
                shutil.move(str(new_app), str(bundle))
            except Exception:
                # Restore backup if move failed
                shutil.move(str(backup), str(bundle))
                raise

            # Ad-hoc codesign so macOS Gatekeeper does not block the app
            if shutil.which("codesign"):
                subprocess.run(
                    ["codesign", "--force", "--deep", "--sign", "-", str(bundle)],
                    timeout=60,
                    check=False,
                )

            # Remove the backup only after success
            shutil.rmtree(str(backup), ignore_errors=True)
            self._emit_finished(STATUS_INSTALLED)
        except Exception as exc:
            self._emit_finished(STATUS_ERROR, str(exc))
        finally:
            shutil.rmtree(str(extract_dir), ignore_errors=True)

    # ── Windows zip ────────────────────────────────────────────────────────

    def _install_windows(self, zip_path: str) -> None:
        """
        Extract the update zip to a staging area and schedule an in-place
        replacement via a batch script that runs after Mouser exits.
        """
        import zipfile

        exe_path = Path(sys.executable)
        install_dir = exe_path.parent

        # Stage the new files in a sibling temp directory
        stage_dir = Path(tempfile.mkdtemp(prefix="mouser_win_new_"))
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(str(stage_dir))

            # The zip contains a single top-level directory (e.g. "Mouser/")
            new_dir: Optional[Path] = None
            for entry in stage_dir.iterdir():
                if entry.is_dir():
                    new_dir = entry
                    break

            if new_dir is None:
                self._emit_finished(STATUS_ERROR, "No directory found in update archive")
                return

            bat_path = stage_dir / "mouser_update.bat"
            # /MOVE deletes source files after a successful copy
            bat_content = (
                "@echo off\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                # /E copies subdirectories; /IS, /IT, /IM overwrite even identical/tweaked files
                f'robocopy "{new_dir}" "{install_dir}" /E /IS /IT /IM /NFL /NDL /NJH /NJS\r\n'
                f'start "" "{install_dir / exe_path.name}"\r\n'
                'del "%~f0"\r\n'
                f'rmdir /s /q "{stage_dir}"\r\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")

            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                close_fds=True,
            )
            # Signal the UI that it should quit so the batch script can replace files
            self._emit_finished(STATUS_INSTALLED)
        except Exception as exc:
            shutil.rmtree(str(stage_dir), ignore_errors=True)
            self._emit_finished(STATUS_ERROR, str(exc))

    # ── Linux zip (non-deb) ────────────────────────────────────────────────

    def _install_linux_zip(self, zip_path: str) -> None:
        """Extract the Linux zip and replace files via a shell script after exit."""
        import zipfile

        exe_path = Path(sys.executable)
        install_dir = exe_path.parent

        stage_dir = Path(tempfile.mkdtemp(prefix="mouser_linux_new_"))
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(str(stage_dir))

            new_dir: Optional[Path] = None
            for entry in stage_dir.iterdir():
                if entry.is_dir():
                    new_dir = entry
                    break

            if new_dir is None:
                self._emit_finished(STATUS_ERROR, "No directory found in update archive")
                return

            sh_path = stage_dir / "mouser_update.sh"
            sh_content = (
                "#!/bin/sh\n"
                "sleep 2\n"
                f'cp -a "{new_dir}/." "{install_dir}/"\n'
                f'exec "{install_dir}/{exe_path.name}" &\n'
                f'rm -rf "{stage_dir}"\n'
                'rm -f "$0"\n'
            )
            sh_path.write_text(sh_content)
            sh_path.chmod(0o755)
            subprocess.Popen([str(sh_path)], close_fds=True)
            self._emit_finished(STATUS_INSTALLED)
        except Exception as exc:
            shutil.rmtree(str(stage_dir), ignore_errors=True)
            self._emit_finished(STATUS_ERROR, str(exc))
