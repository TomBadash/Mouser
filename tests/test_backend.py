import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import DEFAULT_CONFIG
from core.updater import UpdateCheckState

try:
    from PySide6.QtCore import QCoreApplication, Qt, QUrl
    from ui.backend import Backend
except ModuleNotFoundError:
    Backend = None
    QCoreApplication = None
    Qt = None
    QUrl = None


def _ensure_qapp():
    app = QCoreApplication.instance()
    if app is None:
        return QCoreApplication(sys.argv)
    return app


class _FakeEngine:
    def __init__(
        self,
        device_connected=False,
        connected_device=None,
        hid_features_ready=False,
        smart_shift_supported=False,
    ):
        self.device_connected = device_connected
        self.connected_device = connected_device
        self.hid_features_ready = hid_features_ready
        self.smart_shift_supported = smart_shift_supported
        self.profile_callback = None
        self.dpi_callback = None
        self.connection_callback = None
        self.battery_callback = None
        self.debug_callback = None
        self.gesture_callback = None
        self.status_callback = None
        self.debug_enabled = None
        self.start_count = 0
        self.stop_count = 0
        self.start_error = None
        self.reload_mappings_count = 0

    def set_profile_change_callback(self, cb):
        self.profile_callback = cb

    def set_dpi_read_callback(self, cb):
        self.dpi_callback = cb

    def set_connection_change_callback(self, cb):
        self.connection_callback = cb

    def set_battery_callback(self, cb):
        self.battery_callback = cb

    def set_debug_callback(self, cb):
        self.debug_callback = cb

    def set_gesture_event_callback(self, cb):
        self.gesture_callback = cb

    def set_status_callback(self, cb):
        self.status_callback = cb

    def set_debug_enabled(self, enabled):
        self.debug_enabled = enabled

    def start(self):
        self.start_count += 1
        if self.start_error:
            raise self.start_error

    def stop(self):
        self.stop_count += 1

    def reload_mappings(self):
        self.reload_mappings_count += 1


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendDeviceLayoutTests(unittest.TestCase):
    def _make_backend(self, engine=None, root_dir=None, cfg=None):
        loaded_config = copy.deepcopy(cfg or DEFAULT_CONFIG)
        with (
            patch("ui.backend.load_config", return_value=loaded_config),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            return Backend(engine=engine, root_dir=root_dir)

    @staticmethod
    def _fake_create_profile(cfg, name, label=None, copy_from="default", apps=None):
        updated = copy.deepcopy(cfg)
        updated.setdefault("profiles", {})[name] = {
            "label": label or name,
            "apps": list(apps or []),
            "mappings": {},
        }
        return updated

    def test_defaults_to_generic_layout_without_connected_device(self):
        backend = self._make_backend()

        self.assertEqual(backend.effectiveDeviceLayoutKey, "generic_mouse")
        self.assertFalse(backend.hasInteractiveDeviceLayout)

    def test_device_image_source_uses_encoded_file_url(self):
        backend = self._make_backend(root_dir="/tmp/Mouser Build")

        expected = QUrl.fromLocalFile(
            "/tmp/Mouser Build/images/icons/mouse-simple.svg"
        ).toString()

        self.assertEqual(backend.deviceImageSource, expected)

    def test_mx_anywhere_2s_hotspots_expose_horizontal_scroll(self):
        device = SimpleNamespace(
            key="mx_anywhere_2s",
            display_name="MX Anywhere 2S",
            dpi_min=200,
            dpi_max=4000,
            ui_layout="mx_anywhere_2s",
            supported_buttons=("middle", "hscroll_left", "hscroll_right"),
        )
        backend = self._make_backend(
            engine=_FakeEngine(device_connected=True, connected_device=device)
        )

        hscroll_hotspots = [
            hotspot
            for hotspot in backend.deviceHotspots
            if hotspot.get("isHScroll")
        ]

        self.assertEqual(len(hscroll_hotspots), 1)
        self.assertEqual(hscroll_hotspots[0]["buttonKey"], "hscroll_left")
        self.assertEqual(hscroll_hotspots[0]["summaryType"], "hscroll")
        self.assertTrue(hscroll_hotspots[0]["isHScroll"])

    def test_update_checks_disabled_do_not_start_timer(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg.setdefault("settings", {})["check_for_updates"] = False

        backend = self._make_backend(cfg=cfg)

        self.assertFalse(backend.checkForUpdates)
        self.assertFalse(backend._update_timer.isActive())

    def test_disabled_automatic_update_check_does_not_start_thread(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg.setdefault("settings", {})["check_for_updates"] = False
        backend = self._make_backend(cfg=cfg)

        with patch("ui.backend.threading.Thread") as thread_cls:
            backend._startUpdateCheck(manual=False)

        thread_cls.assert_not_called()
        self.assertFalse(backend._update_check_in_progress)

    def test_manual_update_check_triggers_immediate_fetch(self):
        backend = self._make_backend()

        with patch.object(backend, "_startUpdateCheck") as start_check:
            backend.manualCheckForUpdates()

        start_check.assert_called_once_with(manual=True)

    def test_prepare_latest_update_uses_manual_fallback_for_macos(self):
        from pathlib import Path

        from core.update_installer import (
            APP_ID,
            RuntimeLocation,
            UpdateAsset,
            UpdateManifest,
        )

        backend = self._make_backend()
        backend._latest_update_version = "3.7.0"
        backend._update_state = UpdateCheckState(highest_trusted_build=30699)
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
        )

        with (
            patch("ui.backend.fetch_update_manifest_for_release", return_value=manifest) as fetch_manifest,
            patch("ui.backend.locate_runtime", return_value=runtime),
        ):
            backend._runPrepareLatestUpdate()
            _ensure_qapp().processEvents()

        fetch_manifest.assert_called_once_with(
            "v3.7.0",
            repo="TomBadash/Mouser",
            highest_trusted_build=30699,
        )
        self.assertEqual(backend.updateInstallStatus, "manual_fallback")
        self.assertFalse(backend.updateInstallCanInstall)
        self.assertEqual(backend.updateInstallMessage, "macos")

    def test_prepare_latest_update_keeps_windows_install_hidden_by_default(self):
        from pathlib import Path

        from core.update_installer import (
            APP_ID,
            RuntimeLocation,
            UpdateAsset,
            UpdateManifest,
        )

        backend = self._make_backend()
        backend._latest_update_version = "3.7.0"
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
                "windows-x64": UpdateAsset(
                    "windows-x64",
                    "Mouser-Windows.zip",
                    "https://example.test/Mouser-Windows.zip",
                    1,
                    "a" * 64,
                )
            },
        )
        runtime = RuntimeLocation(
            executable=Path("C:/Mouser/Mouser.exe"),
            install_root=Path("C:/Mouser"),
            app_data_dir=Path("C:/Users/test/AppData/Local/Mouser"),
            frozen=True,
            platform_key="windows-x64",
            update_supported=True,
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("ui.backend.fetch_update_manifest_for_release", return_value=manifest),
            patch("ui.backend.locate_runtime", return_value=runtime),
            patch("ui.backend.prepare_downloaded_asset") as prepare_asset,
        ):
            backend._runPrepareLatestUpdate()
            _ensure_qapp().processEvents()
            prepare_asset.assert_not_called()
            self.assertEqual(backend.updateInstallStatus, "manual_fallback")
            self.assertFalse(backend.updateInstallCanInstall)
            self.assertEqual(backend.updateInstallMessage, "windows")
            self.assertFalse(backend.updateInstallEnabled)

    def test_prepare_latest_update_uses_manual_fallback_for_unsupported_windows_runtime(self):
        from pathlib import Path

        from core.update_installer import (
            APP_ID,
            RuntimeLocation,
            UpdateAsset,
            UpdateManifest,
        )

        backend = self._make_backend()
        backend._latest_update_version = "3.7.0"
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
                "windows-x64": UpdateAsset(
                    "windows-x64",
                    "Mouser-Windows.zip",
                    "https://example.test/Mouser-Windows.zip",
                    1,
                    "a" * 64,
                )
            },
        )
        runtime = RuntimeLocation(
            executable=Path("C:/Program Files/Mouser/Mouser.exe"),
            install_root=Path("C:/Program Files/Mouser"),
            app_data_dir=Path("C:/Users/test/AppData/Local/Mouser"),
            frozen=True,
            platform_key="windows-x64",
            update_supported=False,
            reason="install path not writable",
        )

        with (
            patch.dict("os.environ", {"MOUSER_ENABLE_UPDATE_INSTALL": "1"}),
            patch("ui.backend.fetch_update_manifest_for_release", return_value=manifest),
            patch("ui.backend.locate_runtime", return_value=runtime),
            patch("ui.backend.prepare_downloaded_asset") as prepare_asset,
        ):
            backend._runPrepareLatestUpdate()
            _ensure_qapp().processEvents()

            prepare_asset.assert_not_called()
            self.assertEqual(backend.updateInstallStatus, "manual_fallback")
            self.assertFalse(backend.updateInstallCanInstall)
            self.assertEqual(backend.updateInstallMessage, "windows")
            self.assertTrue(backend.updateInstallEnabled)

    def test_prepare_latest_update_stages_windows_bundle_next_to_install_root(self):
        from core.update_installer import (
            APP_ID,
            RuntimeLocation,
            StagedUpdate,
            UpdateAsset,
            UpdateManifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            install.mkdir()
            backend = self._make_backend()
            backend._latest_update_version = "3.7.0"
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
                    "windows-x64": UpdateAsset(
                        "windows-x64",
                        "Mouser-Windows.zip",
                        "https://example.test/Mouser-Windows.zip",
                        1,
                        "a" * 64,
                    )
                },
            )
            runtime = RuntimeLocation(
                executable=install / "Mouser.exe",
                install_root=install,
                app_data_dir=root / "data",
                frozen=True,
                platform_key="windows-x64",
                update_supported=True,
            )
            archive = root / "Mouser-Windows.zip"
            staged_app = root / ".Mouser.update-v3.7.0-1234" / "Mouser"
            staged = StagedUpdate(
                archive_path=archive,
                stage_dir=staged_app.parent,
                app_root=staged_app,
                platform_key="windows-x64",
                asset_name="Mouser-Windows.zip",
            )

            with (
                patch.dict("os.environ", {"MOUSER_ENABLE_UPDATE_INSTALL": "1"}),
                patch("ui.backend.fetch_update_manifest_for_release", return_value=manifest),
                patch("ui.backend.locate_runtime", return_value=runtime),
                patch("ui.backend.prepare_downloaded_asset", return_value=archive),
                patch("ui.backend.extract_validated_zip", return_value=staged) as extract_zip,
                patch("ui.backend.os.getpid", return_value=1234),
            ):
                backend._runPrepareLatestUpdate()
                _ensure_qapp().processEvents()

            extract_zip.assert_called_once()
            stage_arg = extract_zip.call_args.args[1]
            self.assertEqual(stage_arg.parent, install.resolve().parent)
            self.assertEqual(stage_arg.name, ".Mouser.update-v3.7.0-1234")
            self.assertEqual(backend.updateInstallStatus, "ready_to_install")
            self.assertTrue(backend.updateInstallCanInstall)

    def test_install_prepared_update_launches_helper_and_quits(self):
        backend = self._make_backend()
        backend._pending_update_plan_path = "/tmp/pending-update.json"
        backend._update_install_can_install = True

        with (
            patch.dict("os.environ", {"MOUSER_ENABLE_UPDATE_INSTALL": "1"}),
            patch("ui.backend.launch_windows_update_helper") as launch_helper,
            patch("ui.backend.QCoreApplication.quit") as quit_app,
        ):
            backend.installPreparedUpdate()

        launch_helper.assert_called_once_with("/tmp/pending-update.json", helper_dir=None)
        quit_app.assert_called_once()
        self.assertEqual(backend.updateInstallStatus, "installing")

    def test_install_prepared_update_restarts_engine_when_helper_launch_fails(self):
        engine = _FakeEngine()
        backend = self._make_backend(engine=engine)
        backend._pending_update_plan_path = "/tmp/pending-update.json"
        backend._update_install_can_install = True

        with (
            patch.dict("os.environ", {"MOUSER_ENABLE_UPDATE_INSTALL": "1"}),
            patch(
                "ui.backend.launch_windows_update_helper",
                side_effect=OSError("helper failed"),
            ),
            patch("ui.backend.QCoreApplication.quit") as quit_app,
        ):
            backend.installPreparedUpdate()

        self.assertEqual(engine.stop_count, 1)
        self.assertEqual(engine.start_count, 1)
        quit_app.assert_not_called()
        self.assertEqual(backend.updateInstallStatus, "error")

    def test_cancel_update_preparation_sets_inline_cancelled_state(self):
        backend = self._make_backend()
        backend._update_install_status = "downloading"

        backend.cancelUpdatePreparation()

        self.assertTrue(backend._update_cancel.is_set())
        self.assertEqual(backend.updateInstallStatus, "cancelled")

    def test_cancel_before_prepare_worker_runs_does_not_fetch_metadata(self):
        from core.update_installer import RuntimeLocation

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            backend = self._make_backend()
            backend._latest_update_version = "3.7.0"
            runtime = RuntimeLocation(
                executable=data / "Mouser.exe",
                install_root=data,
                app_data_dir=data,
                frozen=True,
                platform_key="windows-x64",
                update_supported=True,
            )
            captured = {}

            def make_thread(*, target, name, daemon):
                captured["target"] = target
                captured["name"] = name
                captured["daemon"] = daemon
                return SimpleNamespace(start=lambda: None)

            with patch("ui.backend.threading.Thread", side_effect=make_thread):
                backend.prepareLatestUpdate()

            self.assertEqual(captured["name"], "MouserPrepareUpdate")
            self.assertTrue(captured["daemon"])

            backend.cancelUpdatePreparation()
            with (
                patch("ui.backend.fetch_update_manifest_for_release") as fetch_manifest,
                patch("ui.backend.locate_runtime", return_value=runtime),
            ):
                captured["target"]()
                _ensure_qapp().processEvents()

            fetch_manifest.assert_not_called()
            self.assertEqual(backend.updateInstallStatus, "cancelled")
            self.assertFalse(backend.updateInstallCanInstall)

    def test_cancel_during_metadata_fetch_keeps_cancelled_state(self):
        from pathlib import Path

        from core.update_installer import APP_ID, RuntimeLocation, UpdateAsset, UpdateManifest

        backend = self._make_backend()
        backend._latest_update_version = "3.7.0"
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
        )

        def fetch_and_cancel(*args, **kwargs):
            backend._update_cancel.set()
            return manifest

        with (
            patch("ui.backend.fetch_update_manifest_for_release", side_effect=fetch_and_cancel),
            patch("ui.backend.locate_runtime", return_value=runtime),
        ):
            backend._runPrepareLatestUpdate()
            _ensure_qapp().processEvents()

        self.assertEqual(backend.updateInstallStatus, "cancelled")
        self.assertFalse(backend.updateInstallCanInstall)

    def test_prepare_latest_update_cleans_install_adjacent_stage_on_error(self):
        from core.update_installer import (
            APP_ID,
            RuntimeLocation,
            UpdateAsset,
            UpdateInstallError,
            UpdateManifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Mouser"
            install.mkdir()
            backend = self._make_backend()
            backend._latest_update_version = "3.7.0"
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
                    "windows-x64": UpdateAsset(
                        "windows-x64",
                        "Mouser-Windows.zip",
                        "https://example.test/Mouser-Windows.zip",
                        1,
                        "a" * 64,
                    )
                },
            )
            runtime = RuntimeLocation(
                executable=install / "Mouser.exe",
                install_root=install,
                app_data_dir=root / "data",
                frozen=True,
                platform_key="windows-x64",
                update_supported=True,
            )
            archive = root / "Mouser-Windows.zip"
            stage_dir = root / ".Mouser.update-v3.7.0-1234"

            def fail_extract(_archive, stage_arg, **_kwargs):
                self.assertEqual(stage_arg, stage_dir)
                stage_arg.mkdir(parents=True)
                (stage_arg / "partial.txt").write_text("partial", encoding="utf-8")
                raise UpdateInstallError("bad_archive", "bad archive")

            with (
                patch.dict("os.environ", {"MOUSER_ENABLE_UPDATE_INSTALL": "1"}),
                patch("ui.backend.fetch_update_manifest_for_release", return_value=manifest),
                patch("ui.backend.locate_runtime", return_value=runtime),
                patch("ui.backend.prepare_downloaded_asset", return_value=archive),
                patch("ui.backend.same_volume_windows_stage_dir", return_value=stage_dir),
                patch("ui.backend.extract_validated_zip", side_effect=fail_extract),
            ):
                backend._runPrepareLatestUpdate()
                _ensure_qapp().processEvents()

            self.assertEqual(backend.updateInstallStatus, "error")
            self.assertEqual(backend.updateInstallMessage, "bad_archive")
            self.assertFalse(stage_dir.exists())

    def test_startup_consumes_successful_update_marker_and_persists_build_number(self):
        from core.update_installer import RuntimeLocation

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            marker = data / "last-update-result.txt"
            marker.write_text(
                json.dumps(
                    {"status": "installed", "version": "3.7.0", "build_number": 30700}
                ),
                encoding="utf-8",
            )
            runtime = RuntimeLocation(
                executable=data / "Mouser.exe",
                install_root=data,
                app_data_dir=data,
                frozen=True,
                platform_key="windows-x64",
                update_supported=True,
            )
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg.setdefault("settings", {})["update_check_state"] = {
                "highest_trusted_build": 30600
            }

            with (
                patch("ui.backend.load_config", return_value=cfg),
                patch("ui.backend.save_config") as save_config,
                patch("ui.backend.supports_login_startup", return_value=False),
                patch("ui.backend.locate_runtime", return_value=runtime),
            ):
                backend = Backend(engine=_FakeEngine())

            self.assertFalse(marker.exists())
            self.assertEqual(backend.updateInstallStatus, "installed")
            self.assertEqual(backend.updateInstallMessage, "3.7.0")
            self.assertEqual(backend._update_state.highest_trusted_build, 30700)
            save_config.assert_called_with(backend._cfg)

    def test_update_check_result_persists_state_on_main_thread(self):
        backend = self._make_backend()
        state = {
            "last_check": 10.0,
            "etag": '"abc"',
            "last_modified": "Wed, 13 May 2026 00:00:00 GMT",
            "backoff_until": 0.0,
            "last_seen_latest_version": "v3.7.1",
            "skipped_version": "",
        }

        with patch("ui.backend.save_config") as save_config:
            backend._handleUpdateCheckFinished(False, True, state)

        self.assertEqual(
            backend._cfg["settings"]["update_check_state"]["etag"], '"abc"'
        )
        self.assertEqual(backend._update_state.last_seen_latest_version, "v3.7.1")
        save_config.assert_called_once_with(backend._cfg)

    def test_disconnected_override_request_does_not_persist(self):
        backend = self._make_backend()
        backend._connected_device_key = "mx_master_3"
        backend.setDeviceLayoutOverride("mx_master")

        overrides = backend._cfg.get("settings", {}).get("device_layout_overrides", {})
        self.assertEqual(overrides, {})

    def test_connected_device_can_override_exact_layout_with_family_layout(self):
        device = SimpleNamespace(
            key="mx_master_4",
            display_name="MX Master 4",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_4",
            supported_buttons=("middle", "xbutton1", "xbutton2"),
        )

        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            backend = Backend(engine=_FakeEngine(device_connected=True, connected_device=device))
            backend.setDeviceLayoutOverride("mx_master")

        overrides = backend._cfg.get("settings", {}).get("device_layout_overrides", {})
        self.assertEqual(overrides, {"mx_master_4": "mx_master"})
        self.assertEqual(backend.effectiveDeviceLayoutKey, "mx_master")

    def test_connected_device_supported_buttons_filter_mapping_list(self):
        device = SimpleNamespace(
            key="mx_master_3s",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_3s",
            supported_buttons=("middle", "xbutton1"),
        )

        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            backend = Backend(engine=_FakeEngine(device_connected=True, connected_device=device))

        button_keys = [button["key"] for button in backend.buttons]
        self.assertIn("middle", button_keys)
        self.assertIn("xbutton1", button_keys)
        self.assertNotIn("gesture", button_keys)
        self.assertNotIn("mode_shift", button_keys)

    def test_disconnect_clears_stale_linux_device_identity_and_layout(self):
        device = SimpleNamespace(
            key="mx_master_3",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_3",
        )

        def fake_layout(key):
            return {"key": key, "interactive": key != "generic_mouse"}

        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
            patch("ui.backend.get_device_layout", side_effect=fake_layout),
        ):
            backend = Backend(engine=_FakeEngine(device_connected=True, connected_device=device))
            self.assertTrue(backend.mouseConnected)
            self.assertEqual(backend.connectedDeviceKey, "mx_master_3")
            self.assertEqual(backend.effectiveDeviceLayoutKey, "mx_master_3")
            backend._battery_level = 42

            backend._handleConnectionChange(False)

        self.assertFalse(backend.mouseConnected)
        self.assertEqual(backend.connectedDeviceKey, "")
        self.assertEqual(backend.effectiveDeviceLayoutKey, "generic_mouse")
        self.assertEqual(backend.batteryLevel, -1)

    def test_refresh_updates_hid_features_without_reemitting_connection_edge(self):
        device = SimpleNamespace(
            key="mx_master_3",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_3",
        )

        def fake_layout(key):
            return {"key": key, "interactive": key != "generic_mouse"}

        engine = _FakeEngine(
            device_connected=True,
            connected_device=None,
            hid_features_ready=False,
            smart_shift_supported=False,
        )

        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
            patch("ui.backend.get_device_layout", side_effect=fake_layout),
        ):
            backend = Backend(engine=engine)
            mouse_notifications = []
            hid_notifications = []
            backend.mouseConnectedChanged.connect(lambda: mouse_notifications.append(True))
            backend.hidFeaturesReadyChanged.connect(lambda: hid_notifications.append(True))

            engine.connected_device = device
            engine.hid_features_ready = True
            engine.smart_shift_supported = True
            backend._handleConnectionChange(True)

        self.assertTrue(backend.mouseConnected)
        self.assertTrue(backend.hidFeaturesReady)
        self.assertTrue(backend.smartShiftSupported)
        self.assertEqual(backend.connectedDeviceKey, "mx_master_3")
        self.assertEqual(mouse_notifications, [])
        self.assertEqual(hid_notifications, [True])

    def test_retry_refresh_promotes_late_hid_features_ready(self):
        device = SimpleNamespace(
            key="mx_master_3",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master",
        )
        engine = _FakeEngine(
            device_connected=True,
            connected_device=None,
            hid_features_ready=False,
            smart_shift_supported=False,
        )
        backend = self._make_backend(engine=engine)
        backend._mouse_connected = True
        hid_notifications = []
        backend.hidFeaturesReadyChanged.connect(lambda: hid_notifications.append(True))

        engine.connected_device = device
        engine.hid_features_ready = True
        engine.smart_shift_supported = True
        backend._refresh_connected_device_info()

        self.assertTrue(backend.hidFeaturesReady)
        self.assertTrue(backend.smartShiftSupported)
        self.assertEqual(backend.connectedDeviceKey, "mx_master_3")
        self.assertEqual(hid_notifications, [True])

    def test_init_wires_engine_status_callback_into_backend(self):
        engine = _FakeEngine()

        backend = self._make_backend(engine=engine)

        self.assertIsNotNone(engine.status_callback)
        self.assertIs(engine.status_callback.__self__, backend)
        self.assertIs(engine.status_callback.__func__, Backend._onEngineStatusMessage)

    def test_screenshot_directory_defaults_to_system_behavior(self):
        backend = self._make_backend()

        self.assertEqual(backend.screenshotDirectory, "")
        self.assertEqual(backend.screenshotDirectoryLabel, "")
        self.assertFalse(backend.hasCustomScreenshotDirectory)

    def test_next_screenshot_file_path_uses_custom_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg["settings"]["screenshot_directory"] = tmp
            with (
                patch("ui.backend.load_config", return_value=cfg),
                patch("ui.backend.save_config"),
                patch("ui.backend.supports_login_startup", return_value=False),
            ):
                backend = Backend(engine=None)

            path = backend.next_screenshot_file_path()

        self.assertEqual(path.parent, Path(tmp))
        self.assertTrue(path.name.startswith("Screenshot "))
        self.assertEqual(path.suffix, ".png")

    def test_next_screenshot_file_paths_reserves_multiple_custom_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg["settings"]["screenshot_directory"] = tmp
            with (
                patch("ui.backend.load_config", return_value=cfg),
                patch("ui.backend.save_config"),
                patch("ui.backend.supports_login_startup", return_value=False),
            ):
                backend = Backend(engine=None)

            paths = backend.next_screenshot_file_paths(2)

        self.assertEqual([path.parent for path in paths], [Path(tmp), Path(tmp)])
        self.assertEqual(len({path.name for path in paths}), 2)

    def test_choose_screenshot_directory_persists_valid_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            with (
                patch("ui.backend.load_config", return_value=cfg),
                patch("ui.backend.save_config") as save_mock,
                patch("ui.backend.supports_login_startup", return_value=False),
                patch(
                    "PySide6.QtWidgets.QFileDialog.getExistingDirectory",
                    return_value=tmp,
                ),
            ):
                backend = Backend(engine=None)
                statuses = []
                backend.statusMessage.connect(statuses.append)
                backend.chooseScreenshotDirectory()

        self.assertEqual(backend.screenshotDirectory, str(Path(tmp)))
        self.assertTrue(backend.hasCustomScreenshotDirectory)
        save_mock.assert_called_once()
        self.assertEqual(statuses, ["Saved"])

    def test_choose_screenshot_directory_ignores_invalid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not-a-folder"
            file_path.write_text("x", encoding="utf-8")
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            with (
                patch("ui.backend.load_config", return_value=cfg),
                patch("ui.backend.save_config") as save_mock,
                patch("ui.backend.supports_login_startup", return_value=False),
                patch(
                    "PySide6.QtWidgets.QFileDialog.getExistingDirectory",
                    return_value=str(file_path),
                ),
            ):
                backend = Backend(engine=None)
                statuses = []
                backend.statusMessage.connect(statuses.append)
                backend.chooseScreenshotDirectory()

        self.assertEqual(backend.screenshotDirectory, "")
        save_mock.assert_not_called()
        self.assertEqual(statuses, ["Choose a valid screenshot folder"])

    def test_reset_screenshot_directory_clears_custom_folder(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["screenshot_directory"] = "/tmp/screens"
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config") as save_mock,
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            backend = Backend(engine=None)
            statuses = []
            backend.statusMessage.connect(statuses.append)
            backend.resetScreenshotDirectory()

        self.assertEqual(backend.screenshotDirectory, "")
        self.assertFalse(backend.hasCustomScreenshotDirectory)
        save_mock.assert_called_once()
        self.assertEqual(statuses, ["Saved"])

    def test_replay_failure_status_becomes_backend_status_message(self):
        app = _ensure_qapp()
        engine = _FakeEngine()

        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            backend = Backend(engine=engine)
            status_messages = []
            backend.statusMessage.connect(status_messages.append)

            engine.status_callback("Failed to replay HID++ settings after reconnect")
            app.processEvents()

        self.assertEqual(
            status_messages,
            ["Failed to replay HID++ settings after reconnect"],
        )

    def test_non_dict_smart_shift_payload_does_not_emit_change_signal(self):
        backend = self._make_backend()
        notifications = []
        backend.smartShiftChanged.connect(lambda: notifications.append(True))

        backend._pending_smart_shift_state = "freespin"
        backend._handleSmartShiftRead()

        self.assertEqual(notifications, [])

    def test_non_dict_smart_shift_payload_does_not_mutate_config(self):
        backend = self._make_backend()
        original = copy.deepcopy(backend._cfg["settings"])

        backend._pending_smart_shift_state = "freespin"
        backend._handleSmartShiftRead()

        self.assertEqual(backend._cfg["settings"], original)

    def test_linux_reports_gesture_direction_support(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "linux"):
            self.assertTrue(backend.supportsGestureDirections)

    def test_known_apps_include_paths_and_refresh_signal(self):
        backend = self._make_backend()
        fake_catalog = [
            {
                "id": "code.desktop",
                "label": "Visual Studio Code",
                "path": "/usr/bin/code",
                "aliases": ["code.desktop", "Visual Studio Code"],
                "legacy_icon": "",
            }
        ]
        notifications = []
        backend.knownAppsChanged.connect(lambda: notifications.append(True))

        with (
            patch("ui.backend.app_catalog.get_app_catalog", return_value=fake_catalog),
            patch("ui.backend.get_icon_for_exe", return_value=""),
        ):
            apps = backend.knownApps
            backend.refreshKnownAppsSilently()

        self.assertEqual(apps[0]["path"], "/usr/bin/code")
        self.assertEqual(len(notifications), 1)

    def test_shortcut_capture_keeps_ctrl_and_super_distinct_on_macos(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "darwin"):
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_W,
                    Qt.ControlModifier,
                    "w",
                ),
                "super+w",
            )
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_W,
                    Qt.MetaModifier,
                    "w",
                ),
                "ctrl+w",
            )

    def test_shortcut_capture_preserves_default_qt_modifier_names_off_macos(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "linux"):
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_W,
                    Qt.ControlModifier,
                    "w",
                ),
                "ctrl+w",
            )
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_W,
                    Qt.MetaModifier,
                    "w",
                ),
                "super+w",
            )

    def test_shortcut_capture_accepts_qt_enum_objects(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "darwin"):
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_W,
                    Qt.ControlModifier,
                    "w",
                ),
                "super+w",
            )

    def test_shortcut_capture_keeps_enter_and_escape_capturable(self):
        backend = self._make_backend()

        self.assertEqual(
            backend.shortcutComboFromQtEvent(
                Qt.Key_Return,
                Qt.NoModifier,
                "",
            ),
            "enter",
        )
        self.assertEqual(
            backend.shortcutComboFromQtEvent(
                Qt.Key_Enter,
                Qt.NoModifier,
                "",
            ),
            "enter",
        )
        self.assertEqual(
            backend.shortcutComboFromQtEvent(
                Qt.Key_Escape,
                Qt.NoModifier,
                "",
            ),
            "esc",
        )

    def test_shortcut_capture_accepts_extended_function_keys(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "win32"):
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_F13,
                    Qt.NoModifier,
                    "",
                ),
                "f13",
            )
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_F24,
                    Qt.ControlModifier,
                    "",
                ),
                "ctrl+f24",
            )

    def test_shortcut_capture_accepts_shifted_symbol_text(self):
        backend = self._make_backend()

        with patch("ui.backend.sys.platform", "win32"):
            self.assertEqual(
                backend.shortcutComboFromQtEvent(
                    Qt.Key_Comma,
                    Qt.ControlModifier | Qt.ShiftModifier,
                    "<",
                ),
                "ctrl+shift+comma",
            )

    def test_reserved_custom_shortcut_warning_slot(self):
        backend = self._make_backend()

        self.assertTrue(backend.isReservedCustomShortcut("Win+Shift+S"))
        self.assertFalse(backend.isReservedCustomShortcut("Ctrl+Shift+P"))

    def test_custom_shortcut_validation_error_info_explains_parse_failure(self):
        backend = self._make_backend()

        self.assertEqual(backend.customShortcutValidationErrorInfo("Ctrl+Shift+P"), {})
        self.assertEqual(
            backend.customShortcutValidationErrorInfo("Ctrl+A+B"),
            {"code": "multiple_main_keys", "detail": ""},
        )
        self.assertEqual(
            backend.customShortcutValidationErrorInfo("Ctrl++"),
            {"code": "empty_segment", "detail": ""},
        )
        self.assertEqual(
            backend.customShortcutValidationErrorInfo("Ctrl+Hyperdrive"),
            {"code": "unknown_key", "detail": "Hyperdrive"},
        )

    def test_add_profile_stores_catalog_id_for_linux_app(self):
        backend = self._make_backend()
        fake_catalog = [
            {
                "id": "firefox.desktop",
                "label": "Firefox",
                "path": "/usr/bin/firefox",
                "aliases": ["firefox.desktop", "/usr/bin/firefox", "firefox"],
                "legacy_icon": "",
            }
        ]
        fake_entry = {
            "id": "firefox.desktop",
            "label": "Firefox",
            "path": "/usr/bin/firefox",
            "aliases": ["firefox.desktop", "/usr/bin/firefox", "firefox"],
            "legacy_icon": "",
        }

        with (
            patch("ui.backend.app_catalog.get_app_catalog", return_value=fake_catalog),
            patch("ui.backend.app_catalog.resolve_app_spec", return_value=fake_entry),
            patch("ui.backend.create_profile", side_effect=self._fake_create_profile),
        ):
            backend.addProfile("firefox.desktop")

        self.assertEqual(
            backend._cfg["profiles"]["firefox"]["apps"],
            ["firefox.desktop"],
        )

    def test_add_profile_rejects_linux_duplicate_when_existing_profile_uses_legacy_path(self):
        backend = self._make_backend()
        backend._cfg["profiles"]["firefox"] = {
            "label": "Firefox",
            "apps": ["/usr/bin/firefox"],
            "mappings": {},
        }
        fake_catalog = [
            {
                "id": "firefox.desktop",
                "label": "Firefox",
                "path": "/usr/bin/firefox",
                "aliases": ["firefox.desktop", "/usr/bin/firefox", "firefox"],
                "legacy_icon": "",
            }
        ]
        status_messages = []
        backend.statusMessage.connect(status_messages.append)

        def resolve_app(spec):
            if spec in ("firefox.desktop", "/usr/bin/firefox"):
                return {
                    "id": "firefox.desktop",
                    "label": "Firefox",
                    "path": "/usr/bin/firefox",
                    "aliases": ["firefox.desktop", "/usr/bin/firefox", "firefox"],
                    "legacy_icon": "",
                }
            return None

        with (
            patch("ui.backend.app_catalog.get_app_catalog", return_value=fake_catalog),
            patch("ui.backend.app_catalog.resolve_app_spec", side_effect=resolve_app),
            patch("ui.backend.create_profile") as create_profile,
        ):
            backend.addProfile("firefox.desktop")

        create_profile.assert_not_called()
        self.assertIn("Profile already exists", status_messages)


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendPerButtonGestureTests(unittest.TestCase):
    """issue #006 -- per-button gesture toggle + namespaced binding get/set."""

    def _make_backend(self, engine=None, cfg=None):
        loaded_config = copy.deepcopy(cfg or DEFAULT_CONFIG)
        with (
            patch("ui.backend.load_config", return_value=loaded_config),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            return Backend(engine=engine)

    def _mx_anywhere_2s(self):
        return SimpleNamespace(
            key="mx_anywhere_2s",
            display_name="MX Anywhere 2S",
            dpi_min=200,
            dpi_max=4000,
            ui_layout="mx_anywhere_2s",
            supported_buttons=(
                "middle", "xbutton1", "xbutton2",
                "gesture_forward_left", "gesture_forward_right",
                "gesture_forward_up", "gesture_forward_down",
            ),
        )

    def test_gesture_owner_for_button_maps_hotspot_keys_to_owners(self):
        backend = self._make_backend()
        self.assertEqual(backend.gestureOwnerForButton("xbutton1"), "back")
        self.assertEqual(backend.gestureOwnerForButton("xbutton2"), "forward")
        self.assertEqual(backend.gestureOwnerForButton("middle"), "middle")
        self.assertEqual(backend.gestureOwnerForButton("hscroll_left"), "")

    def test_gesture_mode_off_by_default(self):
        backend = self._make_backend()
        self.assertEqual(backend.gestureEnabledOwners, [])
        bindings = backend.gestureOwnerBindings("default", "forward")
        self.assertTrue(all(entry["actionId"] == "none" for entry in bindings))

    def test_set_gesture_owner_enabled_persists_and_notifies(self):
        backend = self._make_backend()
        settings_changed = []
        backend.settingsChanged.connect(lambda: settings_changed.append(True))

        with patch("ui.backend.save_config") as save_mock:
            backend.setGestureOwnerEnabled("forward", True)

        save_mock.assert_called_once()
        self.assertEqual(backend.gestureEnabledOwners, ["forward"])
        self.assertEqual(len(settings_changed), 1)

    def test_set_gesture_owner_enabled_noop_when_unchanged(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("forward", True)

        with patch("ui.backend.save_config") as save_mock:
            backend.setGestureOwnerEnabled("forward", True)

        save_mock.assert_not_called()

    def test_set_gesture_owner_enabled_rejects_unknown_owner(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config") as save_mock:
            # "gesture" is the HID thumb button, not a per-button owner.
            backend.setGestureOwnerEnabled("gesture", True)
        save_mock.assert_not_called()
        self.assertEqual(backend.gestureEnabledOwners, [])

    def test_set_gesture_owner_enabled_reruns_engine_mapping_reload(self):
        engine = _FakeEngine()
        backend = self._make_backend(engine=engine)
        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("middle", True)
        self.assertEqual(engine.reload_mappings_count, 1)

    def test_toggle_off_does_not_clear_direction_bindings(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("back", True)
        with patch("core.config.save_config"):
            backend.setGestureOwnerBinding("default", "back", "up", "mission_control")
        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("back", False)

        self.assertEqual(backend.gestureEnabledOwners, [])
        bindings = {
            entry["direction"]: entry["actionId"]
            for entry in backend.gestureOwnerBindings("default", "back")
        }
        self.assertEqual(bindings["up"], "mission_control")

    def test_toggle_off_does_not_touch_single_action_mapping(self):
        backend = self._make_backend()

        def xbutton1_action():
            mappings = backend.getProfileMappings("default")
            return next(m["actionId"] for m in mappings if m["key"] == "xbutton1")

        original = xbutton1_action()
        self.assertEqual(original, "alt_tab")  # DEFAULT_CONFIG value, sanity check

        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("back", True)
        with patch("core.config.save_config"):
            backend.setGestureOwnerBinding("default", "back", "left", "browser_back")
        with patch("ui.backend.save_config"):
            backend.setGestureOwnerEnabled("back", False)

        self.assertEqual(xbutton1_action(), original)

    def test_set_and_get_gesture_owner_binding_round_trip(self):
        backend = self._make_backend()
        with patch("core.config.save_config"):
            backend.setGestureOwnerBinding("default", "forward", "up", "mission_control")

        bindings = {
            entry["direction"]: entry["actionId"]
            for entry in backend.gestureOwnerBindings("default", "forward")
        }
        self.assertEqual(bindings["up"], "mission_control")
        self.assertEqual(bindings["left"], "none")
        self.assertEqual(bindings["right"], "none")
        self.assertEqual(bindings["down"], "none")

    def test_set_gesture_owner_binding_rejects_unknown_owner_or_direction(self):
        backend = self._make_backend()
        with patch("core.config.save_config") as save_mock:
            backend.setGestureOwnerBinding("default", "trigger", "up", "mission_control")
            backend.setGestureOwnerBinding("default", "back", "diagonal", "mission_control")
        save_mock.assert_not_called()

    def test_gesture_owner_bindings_unknown_owner_returns_empty(self):
        backend = self._make_backend()
        self.assertEqual(backend.gestureOwnerBindings("default", "trigger"), [])

    def test_gesture_hold_floor_ms_default(self):
        backend = self._make_backend()
        self.assertEqual(backend.gestureHoldFloorMs, 80)

    def test_set_gesture_hold_floor_ms_clamps_and_persists(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config") as save_mock:
            backend.setGestureHoldFloorMs(-25)
        save_mock.assert_called_once()
        self.assertEqual(backend.gestureHoldFloorMs, 0)

    def test_set_gesture_hold_floor_ms_noop_when_unchanged(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setGestureHoldFloorMs(120)

        with patch("ui.backend.save_config") as save_mock:
            backend.setGestureHoldFloorMs(120)
        save_mock.assert_not_called()

    def test_gesture_eligible_owners_defaults_permissive_without_device(self):
        backend = self._make_backend()
        self.assertEqual(set(backend.gestureEligibleOwners), {"back", "forward", "middle"})

    def test_gesture_eligible_owners_narrowed_by_device_capability(self):
        backend = self._make_backend(
            engine=_FakeEngine(device_connected=True, connected_device=self._mx_anywhere_2s())
        )
        self.assertEqual(backend.gestureEligibleOwners, ["forward"])

    def test_gesture_eligible_owners_empty_when_device_lacks_capability(self):
        device = SimpleNamespace(
            key="mx_master_3s",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_3s",
            supported_buttons=("middle", "xbutton1", "xbutton2"),
        )
        backend = self._make_backend(
            engine=_FakeEngine(device_connected=True, connected_device=device)
        )
        self.assertEqual(backend.gestureEligibleOwners, [])


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendTiltGestureTests(unittest.TestCase):
    """Tilt (horizontal-scroll) slide gesture toggle + namespaced binding get/set
    -- mirrors BackendPerButtonGestureTests, but for the tilt_left/tilt_right
    owners hosted on the hscroll pulse stream instead of a per-button event tap."""

    def _make_backend(self, engine=None, cfg=None):
        loaded_config = copy.deepcopy(cfg or DEFAULT_CONFIG)
        with (
            patch("ui.backend.load_config", return_value=loaded_config),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            return Backend(engine=engine)

    def _mx_anywhere_2s_tilt(self):
        return SimpleNamespace(
            key="mx_anywhere_2s",
            display_name="MX Anywhere 2S",
            dpi_min=200,
            dpi_max=4000,
            ui_layout="mx_anywhere_2s",
            supported_buttons=(
                "middle", "xbutton1", "xbutton2", "hscroll_left", "hscroll_right",
                "gesture_tilt_left_left", "gesture_tilt_left_right",
                "gesture_tilt_left_up", "gesture_tilt_left_down",
            ),
        )

    def test_tilt_gesture_mode_off_by_default(self):
        backend = self._make_backend()
        self.assertEqual(backend.tiltGestureEnabledOwners, [])
        bindings = backend.tiltGestureOwnerBindings("default", "tilt_left")
        self.assertTrue(all(entry["actionId"] == "none" for entry in bindings))

    def test_set_tilt_gesture_owner_enabled_persists_and_notifies(self):
        backend = self._make_backend()
        settings_changed = []
        backend.settingsChanged.connect(lambda: settings_changed.append(True))

        with patch("ui.backend.save_config") as save_mock:
            backend.setTiltGestureOwnerEnabled("tilt_left", True)

        save_mock.assert_called_once()
        self.assertEqual(backend.tiltGestureEnabledOwners, ["tilt_left"])
        self.assertEqual(len(settings_changed), 1)

    def test_set_tilt_gesture_owner_enabled_noop_when_unchanged(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", True)

        with patch("ui.backend.save_config") as save_mock:
            backend.setTiltGestureOwnerEnabled("tilt_left", True)

        save_mock.assert_not_called()

    def test_set_tilt_gesture_owner_enabled_rejects_unknown_owner(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config") as save_mock:
            # "back" is a per-button owner, not a tilt owner.
            backend.setTiltGestureOwnerEnabled("back", True)
        save_mock.assert_not_called()
        self.assertEqual(backend.tiltGestureEnabledOwners, [])

    def test_set_tilt_gesture_owner_enabled_reruns_engine_mapping_reload(self):
        engine = _FakeEngine()
        backend = self._make_backend(engine=engine)
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_right", True)
        self.assertEqual(engine.reload_mappings_count, 1)

    def test_tilt_and_button_owner_enabled_flags_are_independent(self):
        """tilt_left/tilt_right share the gesture_owner_enabled dict with
        back/forward/middle (disjoint keys) -- toggling one must not leak
        into the other's enabled-owner list."""
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", True)
            backend.setGestureOwnerEnabled("forward", True)

        self.assertEqual(backend.tiltGestureEnabledOwners, ["tilt_left"])
        self.assertEqual(backend.gestureEnabledOwners, ["forward"])

    def test_toggle_off_does_not_clear_tilt_direction_bindings(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", True)
        with patch("core.config.save_config"):
            backend.setTiltGestureOwnerBinding("default", "tilt_left", "up", "mission_control")
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", False)

        self.assertEqual(backend.tiltGestureEnabledOwners, [])
        bindings = {
            entry["direction"]: entry["actionId"]
            for entry in backend.tiltGestureOwnerBindings("default", "tilt_left")
        }
        self.assertEqual(bindings["up"], "mission_control")

    def test_toggle_off_does_not_touch_hscroll_tap_mapping(self):
        backend = self._make_backend()

        def hscroll_left_action():
            mappings = backend.getProfileMappings("default")
            return next(m["actionId"] for m in mappings if m["key"] == "hscroll_left")

        original = hscroll_left_action()
        self.assertEqual(original, "browser_back")  # DEFAULT_CONFIG value, sanity check

        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", True)
        with patch("core.config.save_config"):
            backend.setTiltGestureOwnerBinding("default", "tilt_left", "left", "mission_control")
        with patch("ui.backend.save_config"):
            backend.setTiltGestureOwnerEnabled("tilt_left", False)

        self.assertEqual(hscroll_left_action(), original)

    def test_set_and_get_tilt_gesture_owner_binding_round_trip(self):
        backend = self._make_backend()
        with patch("core.config.save_config"):
            backend.setTiltGestureOwnerBinding("default", "tilt_right", "up", "mission_control")

        bindings = {
            entry["direction"]: entry["actionId"]
            for entry in backend.tiltGestureOwnerBindings("default", "tilt_right")
        }
        self.assertEqual(bindings["up"], "mission_control")
        self.assertEqual(bindings["left"], "none")
        self.assertEqual(bindings["right"], "none")
        self.assertEqual(bindings["down"], "none")

    def test_set_tilt_gesture_owner_binding_rejects_unknown_owner_or_direction(self):
        backend = self._make_backend()
        with patch("core.config.save_config") as save_mock:
            backend.setTiltGestureOwnerBinding("default", "trigger", "up", "mission_control")
            backend.setTiltGestureOwnerBinding("default", "tilt_left", "diagonal", "mission_control")
        save_mock.assert_not_called()

    def test_tilt_gesture_owner_bindings_unknown_owner_returns_empty(self):
        backend = self._make_backend()
        self.assertEqual(backend.tiltGestureOwnerBindings("default", "trigger"), [])

    def test_tilt_gesture_release_ms_default(self):
        backend = self._make_backend()
        self.assertEqual(backend.tiltGestureReleaseMs, 150)

    def test_set_tilt_gesture_release_ms_clamps_and_persists(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config") as save_mock:
            backend.setTiltGestureReleaseMs(10)
        save_mock.assert_called_once()
        self.assertEqual(backend.tiltGestureReleaseMs, 50)

    def test_set_tilt_gesture_release_ms_noop_when_unchanged(self):
        backend = self._make_backend()
        with patch("ui.backend.save_config"):
            backend.setTiltGestureReleaseMs(200)

        with patch("ui.backend.save_config") as save_mock:
            backend.setTiltGestureReleaseMs(200)
        save_mock.assert_not_called()

    def test_tilt_gesture_eligible_owners_defaults_permissive_without_device(self):
        backend = self._make_backend()
        self.assertEqual(set(backend.tiltGestureEligibleOwners), {"tilt_left", "tilt_right"})

    def test_tilt_gesture_eligible_owners_narrowed_by_device_capability(self):
        backend = self._make_backend(
            engine=_FakeEngine(device_connected=True, connected_device=self._mx_anywhere_2s_tilt())
        )
        self.assertEqual(backend.tiltGestureEligibleOwners, ["tilt_left"])

    def test_tilt_gesture_eligible_owners_empty_when_device_lacks_capability(self):
        device = SimpleNamespace(
            key="mx_master_3s",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master_3s",
            supported_buttons=("middle", "xbutton1", "xbutton2", "hscroll_left", "hscroll_right"),
        )
        backend = self._make_backend(
            engine=_FakeEngine(device_connected=True, connected_device=device)
        )
        self.assertEqual(backend.tiltGestureEligibleOwners, [])


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendLoginStartupTests(unittest.TestCase):
    def test_init_calls_sync_from_config_when_supported(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["start_at_login"] = True
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config") as sync_mock,
        ):
            Backend(engine=None)
        sync_mock.assert_called_once_with(True)

    def test_init_clears_start_at_login_when_sync_fails(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["start_at_login"] = True
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config") as save_mock,
            patch("ui.backend.supports_login_startup", return_value=True),
            patch(
                "ui.backend.sync_login_startup_from_config",
                side_effect=RuntimeError("bootstrap failed"),
            ),
        ):
            backend = Backend(engine=None)

        self.assertFalse(backend.startAtLogin)
        save_mock.assert_called_once()

    def test_init_sync_failure_keeps_disabled_config_disabled(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["start_at_login"] = False
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config") as save_mock,
            patch("ui.backend.supports_login_startup", return_value=True),
            patch(
                "ui.backend.sync_login_startup_from_config",
                side_effect=RuntimeError("bootout failed"),
            ),
        ):
            backend = Backend(engine=None)

        self.assertFalse(backend.startAtLogin)
        save_mock.assert_not_called()

    def test_init_clears_start_at_login_when_unsupported(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["start_at_login"] = True
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
            patch("ui.backend.sync_login_startup_from_config") as sync_mock,
        ):
            backend = Backend(engine=None)
        sync_mock.assert_not_called()
        self.assertFalse(backend.startAtLogin)

    def test_set_start_at_login_calls_apply(self):
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config"),
            patch("ui.backend.apply_login_startup") as apply_mock,
        ):
            backend = Backend(engine=None)
            backend.setStartAtLogin(True)

        apply_mock.assert_called_once_with(True)
        self.assertTrue(backend.startAtLogin)

    def test_set_start_at_login_keeps_config_when_os_apply_fails(self):
        status_messages = []
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config") as save_mock,
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config"),
            patch("ui.backend.apply_login_startup", side_effect=RuntimeError("denied")),
        ):
            backend = Backend(engine=None)
            backend.statusMessage.connect(status_messages.append)
            backend.setStartAtLogin(True)

        save_mock.assert_not_called()
        self.assertFalse(backend.startAtLogin)
        self.assertEqual(status_messages, ["Failed to update login item: denied"])

    def test_set_start_at_login_rolls_back_os_when_config_save_fails(self):
        status_messages = []
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config", side_effect=RuntimeError("disk full")),
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config"),
            patch("ui.backend.apply_login_startup") as apply_mock,
        ):
            backend = Backend(engine=None)
            backend.statusMessage.connect(status_messages.append)
            backend.setStartAtLogin(True)

        self.assertEqual([c.args for c in apply_mock.call_args_list], [(True,), (False,)])
        self.assertFalse(backend.startAtLogin)
        self.assertEqual(status_messages, ["Failed to save login item setting: disk full"])

    def test_set_start_at_login_reports_inconsistent_state_when_rollback_fails(self):
        status_messages = []
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config", side_effect=RuntimeError("disk full")),
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config"),
            patch(
                "ui.backend.apply_login_startup",
                side_effect=[None, RuntimeError("rollback failed")],
            ) as apply_mock,
        ):
            backend = Backend(engine=None)
            backend.statusMessage.connect(status_messages.append)
            backend.setStartAtLogin(True)

        self.assertEqual([c.args for c in apply_mock.call_args_list], [(True,), (False,)])
        self.assertFalse(backend.startAtLogin)
        self.assertEqual(
            status_messages,
            ["Start-at-login state is inconsistent; please restart Mouser to recover."],
        )

    def test_set_start_minimized_does_not_call_apply_login_startup(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["start_at_login"] = True
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=True),
            patch("ui.backend.sync_login_startup_from_config"),
            patch("ui.backend.apply_login_startup") as apply_mock,
        ):
            backend = Backend(engine=None)
            apply_mock.reset_mock()
            backend.setStartMinimized(False)

        apply_mock.assert_not_called()
        self.assertFalse(backend.startMinimized)


if __name__ == "__main__":
    unittest.main()
