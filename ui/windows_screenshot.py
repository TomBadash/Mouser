"""Native Windows screenshot actions for Mouser.

The mouse hook can invoke actions from a non-Qt thread.  This module exposes a
Qt controller whose public request method only emits a queued signal; all
capture, clipboard, file, and overlay work then runs on the GUI thread.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageGrab
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.screenshot_common import (
    SCREENSHOT_ACTIONS,
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
    copy_image_to_clipboard,
    save_image_to_file,
)


@dataclass(frozen=True)
class IntRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def translated(self, dx: int, dy: int) -> "IntRect":
        return IntRect(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)

    def intersected(self, other: "IntRect") -> "IntRect | None":
        rect = IntRect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )
        return None if rect.is_empty else rect

    def to_qrect(self) -> QRect:
        return QRect(self.left, self.top, self.width, self.height)


@dataclass(frozen=True)
class MonitorMap:
    logical: IntRect
    physical: IntRect


@dataclass(frozen=True)
class VirtualCapture:
    image: Image.Image
    physical_rect: IntRect
    monitor_maps: tuple[MonitorMap, ...]


def _union_rect(rects: Iterable[IntRect]) -> IntRect:
    rects = [r for r in rects if not r.is_empty]
    if not rects:
        raise ValueError("no non-empty rectangles")
    return IntRect(
        min(r.left for r in rects),
        min(r.top for r in rects),
        max(r.right for r in rects),
        max(r.bottom for r in rects),
    )


def _rect_from_qrect(rect: QRect) -> IntRect:
    return IntRect(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())


def _sort_rects_spatially(rects: Sequence[IntRect]) -> list[IntRect]:
    return sorted(rects, key=lambda r: (r.left, r.top, r.width, r.height))


def build_monitor_maps(
    logical_rects: Sequence[IntRect],
    physical_rects: Sequence[IntRect],
) -> tuple[MonitorMap, ...]:
    """Pair Qt logical screen rectangles with Win32 physical monitor rectangles."""
    logical = [r for r in logical_rects if not r.is_empty]
    physical = [r for r in physical_rects if not r.is_empty]
    if not logical or not physical:
        raise ValueError("monitor mapping requires at least one logical and physical rect")
    if len(logical) != len(physical):
        physical_union = _union_rect(physical)
        return (MonitorMap(physical_union, physical_union),)
    return tuple(
        MonitorMap(logical_rect, physical_rect)
        for logical_rect, physical_rect in zip(
            _sort_rects_spatially(logical),
            _sort_rects_spatially(physical),
        )
    )


def _enum_windows_monitor_rects() -> tuple[IntRect, ...]:
    if sys.platform != "win32":
        raise RuntimeError("Win32 monitor enumeration is only available on Windows")

    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32

    monitors: list[IntRect] = []
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(_monitor, _dc, rect_ptr, _data):
        rect = rect_ptr.contents
        monitors.append(IntRect(rect.left, rect.top, rect.right, rect.bottom))
        return 1

    if not user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(_callback), 0):
        raise RuntimeError("EnumDisplayMonitors failed")
    return tuple(monitors)


def _system_monitor_maps() -> tuple[MonitorMap, ...]:
    physical_rects = _enum_windows_monitor_rects()
    app = QGuiApplication.instance()
    screens = app.screens() if app is not None else []
    logical_rects = [_rect_from_qrect(screen.geometry()) for screen in screens]
    return build_monitor_maps(logical_rects, physical_rects)


def logical_to_physical_rect(monitor: MonitorMap, logical_rect: IntRect) -> IntRect:
    if monitor.logical.is_empty:
        raise ValueError("logical monitor rectangle is empty")
    scale_x = monitor.physical.width / float(monitor.logical.width)
    scale_y = monitor.physical.height / float(monitor.logical.height)
    return IntRect(
        monitor.physical.left + int(round((logical_rect.left - monitor.logical.left) * scale_x)),
        monitor.physical.top + int(round((logical_rect.top - monitor.logical.top) * scale_y)),
        monitor.physical.left + int(round((logical_rect.right - monitor.logical.left) * scale_x)),
        monitor.physical.top + int(round((logical_rect.bottom - monitor.logical.top) * scale_y)),
    )


def capture_virtual_desktop(
    monitor_maps: Sequence[MonitorMap] | None = None,
    grab: Callable[..., Image.Image] | None = None,
) -> VirtualCapture:
    maps = tuple(monitor_maps or _system_monitor_maps())
    physical_bounds = _union_rect(m.physical for m in maps)
    grab_screen = grab or ImageGrab.grab
    canvas = Image.new("RGB", (physical_bounds.width, physical_bounds.height), (0, 0, 0))
    for monitor in maps:
        bbox = (
            monitor.physical.left,
            monitor.physical.top,
            monitor.physical.right,
            monitor.physical.bottom,
        )
        image = grab_screen(
            bbox=bbox,
            all_screens=True,
            include_layered_windows=True,
        ).convert("RGB")
        canvas.paste(
            image,
            (
                monitor.physical.left - physical_bounds.left,
                monitor.physical.top - physical_bounds.top,
            ),
        )
    return VirtualCapture(canvas, physical_bounds, maps)


def crop_logical_region(capture: VirtualCapture, logical_rect: IntRect) -> Image.Image:
    segments: list[IntRect] = []
    for monitor in capture.monitor_maps:
        logical_part = logical_rect.intersected(monitor.logical)
        if logical_part is not None:
            segments.append(logical_to_physical_rect(monitor, logical_part))
    if not segments:
        raise ValueError("selected region does not intersect any screen")

    output_rect = _union_rect(segments)
    result = Image.new(capture.image.mode, (output_rect.width, output_rect.height), (0, 0, 0))
    for segment in segments:
        source = segment.translated(-capture.physical_rect.left, -capture.physical_rect.top)
        patch = capture.image.crop((source.left, source.top, source.right, source.bottom))
        result.paste(patch, (segment.left - output_rect.left, segment.top - output_rect.top))
    return result


class RegionSelectionOverlay(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, logical_bounds: IntRect, parent=None):
        super().__init__(parent)
        self._bounds = logical_bounds
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(logical_bounds.to_qrect())

    def show(self) -> None:
        super().show()
        self.raise_()
        self.activateWindow()
        self.grabMouse()
        self.grabKeyboard()

    def closeEvent(self, event):
        try:
            self.releaseMouse()
            self.releaseKeyboard()
        finally:
            super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = self._event_global_pos(event)
        self._current = self._start
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is None:
            return
        self._current = self._event_global_pos(event)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._current = self._event_global_pos(event)
        rect = QRect(self._start, self._current).normalized()
        if rect.width() < 2 or rect.height() < 2:
            self.cancelled.emit()
        else:
            self.selected.emit(rect)
        self.close()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._start is not None and self._current is not None:
            selected = QRect(self._start, self._current).normalized()
            local = selected.translated(-self._bounds.left, -self._bounds.top)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(local, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawRect(local.adjusted(0, 0, -1, -1))
        painter.end()

    @staticmethod
    def _event_global_pos(event: QMouseEvent) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()


class WindowsScreenshotController(QObject):
    _requestAction = Signal(str)

    def __init__(self, status_callback: Callable[[str], None] | None = None, parent=None):
        super().__init__(parent)
        self._status_callback = status_callback
        self._overlay: RegionSelectionOverlay | None = None
        self._pending_capture: VirtualCapture | None = None
        self._pending_action = ""
        self._requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)

    def request_action(self, action_id: str) -> None:
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if self._overlay is not None:
            self._emit_status("Finish the current screenshot selection first")
            return
        try:
            capture = capture_virtual_desktop()
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] capture failed: {exc}")
            return

        if action_id in (SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE):
            self._deliver_image(capture.image, action_id)
            return

        self._pending_capture = capture
        self._pending_action = action_id
        self._overlay = RegionSelectionOverlay(_union_rect(m.logical for m in capture.monitor_maps))
        self._overlay.selected.connect(self._finish_region)
        self._overlay.cancelled.connect(self._cancel_region)
        self._overlay.show()

    @Slot(QRect)
    def _finish_region(self, rect: QRect) -> None:
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()
        capture = self._pending_capture
        action_id = self._pending_action
        self._pending_capture = None
        self._pending_action = ""
        if capture is None:
            return
        try:
            image = crop_logical_region(capture, _rect_from_qrect(rect))
            self._deliver_image(image, action_id)
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] region failed: {exc}")

    @Slot()
    def _cancel_region(self) -> None:
        overlay = self._overlay
        self._overlay = None
        self._pending_capture = None
        self._pending_action = ""
        if overlay is not None:
            overlay.deleteLater()
        self._emit_status("Screenshot cancelled")

    def _deliver_image(self, image: Image.Image, action_id: str) -> None:
        try:
            if action_id in (SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_CLIP):
                copy_image_to_clipboard(image)
                self._emit_status("Screenshot copied to clipboard")
            else:
                path = save_image_to_file(image)
                self._emit_status(f"Screenshot saved to {path}")
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] delivery failed: {exc}")

    def _emit_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)
