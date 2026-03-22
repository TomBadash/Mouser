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
