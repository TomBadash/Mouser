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


if __name__ == "__main__":
    unittest.main()
