"""Linux screenshot actions backed by the desktop portal or KDE Spectacle."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image
from PySide6.QtCore import QObject, QEventLoop, Qt, QTimer, QUrl, Signal, Slot

try:
    from PySide6.QtCore import SLOT
    from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
except Exception:  # pragma: no cover - depends on platform PySide6 build
    SLOT = None
    QDBusConnection = None
    QDBusInterface = None
    QDBusMessage = None

from ui.screenshot_common import (
    SCREENSHOT_ACTIONS,
    SCREENSHOT_CLIPBOARD_ACTIONS,
    SCREENSHOT_FILE_ACTIONS,
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_ACTIONS,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
    copy_image_to_clipboard,
    screenshot_file_path,
)


FULLSCREEN_TIMEOUT_SECONDS = 15
REGION_TIMEOUT_SECONDS = 300
PORTAL_RESPONSE_TIMEOUT_MS = REGION_TIMEOUT_SECONDS * 1000
PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
PORTAL_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
PORTAL_TARGET_SCREEN = 1
PORTAL_TARGET_AREA = 4


class ScreenshotError(RuntimeError):
    """Screenshot action failed."""


class ScreenshotCancelled(Exception):
    """Screenshot action was cancelled by the user."""


@dataclass(frozen=True)
class ScreenshotResult:
    action_id: str
    path: Path | None = None
    image: Image.Image | None = None


def is_gnome_desktop(environ: Mapping[str, str] | None = None) -> bool:
    env = environ or os.environ
    desktops = [
        part.strip().lower()
        for part in (env.get("XDG_CURRENT_DESKTOP") or "").replace(";", ":").split(":")
        if part.strip()
    ]
    return "gnome" in desktops


def select_linux_screenshot_backend(
    environ: Mapping[str, str] | None = None,
    portal_factory: Callable[[], "PortalScreenshotClient"] | None = None,
    spectacle_detector: Callable[
        [], "SpectacleScreenshotBackend | None"
    ] | None = None,
):
    if is_gnome_desktop(environ):
        portal = PortalScreenshotBackend.detect(client_factory=portal_factory)
        if portal is not None:
            return portal
    detector = spectacle_detector or SpectacleScreenshotBackend.detect
    return detector()


class SpectacleScreenshotBackend:
    def __init__(
        self,
        executable: str = "spectacle",
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        path_factory: Callable[[], Path] | None = None,
        temp_dir: Path | None = None,
    ):
        self.executable = executable
        self._runner = runner or subprocess.run
        self._path_factory = path_factory or screenshot_file_path
        self._temp_dir = temp_dir

    @classmethod
    def detect(cls) -> "SpectacleScreenshotBackend | None":
        executable = shutil.which("spectacle")
        if not executable:
            return None
        return cls(executable=executable)

    def command_for_action(self, action_id: str, output_path: Path) -> list[str]:
        if action_id not in SCREENSHOT_ACTIONS:
            raise ValueError(f"unknown screenshot action: {action_id}")
        mode = "-r" if action_id in SCREENSHOT_REGION_ACTIONS else "-f"
        return [self.executable, "-n", "-b", mode, "-o", str(output_path)]

    def timeout_for_action(self, action_id: str) -> int:
        if action_id in SCREENSHOT_REGION_ACTIONS:
            return REGION_TIMEOUT_SECONDS
        return FULLSCREEN_TIMEOUT_SECONDS

    def perform_action(self, action_id: str) -> ScreenshotResult:
        if action_id in SCREENSHOT_FILE_ACTIONS:
            path = self._path_factory()
            self.capture_to_path(action_id, path)
            return ScreenshotResult(action_id=action_id, path=path)
        if action_id in SCREENSHOT_CLIPBOARD_ACTIONS:
            image = self._capture_to_temp_image(action_id)
            return ScreenshotResult(action_id=action_id, image=image)
        raise ValueError(f"unknown screenshot action: {action_id}")

    def capture_to_path(self, action_id: str, output_path: Path) -> Path:
        cmd = self.command_for_action(action_id, output_path)
        try:
            completed = self._runner(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_for_action(action_id),
            )
        except FileNotFoundError as exc:
            raise ScreenshotError("Screenshot backend unavailable: Spectacle is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError("Screenshot timed out") from exc

        self._raise_for_completed(action_id, output_path, completed)
        return output_path

    def _capture_to_temp_image(self, action_id: str) -> Image.Image:
        temp_path = self._new_temp_path()
        try:
            self.capture_to_path(action_id, temp_path)
            with Image.open(temp_path) as image:
                return image.convert("RGBA")
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _new_temp_path(self) -> Path:
        temp_dir = None if self._temp_dir is None else str(self._temp_dir)
        handle = tempfile.NamedTemporaryFile(
            prefix="mouser-screenshot-",
            suffix=".png",
            dir=temp_dir,
            delete=False,
        )
        handle.close()
        path = Path(handle.name)
        path.unlink()
        return path

    def _raise_for_completed(
        self,
        action_id: str,
        output_path: Path,
        completed: subprocess.CompletedProcess,
    ) -> None:
        output_missing = not output_path.exists() or output_path.stat().st_size <= 0
        combined_output = _combined_process_output(completed)
        if "not authorized" in combined_output.lower():
            _unlink_empty_file(output_path)
            raise ScreenshotError(
                "Screenshot failed: Spectacle is not authorized to take screenshots. "
                "On Nobara/KDE, remove ~/.local/share/applications/org.kde.spectacle.desktop "
                "or check KDE screenshot permissions."
            )
        if completed.returncode != 0:
            _unlink_empty_file(output_path)
            if action_id in SCREENSHOT_REGION_ACTIONS and output_missing:
                raise ScreenshotCancelled()
            detail = combined_output.strip() or f"Spectacle exited with status {completed.returncode}"
            raise ScreenshotError(f"Screenshot failed: {detail}")
        if output_missing:
            _unlink_empty_file(output_path)
            if action_id in SCREENSHOT_REGION_ACTIONS:
                raise ScreenshotCancelled()
            raise ScreenshotError("Screenshot failed: Spectacle did not create an image")


class PortalScreenshotBackend:
    def __init__(
        self,
        client_factory: Callable[[], "PortalScreenshotClient"] | None = None,
        path_factory: Callable[[], Path] | None = None,
    ):
        self._client_factory = client_factory or PortalScreenshotClient
        self._path_factory = path_factory or screenshot_file_path

    @classmethod
    def detect(
        cls,
        client_factory: Callable[[], "PortalScreenshotClient"] | None = None,
    ) -> "PortalScreenshotBackend | None":
        factory = client_factory or PortalScreenshotClient
        try:
            client = factory()
            targets = client.available_targets()
        except Exception:
            return None
        required = PORTAL_TARGET_SCREEN | PORTAL_TARGET_AREA
        if targets & required != required:
            return None
        return cls(client_factory=factory)

    def perform_action(self, action_id: str) -> ScreenshotResult:
        client = self._client_factory()
        uri = client.request_screenshot(
            action_id,
            timeout_ms=self.timeout_for_action(action_id),
        )
        if not uri:
            raise ScreenshotError(
                "Screenshot failed: portal response did not include an image URI"
            )
        source = portal_file_uri_to_path(uri)
        if action_id in SCREENSHOT_FILE_ACTIONS:
            target = self._path_factory()
            shutil.copyfile(source, target)
            return ScreenshotResult(action_id=action_id, path=target)
        if action_id in SCREENSHOT_CLIPBOARD_ACTIONS:
            with Image.open(source) as image:
                return ScreenshotResult(action_id=action_id, image=image.convert("RGBA"))
        raise ValueError(f"unknown screenshot action: {action_id}")

    def timeout_for_action(self, action_id: str) -> int:
        return PORTAL_RESPONSE_TIMEOUT_MS


class PortalScreenshotClient(QObject):
    def __init__(
        self,
        bus=None,
        token_factory: Callable[[], str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        if QDBusConnection is None or QDBusInterface is None:
            raise ScreenshotError("Screenshot backend unavailable: QtDBus is not available")
        self._bus = bus or QDBusConnection.sessionBus()
        if not self._bus.isConnected():
            raise ScreenshotError(
                "Screenshot backend unavailable: D-Bus session bus is not connected"
            )
        self._token_factory = token_factory or (lambda: f"mouser_{uuid.uuid4().hex}")
        self._response_code: int | None = None
        self._response_results = None
        self._response_loop: QEventLoop | None = None

    def available_targets(self) -> int:
        interface = QDBusInterface(
            PORTAL_SERVICE,
            PORTAL_PATH,
            "org.freedesktop.DBus.Properties",
            self._bus,
        )
        reply = interface.call("Get", PORTAL_SCREENSHOT_INTERFACE, "AvailableTargets")
        if _is_dbus_error(reply):
            raise ScreenshotError(f"Screenshot portal unavailable: {_dbus_error_text(reply)}")
        args = reply.arguments()
        if not args:
            return 0
        return int(_unwrap_dbus_value(args[0]) or 0)

    def request_screenshot(
        self,
        action_id: str,
        timeout_ms: int = PORTAL_RESPONSE_TIMEOUT_MS,
    ) -> str:
        token = self._token_factory()
        request_path = portal_request_path(self._bus.baseService(), token)
        self._response_code = None
        self._response_results = None

        connected = self._bus.connect(
            PORTAL_SERVICE,
            request_path,
            PORTAL_REQUEST_INTERFACE,
            "Response",
            self,
            SLOT("_handle_response(uint,QVariantMap)"),
        )
        if not connected:
            raise ScreenshotError("Screenshot failed: could not listen for portal response")

        try:
            interface = QDBusInterface(
                PORTAL_SERVICE,
                PORTAL_PATH,
                PORTAL_SCREENSHOT_INTERFACE,
                self._bus,
            )
            options = portal_options_for_action(action_id, token)
            reply = interface.call("Screenshot", "", options)
            if _is_dbus_error(reply):
                raise ScreenshotError(f"Screenshot failed: {_dbus_error_text(reply)}")
            if self._response_code is None:
                loop = QEventLoop()
                self._response_loop = loop
                QTimer.singleShot(timeout_ms, loop.quit)
                loop.exec()
        finally:
            self._response_loop = None
            self._bus.disconnect(
                PORTAL_SERVICE,
                request_path,
                PORTAL_REQUEST_INTERFACE,
                "Response",
                self,
                SLOT("_handle_response(uint,QVariantMap)"),
            )

        if self._response_code is None:
            raise ScreenshotError(
                "Screenshot failed: GNOME portal did not respond. "
                "Open the Mouser window once and retry if this is the first "
                "screenshot permission request."
            )
        if self._response_code == 1:
            raise ScreenshotCancelled()
        if self._response_code != 0:
            raise ScreenshotError(f"Screenshot failed: portal response {self._response_code}")
        uri = (_unwrap_dbus_value(self._response_results) or {}).get("uri")
        if not uri:
            raise ScreenshotError("Screenshot failed: portal response did not include an image URI")
        return str(_unwrap_dbus_value(uri))

    @Slot("uint", "QVariantMap")
    def _handle_response(self, response: int, results) -> None:
        self._response_code = int(response)
        self._response_results = results
        if self._response_loop is not None:
            self._response_loop.quit()


_DEFAULT_BACKEND = object()


class LinuxScreenshotController(QObject):
    _requestAction = Signal(str)
    _workerFinished = Signal(str, object, str)

    def __init__(
        self,
        backend=_DEFAULT_BACKEND,
        status_callback: Callable[[str], None] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._backend = (
            select_linux_screenshot_backend() if backend is _DEFAULT_BACKEND else backend
        )
        self._status_callback = status_callback
        self._thread_factory = thread_factory or threading.Thread
        self._busy = False
        self._requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)
        self._workerFinished.connect(self._finish_worker, Qt.ConnectionType.QueuedConnection)

    def request_action(self, action_id: str) -> None:
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if self._backend is None:
            self._emit_status("Screenshot backend unavailable")
            return
        if self._busy:
            self._emit_status("Finish the current screenshot first")
            return
        self._busy = True
        thread = self._thread_factory(
            target=self._run_action,
            args=(action_id,),
            daemon=True,
            name="LinuxScreenshot",
        )
        thread.start()

    def _run_action(self, action_id: str) -> None:
        try:
            result = self._backend.perform_action(action_id)
            self._workerFinished.emit(action_id, result, "")
        except ScreenshotCancelled:
            self._workerFinished.emit(action_id, None, "cancelled")
        except ScreenshotError as exc:
            self._workerFinished.emit(action_id, None, str(exc))
        except Exception as exc:
            print(f"[Screenshot] Linux screenshot failed: {exc}")
            traceback.print_exc()
            self._workerFinished.emit(action_id, None, f"Screenshot failed: {exc}")

    @Slot(str, object, str)
    def _finish_worker(self, action_id: str, result: ScreenshotResult | None, error: str) -> None:
        self._busy = False
        if error == "cancelled":
            self._emit_status("Screenshot cancelled")
            return
        if error:
            self._emit_status(error)
            return
        if result is None:
            return
        try:
            if action_id in (SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_CLIP):
                if result.image is None:
                    raise ScreenshotError("Screenshot failed: no image was captured")
                copy_image_to_clipboard(result.image)
                self._emit_status("Screenshot copied to clipboard")
            elif action_id in (SCREENSHOT_REGION_FILE, SCREENSHOT_FULL_FILE):
                if result.path is None:
                    raise ScreenshotError("Screenshot failed: no file was captured")
                self._emit_status(f"Screenshot saved to {result.path}")
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] Linux delivery failed: {exc}")

    def _emit_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)


def _combined_process_output(completed: subprocess.CompletedProcess) -> str:
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return f"{stdout}\n{stderr}".strip()


def _unlink_empty_file(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size <= 0:
            path.unlink()
    except OSError:
        pass


def portal_options_for_action(action_id: str, token: str) -> dict:
    if action_id in SCREENSHOT_REGION_ACTIONS:
        target = PORTAL_TARGET_AREA
    elif action_id in SCREENSHOT_ACTIONS:
        target = PORTAL_TARGET_SCREEN
    else:
        raise ValueError(f"unknown screenshot action: {action_id}")
    return {
        "handle_token": token,
        "interactive": True,
        "modal": True,
        "target": target,
    }


def portal_request_path(base_service: str, token: str) -> str:
    sender = (base_service or "").strip()
    if not sender:
        raise ScreenshotError(
            "Screenshot backend unavailable: D-Bus session has no unique sender name"
        )
    if sender.startswith(":"):
        sender = sender[1:]
    sender = sender.replace(".", "_")
    return f"{PORTAL_PATH}/request/{sender}/{token}"


def portal_file_uri_to_path(uri: str) -> Path:
    url = QUrl(uri)
    if not url.isLocalFile():
        raise ScreenshotError("Screenshot failed: portal returned a non-file image URI")
    path = Path(url.toLocalFile())
    if not path.exists():
        raise ScreenshotError("Screenshot failed: portal image file was not available")
    return path


def _unwrap_dbus_value(value):
    current = value
    for attr in ("variant", "value"):
        method = getattr(current, attr, None)
        if callable(method):
            current = method()
    return current


def _is_dbus_error(reply) -> bool:
    if QDBusMessage is not None and hasattr(reply, "type"):
        try:
            return reply.type() == QDBusMessage.MessageType.ErrorMessage
        except Exception:
            return False
    return False


def _dbus_error_text(reply) -> str:
    for attr in ("errorMessage", "errorName"):
        method = getattr(reply, attr, None)
        if callable(method):
            value = method()
            if value:
                return str(value)
    return "D-Bus call failed"
