"""Small Unix-domain control channel used without importing Qt."""
from __future__ import annotations

import getpass
import hashlib
import os
import socket
import tempfile
import threading


def control_socket_path(name: str) -> str:
    identity = f"{getpass.getuser()}\0{name}".encode("utf-8", errors="replace")
    suffix = hashlib.sha256(identity).hexdigest()[:16]
    filename = f"mouser-{name}-{suffix}.sock"
    candidate = os.path.join(tempfile.gettempdir(), filename)
    if len(candidate.encode("utf-8")) >= 100:
        candidate = os.path.join("/tmp", filename)
    return candidate


def send_control_message(name: str, message: str, timeout: float = 0.4) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(control_socket_path(name))
            connection.sendall(message.encode("utf-8") + b"\n")
        return True
    except OSError:
        return False


class LocalControlServer:
    def __init__(self, name: str, callback):
        self.name = name
        self.path = control_socket_path(name)
        self._callback = callback
        self._closed = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name=f"MouserControl-{name}",
        )

    def start(self) -> None:
        if send_control_message(self.name, "ping", timeout=0.15):
            raise RuntimeError(f"control server already active: {self.name}")
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        try:
            self._socket.bind(self.path)
            self._socket.listen(4)
            self._socket.settimeout(0.5)
        except BaseException:
            self._socket.close()
            raise
        self._thread.start()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._socket.close()
        except OSError:
            pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    payload = connection.recv(4096)
                    message = payload.partition(b"\n")[0].decode(
                        "utf-8", errors="replace"
                    )
                    if message and message != "ping":
                        self._callback(message)
                except Exception as exc:
                    print(f"[LocalControl] {self.name}: {exc}")
