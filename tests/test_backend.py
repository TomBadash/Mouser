import copy
import unittest
from unittest.mock import patch

from core.config import DEFAULT_CONFIG

try:
    from ui.backend import Backend
except ModuleNotFoundError:
    Backend = None


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class BackendDeviceLayoutTests(unittest.TestCase):
    def _make_backend(self):
        with (
            patch("ui.backend.load_config", return_value=copy.deepcopy(DEFAULT_CONFIG)),
            patch("ui.backend.save_config"),
        ):
            return Backend(engine=None)

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
class BackendAutostartTests(unittest.TestCase):
    def _make_backend(
        self,
        *,
        config=None,
        autostart_supported=True,
        launch_enabled=False,
    ):
        effective_config = copy.deepcopy(config or DEFAULT_CONFIG)
        with (
            patch("ui.backend.load_config", return_value=effective_config),
            patch("ui.backend.save_config") as save_config_mock,
            patch("ui.backend.autostart.is_supported", return_value=autostart_supported),
            patch(
                "ui.backend.autostart.is_launch_at_login_enabled",
                return_value=launch_enabled,
            ),
        ):
            backend = Backend(engine=None)
        return backend, save_config_mock

    def test_syncs_start_at_login_from_existing_launch_agent(self):
        backend, save_config_mock = self._make_backend(
            autostart_supported=True,
            launch_enabled=True,
        )

        self.assertTrue(backend.startAtLogin)
        save_config_mock.assert_called_once()

    def test_set_start_at_login_uses_current_hidden_start_preference(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["settings"]["start_minimized"] = False

        with (
            patch("ui.backend.load_config", return_value=config),
            patch("ui.backend.save_config"),
            patch("ui.backend.autostart.is_supported", return_value=True),
            patch("ui.backend.autostart.is_launch_at_login_enabled", return_value=False),
            patch("ui.backend.autostart.enable_launch_at_login") as enable_mock,
        ):
            backend = Backend(engine=None)
            backend.setStartAtLogin(True)

        enable_mock.assert_called_once_with(start_hidden=False)
        self.assertTrue(backend.startAtLogin)

    def test_set_start_minimized_refreshes_existing_login_item(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["settings"]["start_at_login"] = True
        config["settings"]["start_minimized"] = True

        with (
            patch("ui.backend.load_config", return_value=config),
            patch("ui.backend.save_config"),
            patch("ui.backend.autostart.is_supported", return_value=True),
            patch("ui.backend.autostart.is_launch_at_login_enabled", return_value=True),
            patch("ui.backend.autostart.enable_launch_at_login") as enable_mock,
        ):
            backend = Backend(engine=None)
            backend.setStartMinimized(False)

        enable_mock.assert_called_once_with(start_hidden=False)
        self.assertFalse(backend.startMinimized)


if __name__ == "__main__":
    unittest.main()
