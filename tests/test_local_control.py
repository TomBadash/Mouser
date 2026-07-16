import threading
import time
import unittest
import uuid
import errno

from core.local_control import LocalControlServer, send_control_message


class LocalControlTests(unittest.TestCase):
    def test_round_trip_message(self):
        name = f"test-{uuid.uuid4().hex}"
        received = []
        event = threading.Event()

        def callback(message):
            received.append(message)
            event.set()

        server = LocalControlServer(name, callback)
        try:
            server.start()
        except OSError as exc:
            if exc.errno == errno.EPERM:
                self.skipTest("sandbox blocks Unix-domain listeners")
            raise
        try:
            self.assertTrue(send_control_message(name, "show"))
            self.assertTrue(event.wait(1.0))
            self.assertEqual(received, ["show"])
        finally:
            server.close()

    def test_stale_socket_is_reclaimed(self):
        name = f"test-{uuid.uuid4().hex}"
        first = LocalControlServer(name, lambda _message: None)
        try:
            first.start()
        except OSError as exc:
            if exc.errno == errno.EPERM:
                self.skipTest("sandbox blocks Unix-domain listeners")
            raise
        first.close()
        time.sleep(0.01)

        second = LocalControlServer(name, lambda _message: None)
        second.start()
        second.close()


if __name__ == "__main__":
    unittest.main()
