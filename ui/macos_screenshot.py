"""macOS screenshot actions with optional Mouser-owned file delivery."""
from __future__ import annotations

import ctypes
import math
import subprocess
import tempfile
import threading
from ctypes import util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PIL import Image

from ui.screenshot_common import (
    SCREENSHOT_ACTIONS,
    SCREENSHOT_CLIPBOARD_ACTIONS,
    SCREENSHOT_FILE_ACTIONS,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_ACTIONS,
    SCREENSHOT_REGION_FILE,
)


FULLSCREEN_TIMEOUT_SECONDS = 15
REGION_TIMEOUT_SECONDS = 300
FALLBACK_STATUS = (
    "Could not save to selected folder; used macOS screenshot shortcut instead."
)
PERMISSION_FALLBACK_STATUS = (
    "Custom screenshot folder requires macOS Screen Recording permission; "
    "used macOS default screenshot shortcut instead."
)


@dataclass(frozen=True)
class MacDisplayInfo:
    index: int
    x: int
    y: int
    width: int
    height: int


class MacScreenshotController(QObject):
    _requestAction = Signal(str)
    _workerFinished = Signal(str, object, str, bool)

    def __init__(
        self,
        status_callback: Callable[[str], None] | None = None,
        path_factory: Callable[[], Path] | None = None,
        has_custom_directory: Callable[[], bool] | None = None,
        fallback_action: Callable[[str], bool] | None = None,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
        display_info_provider: Callable[[], Sequence[MacDisplayInfo]] | None = None,
        screen_capture_access_checker: Callable[[], bool] | None = None,
        temp_path_factory: Callable[[], Path] | None = None,
        executable: str = "/usr/sbin/screencapture",
        parent=None,
    ):
        super().__init__(parent)
        self._status_callback = status_callback
        self._path_factory = path_factory
        self._has_custom_directory = has_custom_directory or (lambda: False)
        self._fallback_action = fallback_action
        self._runner = runner or subprocess.run
        self._thread_factory = thread_factory or threading.Thread
        self._display_info_provider = display_info_provider or _display_infos
        self._screen_capture_access_checker = (
            screen_capture_access_checker or _screen_capture_access_granted
        )
        self._temp_path_factory = temp_path_factory or _temporary_png_path
        self._executable = executable
        self._busy = False
        self._requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)
        self._workerFinished.connect(
            self._finish_worker,
            Qt.ConnectionType.QueuedConnection,
        )

    def request_action(self, action_id: str) -> None:
        self._requestAction.emit(action_id)

    def command_for_action(
        self,
        action_id: str,
        target: Path,
    ) -> list[str]:
        if action_id == SCREENSHOT_FULL_FILE:
            return [self._executable, "-x", "-t", "png", str(target)]
        if action_id == SCREENSHOT_REGION_FILE:
            return [self._executable, "-x", "-i", "-s", "-t", "png", str(target)]
        raise ValueError(f"unsupported macOS screenshot file action: {action_id}")

    def command_for_display(self, display_index: int, target: Path) -> list[str]:
        return [
            self._executable,
            "-x",
            "-D",
            str(display_index),
            "-t",
            "png",
            str(target),
        ]

    def timeout_for_action(self, action_id: str) -> int:
        if action_id in SCREENSHOT_REGION_ACTIONS:
            return REGION_TIMEOUT_SECONDS
        return FULLSCREEN_TIMEOUT_SECONDS

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if action_id in SCREENSHOT_CLIPBOARD_ACTIONS or not self._custom_directory_enabled():
            self._run_shortcut_fallback(action_id)
            return
        if action_id not in SCREENSHOT_FILE_ACTIONS:
            return
        if self._busy:
            self._emit_status("Finish the current screenshot first")
            return
        if not self._screen_capture_access_granted():
            self._run_shortcut_fallback(
                action_id,
                emit_fallback_status=True,
                fallback_status=PERMISSION_FALLBACK_STATUS,
            )
            return
        try:
            target = self._allocate_target()
        except Exception as exc:
            print(f"[Screenshot] macOS path allocation failed: {exc}")
            self._run_shortcut_fallback(action_id, emit_fallback_status=True)
            return
        self._busy = True
        self._start_thread(
            self._run_file_action,
            action_id,
            target,
            name="MacScreenshot",
        )

    def _allocate_target(self) -> Path:
        if self._path_factory is None:
            raise RuntimeError("screenshot path provider is unavailable")
        return Path(self._path_factory())

    def _screen_capture_access_granted(self) -> bool:
        try:
            return bool(self._screen_capture_access_checker())
        except Exception as exc:
            print(f"[Screenshot] macOS screen capture permission check failed: {exc}")
            return True

    def _run_file_action(
        self,
        action_id: str,
        target: Path,
    ) -> None:
        if action_id == SCREENSHOT_FULL_FILE:
            self._run_full_file_action(target)
            return
        self._run_region_file_action(action_id, target)

    def _run_region_file_action(self, action_id: str, target: Path) -> None:
        try:
            command = self.command_for_action(action_id, target)
            completed = self._runner(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_for_action(action_id),
            )
        except subprocess.TimeoutExpired as exc:
            _delete_partial_outputs([target])
            self._workerFinished.emit(action_id, target, f"Screenshot timed out: {exc}", True)
            return
        except Exception as exc:
            _delete_partial_outputs([target])
            self._workerFinished.emit(action_id, target, str(exc), True)
            return

        if _output_missing(target):
            _delete_partial_outputs([target])
            if action_id in SCREENSHOT_REGION_ACTIONS:
                self._workerFinished.emit(action_id, target, "cancelled", False)
            else:
                self._workerFinished.emit(
                    action_id,
                    target,
                    "screencapture did not create an image",
                    True,
                )
            return
        if completed.returncode != 0:
            _delete_partial_outputs([target])
            self._workerFinished.emit(
                action_id,
                target,
                _combined_process_output(completed)
                or f"screencapture exited with status {completed.returncode}",
                True,
            )
            return
        self._workerFinished.emit(action_id, target, "", False)

    def _run_full_file_action(self, target: Path) -> None:
        temp_paths: list[Path] = []
        captures: list[tuple[MacDisplayInfo, Image.Image]] = []
        try:
            display_infos = list(self._display_info_provider())
            if not display_infos:
                raise RuntimeError("no displays available")
            for display in display_infos:
                temp_path = Path(self._temp_path_factory())
                temp_paths.append(temp_path)
                command = self.command_for_display(display.index, temp_path)
                completed = self._runner(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=FULLSCREEN_TIMEOUT_SECONDS,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        _combined_process_output(completed)
                        or f"screencapture exited with status {completed.returncode}"
                    )
                if _output_missing(temp_path):
                    raise RuntimeError("screencapture did not create an image")
                image = Image.open(temp_path).convert("RGBA")
                image.load()
                captures.append((display, image))
            composed = compose_display_images(captures)
            target.parent.mkdir(parents=True, exist_ok=True)
            composed.save(target, format="PNG")
        except subprocess.TimeoutExpired as exc:
            _delete_partial_outputs([target, *temp_paths])
            self._workerFinished.emit(
                SCREENSHOT_FULL_FILE,
                target,
                f"Screenshot timed out: {exc}",
                True,
            )
            return
        except Exception as exc:
            _delete_partial_outputs([target, *temp_paths])
            self._workerFinished.emit(SCREENSHOT_FULL_FILE, target, str(exc), True)
            return
        finally:
            _delete_partial_outputs(temp_paths)
        self._workerFinished.emit(SCREENSHOT_FULL_FILE, target, "", False)

    @Slot(str, object, str, bool)
    def _finish_worker(
        self,
        action_id: str,
        target: Path | None,
        error: str,
        use_fallback: bool,
    ) -> None:
        self._busy = False
        if error == "cancelled":
            self._emit_status("Screenshot cancelled")
            return
        if error and use_fallback:
            print(f"[Screenshot] macOS screencapture failed: {error}")
            self._run_shortcut_fallback(action_id, emit_fallback_status=True)
            return
        if error:
            self._emit_status(f"Screenshot failed: {error}")
            return
        if target is not None:
            self._emit_status(f"Screenshot saved to {target}")

    def _run_shortcut_fallback(
        self,
        action_id: str,
        emit_fallback_status: bool = False,
        fallback_status: str = FALLBACK_STATUS,
    ) -> None:
        fallback = self._fallback_action or _default_shortcut_fallback
        try:
            used_fallback = bool(fallback(action_id))
        except Exception as exc:
            print(f"[Screenshot] macOS shortcut fallback failed: {exc}")
            used_fallback = False
        if emit_fallback_status:
            if used_fallback:
                self._emit_status(fallback_status)
            else:
                self._emit_status("Screenshot failed: macOS screenshot shortcut unavailable")

    def _custom_directory_enabled(self) -> bool:
        try:
            return bool(self._has_custom_directory())
        except Exception as exc:
            print(f"[Screenshot] macOS screenshot setting unavailable: {exc}")
            return False

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


def _default_shortcut_fallback(action_id: str) -> bool:
    from core.key_simulator import execute_screenshot_shortcut

    return execute_screenshot_shortcut(action_id)


def _combined_process_output(completed: subprocess.CompletedProcess) -> str:
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return f"{stdout}\n{stderr}".strip()


def _output_missing(path: Path) -> bool:
    return not path.exists() or path.stat().st_size <= 0


def _delete_partial_outputs(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def compose_display_images(
    captures: Sequence[tuple[MacDisplayInfo, Image.Image]],
) -> Image.Image:
    if not captures:
        raise RuntimeError("no display images to compose")
    min_x = min(display.x for display, _image in captures)
    min_y = min(display.y for display, _image in captures)
    max_x = max(display.x + display.width for display, _image in captures)
    max_y = max(display.y + display.height for display, _image in captures)
    scale = max(
        max(image.width / display.width, image.height / display.height)
        for display, image in captures
        if display.width > 0 and display.height > 0
    )
    canvas_width = max(1, math.ceil((max_x - min_x) * scale))
    canvas_height = max(1, math.ceil((max_y - min_y) * scale))
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (255, 255, 255, 255))
    for display, image in captures:
        target_size = (
            max(1, round(display.width * scale)),
            max(1, round(display.height * scale)),
        )
        source = image.convert("RGBA")
        if source.size != target_size:
            source = source.resize(target_size, _resize_filter())
        offset = (
            round((display.x - min_x) * scale),
            round((display.y - min_y) * scale),
        )
        canvas.paste(source, offset)
    return canvas


def _resize_filter():
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _display_infos() -> list[MacDisplayInfo]:
    app = QGuiApplication.instance()
    if app is None:
        return [MacDisplayInfo(index=1, x=0, y=0, width=1, height=1)]
    infos: list[MacDisplayInfo] = []
    for index, screen in enumerate(_ordered_screens(app), 1):
        geometry = screen.geometry()
        infos.append(
            MacDisplayInfo(
                index=index,
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
        )
    return infos or [MacDisplayInfo(index=1, x=0, y=0, width=1, height=1)]


def _ordered_screens(app: QGuiApplication):
    screens = list(app.screens())
    primary = app.primaryScreen()
    if primary is None or primary not in screens:
        return screens
    return [primary, *[screen for screen in screens if screen is not primary]]


def _temporary_png_path() -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="mouser-screenshot-display-",
        suffix=".png",
        delete=False,
    )
    try:
        return Path(handle.name)
    finally:
        handle.close()


def _screen_capture_access_granted() -> bool:
    library = util.find_library("CoreGraphics")
    if not library:
        return True
    core_graphics = ctypes.CDLL(library)
    preflight = core_graphics.CGPreflightScreenCaptureAccess
    preflight.restype = ctypes.c_bool
    return bool(preflight())
