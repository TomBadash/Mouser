"""Linux screenshot actions backed by KDE Spectacle."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal, Slot

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


class ScreenshotError(RuntimeError):
    """Screenshot action failed."""


class ScreenshotCancelled(Exception):
    """Screenshot action was cancelled by the user."""


@dataclass(frozen=True)
class ScreenshotResult:
    action_id: str
    path: Path | None = None
    image: Image.Image | None = None


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
        self._backend = SpectacleScreenshotBackend.detect() if backend is _DEFAULT_BACKEND else backend
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
            self._emit_status("Screenshot backend unavailable: install Spectacle")
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
