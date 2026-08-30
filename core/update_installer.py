"""Verified update metadata, archive staging, and install planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from core.version import APP_VERSION


APP_ID = "io.github.tombadash.mouser"
STABLE_CHANNEL = "stable"
MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MANIFEST_NAME = "mouser-v{version}-update.json"
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120.0
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 750 * 1024 * 1024
_UPDATE_MANIFEST_URL_ENV = "MOUSER_UPDATE_MANIFEST_URL"
_WINDOWS_SYNCHRONIZE = 0x00100000
_WINDOWS_WAIT_OBJECT_0 = 0x00000000
_WINDOWS_WAIT_TIMEOUT = 0x00000102
_WINDOWS_WAIT_FAILED = 0xFFFFFFFF
_WINDOWS_ERROR_ACCESS_DENIED = 5
_WINDOWS_ERROR_INVALID_PARAMETER = 87


class UpdateInstallError(Exception):
    """Raised when update metadata, staging, or installation is unsafe."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdateManifest:
    schema: int
    app_id: str
    channel: str
    version: str
    tag: str
    build_number: int
    expires_at: str
    commit: str
    release_notes_url: str
    assets: dict[str, UpdateAsset]


@dataclass(frozen=True)
class ArchiveRequirements:
    require_windows_app: bool = False


@dataclass(frozen=True)
class StagedUpdate:
    archive_path: Path
    stage_dir: Path
    app_root: Path
    platform_key: str
    asset_name: str


@dataclass(frozen=True)
class RuntimeLocation:
    executable: Path
    install_root: Path
    app_data_dir: Path
    frozen: bool
    platform_key: str
    update_supported: bool
    reason: str = ""


@dataclass(frozen=True)
class InstallPlan:
    platform_key: str
    can_install: bool
    status: str
    message: str
    asset: UpdateAsset | None = None
    staged: StagedUpdate | None = None


@dataclass(frozen=True)
class WindowsUpdatePlan:
    current_pid: int
    install_root: str
    staged_root: str
    backup_root: str
    result_marker: str
    target_version: str = ""
    target_build_number: int = 0
    executable_name: str = "Mouser.exe"

    def to_dict(self) -> dict[str, object]:
        return {
            "current_pid": self.current_pid,
            "install_root": self.install_root,
            "staged_root": self.staged_root,
            "backup_root": self.backup_root,
            "result_marker": self.result_marker,
            "target_version": self.target_version,
            "target_build_number": self.target_build_number,
            "executable_name": self.executable_name,
        }

    @classmethod
    def from_dict(cls, data) -> "WindowsUpdatePlan":
        if not isinstance(data, dict):
            raise UpdateInstallError("invalid_plan", "Update plan is not valid.")
        try:
            return cls(
                current_pid=int(data["current_pid"]),
                install_root=str(data["install_root"]),
                staged_root=str(data["staged_root"]),
                backup_root=str(data["backup_root"]),
                result_marker=str(data["result_marker"]),
                target_version=str(data.get("target_version") or ""),
                target_build_number=int(data.get("target_build_number") or 0),
                executable_name=str(data.get("executable_name") or "Mouser.exe"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateInstallError("invalid_plan", "Update plan is incomplete.") from exc


@dataclass(frozen=True)
class ValidatedWindowsUpdatePlan:
    plan: WindowsUpdatePlan
    install_root: Path
    staged_root: Path
    backup_root: Path
    result_marker: Path


def build_number_from_version(version: str) -> int:
    value = (version or "").strip()
    if value.startswith("v"):
        value = value[1:]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise UpdateInstallError(
            "invalid_version",
            "Version must be major.minor.patch or major.minor.patch.revision.",
        )
    major, minor, patch = (int(part) for part in match.groups()[:3])
    base_build = major * 10000 + minor * 100 + patch
    revision_text = match.group(4)
    if revision_text is None:
        return base_build
    revision = int(revision_text)
    if revision > 99:
        raise UpdateInstallError(
            "invalid_version",
            "Version revision must be between 0 and 99.",
        )
    return base_build * 100 + revision


def current_build_number() -> int:
    return build_number_from_version(APP_VERSION)


def manifest_name_for_version(version: str) -> str:
    value = (version or "").strip()
    if value.startswith("v"):
        value = value[1:]
    build_number_from_version(value)
    return DEFAULT_MANIFEST_NAME.format(version=value)


def _parse_datetime(value: str) -> float:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise UpdateInstallError("invalid_expiry", "Release metadata expiry is invalid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _asset_from_payload(platform_key: str, data) -> UpdateAsset:
    if not isinstance(data, dict):
        raise UpdateInstallError("missing_asset", "Selected update asset is missing.")
    name = str(data.get("name") or "").strip()
    url = str(data.get("url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip().lower()
    try:
        size = int(data.get("size"))
    except (TypeError, ValueError) as exc:
        raise UpdateInstallError("missing_asset_size", "Selected update asset size is missing.") from exc
    if not name or not url or not sha256:
        raise UpdateInstallError("missing_asset_fields", "Selected update asset is incomplete.")
    if size <= 0:
        raise UpdateInstallError("missing_asset_size", "Selected update asset size is invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise UpdateInstallError("invalid_sha256", "Selected update asset checksum is invalid.")
    return UpdateAsset(platform_key, name, url, size, sha256)


def verify_update_manifest(
    payload: dict,
    *,
    platform_key: str,
    now: float | None = None,
    highest_trusted_build: int | None = None,
) -> UpdateManifest:
    if not isinstance(payload, dict):
        raise UpdateInstallError("invalid_metadata", "Release metadata is not valid.")
    payload = payload.get("payload", payload)
    if not isinstance(payload, dict):
        raise UpdateInstallError("invalid_metadata", "Release metadata is incomplete.")
    if int(payload.get("schema", 0)) != MANIFEST_SCHEMA_VERSION:
        raise UpdateInstallError("unsupported_schema", "Release metadata schema is not supported.")
    if str(payload.get("app_id") or "") != APP_ID:
        raise UpdateInstallError("wrong_app", "Release metadata is for a different app.")
    if str(payload.get("channel") or "") != STABLE_CHANNEL:
        raise UpdateInstallError("wrong_channel", "Release metadata is for a different channel.")
    expires_at = str(payload.get("expires_at") or "")
    if _parse_datetime(expires_at) <= (time.time() if now is None else float(now)):
        raise UpdateInstallError("expired_metadata", "Release metadata has expired.")
    version = str(payload.get("version") or "").strip()
    tag = str(payload.get("tag") or "").strip()
    commit = str(payload.get("commit") or "").strip()
    release_notes_url = str(payload.get("release_notes_url") or "").strip()
    if not version or not tag or not commit or not release_notes_url:
        raise UpdateInstallError("missing_metadata_fields", "Release metadata is incomplete.")
    try:
        build_number = int(payload.get("build_number"))
    except (TypeError, ValueError) as exc:
        raise UpdateInstallError("missing_build_number", "Release metadata build number is missing.") from exc
    if build_number < build_number_from_version(version):
        raise UpdateInstallError("invalid_build_number", "Release metadata build number is invalid.")
    if highest_trusted_build is not None and build_number < int(highest_trusted_build):
        raise UpdateInstallError("older_build", "Release metadata is older than the trusted version.")
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, dict):
        raise UpdateInstallError("missing_assets", "Release metadata has no assets.")
    selected = _asset_from_payload(platform_key, assets_payload.get(platform_key))
    assets = {
        str(key): _asset_from_payload(str(key), value)
        for key, value in assets_payload.items()
    }
    assets[selected.platform] = selected
    return UpdateManifest(
        schema=MANIFEST_SCHEMA_VERSION,
        app_id=APP_ID,
        channel=STABLE_CHANNEL,
        version=version,
        tag=tag,
        build_number=build_number,
        expires_at=expires_at,
        commit=commit,
        release_notes_url=release_notes_url,
        assets=assets,
    )


def platform_key(sys_platform: str | None = None, machine: str | None = None) -> str:
    system = sys_platform or sys.platform
    arch = (machine or platform.machine() or "").lower()
    if system.startswith("win"):
        if arch in {"arm64", "aarch64"}:
            return "windows-arm64"
        return "windows-x64"
    if system == "darwin":
        if arch in {"arm64", "aarch64"}:
            return "macos-arm64"
        return "macos-x86_64"
    if system.startswith("linux"):
        if arch in {"arm64", "aarch64"}:
            return "linux-arm64"
        return "linux-x64"
    return f"{system}-{arch or 'unknown'}"


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str | os.PathLike, *, expected_sha256: str, expected_size: int) -> None:
    file_path = Path(path)
    if file_path.stat().st_size != int(expected_size):
        raise UpdateInstallError("size_mismatch", "Downloaded update size does not match.")
    actual = sha256_file(file_path)
    if actual.lower() != str(expected_sha256).lower():
        raise UpdateInstallError("sha256_mismatch", "Downloaded update checksum does not match.")


def _cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set")())


def download_to_file(
    url: str,
    target: str | os.PathLike,
    *,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    expected_size: int | None = None,
    cancel_event=None,
    progress_callback=None,
) -> Path:
    if _cancelled(cancel_event):
        raise UpdateInstallError("cancelled", "Update cancelled.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"Mouser/{APP_VERSION}"},
    )
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    success = False
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = 0
            with open(target_path, "wb") as out:
                while True:
                    if _cancelled(cancel_event):
                        raise UpdateInstallError("cancelled", "Update cancelled.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if expected_size is not None and total > int(expected_size):
                        raise UpdateInstallError(
                            "size_mismatch",
                            "Downloaded update size does not match.",
                        )
                    out.write(chunk)
                    if progress_callback:
                        progress_callback(total)
        success = True
    finally:
        if not success:
            try:
                target_path.unlink()
            except OSError:
                pass
    return target_path


def fetch_json(url: str, *, timeout: float = 10.0):
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": f"Mouser/{APP_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def manifest_url_for_release(tag: str, repo: str = "TomBadash/Mouser") -> str:
    override = os.environ.get(_UPDATE_MANIFEST_URL_ENV, "").strip()
    if override:
        return override
    return f"https://github.com/{repo}/releases/download/{tag}/{manifest_name_for_version(tag)}"


def fetch_update_manifest_for_release(
    tag: str,
    *,
    repo: str = "TomBadash/Mouser",
    target_platform: str | None = None,
    timeout: float = 10.0,
    highest_trusted_build: int | None = None,
) -> UpdateManifest:
    key = target_platform or platform_key()
    payload = fetch_json(manifest_url_for_release(tag, repo), timeout=timeout)
    return verify_update_manifest(
        payload,
        platform_key=key,
        highest_trusted_build=highest_trusted_build,
    )


def _normalized_member_name(name: str) -> str:
    raw = str(name or "")
    if "\x00" in raw:
        raise UpdateInstallError("unsafe_archive", "Update archive contains an unsafe path.")
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise UpdateInstallError("unsafe_archive", "Update archive contains an absolute path.")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("//"):
        raise UpdateInstallError("unsafe_archive", "Update archive contains an unsafe path.")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UpdateInstallError("unsafe_archive", "Update archive contains path traversal.")
    return "/".join(parts)


def _entry_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0o177777


def _is_regular_or_dir(info: zipfile.ZipInfo) -> bool:
    mode = _entry_mode(info)
    if mode == 0:
        return True
    if stat.S_IFMT(mode) == 0:
        return True
    return stat.S_ISREG(mode) or stat.S_ISDIR(mode)


def validate_zip_archive(
    zip_path: str | os.PathLike,
    *,
    requirements: ArchiveRequirements | None = None,
    max_uncompressed_bytes: int = MAX_ARCHIVE_UNCOMPRESSED_BYTES,
) -> str:
    requirements = requirements or ArchiveRequirements()
    seen: set[str] = set()
    roots: set[str] = set()
    files: set[str] = set()
    total_size = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if not infos:
            raise UpdateInstallError("empty_archive", "Update archive is empty.")
        bad_crc = zf.testzip()
        if bad_crc:
            raise UpdateInstallError("bad_archive", "Update archive failed integrity checks.")
        for info in infos:
            normalized = _normalized_member_name(info.filename)
            key = normalized.casefold()
            if key in seen:
                raise UpdateInstallError("duplicate_archive_entry", "Update archive contains duplicate paths.")
            seen.add(key)
            if not _is_regular_or_dir(info):
                raise UpdateInstallError("unsafe_archive", "Update archive contains unsupported file types.")
            total_size += max(0, int(info.file_size))
            if total_size > max_uncompressed_bytes:
                raise UpdateInstallError("archive_too_large", "Update archive is too large.")
            roots.add(normalized.split("/", 1)[0])
            if not info.is_dir():
                files.add(normalized)
        if len(roots) != 1:
            raise UpdateInstallError("invalid_archive_root", "Update archive must contain one app folder.")
        root = next(iter(roots))
        if requirements.require_windows_app:
            if f"{root}/Mouser.exe" not in files:
                raise UpdateInstallError("missing_entrypoint", "Update archive does not contain Mouser.exe.")
            if not any(path.startswith(f"{root}/_internal/") for path in files):
                raise UpdateInstallError("missing_runtime", "Update archive does not contain the runtime folder.")
        return root


def _copy_zip_member(source, dest, *, declared_size: int, max_bytes: int) -> int:
    written = 0
    declared = int(declared_size)
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        written += len(chunk)
        if written > declared:
            raise UpdateInstallError(
                "bad_archive",
                "Update archive entry size is invalid.",
            )
        if written > int(max_bytes):
            raise UpdateInstallError(
                "archive_too_large",
                "Update archive is too large.",
            )
        dest.write(chunk)
    if written != declared:
        raise UpdateInstallError(
            "bad_archive",
            "Update archive entry size is invalid.",
        )
    return written


def extract_validated_zip(
    zip_path: str | os.PathLike,
    stage_dir: str | os.PathLike,
    *,
    requirements: ArchiveRequirements | None = None,
) -> StagedUpdate:
    root = validate_zip_archive(zip_path, requirements=requirements)
    stage_path = Path(stage_dir)
    if stage_path.exists():
        shutil.rmtree(stage_path)
    stage_path.mkdir(parents=True)
    success = False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            total_written = 0
            for info in zf.infolist():
                normalized = _normalized_member_name(info.filename)
                target = stage_path.joinpath(*PurePosixPath(normalized).parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(target, "wb") as dest:
                    total_written += _copy_zip_member(
                        source,
                        dest,
                        declared_size=int(info.file_size),
                        max_bytes=MAX_ARCHIVE_UNCOMPRESSED_BYTES - total_written,
                    )
        success = True
    finally:
        if not success:
            shutil.rmtree(stage_path, ignore_errors=True)
    return StagedUpdate(
        archive_path=Path(zip_path),
        stage_dir=stage_path,
        app_root=stage_path / root,
        platform_key="",
        asset_name=Path(zip_path).name,
    )


def same_volume_windows_stage_dir(
    install_root: str | os.PathLike,
    tag: str,
    *,
    pid: int | None = None,
) -> Path:
    root = Path(install_root).resolve()
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", str(tag or "update")).strip(".-")
    if not safe_tag:
        safe_tag = "update"
    return root.with_name(f".{root.name}.update-{safe_tag}-{pid or os.getpid()}")


def _probe_directory_writable(directory: Path) -> bool:
    try:
        handle, marker = tempfile.mkstemp(
            prefix=".mouser-update-write-test-",
            dir=str(directory),
        )
    except OSError:
        return False
    try:
        with os.fdopen(handle, "wb") as marker_file:
            marker_file.write(b"mouser")
            marker_file.flush()
            os.fsync(marker_file.fileno())
    except OSError:
        try:
            os.close(handle)
        except OSError:
            pass
        try:
            Path(marker).unlink()
        except OSError:
            pass
        return False
    try:
        Path(marker).unlink()
    except OSError:
        return False
    return True


def locate_runtime(
    *,
    executable: str | os.PathLike | None = None,
    sys_platform: str | None = None,
    frozen: bool | None = None,
    app_data_dir: str | os.PathLike | None = None,
) -> RuntimeLocation:
    exe = Path(executable or sys.executable).resolve()
    system = sys_platform or sys.platform
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    if app_data_dir is None and (sys_platform or sys.platform).startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        app_data_dir = Path(base) / "Mouser" / "updates"
    data_dir = Path(app_data_dir or Path.home() / ".mouser" / "updates").resolve()
    key = platform_key(system)
    if not is_frozen:
        return RuntimeLocation(exe, exe.parent, data_dir, False, key, False, "source run")
    if system.startswith("win"):
        root = exe.parent
        if not (root / "Mouser.exe").exists() or not (root / "_internal").exists():
            return RuntimeLocation(exe, root, data_dir, True, key, False, "unsupported install layout")
        if not _probe_directory_writable(root.parent):
            return RuntimeLocation(exe, root, data_dir, True, key, False, "install path not writable")
        return RuntimeLocation(exe, root, data_dir, True, key, True)
    return RuntimeLocation(exe, exe.parent, data_dir, True, key, False, "manual install required")


def plan_install_for_platform(
    manifest: UpdateManifest,
    *,
    runtime: RuntimeLocation | None = None,
    staged: StagedUpdate | None = None,
) -> InstallPlan:
    runtime = runtime or locate_runtime()
    asset = manifest.assets.get(runtime.platform_key)
    if asset is None:
        return InstallPlan(
            runtime.platform_key,
            False,
            "manual_fallback",
            "No update is available for this platform.",
        )
    if not runtime.platform_key.startswith("windows"):
        system = "macOS" if runtime.platform_key.startswith("macos") else "Linux"
        return InstallPlan(
            runtime.platform_key,
            False,
            "manual_fallback",
            f"A new Mouser release is available. Install manually on {system}.",
            asset,
            staged,
        )
    if not runtime.update_supported:
        return InstallPlan(
            runtime.platform_key,
            False,
            "manual_fallback",
            "Mouser cannot safely update this install automatically. Please install manually from the release page.",
            asset,
            staged,
        )
    return InstallPlan(
        runtime.platform_key,
        True,
        "ready_to_install",
        "Mouser is ready to install the verified update.",
        asset,
        staged,
    )


class ProcessRunner:
    def run(self, argv, *, cwd=None, env=None, timeout=None):
        return subprocess.run(
            list(argv),
            cwd=cwd,
            env=env,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )

    def popen(self, argv, *, cwd=None, env=None):
        return subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )


def write_windows_update_plan(plan: WindowsUpdatePlan, path: str | os.PathLike) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target


def read_windows_update_plan(path: str | os.PathLike) -> WindowsUpdatePlan:
    return WindowsUpdatePlan.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _safe_result_marker_for_state(path: str | os.PathLike) -> Path:
    return Path(path).resolve().parent / "last-update-result.txt"


def validate_windows_update_plan(
    plan: WindowsUpdatePlan,
    *,
    state_path: str | os.PathLike | None = None,
) -> ValidatedWindowsUpdatePlan:
    install_root = Path(plan.install_root).resolve()
    staged_root = Path(plan.staged_root).resolve()
    backup_root = Path(plan.backup_root).resolve()
    result_marker = Path(plan.result_marker).resolve()

    def reject() -> None:
        raise UpdateInstallError("invalid_plan", "Update plan is not valid.")

    if plan.current_pid <= 0:
        reject()
    if plan.executable_name != "Mouser.exe":
        reject()
    if not install_root.is_dir():
        reject()
    if not (install_root / "Mouser.exe").is_file():
        reject()
    if not (install_root / "_internal").is_dir():
        reject()
    if not staged_root.is_dir():
        reject()
    if staged_root.name != install_root.name:
        reject()
    if not (staged_root / "Mouser.exe").is_file():
        reject()
    if not (staged_root / "_internal").is_dir():
        reject()
    staged_parent = staged_root.parent
    if staged_parent.parent != install_root.parent:
        reject()
    if not staged_parent.name.startswith(f".{install_root.name}.update-"):
        reject()
    if backup_root.parent != install_root.parent:
        reject()
    if not backup_root.name.startswith(f"{install_root.name}.backup-"):
        reject()
    if state_path is not None and result_marker != _safe_result_marker_for_state(state_path):
        reject()
    return ValidatedWindowsUpdatePlan(
        plan=plan,
        install_root=install_root,
        staged_root=staged_root,
        backup_root=backup_root,
        result_marker=result_marker,
    )


def stage_windows_update_helper(
    source_executable: str | os.PathLike,
    helper_dir: str | os.PathLike,
) -> Path:
    source = Path(source_executable).resolve()
    if not source.is_file():
        raise UpdateInstallError("missing_helper_source", "Update helper could not be prepared.")
    # The Windows release is a PyInstaller one-dir bundle; the helper exe needs
    # its adjacent runtime directory to start after we move it out of install_root.
    runtime_dir = source.parent / "_internal"
    if not runtime_dir.is_dir():
        raise UpdateInstallError("missing_helper_runtime", "Update helper runtime is missing.")
    target_dir = Path(helper_dir).resolve()
    target_root = target_dir / "MouserUpdateHelper"
    try:
        target_root.relative_to(source.parent)
    except ValueError:
        pass
    else:
        raise UpdateInstallError("unsafe_helper_location", "Update helper must be outside the install folder.")

    target_dir.mkdir(parents=True, exist_ok=True)
    temp_root = target_dir / f".{target_root.name}.{os.getpid()}.tmp"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    try:
        temp_root.mkdir(parents=True)
        target = temp_root / source.name
        shutil.copy2(source, target)
        shutil.copytree(runtime_dir, temp_root / "_internal", symlinks=True)
        if target_root.exists():
            shutil.rmtree(target_root)
        temp_root.rename(target_root)
        temp_root = None
        return target_root / source.name
    finally:
        if temp_root is not None and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)


def launch_windows_update_helper(
    plan_path: str | os.PathLike,
    *,
    executable: str | os.PathLike | None = None,
    helper_dir: str | os.PathLike | None = None,
    runner: ProcessRunner | None = None,
) -> None:
    source = Path(executable or sys.executable)
    helper = (
        stage_windows_update_helper(source, helper_dir)
        if helper_dir is not None
        else source.resolve()
    )
    exe = str(helper)
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    (runner or ProcessRunner()).popen(
        [exe, "--mouser-apply-update", str(plan_path)],
        cwd=str(Path(exe).resolve().parent),
        env=env,
    )


def _windows_pid_exists(pid: int, *, kernel32=None, get_last_error=None) -> bool:
    if kernel32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        get_last_error = ctypes.get_last_error

    handle = kernel32.OpenProcess(_WINDOWS_SYNCHRONIZE, False, int(pid))
    if not handle:
        error = int(get_last_error() if get_last_error is not None else 0)
        if error == _WINDOWS_ERROR_INVALID_PARAMETER:
            return False
        if error == _WINDOWS_ERROR_ACCESS_DENIED:
            return True
        # Unknown OpenProcess failures are treated as alive so the installer
        # times out instead of replacing files while the old process may run.
        return True
    try:
        status = int(kernel32.WaitForSingleObject(handle, 0))
        if status == _WINDOWS_WAIT_TIMEOUT:
            return True
        if status == _WINDOWS_WAIT_OBJECT_0:
            return False
        if status == _WINDOWS_WAIT_FAILED:
            return True
        return True
    finally:
        kernel32.CloseHandle(handle)


def _posix_pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return True


def _pid_exists(
    pid: int,
    *,
    sys_platform: str | None = None,
    windows_api=None,
    get_last_error=None,
) -> bool:
    if pid <= 0:
        return False
    if (sys_platform or sys.platform).startswith("win"):
        return _windows_pid_exists(
            pid,
            kernel32=windows_api,
            get_last_error=get_last_error,
        )
    return _posix_pid_exists(pid)


def _apply_validated_windows_update_plan(
    validated: ValidatedWindowsUpdatePlan,
    *,
    wait_timeout: float = 30.0,
    runner: ProcessRunner | None = None,
) -> int:
    plan = validated.plan
    result_marker = validated.result_marker
    start = time.time()
    while _pid_exists(plan.current_pid):
        if time.time() - start > wait_timeout:
            _write_update_result(
                result_marker,
                "failed",
                plan.target_version,
                plan.target_build_number,
                "Mouser did not exit",
            )
            return 2
        time.sleep(0.2)

    install_root = validated.install_root
    staged_root = validated.staged_root
    backup_root = validated.backup_root
    try:
        if backup_root.exists():
            raise UpdateInstallError("backup_exists", "Update backup path already exists.")
        install_root.rename(backup_root)
        try:
            staged_root.rename(install_root)
        except Exception as install_exc:
            restore_error = None
            try:
                if install_root.exists():
                    shutil.rmtree(install_root)
            except Exception as exc:
                restore_error = exc
            if restore_error is None:
                for attempt in range(2):
                    try:
                        backup_root.rename(install_root)
                        _write_update_result(
                            result_marker,
                            "failed",
                            plan.target_version,
                            plan.target_build_number,
                            f"Update failed before replacement completed: {install_exc}",
                        )
                        return 1
                    except Exception as exc:
                        restore_error = exc
                        if attempt == 0:
                            time.sleep(0.5)
            _write_update_result(
                result_marker,
                "failed",
                plan.target_version,
                plan.target_build_number,
                (
                    "Update failed and rollback could not be restored. "
                    f"Previous install remains at {backup_root}; "
                    f"expected install path is {install_root}. {restore_error}"
                ),
            )
            return 1
        _write_update_result(
            result_marker,
            "installed",
            plan.target_version,
            plan.target_build_number,
            "",
        )
        try:
            staged_parent = staged_root.parent
            if (
                staged_parent != install_root.parent
                and staged_parent.name.startswith(f".{install_root.name}.update-")
            ):
                staged_parent.rmdir()
        except OSError:
            pass
        executable = install_root / plan.executable_name
        if executable.exists() and os.access(executable, os.X_OK):
            env = dict(os.environ)
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            (runner or ProcessRunner()).popen(
                [str(executable)], cwd=str(install_root), env=env
            )
        return 0
    except Exception as exc:
        _write_update_result(
            result_marker,
            "failed",
            plan.target_version,
            plan.target_build_number,
            str(exc),
        )
        return 1


def apply_windows_update_from_state(
    path: str | os.PathLike,
    *,
    runner: ProcessRunner | None = None,
) -> int:
    plan = None
    safe_marker = _safe_result_marker_for_state(path)
    try:
        plan = read_windows_update_plan(path)
        validated = validate_windows_update_plan(plan, state_path=path)
    except Exception as exc:
        _write_update_result(
            safe_marker,
            "failed",
            plan.target_version if plan is not None else "",
            plan.target_build_number if plan is not None else 0,
            str(exc),
        )
        return 1
    return _apply_validated_windows_update_plan(validated, runner=runner)


def _write_update_result(
    path: str | os.PathLike,
    status: str,
    version: str,
    build_number: int,
    message: str,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "status": status,
                "version": version,
                "build_number": int(build_number or 0),
                "message": message,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def read_update_result(path: str | os.PathLike) -> dict[str, object] | None:
    target = Path(path)
    if not target.exists():
        return None
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if text == "installed":
        return {"status": "installed", "version": "", "build_number": 0, "message": ""}
    if text.startswith("failed:"):
        return {
            "status": "failed",
            "version": "",
            "build_number": 0,
            "message": text.split(":", 1)[1].strip(),
        }
    data = json.loads(text)
    if not isinstance(data, dict):
        return None
    return data


def cleanup_stale_update_state(app_data_dir: str | os.PathLike) -> None:
    root = Path(app_data_dir)
    pending = root / "pending-update.json"
    try:
        plan = read_windows_update_plan(pending)
    except Exception:
        plan = None
    if plan is not None:
        try:
            install_root = Path(plan.install_root).resolve()
            staged_root = Path(plan.staged_root).resolve()
            staged_parent = staged_root.parent
            if (
                staged_parent.name.startswith(f".{install_root.name}.update-")
                and staged_parent.parent == install_root.parent
            ):
                shutil.rmtree(staged_parent, ignore_errors=True)
        except Exception:
            pass
    for name in ("pending-update.json",):
        try:
            (root / name).unlink()
        except FileNotFoundError:
            pass
    for name in ("downloads", "staged", "helper"):
        path = root / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def prepare_downloaded_asset(
    asset: UpdateAsset,
    *,
    download_dir: str | os.PathLike | None = None,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    cancel_event=None,
    progress_callback=None,
) -> Path:
    root = Path(download_dir or tempfile.mkdtemp(prefix="mouser-update-download-"))
    target = root / asset.name
    download_to_file(
        asset.url,
        target,
        timeout=timeout,
        expected_size=asset.size,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )
    if _cancelled(cancel_event):
        raise UpdateInstallError("cancelled", "Update cancelled.")
    verify_file(target, expected_sha256=asset.sha256, expected_size=asset.size)
    return target
