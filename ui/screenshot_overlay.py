"""Shared screenshot geometry and region selection overlay helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


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


def union_rect(rects: Iterable[IntRect]) -> IntRect:
    rects = [r for r in rects if not r.is_empty]
    if not rects:
        raise ValueError("no non-empty rectangles")
    return IntRect(
        min(r.left for r in rects),
        min(r.top for r in rects),
        max(r.right for r in rects),
        max(r.bottom for r in rects),
    )


def rect_from_qrect(rect: QRect) -> IntRect:
    return IntRect(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())


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
