import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

try:
    import main_qml
    from PySide6.QtWidgets import QApplication
    from PySide6.QtNetwork import QLocalServer
except Exception:  # pragma: no cover - env without PySide6 / project deps
    main_qml = None
    QApplication = None
    QLocalServer = None


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        return QApplication(sys.argv)
    return app


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class SingleInstanceServerNameTests(unittest.TestCase):
    def test_server_name_format_and_stability(self):
        with patch.object(main_qml.getpass, "getuser", return_value="testuser"):
            a = main_qml._single_instance_server_name()
            b = main_qml._single_instance_server_name()
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("mouser_instance_"))
        self.assertEqual(len(a), len("mouser_instance_") + 16)


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class TryActivateExistingTests(unittest.TestCase):
    @patch("main_qml.QLocalSocket")
    def test_returns_false_when_not_connected(self, mock_sock_cls):
        sock = MagicMock()
        sock.waitForConnected.return_value = False
        mock_sock_cls.return_value = sock
        self.assertFalse(main_qml._try_activate_existing_instance("pipe_name"))
        sock.write.assert_not_called()

    @patch("main_qml.QLocalSocket")
    def test_returns_true_and_sends_payload_when_connected(self, mock_sock_cls):
        sock = MagicMock()
        sock.waitForConnected.return_value = True
        sock.waitForBytesWritten.return_value = True
        mock_sock_cls.return_value = sock
        self.assertTrue(main_qml._try_activate_existing_instance("pipe_name"))
        sock.connectToServer.assert_called_once_with("pipe_name")
        sock.write.assert_called_once_with(main_qml._SINGLE_INSTANCE_ACTIVATE_MSG)
        sock.disconnectFromServer.assert_called_once()


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class SingleInstanceAcquireTests(unittest.TestCase):
    @patch("main_qml._try_activate_existing_instance", return_value=True)
    def test_secondary_instance_returns_exit_zero(self, _):
        app = _ensure_qapp()
        server, code = main_qml._single_instance_acquire(app, "any_name")
        self.assertIsNone(server)
        self.assertEqual(code, 0)

    @patch("main_qml._try_activate_existing_instance", return_value=False)
    @patch.object(main_qml.QLocalServer, "removeServer")
    def test_primary_gets_server_when_listen_succeeds(self, _remove, _try_act):
        mock_server = MagicMock()
        mock_server.listen.return_value = True
        with patch("main_qml.QLocalServer", return_value=mock_server):
            app = _ensure_qapp()
            server, code = main_qml._single_instance_acquire(app, "unique_name")
        self.assertIsNone(code)
        self.assertIs(server, mock_server)
        mock_server.listen.assert_called_once_with("unique_name")

    def test_primary_integration_unique_pipe(self):
        app = _ensure_qapp()
        name = f"mouser_unittest_{uuid.uuid4().hex}"
        server, code = main_qml._single_instance_acquire(app, name)
        self.addCleanup(lambda: (server.close(), QLocalServer.removeServer(name)))
        self.assertIsNone(code)
        self.assertIsNotNone(server)
        self.assertTrue(server.isListening())

        server2, code2 = main_qml._single_instance_acquire(app, name)
        self.assertEqual(code2, 0)
        self.assertIsNone(server2)


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class DrainActivateSocketTests(unittest.TestCase):
    def test_noop_when_sock_is_none(self):
        main_qml._drain_local_activate_socket(None)

    def test_drains_when_sock_present(self):
        mock_sock = MagicMock()
        main_qml._drain_local_activate_socket(mock_sock)
        mock_sock.waitForReadyRead.assert_called_once_with(300)
        mock_sock.readAll.assert_called_once()
        mock_sock.deleteLater.assert_called_once()
