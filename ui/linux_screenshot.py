"""Linux screenshot actions backed by KWin, the desktop portal, or Spectacle."""
from __future__ import annotations

import os
import select
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from PIL import Image
from PySide6.QtCore import QObject, QEventLoop, QRect, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage

try:
    from PySide6.QtCore import SLOT
    from PySide6.QtDBus import (
        QDBusConnection,
        QDBusInterface,
        QDBusMessage,
        QDBusUnixFileDescriptor,
    )
except Exception:  # pragma: no cover - depends on platform PySide6 build
    SLOT = None
    QDBusConnection = None
    QDBusInterface = None
    QDBusMessage = None
    QDBusUnixFileDescriptor = None

from ui.screenshot_common import (
    SCREENSHOT_ACTIONS,
    SCREENSHOT_CLIPBOARD_ACTIONS,
    SCREENSHOT_FILE_ACTIONS,
    SCREENSHOT_FULL_ACTIONS,
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_ACTIONS,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
    copy_image_to_clipboard,
    save_image_to_file,
)
from ui.screenshot_overlay import (
    IntRect,
    RegionSelectionOverlay,
    rect_from_qrect,
    union_rect,
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

KWIN_SERVICE = "org.kde.KWin.ScreenShot2"
KWIN_PATH = "/org/kde/KWin/ScreenShot2"
KWIN_INTERFACE = "org.kde.KWin.ScreenShot2"
KWIN_REQUIRED_METHODS = frozenset({"CaptureWorkspace", "CaptureArea"})
KWIN_NOT_AUTHORIZED = "org.kde.KWin.ScreenShot2.Error.NoAuthorized"
KWIN_CANCELLED = "org.kde.KWin.ScreenShot2.Error.Cancelled"
SPECTACLE_REGION_GUIDANCE = (
    "Region was not saved. Press Enter/Accept in Spectacle to finish, or Esc to cancel."
)


class ScreenshotError(RuntimeError):
    """Screenshot action failed."""


class BackendUnavailable(ScreenshotError):
    """Screenshot backend is unavailable and the controller should try the next backend."""


class ScreenshotCancelled(Exception):
    """Screenshot action was cancelled by the user."""


@dataclass(frozen=True)
class ScreenshotResult:
    action_id: str
    image: Image.Image


def desktop_names(environ: Mapping[str, str] | None = None) -> list[str]:
    env = environ or os.environ
    raw = (env.get("XDG_CURRENT_DESKTOP") or "").replace(";", ":")
    return [part.strip().lower() for part in raw.split(":") if part.strip()]


def is_gnome_desktop(environ: Mapping[str, str] | None = None) -> bool:
    return "gnome" in desktop_names(environ)


def is_kde_desktop(environ: Mapping[str, str] | None = None) -> bool:
    names = desktop_names(environ)
    return any(name in {"kde", "plasma"} or "plasma" in name for name in names)


def select_linux_screenshot_backends(
    environ: Mapping[str, str] | None = None,
    kwin_detector: Callable[[], "KWinScreenshotBackend | None"] | None = None,
    portal_factory: Callable[[], "PortalScreenshotClient"] | None = None,
    spectacle_detector: Callable[
        [], "SpectacleScreenshotBackend | None"
    ] | None = None,
) -> list[object]:
    backends: list[object] = []
    if is_kde_desktop(environ):
        detector = kwin_detector or (
            lambda: KWinScreenshotBackend.detect(
                environ=environ,
                client_factory=None,
            )
        )
        backend = detector()
        if backend is not None:
            backends.append(backend)

    portal = PortalScreenshotBackend.detect(client_factory=portal_factory)
    if portal is not None:
        backends.append(portal)

    detector = spectacle_detector or SpectacleScreenshotBackend.detect
    spectacle = detector()
    if spectacle is not None:
        backends.append(spectacle)
    return backends


def select_linux_screenshot_backend(
    environ: Mapping[str, str] | None = None,
    portal_factory: Callable[[], "PortalScreenshotClient"] | None = None,
    spectacle_detector: Callable[
        [], "SpectacleScreenshotBackend | None"
    ] | None = None,
):
    backends = select_linux_screenshot_backends(
        environ=environ,
        portal_factory=portal_factory,
        spectacle_detector=spectacle_detector,
    )
    return backends[0] if backends else None


def _capture_for_action(backend, action_id: str) -> Image.Image:
    if action_id in SCREENSHOT_FULL_ACTIONS:
        return backend.capture_full()
    if action_id in SCREENSHOT_REGION_ACTIONS:
        return backend.capture_region(None)
    raise ValueError(f"unknown screenshot action: {action_id}")


class KWinScreenshotBackend:
    needs_mouser_region_selection = True

    def __init__(
        self,
        client_factory: Callable[[], "KWinScreenshotClient"] | None = None,
        probe_rect_factory: Callable[[], IntRect] | None = None,
    ):
        self._client_factory = client_factory or KWinScreenshotClient
        self._probe_rect_factory = probe_rect_factory or _default_probe_rect
        self._probe_ok: bool | None = None
        self._probe_error = "Screenshot backend unavailable: KWin ScreenShot2 is unavailable"

    @classmethod
    def detect(
        cls,
        environ: Mapping[str, str] | None = None,
        client_factory: Callable[[], "KWinScreenshotClient"] | None = None,
    ) -> "KWinScreenshotBackend | None":
        if not is_kde_desktop(environ):
            return None
        factory = client_factory or KWinScreenshotClient
        try:
            client = factory()
            methods = client.available_methods()
        except Exception:
            return None
        if not KWIN_REQUIRED_METHODS.issubset(methods):
            return None
        return cls(client_factory=factory)

    def probe(self) -> None:
        if self._probe_ok is True:
            return
        if self._probe_ok is False:
            raise BackendUnavailable(self._probe_error)
        try:
            self._client_factory().capture_area(
                self._probe_rect_factory(),
                options=kwin_capture_options(),
                timeout_seconds=FULLSCREEN_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            self._probe_ok = False
            detail = str(exc) or "KWin ScreenShot2 probe failed"
            self._probe_error = f"Screenshot backend unavailable: {detail}"
            raise BackendUnavailable(self._probe_error) from exc
        self._probe_ok = True

    def capture_full(self) -> Image.Image:
        self.probe()
        return self._client_factory().capture_workspace(
            options=kwin_capture_options(),
            timeout_seconds=FULLSCREEN_TIMEOUT_SECONDS,
        )

    def capture_region(self, rect: IntRect | None) -> Image.Image:
        if rect is None or rect.is_empty:
            raise ScreenshotError("Screenshot failed: no region was selected")
        self.probe()
        return self._client_factory().capture_area(
            rect,
            options=kwin_capture_options(),
            timeout_seconds=FULLSCREEN_TIMEOUT_SECONDS,
        )


class KWinScreenshotClient:
    def __init__(
        self,
        bus=None,
        interface_factory=None,
        unix_fd_factory=None,
        fd_reader: Callable[[int, int, float], bytes] | None = None,
    ):
        if (
            QDBusConnection is None
            or QDBusInterface is None
            or QDBusUnixFileDescriptor is None
        ):
            raise BackendUnavailable("QtDBus Unix file descriptor support is not available")
        self._bus = bus or QDBusConnection.sessionBus()
        if not self._bus.isConnected():
            raise BackendUnavailable("D-Bus session bus is not connected")
        self._interface_factory = interface_factory or QDBusInterface
        self._unix_fd_factory = unix_fd_factory or QDBusUnixFileDescriptor
        self._fd_reader = fd_reader or _read_fd_exact

    def available_methods(self) -> set[str]:
        interface = self._interface_factory(
            KWIN_SERVICE,
            KWIN_PATH,
            "org.freedesktop.DBus.Introspectable",
            self._bus,
        )
        reply = interface.call("Introspect")
        if _is_dbus_error(reply):
            raise BackendUnavailable(_dbus_error_text(reply))
        args = reply.arguments()
        if not args:
            return set()
        return kwin_methods_from_introspection(str(_unwrap_dbus_value(args[0])))

    def capture_workspace(
        self,
        options: Mapping[str, object] | None = None,
        timeout_seconds: int = FULLSCREEN_TIMEOUT_SECONDS,
    ) -> Image.Image:
        return self._capture(
            "CaptureWorkspace",
            [dict(options or kwin_capture_options())],
            timeout_seconds,
        )

    def capture_area(
        self,
        rect: IntRect,
        options: Mapping[str, object] | None = None,
        timeout_seconds: int = FULLSCREEN_TIMEOUT_SECONDS,
    ) -> Image.Image:
        return self._capture(
            "CaptureArea",
            [
                int(rect.left),
                int(rect.top),
                int(rect.width),
                int(rect.height),
                dict(options or kwin_capture_options()),
            ],
            timeout_seconds,
        )

    def _capture(
        self,
        method: str,
        args: Sequence[object],
        timeout_seconds: int,
    ) -> Image.Image:
        read_fd, write_fd = os.pipe()
        try:
            try:
                interface = self._interface_factory(
                    KWIN_SERVICE,
                    KWIN_PATH,
                    KWIN_INTERFACE,
                    self._bus,
                )
                if hasattr(interface, "setTimeout"):
                    interface.setTimeout(int(timeout_seconds * 1000))
                reply = interface.call(method, *args, self._unix_fd_factory(write_fd))
            finally:
                os.close(write_fd)
            if _is_dbus_error(reply):
                _raise_kwin_reply_error(reply)
            args = reply.arguments()
            if not args:
                raise ScreenshotError("Screenshot failed: KWin did not return image metadata")
            metadata = _metadata_dict(_unwrap_dbus_value(args[0]))
            byte_count = int(metadata.get("stride", 0)) * int(metadata.get("height", 0))
            if byte_count <= 0:
                raise ScreenshotError("Screenshot failed: KWin returned invalid image metadata")
            data = self._fd_reader(read_fd, byte_count, float(timeout_seconds))
            return kwin_raw_image_to_pil(metadata, data)
        finally:
            os.close(read_fd)


class SpectacleScreenshotBackend:
    needs_mouser_region_selection = False

    def __init__(
        self,
        executable: str = "spectacle",
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        temp_dir: Path | None = None,
    ):
        self.executable = executable
        self._runner = runner or subprocess.run
        self._temp_dir = temp_dir

    @classmethod
    def detect(cls) -> "SpectacleScreenshotBackend | None":
        executable = shutil.which("spectacle")
        if not executable:
            return None
        return cls(executable=executable)

    def probe(self) -> None:
        return None

    def capture_full(self) -> Image.Image:
        return self._capture_to_temp_image(SCREENSHOT_FULL_FILE)

    def capture_region(self, rect: IntRect | None = None) -> Image.Image:
        return self._capture_to_temp_image(SCREENSHOT_REGION_FILE)

    def perform_action(self, action_id: str) -> ScreenshotResult:
        return ScreenshotResult(action_id=action_id, image=_capture_for_action(self, action_id))

    def command_for_action(self, action_id: str, output_path: Path) -> list[str]:
        if action_id not in SCREENSHOT_ACTIONS:
            raise ValueError(f"unknown screenshot action: {action_id}")
        mode = "-r" if action_id in SCREENSHOT_REGION_ACTIONS else "-f"
        return [self.executable, "-n", "-b", mode, "-o", str(output_path)]

    def timeout_for_action(self, action_id: str) -> int:
        if action_id in SCREENSHOT_REGION_ACTIONS:
            return REGION_TIMEOUT_SECONDS
        return FULLSCREEN_TIMEOUT_SECONDS

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
            raise BackendUnavailable("Screenshot backend unavailable: Spectacle is not installed") from exc
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
        if action_id in SCREENSHOT_REGION_ACTIONS and output_missing:
            _unlink_empty_file(output_path)
            raise ScreenshotError(SPECTACLE_REGION_GUIDANCE)
        if completed.returncode != 0:
            _unlink_empty_file(output_path)
            detail = combined_output.strip() or f"Spectacle exited with status {completed.returncode}"
            raise ScreenshotError(f"Screenshot failed: {detail}")
        if output_missing:
            _unlink_empty_file(output_path)
            raise ScreenshotError("Screenshot failed: Spectacle did not create an image")


class PortalScreenshotBackend:
    needs_mouser_region_selection = False

    def __init__(
        self,
        client_factory: Callable[[], "PortalScreenshotClient"] | None = None,
    ):
        self._client_factory = client_factory or PortalScreenshotClient

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

    def probe(self) -> None:
        return None

    def capture_full(self) -> Image.Image:
        return self._capture_action(SCREENSHOT_FULL_FILE)

    def capture_region(self, rect: IntRect | None = None) -> Image.Image:
        return self._capture_action(SCREENSHOT_REGION_FILE)

    def perform_action(self, action_id: str) -> ScreenshotResult:
        return ScreenshotResult(action_id=action_id, image=_capture_for_action(self, action_id))

    def _capture_action(self, action_id: str) -> Image.Image:
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
        with Image.open(source) as image:
            return image.convert("RGBA")

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
            raise BackendUnavailable("Screenshot backend unavailable: QtDBus is not available")
        self._bus = bus or QDBusConnection.sessionBus()
        if not self._bus.isConnected():
            raise BackendUnavailable(
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
                "Screenshot failed: desktop portal did not respond. "
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
    _regionSelectionReady = Signal(str, object, str)

    def __init__(
        self,
        backend=_DEFAULT_BACKEND,
        status_callback: Callable[[str], None] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
        region_overlay_factory=RegionSelectionOverlay,
        logical_bounds_factory: Callable[[], IntRect] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._backends = _coerce_backends(backend)
        self._status_callback = status_callback
        self._thread_factory = thread_factory or threading.Thread
        self._region_overlay_factory = region_overlay_factory
        self._logical_bounds_factory = logical_bounds_factory or _system_logical_bounds
        self._busy = False
        self._overlay = None
        self._region_action = ""
        self._region_backend = None
        self._requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)
        self._workerFinished.connect(self._finish_worker, Qt.ConnectionType.QueuedConnection)
        self._regionSelectionReady.connect(
            self._begin_region_selection,
            Qt.ConnectionType.QueuedConnection,
        )

    def request_action(self, action_id: str) -> None:
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if not self._backends:
            self._emit_status("Screenshot backend unavailable")
            return
        if self._busy:
            self._emit_status("Finish the current screenshot first")
            return
        self._busy = True
        self._start_thread(self._run_action, action_id, name="LinuxScreenshot")

    def _run_action(self, action_id: str) -> None:
        try:
            for backend in self._backends:
                try:
                    probe = getattr(backend, "probe", None)
                    if callable(probe):
                        probe()
                except BackendUnavailable as exc:
                    print(f"[Screenshot] backend unavailable: {exc}")
                    continue

                if (
                    action_id in SCREENSHOT_REGION_ACTIONS
                    and getattr(backend, "needs_mouser_region_selection", False)
                ):
                    self._regionSelectionReady.emit(action_id, backend, "")
                    return

                try:
                    image = _capture_for_action(backend, action_id)
                    self._workerFinished.emit(action_id, image, "")
                    return
                except BackendUnavailable as exc:
                    print(f"[Screenshot] backend unavailable: {exc}")
                    continue
            self._workerFinished.emit(action_id, None, "Screenshot backend unavailable")
        except ScreenshotCancelled:
            self._workerFinished.emit(action_id, None, "cancelled")
        except ScreenshotError as exc:
            self._workerFinished.emit(action_id, None, str(exc))
        except Exception as exc:
            print(f"[Screenshot] Linux screenshot failed: {exc}")
            traceback.print_exc()
            self._workerFinished.emit(action_id, None, f"Screenshot failed: {exc}")

    @Slot(str, object, str)
    def _begin_region_selection(self, action_id: str, backend, error: str = "") -> None:
        if error:
            self._busy = False
            self._emit_status(error)
            return
        try:
            logical_bounds = self._logical_bounds_factory()
        except Exception as exc:
            self._busy = False
            self._emit_status(f"Screenshot failed: {exc}")
            return

        self._region_action = action_id
        self._region_backend = backend
        self._overlay = self._region_overlay_factory(logical_bounds)
        self._overlay.selected.connect(self._finish_region)
        self._overlay.cancelled.connect(self._cancel_region)
        self._overlay.show()

    @Slot(QRect)
    def _finish_region(self, rect: QRect) -> None:
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()
        action_id = self._region_action
        backend = self._region_backend
        self._region_action = ""
        self._region_backend = None
        try:
            selected = rect_from_qrect(rect)
        except Exception as exc:
            self._workerFinished.emit(action_id, None, f"Screenshot failed: {exc}")
            return
        self._start_thread(
            self._run_selected_region,
            action_id,
            backend,
            selected,
            name="LinuxScreenshotRegion",
        )

    @Slot()
    def _cancel_region(self) -> None:
        overlay = self._overlay
        self._overlay = None
        self._region_action = ""
        self._region_backend = None
        if overlay is not None:
            overlay.deleteLater()
        self._busy = False
        self._emit_status("Screenshot cancelled")

    def _run_selected_region(self, action_id: str, backend, rect: IntRect) -> None:
        try:
            image = backend.capture_region(rect)
            self._workerFinished.emit(action_id, image, "")
        except ScreenshotCancelled:
            self._workerFinished.emit(action_id, None, "cancelled")
        except ScreenshotError as exc:
            self._workerFinished.emit(action_id, None, str(exc))
        except Exception as exc:
            print(f"[Screenshot] Linux region screenshot failed: {exc}")
            traceback.print_exc()
            self._workerFinished.emit(action_id, None, f"Screenshot failed: {exc}")

    @Slot(str, object, str)
    def _finish_worker(self, action_id: str, image: Image.Image | None, error: str) -> None:
        self._busy = False
        if error == "cancelled":
            self._emit_status("Screenshot cancelled")
            return
        if error:
            self._emit_status(error)
            return
        if image is None:
            return
        try:
            if action_id in SCREENSHOT_CLIPBOARD_ACTIONS:
                copy_image_to_clipboard(image)
                self._emit_status("Screenshot copied to clipboard")
            elif action_id in SCREENSHOT_FILE_ACTIONS:
                path = save_image_to_file(image)
                self._emit_status(f"Screenshot saved to {path}")
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] Linux delivery failed: {exc}")

    def _start_thread(self, target, *args, name: str) -> None:
        thread = self._thread_factory(
            target=target,
            args=args,
            daemon=True,
            name=name,
        )
        thread.start()

    def _emit_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)


def _coerce_backends(backend) -> list[object]:
    if backend is _DEFAULT_BACKEND:
        return select_linux_screenshot_backends()
    if backend is None:
        return []
    if isinstance(backend, (list, tuple)):
        return list(backend)
    return [backend]


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


def _system_logical_bounds() -> IntRect:
    app = QGuiApplication.instance()
    screens = app.screens() if app is not None else []
    if not screens and app is not None and app.primaryScreen() is not None:
        screens = [app.primaryScreen()]
    rects = [rect_from_qrect(screen.geometry()) for screen in screens]
    return union_rect(rects)


def _default_probe_rect() -> IntRect:
    try:
        bounds = _system_logical_bounds()
        return IntRect(bounds.left, bounds.top, bounds.left + 1, bounds.top + 1)
    except Exception:
        return IntRect(0, 0, 1, 1)


def kwin_capture_options() -> dict[str, object]:
    return {
        "native-resolution": True,
        "include-cursor": False,
        "include-shadow": False,
        "hide-caller-windows": False,
    }


def kwin_methods_from_introspection(xml_text: str) -> set[str]:
    root = ET.fromstring(xml_text)
    methods: set[str] = set()
    for interface in root.findall(".//interface"):
        if interface.attrib.get("name") != KWIN_INTERFACE:
            continue
        methods.update(
            method.attrib["name"]
            for method in interface.findall("method")
            if method.attrib.get("name")
        )
    return methods


def kwin_raw_image_to_pil(metadata: Mapping[str, object], data: bytes) -> Image.Image:
    meta = _metadata_dict(metadata)
    image_type = str(meta.get("type", "raw"))
    if image_type != "raw":
        raise ScreenshotError(f"Screenshot failed: unsupported KWin image type {image_type}")
    width = int(meta.get("width", 0))
    height = int(meta.get("height", 0))
    stride = int(meta.get("stride", 0))
    format_value = int(meta.get("format", 0))
    if width <= 0 or height <= 0 or stride <= 0:
        raise ScreenshotError("Screenshot failed: KWin returned invalid image metadata")
    qformat = QImage.Format(format_value)
    qimage = QImage(data, width, height, stride, qformat).copy()
    if qimage.isNull():
        raise ScreenshotError("Screenshot failed: KWin returned an invalid image")
    return qimage_to_pil_image(qimage)


def qimage_to_pil_image(qimage: QImage) -> Image.Image:
    rgba = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    width = rgba.width()
    height = rgba.height()
    stride = rgba.bytesPerLine()
    raw = bytes(rgba.bits()[: rgba.sizeInBytes()])
    row_bytes = width * 4
    if stride != row_bytes:
        raw = b"".join(
            raw[offset : offset + row_bytes]
            for offset in range(0, stride * height, stride)
        )
    else:
        raw = raw[: row_bytes * height]
    return Image.frombytes("RGBA", (width, height), raw)


def _read_fd_exact(fd: int, byte_count: int, timeout_seconds: float) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    chunks = bytearray()
    while len(chunks) < byte_count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScreenshotError("Screenshot timed out")
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            raise ScreenshotError("Screenshot timed out")
        chunk = os.read(fd, byte_count - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    if len(chunks) < byte_count:
        raise ScreenshotError("Screenshot failed: KWin returned incomplete image data")
    return bytes(chunks)


def _metadata_dict(value) -> dict[str, object]:
    value = _unwrap_dbus_value(value) or {}
    return {
        str(_unwrap_dbus_value(key)): _unwrap_dbus_value(item)
        for key, item in dict(value).items()
    }


def _raise_kwin_reply_error(reply) -> None:
    name = _dbus_error_name(reply)
    text = _dbus_error_text(reply)
    if name == KWIN_CANCELLED or "cancelled" in text.lower():
        raise ScreenshotCancelled()
    if name == KWIN_NOT_AUTHORIZED or "authorized" in text.lower():
        raise BackendUnavailable(
            "KWin ScreenShot2 is not authorized. Launch Mouser from its installed "
            "desktop entry or use the portal/Spectacle fallback."
        )
    raise ScreenshotError(f"Screenshot failed: {text}")


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


def _dbus_error_name(reply) -> str:
    method = getattr(reply, "errorName", None)
    if callable(method):
        value = method()
        if value:
            return str(value)
    return ""


def _dbus_error_text(reply) -> str:
    for attr in ("errorMessage", "errorName"):
        method = getattr(reply, attr, None)
        if callable(method):
            value = method()
            if value:
                return str(value)
    return "D-Bus call failed"
