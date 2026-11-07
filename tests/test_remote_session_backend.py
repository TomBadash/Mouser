import copy
import ctypes
import unittest
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.config import DEFAULT_CONFIG
from test_backend import Backend, _FakeEngine, _ensure_qapp


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class RemoteSessionBackendTests(unittest.TestCase):
    def _make_backend(self):
        self.app = _ensure_qapp()
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["check_for_updates"] = False
        engine = _FakeEngine()
        engine.remote_paused = False
        engine.remote_session_state = "local"
        engine.refresh_remote_session = Mock()
        engine.set_remote_session_change_callback = Mock(
            side_effect=lambda cb: setattr(engine, "session_callback", cb),
        )
        with (
            patch("ui.backend.load_config", return_value=cfg),
            patch("ui.backend.save_config"),
            patch("ui.backend.supports_login_startup", return_value=False),
        ):
            backend = Backend(engine=engine)
        return backend, engine

    def test_warning_only_once_until_confirmed_local_return(self):
        backend, engine = self._make_backend()
        warnings = []
        backend.remoteSessionWarning.connect(warnings.append)

        def notify(state, paused):
            engine.remote_session_state = state
            engine.remote_paused = paused
            engine.session_callback(state, paused)
            self.app.processEvents()
            self.assertEqual(backend.remoteSessionState, state)
            self.assertEqual(backend.remotePaused, paused)

        notify("remote", True)
        notify("remote", True)  # reconnect
        notify("unknown", True)  # transient query failure
        notify("remote", False)  # opt out
        notify("remote", True)  # opt back in, same remote period
        self.assertEqual(warnings, ["session.remote_warning"])
        notify("local", False)
        notify("unknown", True)
        notify("remote", True)
        self.assertEqual(warnings, ["session.remote_warning", "session.unknown_warning"])

    def test_policy_setting_is_saved_and_rechecked_immediately(self):
        backend, engine = self._make_backend()
        with patch("ui.backend.save_config") as save:
            backend.setPauseInRemoteSession(False)
        self.assertFalse(backend.pauseInRemoteSession)
        self.assertIs(engine.cfg, backend._cfg)
        self.assertFalse(engine.cfg["settings"]["pause_in_remote_session"])
        save.assert_called_once_with(backend._cfg)
        engine.refresh_remote_session.assert_called_once()


@unittest.skipIf(Backend is None, "PySide6 not installed in test environment")
class WindowsSessionMonitorTests(unittest.TestCase):
    def _make_monitor(self, wts=None, error=None):
        from ui import windows_session_monitor as module
        engine = SimpleNamespace(refresh_remote_session=Mock())
        app = Mock()
        window = SimpleNamespace(winId=lambda: 123)
        wts = wts or SimpleNamespace(
            WTSRegisterSessionNotification=Mock(return_value=True),
            WTSUnRegisterSessionNotification=Mock(),
        )
        with (
            patch.object(module.ctypes, "WinDLL", return_value=wts,
                         side_effect=error, create=True),
            patch.object(module, "QTimer") as timer,
        ):
            monitor = module.WindowsSessionMonitor(engine, window, app)
        return module, monitor, engine, app, wts, timer

    def test_watches_own_window_and_rechecks_after_connect_notification(self):
        module, monitor, engine, app, wts, timer = self._make_monitor()
        wts.WTSRegisterSessionNotification.assert_called_once_with(123, 0)
        timer.return_value.setInterval.assert_called_once_with(1000)
        timer.return_value.timeout.connect.assert_called_once_with(engine.refresh_remote_session)
        msg = wintypes.MSG()
        msg.message = 0x02B1
        msg.hWnd = 456
        monitor.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
        engine.refresh_remote_session.assert_not_called()
        msg.hWnd = 123
        with patch.object(module.QTimer, "singleShot") as deferred:
            self.assertEqual(monitor.nativeEventFilter(
                b"windows_generic_MSG", ctypes.addressof(msg)), (False, 0))
        engine.refresh_remote_session.assert_called_once()
        deferred.call_args.args[1]()
        self.assertEqual(engine.refresh_remote_session.call_count, 2)
        monitor.stop()
        monitor.stop()
        wts.WTSUnRegisterSessionNotification.assert_called_once_with(123)
        app.removeNativeEventFilter.assert_called_with(monitor)

    def test_registration_failure_still_starts_fallback_timer(self):
        _, monitor, _, _, wts, timer = self._make_monitor(error=OSError)
        self.assertFalse(monitor._registered)
        timer.return_value.start.assert_called_once()
        monitor.stop()
        wts.WTSUnRegisterSessionNotification.assert_not_called()


if __name__ == "__main__":
    unittest.main()
