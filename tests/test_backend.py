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


if __name__ == "__main__":
    unittest.main()
