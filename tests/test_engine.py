import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import DEFAULT_CONFIG
from core.mouse_hook import MouseEvent


class _FakeMouseHook:
    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False

    def set_debug_callback(self, cb):
        self._debug_callback = cb

    def set_gesture_callback(self, cb):
        self._gesture_callback = cb

    def set_connection_change_callback(self, cb):
        self._connection_change_callback = cb

    def configure_gestures(self, **kwargs):
        self._gesture_config = kwargs

    def block(self, event_type):
        pass

    def register(self, event_type, callback):
        pass

    def reset_bindings(self):
        pass


class _FakeAppDetector:
    def __init__(self, callback):
        self.callback = callback


class EngineHorizontalScrollTests(unittest.TestCase):
    def _make_engine(self):
        from core.engine import Engine

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["hscroll_threshold"] = 1

        with (
            patch("core.engine.MouseHook", _FakeMouseHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_hscroll_desktop_action_uses_cooldown(self):
        engine = self._make_engine()
        handler = engine._make_hscroll_handler("space_left")

        with patch("core.engine.execute_action") as execute_action_mock:
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.00,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.05,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_LEFT,
                raw_data=1,
                timestamp=1.45,
            ))

        self.assertEqual(execute_action_mock.call_count, 2)

    def test_hscroll_accumulates_fractional_mac_deltas(self):
        engine = self._make_engine()
        handler = engine._make_hscroll_handler("space_right")

        with patch("core.engine.execute_action") as execute_action_mock:
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.35,
                timestamp=2.00,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.40,
                timestamp=2.02,
            ))
            handler(SimpleNamespace(
                event_type=MouseEvent.HSCROLL_RIGHT,
                raw_data=0.30,
                timestamp=2.04,
            ))

        self.assertEqual(execute_action_mock.call_count, 1)

    def test_connection_callback_receives_current_state_immediately(self):
        engine = self._make_engine()
        engine.hook.device_connected = True

        seen = []
        engine.set_connection_change_callback(seen.append)

        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()
