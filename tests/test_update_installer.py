from datetime import datetime, timedelta, timezone
import errno
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from core.update_installer import (
    APP_ID,
    ArchiveRequirements,
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    UpdateInstallError,
    WindowsUpdatePlan,
    apply_windows_update_from_state,
    build_number_from_version,
    cleanup_stale_update_state,
    download_to_file,
    extract_validated_zip,
    fetch_json,
    launch_windows_update_helper,
    locate_runtime,
    manifest_name_for_version,
    manifest_url_for_release,
    platform_key,
    plan_install_for_platform,
    prepare_downloaded_asset,
    read_update_result,
    same_volume_windows_stage_dir,
    sha256_file,
    stage_windows_update_helper,
    validate_zip_archive,
    verify_file,
    verify_update_manifest,
    write_windows_update_plan,
    _normalized_member_name,
    _pid_exists,
)
from core.update_installer import UpdateManifest, UpdateAsset, RuntimeLocation


def _payload(**updates):
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    payload = {
        "schema": 1,
        "app_id": APP_ID,
        "channel": "stable",
        "version": "3.7.0",
        "tag": "v3.7.0",
        "build_number": 30700,
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "commit": "abc123",
        "release_notes_url": "https://github.com/TomBadash/Mouser/releases/tag/v3.7.0",
        "assets": {
            "windows-x64": {
                "name": "Mouser-Windows.zip",
                "url": "https://github.com/TomBadash/Mouser/releases/download/v3.7.0/Mouser-Windows.zip",
                "size": 123,
                "sha256": "a" * 64,
            },
            "macos-arm64": {
                "name": "Mouser-macOS.zip",
                "url": "https://github.com/TomBadash/Mouser/releases/download/v3.7.0/Mouser-macOS.zip",
                "size": 456,
                "sha256": "b" * 64,
            },
        },
    }
    payload.update(updates)
    return payload


def _zip(path: Path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)


class _CancelEvent:
    def __init__(self, value=True):
        self.value = value

    def is_set(self):
        return self.value


class _FakeRunner:
    def __init__(self):
        self.popen_calls = []

    def popen(self, argv, *, cwd=None, env=None):
        self.popen_calls.append((list(argv), cwd, dict(env or {})))
        return object()


class _FakeKernel32:
    def __init__(self, *, handle=100, wait_result=0x00000102):
        self.handle = handle
        self.wait_result = wait_result
        self.open_calls = []
        self.wait_calls = []
        self.close_calls = []

    def OpenProcess(self, access, inherit_handle, pid):
        self.open_calls.append((access, inherit_handle, pid))
        return self.handle

    def WaitForSingleObject(self, handle, milliseconds):
        self.wait_calls.append((handle, milliseconds))
        return self.wait_result

    def CloseHandle(self, handle):
        self.close_calls.append(handle)
        return True


class _FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class UpdateInstallerTests(unittest.TestCase):
    def test_build_number_from_version_uses_semver_digits(self):
        self.assertEqual(build_number_from_version("v3.7.0"), 30700)
        self.assertEqual(build_number_from_version("3.7.12"), 30712)
        self.assertEqual(build_number_from_version("3.7.3.2"), 3070302)
        with self.assertRaises(UpdateInstallError):
            build_number_from_version("3.7")
        with self.assertRaises(UpdateInstallError):
            build_number_from_version("3.7.3.100")

    def test_manifest_name_matches_release_url_contract(self):
        self.assertEqual(manifest_name_for_version("v3.7.0"), "mouser-v3.7.0-update.json")
        self.assertEqual(
            manifest_name_for_version("v3.7.3.2"),
            "mouser-v3.7.3.2-update.json",
        )
        self.assertTrue(
            manifest_url_for_release("v3.7.0").endswith(
                "/v3.7.0/mouser-v3.7.0-update.json"
            )
        )

    def test_manifest_url_can_use_test_endpoint_override(self):
        with patch.dict(
            "os.environ",
            {"MOUSER_UPDATE_MANIFEST_URL": "http://127.0.0.1:8765/update.json"},
        ):
            self.assertEqual(
                manifest_url_for_release("v3.7.0"),
                "http://127.0.0.1:8765/update.json",
            )

    def test_fetch_json_accepts_utf8_bom_response(self):
        payload = b'\xef\xbb\xbf{"schema": 1, "app_id": "io.github.tombadash.mouser"}'

        with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(payload)):
            parsed = fetch_json("https://example.test/update.json")

        self.assertEqual(parsed["schema"], 1)
        self.assertEqual(parsed["app_id"], APP_ID)

    def test_update_manifest_verifies_selected_platform(self):
        manifest = verify_update_manifest(_payload(), platform_key="windows-x64")

        self.assertEqual(manifest.version, "3.7.0")
        self.assertEqual(manifest.build_number, 30700)
        self.assertEqual(manifest.assets["windows-x64"].name, "Mouser-Windows.zip")

    def test_update_manifest_accepts_ci_payload_wrapper(self):
        manifest = verify_update_manifest({"payload": _payload()}, platform_key="windows-x64")

        self.assertEqual(manifest.version, "3.7.0")

    def test_update_manifest_rejects_wrong_app(self):
        payload = _payload(app_id="other.app")

        with self.assertRaises(UpdateInstallError) as ctx:
            verify_update_manifest(payload, platform_key="windows-x64")

        self.assertEqual(ctx.exception.code, "wrong_app")

    def test_update_manifest_rejects_missing_selected_asset(self):
        with self.assertRaises(UpdateInstallError) as ctx:
            verify_update_manifest(_payload(), platform_key="linux-x64")

        self.assertEqual(ctx.exception.code, "missing_asset")

    def test_update_manifest_rejects_older_build_number(self):
        with self.assertRaises(UpdateInstallError) as ctx:
            verify_update_manifest(
                _payload(),
                platform_key="windows-x64",
                highest_trusted_build=30701,
            )

        self.assertEqual(ctx.exception.code, "older_build")

    def test_platform_key_detects_common_architectures(self):
        self.assertEqual(platform_key("win32", "AMD64"), "windows-x64")
        self.assertEqual(platform_key("win32", "ARM64"), "windows-arm64")
        self.assertEqual(platform_key("darwin", "arm64"), "macos-arm64")
        self.assertEqual(platform_key("linux", "x86_64"), "linux-x64")

    def test_verify_file_checks_size_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.zip"
            path.write_bytes(b"abc")

            verify_file(path, expected_sha256=sha256_file(path), expected_size=3)

            with self.assertRaises(UpdateInstallError) as ctx:
                verify_file(path, expected_sha256="0" * 64, expected_size=3)
            self.assertEqual(ctx.exception.code, "sha256_mismatch")

    def test_archive_validator_accepts_windows_bundle_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Mouser-Windows.zip"
            _zip(
                archive,
                [
                    ("Mouser/Mouser.exe", b"exe"),
                    ("Mouser/_internal/runtime.dll", b"dll"),
                ],
            )

            root = validate_zip_archive(
                archive,
                requirements=ArchiveRequirements(require_windows_app=True),
            )

            self.assertEqual(root, "Mouser")

    def test_archive_validator_rejects_traversal_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            traversal = Path(tmp) / "bad.zip"
            _zip(traversal, [("../evil.txt", b"no")])
            with self.assertRaises(UpdateInstallError):
                validate_zip_archive(traversal)

            duplicate = Path(tmp) / "dup.zip"
            _zip(duplicate, [("Mouser/a.txt", b"1"), ("mouser/A.txt", b"2")])
            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(duplicate)
            self.assertEqual(ctx.exception.code, "duplicate_archive_entry")

    def test_archive_validator_rejects_unsafe_path_forms(self):
        cases = [
            ("/tmp/evil.txt", "unsafe_archive"),
            ("C:/Temp/evil.txt", "unsafe_archive"),
            ("//server/share/evil.txt", "unsafe_archive"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for name, code in cases:
                with self.subTest(name=name):
                    archive = Path(tmp) / f"{abs(hash(name))}.zip"
                    _zip(archive, [(name, b"no")])
                    with self.assertRaises(UpdateInstallError) as ctx:
                        validate_zip_archive(archive)
                    self.assertEqual(ctx.exception.code, code)

        with self.assertRaises(UpdateInstallError) as ctx:
            _normalized_member_name("Mouser/\x00evil.txt")
        self.assertEqual(ctx.exception.code, "unsafe_archive")

    def test_archive_validator_rejects_symlink_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "symlink.zip"
            info = zipfile.ZipInfo("Mouser/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(info, "target")

            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(archive)

            self.assertEqual(ctx.exception.code, "unsafe_archive")

    def test_archive_validator_rejects_bad_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad-crc.zip"
            _zip(archive, [("Mouser/file.txt", b"CORRUPT_ME")])
            data = bytearray(archive.read_bytes())
            offset = data.index(b"CORRUPT_ME")
            data[offset] = ord("X")
            archive.write_bytes(data)

            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(archive)

            self.assertEqual(ctx.exception.code, "bad_archive")

    def test_archive_validator_rejects_empty_and_too_large_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.zip"
            with zipfile.ZipFile(empty, "w"):
                pass
            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(empty)
            self.assertEqual(ctx.exception.code, "empty_archive")

            large = Path(tmp) / "large.zip"
            _zip(large, [("Mouser/file.bin", b"123456")])
            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(large, max_uncompressed_bytes=5)
            self.assertEqual(ctx.exception.code, "archive_too_large")

    def test_archive_validator_rejects_incomplete_windows_bundle_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            no_exe = Path(tmp) / "no-exe.zip"
            _zip(no_exe, [("Mouser/_internal/runtime.dll", b"dll")])
            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(
                    no_exe,
                    requirements=ArchiveRequirements(require_windows_app=True),
                )
            self.assertEqual(ctx.exception.code, "missing_entrypoint")

            no_runtime = Path(tmp) / "no-runtime.zip"
            _zip(no_runtime, [("Mouser/Mouser.exe", b"exe")])
            with self.assertRaises(UpdateInstallError) as ctx:
                validate_zip_archive(
                    no_runtime,
                    requirements=ArchiveRequirements(require_windows_app=True),
                )
            self.assertEqual(ctx.exception.code, "missing_runtime")

    def test_extract_validated_zip_writes_only_inside_stage_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Mouser-Windows.zip"
            _zip(
                archive,
                [
                    ("Mouser/Mouser.exe", b"exe"),
                    ("Mouser/_internal/runtime.dll", b"dll"),
                ],
            )
            staged = extract_validated_zip(
                archive,
                Path(tmp) / "stage",
                requirements=ArchiveRequirements(require_windows_app=True),
            )

            self.assertTrue((staged.app_root / "Mouser.exe").exists())
            self.assertTrue((staged.app_root / "_internal" / "runtime.dll").exists())

    def test_extract_validated_zip_removes_partial_stage_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Mouser-Windows.zip"
            stage = Path(tmp) / "stage"
            _zip(
                archive,
                [
                    ("Mouser/Mouser.exe", b"exe"),
                    ("Mouser/_internal/runtime.dll", b"dll"),
                ],
            )

            with (
                patch(
                    "core.update_installer._copy_zip_member",
                    side_effect=OSError("write failed"),
                ),
                self.assertRaises(OSError),
            ):
                extract_validated_zip(
                    archive,
                    stage,
                    requirements=ArchiveRequirements(require_windows_app=True),
                )

            self.assertFalse(stage.exists())

    def test_extract_validated_zip_rejects_member_size_mismatch(self):
        class _FakeInfo:
            filename = "Mouser/Mouser.exe"
            file_size = 1
            external_attr = 0

            def is_dir(self):
                return False

        class _FakeRuntimeInfo:
            filename = "Mouser/_internal/runtime.dll"
            file_size = 1
            external_attr = 0

            def is_dir(self):
                return False

        class _FakeZip:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def infolist(self):
                return [_FakeInfo(), _FakeRuntimeInfo()]

            def testzip(self):
                return None

            def open(self, info):
                return io.BytesIO(b"too large")

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Mouser-Windows.zip"
            archive.write_bytes(b"not used by fake zip")
            stage = Path(tmp) / "stage"

            with (
                patch("core.update_installer.zipfile.ZipFile", _FakeZip),
                self.assertRaises(UpdateInstallError) as ctx,
            ):
                extract_validated_zip(
                    archive,
                    stage,
                    requirements=ArchiveRequirements(require_windows_app=True),
                )

            self.assertEqual(ctx.exception.code, "bad_archive")
            self.assertFalse(stage.exists())

    def test_platform_install_strategy_returns_manual_fallback_for_macos(self):
        manifest = UpdateManifest(
            schema=1,
            app_id=APP_ID,
            channel="stable",
            version="3.7.0",
            tag="v3.7.0",
            build_number=30700,
            expires_at="2026-06-01T00:00:00Z",
            commit="abc",
            release_notes_url="https://example.test",
            assets={
                "macos-arm64": UpdateAsset(
                    "macos-arm64",
                    "Mouser-macOS.zip",
                    "https://example.test/Mouser-macOS.zip",
                    1,
                    "a" * 64,
                )
            },
        )
        runtime = RuntimeLocation(
            executable=Path("/Applications/Mouser.app/Contents/MacOS/Mouser"),
            install_root=Path("/Applications/Mouser.app"),
            app_data_dir=Path("/tmp/mouser"),
            frozen=True,
            platform_key="macos-arm64",
            update_supported=False,
            reason="manual",
        )

        plan = plan_install_for_platform(manifest, runtime=runtime)

        self.assertFalse(plan.can_install)
        self.assertEqual(plan.status, "manual_fallback")
        self.assertIn("manual", plan.message.lower())

    def test_locate_runtime_classifies_source_windows_onedir_and_manual_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "repo" / "main.py"
            source.parent.mkdir()
            source.write_text("print('x')", encoding="utf-8")

            source_runtime = locate_runtime(
                executable=source,
                sys_platform="darwin",
                frozen=False,
                app_data_dir=root / "data",
            )
            self.assertFalse(source_runtime.update_supported)
            self.assertEqual(source_runtime.reason, "source run")

            install = root / "Mouser Install With Spaces"
            install.mkdir()
            exe = install / "Mouser.exe"
            exe.write_text("exe", encoding="utf-8")
            (install / "_internal").mkdir()
            windows_runtime = locate_runtime(
                executable=exe,
                sys_platform="win32",
                frozen=True,
                app_data_dir=root / "data",
            )
            self.assertTrue(windows_runtime.update_supported)
            self.assertEqual(windows_runtime.install_root, install.resolve())

            mac_runtime = locate_runtime(
                executable=root / "Mouser.app" / "Contents" / "MacOS" / "Mouser",
                sys_platform="darwin",
                frozen=True,
                app_data_dir=root / "data",
            )
            self.assertFalse(mac_runtime.update_supported)
            self.assertEqual(mac_runtime.reason, "manual install required")

    def test_locate_runtime_rejects_unsupported_windows_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "Mouser.exe"
            exe.write_text("exe", encoding="utf-8")

            runtime = locate_runtime(
                executable=exe,
                sys_platform="win32",
                frozen=True,
                app_data_dir=root / "data",
            )

            self.assertFalse(runtime.update_supported)
            self.assertEqual(runtime.reason, "unsupported install layout")

    def test_locate_runtime_rejects_windows_install_parent_without_write_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            install.mkdir()
            exe = install / "Mouser.exe"
            exe.write_text("exe", encoding="utf-8")
            (install / "_internal").mkdir()

            with patch("core.update_installer._probe_directory_writable", return_value=False) as probe:
                runtime = locate_runtime(
                    executable=exe,
                    sys_platform="win32",
                    frozen=True,
                    app_data_dir=root / "data",
                )

            probe.assert_called_once_with(install.resolve().parent)
            self.assertFalse(runtime.update_supported)
            self.assertEqual(runtime.reason, "install path not writable")

    def test_download_to_file_reports_progress_and_honors_pre_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "asset.zip"
            source.write_bytes(b"downloaded")
            target = root / "download" / "asset.zip"
            progress = []

            download_to_file(source.as_uri(), target, progress_callback=progress.append)

            self.assertEqual(target.read_bytes(), b"downloaded")
            self.assertEqual(progress[-1], len(b"downloaded"))

            with self.assertRaises(UpdateInstallError) as ctx:
                download_to_file(source.as_uri(), root / "cancel.zip", cancel_event=_CancelEvent())
            self.assertEqual(ctx.exception.code, "cancelled")

    def test_prepare_downloaded_asset_verifies_file_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "asset.zip"
            source.write_bytes(b"verified")
            asset = UpdateAsset(
                "windows-x64",
                "Mouser-Windows.zip",
                source.as_uri(),
                source.stat().st_size,
                sha256_file(source),
            )
            progress = []

            path = prepare_downloaded_asset(
                asset,
                download_dir=root / "downloads",
                progress_callback=progress.append,
            )

            self.assertEqual(path.read_bytes(), b"verified")
            self.assertEqual(progress[-1], source.stat().st_size)

    def test_prepare_downloaded_asset_uses_default_download_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_path = root / "downloads" / "Mouser-Windows.zip"
            target_path.parent.mkdir()
            target_path.write_bytes(b"verified")
            asset = UpdateAsset(
                "windows-x64",
                "Mouser-Windows.zip",
                "https://example.invalid/Mouser-Windows.zip",
                target_path.stat().st_size,
                sha256_file(target_path),
            )

            with patch("core.update_installer.download_to_file") as download:
                download.return_value = target_path

                prepare_downloaded_asset(asset, download_dir=target_path.parent)

            self.assertEqual(
                download.call_args.kwargs["timeout"],
                DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
            )

    def test_prepare_downloaded_asset_honors_explicit_download_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_path = root / "downloads" / "Mouser-Windows.zip"
            target_path.parent.mkdir()
            target_path.write_bytes(b"verified")
            asset = UpdateAsset(
                "windows-x64",
                "Mouser-Windows.zip",
                "https://example.invalid/Mouser-Windows.zip",
                target_path.stat().st_size,
                sha256_file(target_path),
            )

            with patch("core.update_installer.download_to_file") as download:
                download.return_value = target_path

                prepare_downloaded_asset(
                    asset,
                    download_dir=target_path.parent,
                    timeout=7.5,
                )

            self.assertEqual(download.call_args.kwargs["timeout"], 7.5)

    def test_download_to_file_aborts_when_stream_exceeds_expected_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "asset.zip"
            source.write_bytes(b"too large")
            target = root / "download" / "asset.zip"

            with self.assertRaises(UpdateInstallError) as ctx:
                download_to_file(source.as_uri(), target, expected_size=3)

            self.assertEqual(ctx.exception.code, "size_mismatch")
            self.assertFalse(target.exists())

    def test_same_volume_windows_stage_dir_is_adjacent_to_install_root(self):
        install_root = Path("C:/Users/example/Mouser")

        stage_dir = same_volume_windows_stage_dir(install_root, "v3.7.0/test", pid=42)

        self.assertEqual(stage_dir.parent, install_root.resolve().parent)
        self.assertEqual(stage_dir.name, ".Mouser.update-v3.7.0-test-42")

    def test_launch_windows_helper_copies_executable_outside_install_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            exe = install / "Mouser.exe"
            exe.write_text("exe", encoding="utf-8")
            internal = install / "_internal"
            internal.mkdir()
            (internal / "python312.dll").write_text("runtime", encoding="utf-8")
            plan_path = root / "pending-update.json"
            plan_path.write_text("{}", encoding="utf-8")
            helper_dir = root / "data" / "helper"
            runner = _FakeRunner()

            helper = stage_windows_update_helper(exe, helper_dir)
            self.assertTrue(helper.exists())
            self.assertEqual(helper, (helper_dir / "MouserUpdateHelper" / "Mouser.exe").resolve())
            self.assertNotEqual(helper.parent, install)
            self.assertTrue((helper.parent / "_internal" / "python312.dll").exists())

            launch_windows_update_helper(
                plan_path,
                executable=exe,
                helper_dir=helper_dir,
                runner=runner,
            )

            argv, cwd, env = runner.popen_calls[0]
            self.assertEqual(Path(argv[0]).parent, (helper_dir / "MouserUpdateHelper").resolve())
            self.assertEqual(argv[1:], ["--mouser-apply-update", str(plan_path)])
            self.assertEqual(cwd, str((helper_dir / "MouserUpdateHelper").resolve()))
            self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_pid_exists_windows_uses_wait_handle_without_os_kill(self):
        kernel32 = _FakeKernel32(handle=123, wait_result=0x00000102)

        with patch(
            "core.update_installer.os.kill",
            side_effect=AssertionError("Windows path must not signal the process"),
        ):
            self.assertTrue(
                _pid_exists(
                    4242,
                    sys_platform="win32",
                    windows_api=kernel32,
                    get_last_error=lambda: 0,
                )
            )

        self.assertEqual(kernel32.open_calls, [(0x00100000, False, 4242)])
        self.assertEqual(kernel32.wait_calls, [(123, 0)])
        self.assertEqual(kernel32.close_calls, [123])

    def test_pid_exists_windows_reports_exited_and_invalid_processes(self):
        exited = _FakeKernel32(handle=123, wait_result=0x00000000)

        self.assertFalse(
            _pid_exists(
                4242,
                sys_platform="win32",
                windows_api=exited,
                get_last_error=lambda: 0,
            )
        )
        self.assertEqual(exited.close_calls, [123])

        missing = _FakeKernel32(handle=0)
        self.assertFalse(
            _pid_exists(
                4242,
                sys_platform="win32",
                windows_api=missing,
                get_last_error=lambda: 87,
            )
        )

    def test_pid_exists_posix_treats_permission_denied_as_alive(self):
        with patch(
            "core.update_installer.os.kill",
            side_effect=PermissionError(errno.EPERM, "not permitted"),
        ):
            self.assertTrue(_pid_exists(4242, sys_platform="linux"))

        with patch(
            "core.update_installer.os.kill",
            side_effect=ProcessLookupError(errno.ESRCH, "not found"),
        ):
            self.assertFalse(_pid_exists(4242, sys_platform="linux"))

        with patch(
            "core.update_installer.os.kill",
            side_effect=OSError(errno.EIO, "unknown"),
        ):
            self.assertTrue(_pid_exists(4242, sys_platform="linux"))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows process check")
    def test_pid_exists_windows_observes_live_process_without_terminating_it(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertTrue(_pid_exists(proc.pid))
            time.sleep(0.1)
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_windows_helper_staging_requires_onedir_runtime_outside_install_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            exe = install / "Mouser.exe"
            exe.write_text("exe", encoding="utf-8")

            with self.assertRaises(UpdateInstallError) as ctx:
                stage_windows_update_helper(exe, root / "helper")
            self.assertEqual(ctx.exception.code, "missing_helper_runtime")

            (install / "_internal").mkdir()
            with self.assertRaises(UpdateInstallError) as ctx:
                stage_windows_update_helper(exe, install / "helper")
            self.assertEqual(ctx.exception.code, "unsafe_helper_location")
            self.assertFalse((install / "helper").exists())

    def test_apply_windows_update_from_state_preserves_backup_and_installs_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=77)
            staged = stage_parent / "install"
            backup = root / "install.backup-123"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "Mouser.exe").chmod(0o755)
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(backup),
                result_marker=str(marker),
            )
            write_windows_update_plan(plan, state)

            runner = _FakeRunner()

            with patch("core.update_installer._pid_exists", return_value=False):
                result = apply_windows_update_from_state(state, runner=runner)

            self.assertEqual(result, 0)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "new")
            self.assertEqual((backup / "Mouser.exe").read_text(encoding="utf-8"), "old")
            self.assertEqual(read_update_result(marker)["status"], "installed")
            self.assertEqual(len(runner.popen_calls), 1)

    def test_apply_windows_update_from_state_restores_backup_after_transient_rollback_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=83)
            staged = stage_parent / "Mouser"
            backup = root / "Mouser.backup-123"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(backup),
                result_marker=str(marker),
                target_version="3.7.0",
                target_build_number=30700,
            )
            write_windows_update_plan(plan, state)
            original_rename = Path.rename
            rollback_attempts = {"count": 0}

            def rename_side_effect(path, target):
                if Path(path) == staged.resolve() and Path(target) == install.resolve():
                    raise OSError("replacement locked")
                if Path(path) == backup.resolve() and Path(target) == install.resolve():
                    rollback_attempts["count"] += 1
                    if rollback_attempts["count"] == 1:
                        raise OSError("backup briefly locked")
                return original_rename(path, target)

            with (
                patch("core.update_installer._pid_exists", return_value=False),
                patch("core.update_installer.Path.rename", autospec=True, side_effect=rename_side_effect),
                patch("core.update_installer.time.sleep"),
            ):
                result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertEqual(rollback_attempts["count"], 2)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")
            update_result = read_update_result(marker)
            self.assertEqual(update_result["status"], "failed")
            self.assertIn("replacement locked", update_result["message"])

    def test_apply_windows_update_from_state_reports_backup_path_when_rollback_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=84)
            staged = stage_parent / "Mouser"
            backup = root / "Mouser.backup-123"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(backup),
                result_marker=str(marker),
                target_version="3.7.0",
                target_build_number=30700,
            )
            write_windows_update_plan(plan, state)
            original_rename = Path.rename

            def rename_side_effect(path, target):
                if Path(path) == staged.resolve() and Path(target) == install.resolve():
                    raise OSError("replacement locked")
                if Path(path) == backup.resolve() and Path(target) == install.resolve():
                    raise OSError("backup locked")
                return original_rename(path, target)

            with (
                patch("core.update_installer._pid_exists", return_value=False),
                patch("core.update_installer.Path.rename", autospec=True, side_effect=rename_side_effect),
                patch("core.update_installer.time.sleep"),
            ):
                result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertFalse(install.exists())
            self.assertTrue(backup.exists())
            update_result = read_update_result(marker)
            self.assertEqual(update_result["status"], "failed")
            self.assertIn(str(backup.resolve()), update_result["message"])
            self.assertIn(str(install.resolve()), update_result["message"])

    def test_apply_windows_update_from_state_threads_runner_seam(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=78)
            staged = stage_parent / "install"
            backup = root / "install.backup-123"
            marker = root / "result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "Mouser.exe").chmod(0o755)
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(backup),
                result_marker=str(root / "last-update-result.txt"),
            )
            state.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
            runner = _FakeRunner()

            with patch("core.update_installer._pid_exists", return_value=False):
                result = apply_windows_update_from_state(state, runner=runner)

            self.assertEqual(result, 0)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "new")
            self.assertEqual(len(runner.popen_calls), 1)

    def test_apply_windows_update_from_state_rejects_malformed_paths_before_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            staged = root / "staged"
            outside = root / "outside"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir()
            outside.mkdir()
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(outside),
                result_marker=str(marker),
            )
            write_windows_update_plan(plan, state)

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")
            self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual(read_update_result(marker)["status"], "failed")

    def test_apply_windows_update_from_state_rejects_mismatched_staged_root_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=79)
            staged = stage_parent / "Other"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(root / "Mouser.backup-123"),
                result_marker=str(marker),
            )
            write_windows_update_plan(plan, state)

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")
            self.assertEqual(read_update_result(marker)["status"], "failed")

    def test_apply_windows_update_from_state_rejects_existing_backup_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=80)
            staged = stage_parent / "Mouser"
            backup = root / "Mouser.backup-123"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            backup.mkdir()
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            (backup / "keep.txt").write_text("keep", encoding="utf-8")
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(backup),
                result_marker=str(marker),
            )
            write_windows_update_plan(plan, state)

            with patch("core.update_installer._pid_exists", return_value=False):
                result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")
            self.assertEqual((backup / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual(read_update_result(marker)["status"], "failed")

    def test_apply_windows_update_from_state_rejects_external_result_marker_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=81)
            staged = stage_parent / "Mouser"
            external = root / "external"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            external.mkdir()
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=123,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(root / "Mouser.backup-123"),
                result_marker=str(external / "last-update-result.txt"),
            )
            state.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertFalse((external / "last-update-result.txt").exists())
            safe_marker = root / "last-update-result.txt"
            self.assertEqual(read_update_result(safe_marker)["status"], "failed")
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")

    def test_apply_windows_update_from_state_reports_unreadable_plan_to_safe_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "pending-update.json"
            state.write_text("{", encoding="utf-8")

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            marker = root / "last-update-result.txt"
            update_result = read_update_result(marker)
            self.assertEqual(update_result["status"], "failed")
            self.assertEqual(update_result["version"], "")
            self.assertEqual(update_result["build_number"], 0)

    def test_apply_windows_update_from_state_reports_incomplete_plan_to_safe_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "pending-update.json"
            state.write_text(json.dumps({"current_pid": 123}), encoding="utf-8")

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            marker = root / "last-update-result.txt"
            update_result = read_update_result(marker)
            self.assertEqual(update_result["status"], "failed")
            self.assertEqual(update_result["version"], "")
            self.assertEqual(update_result["build_number"], 0)

    def test_apply_windows_update_from_state_rejects_non_positive_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=82)
            staged = stage_parent / "Mouser"
            marker = root / "last-update-result.txt"
            state = root / "pending-update.json"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "Mouser.exe").write_text("old", encoding="utf-8")
            (install / "_internal").mkdir()
            (staged / "Mouser.exe").write_text("new", encoding="utf-8")
            (staged / "_internal").mkdir()
            plan = WindowsUpdatePlan(
                current_pid=0,
                install_root=str(install),
                staged_root=str(staged),
                backup_root=str(root / "Mouser.backup-123"),
                result_marker=str(marker),
            )
            write_windows_update_plan(plan, state)

            result = apply_windows_update_from_state(state)

            self.assertEqual(result, 1)
            self.assertEqual((install / "Mouser.exe").read_text(encoding="utf-8"), "old")
            self.assertEqual(read_update_result(marker)["status"], "failed")

    def test_cleanup_stale_update_state_removes_pending_staging_and_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install" / "Mouser"
            install.mkdir(parents=True)
            stage_parent = same_volume_windows_stage_dir(install, "v3.7.0", pid=99)
            staged_root = stage_parent / "Mouser"
            staged_root.mkdir(parents=True)
            (staged_root / "Mouser.exe").write_text("new", encoding="utf-8")
            plan = WindowsUpdatePlan(
                current_pid=0,
                install_root=str(install),
                staged_root=str(staged_root),
                backup_root=str(root / "install" / "Mouser.backup"),
                result_marker=str(root / "last-update-result.txt"),
            )
            (root / "pending-update.json").write_text(
                json.dumps(plan.to_dict()),
                encoding="utf-8",
            )
            for name in ("downloads", "staged", "helper"):
                path = root / name
                path.mkdir()
                (path / "file.txt").write_text("x", encoding="utf-8")

            cleanup_stale_update_state(root)

            self.assertFalse((root / "pending-update.json").exists())
            self.assertFalse(stage_parent.exists())
            for name in ("downloads", "staged", "helper"):
                self.assertFalse((root / name).exists())


if __name__ == "__main__":
    unittest.main()
