import socket
import threading
import unittest

from core.process_bridge import (
    DaemonBridgeServer,
    _read_message,
    _write_message,
)


class FakeEngine:
    def __init__(self):
        self.cfg = {
            "settings": {
                "dpi": 1200,
                "smart_shift_mode": "ratchet",
                "smart_shift_enabled": False,
                "smart_shift_threshold": 25,
            }
        }
        self._current_profile = "default"
        self.connected_device = None
        self.device_connected = False
        self.enabled = True
        self.force_sensing_range = (20, 80)
        self.force_sensing_supported = True
        self.haptic_supported = True
        self.hid_features_ready = True
        self.smart_shift_supported = True
        self.last_dpi = None

    def set_dpi(self, value):
        self.last_dpi = value
        self.cfg["settings"]["dpi"] = value
        return value

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)


class ProcessBridgeTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.server = DaemonBridgeServer.__new__(DaemonBridgeServer)
        self.server._engine = self.engine
        self.server._on_shutdown = None
        self.server._state_provider = None
        self.server._token = "test-token"

    def test_remote_engine_reads_state_and_invokes_whitelisted_method(self):
        state = self.server._dispatch("get_state", [], {})
        self.assertTrue(state["haptic_supported"])
        self.assertEqual(state["force_sensing_range"], [20, 80])
        self.assertEqual(self.server._dispatch("set_dpi", [2400], {}), 2400)
        self.assertEqual(self.engine.last_dpi, 2400)

    def test_invalid_token_is_rejected(self):
        client, server_side = socket.socketpair()
        worker = threading.Thread(
            target=self.server._handle_connection,
            args=(server_side,),
        )
        worker.start()
        with client:
            _write_message(client, {
                "token": "wrong",
                "method": "get_state",
                "args": [],
                "kwargs": {},
            })
            response = _read_message(client)
        worker.join(timeout=1)
        self.assertFalse(response["ok"])
        self.assertIn("authentication failed", response["error"])

    def test_non_whitelisted_method_is_rejected(self):
        with self.assertRaisesRegex(Exception, "method is not allowed"):
            self.server._dispatch("__getattribute__", [], {})


if __name__ == "__main__":
    unittest.main()
