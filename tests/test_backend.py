import copy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import DEFAULT_CONFIG

try:
    from PySide6.QtCore import QCoreApplication
    from ui.backend import Backend
except ModuleNotFoundError:
    Backend = None
    QCoreApplication = None


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


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendDeviceLayoutTests(unittest.TestCase):
    def _make_backend(self, engine=None):
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
        ):
            return Backend(engine=engine)

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

    def test_disconnected_override_request_does_not_persist(self):
        backend = self._make_backend()
        backend._connected_device_key = "mx_master_3"
        backend.setDeviceLayoutOverride("mx_master")

        overrides = backend._cfg.get("settings", {}).get("device_layout_overrides", {})
        self.assertEqual(overrides, {})

    def test_disconnect_clears_stale_linux_device_identity_and_layout(self):
        device = SimpleNamespace(
            key="mx_master_3",
            display_name="MX Master 3S",
            dpi_min=200,
            dpi_max=8000,
            ui_layout="mx_master",
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
            self.assertEqual(backend.effectiveDeviceLayoutKey, "mx_master")
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
            ui_layout="mx_master",
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

    def test_init_wires_engine_status_callback_into_backend(self):
        engine = _FakeEngine()

        backend = self._make_backend(engine=engine)

        self.assertIsNotNone(engine.status_callback)
        self.assertIs(engine.status_callback.__self__, backend)
        self.assertIs(engine.status_callback.__func__, Backend._onEngineStatusMessage)

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
