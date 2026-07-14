"""Radial pie-menu overlay for the Actions Ring — glassmorphism design."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

from core.actions_ring import DEAD_ZONE_RADIUS, angle_to_sector

# ── short-label mapping ────────────────────────────────────────────

RING_LABEL_MAP: dict[str, str] = {
    "mission_control":      "Mission Control",
    "app_expose":           "App Expose",
    "show_desktop":         "Show Desktop",
    "launchpad":            "Launchpad",
    "task_view":            "Task View",
    "win_d":                "Show Desktop",
    "screenshot_region_clip": "Screenshot",
    "play_pause":           "Play / Pause",
    "next_track":           "Next Track",
    "prev_track":           "Prev Track",
    "volume_up":            "Volume Up",
    "volume_down":          "Volume Down",
    "volume_mute":          "Mute",
    "browser_back":         "Back",
    "browser_forward":      "Forward",
    "copy":                 "Copy",
    "paste":                "Paste",
    "cut":                  "Cut",
    "undo":                 "Undo",
    "select_all":           "Select All",
    "save":                 "Save",
    "find":                 "Find",
    "next_tab":             "Next Tab",
    "prev_tab":             "Prev Tab",
    "close_tab":            "Close Tab",
    "new_tab":              "New Tab",
    "space_left":           "Desk Left",
    "space_right":          "Desk Right",
    "alt_tab":              "Switch App",
    "alt_shift_tab":        "Switch Back",
    "page_up":              "Page Up",
    "page_down":            "Page Down",
    "home":                 "Home",
    "end":                  "End",
    "cycle_dpi":            "Cycle DPI",
    "toggle_smart_shift":   "SmartShift",
    "switch_scroll_mode":   "Scroll Mode",
    "activate_actions_ring":"Actions Ring",
    "mouse_left_click":     "Left Click",
    "mouse_right_click":    "Right Click",
    "mouse_middle_click":   "Middle Click",
    "mouse_back_click":     "Back",
    "mouse_forward_click":  "Forward",
    "none":                 "None",
    "cycle_desktops":       "Desktops",
    "zoom_in":              "Zoom In",
    "zoom_out":             "Zoom Out",
}


def _resolve_ring_label(action_id: str, full_label: str) -> str:
    if action_id in RING_LABEL_MAP:
        return RING_LABEL_MAP[action_id]
    if action_id.startswith("custom:"):
        return full_label[:14]
    return full_label[:14]


# ── layout constants ────────────────────────────────────────────────

_INNER_GAP = 4
_GAP_DEG = 2.5
_MARGIN = 50

# ── glassmorphism palette ───────────────────────────────────────────

_COLOR_SECTOR = QColor(22, 22, 26, 150)
_COLOR_SECTOR_HL_CENTER = QColor(0, 212, 170, 70)
_COLOR_SECTOR_HL_EDGE = QColor(0, 212, 170, 22)

_COLOR_GLASS_BORDER = QColor(255, 255, 255, 48)

_COLOR_OUTER_GLOW_CENTER = QColor(0, 212, 170, 28)
_COLOR_OUTER_GLOW_EDGE = QColor(0, 212, 170, 0)

_COLOR_DEAD_ZONE = QColor(18, 18, 22, 210)
_COLOR_DEAD_ZONE_BORDER = QColor(255, 255, 255, 30)
_COLOR_CENTER_ICON = QColor(255, 255, 255, 140)

_COLOR_LABEL = QColor(255, 255, 255, 220)

# ── animation timing ────────────────────────────────────────────────

_TICK_MS = 16
_APPEAR_DURATION_MS = 120
_APPEAR_FRAMES = max(1, _APPEAR_DURATION_MS // _TICK_MS)
_SECTOR_STAGGER_MS = 40
_DISMISS_DURATION_MS = 80
_DISMISS_FRAMES = max(1, _DISMISS_DURATION_MS // _TICK_MS)
_HIGHLIGHT_SPEED = _TICK_MS / 100.0
_PULSE_SPEED = (2.0 * math.pi * _TICK_MS) / 2000.0


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 2


def _ease_in(t: float) -> float:
    return t * t


class ActionsRingOverlay(QWidget):
    """Radial pie-menu overlay with glassmorphism styling."""

    action_selected = Signal(int)
    cancelled = Signal()
    sector_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._slot_labels: list[str] = []
        self._ring_diameter = 220
        self._highlighted_sector = -1
        self._target_sector = -1
        self._center = QPointF()
        self._interactive = False

        # animation state
        self._tick_count = 0
        self._appear_progress = 1.0
        self._sector_reveal: list[float] = []
        self._sector_alphas: list[float] = []
        self._pulse_phase = 0.0
        self._dismiss_progress = -1.0
        self._dismiss_step = 0

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

        self._rawxy_offset = None

        self._label_font = QFont()
        self._label_font.setPixelSize(12)
        self._label_font.setWeight(QFont.Weight.Medium)
        self._label_fm = QFontMetricsF(self._label_font)

        self._center_font = QFont()
        self._center_font.setPixelSize(14)
        self._center_fm = QFontMetricsF(self._center_font)

    # -- public API ----------------------------------------------------------

    def show_ring(
        self,
        center_x: int,
        center_y: int,
        slot_labels: list[str],
        ring_diameter: int = 220,
        interactive: bool = False,
    ) -> None:
        n = len(slot_labels)
        self._slot_labels = list(slot_labels)
        self._ring_diameter = ring_diameter
        self._highlighted_sector = -1
        self._target_sector = -1
        self._interactive = interactive
        self._rawxy_offset = None if interactive else (0, 0)

        self._tick_count = 0
        self._appear_progress = 0.0
        self._sector_reveal = [0.0] * n
        self._sector_alphas = [0.0] * n
        self._pulse_phase = 0.0
        self._dismiss_progress = -1.0
        self._dismiss_step = 0

        widget_size = ring_diameter + _MARGIN * 2
        half = widget_size // 2

        # Position widget so ring center stays at cursor. Clamp the
        # widget to stay on-screen, then offset _center within it so
        # the ring tracks the cursor exactly. Near edges some sectors
        # may be clipped by the widget boundary — that's acceptable.
        wx = center_x - half
        wy = center_y - half
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screens = QApplication.screens()
            screen = screens[0] if screens else None
        if screen is not None:
            geom = screen.availableGeometry()
            clamped_wx = max(geom.left(), min(wx, geom.right() - widget_size))
            clamped_wy = max(geom.top(), min(wy, geom.bottom() - widget_size))
        else:
            clamped_wx, clamped_wy = wx, wy

        self.setFixedSize(widget_size, widget_size)
        self.move(clamped_wx, clamped_wy)
        self._center = QPointF(half + (wx - clamped_wx), half + (wy - clamped_wy))

        self.show()
        self.raise_()
        self._tick_timer.start()

    def hide_ring(self) -> None:
        if self._dismiss_progress >= 0:
            return
        self._dismiss_progress = 0.0
        self._dismiss_step = 0

    def set_highlighted_sector(self, index: int) -> None:
        if self._highlighted_sector != index:
            self._highlighted_sector = index
            self.update()

    def accumulate_rawxy(self, dx: int, dy: int) -> None:
        off = self._rawxy_offset
        if off is not None:
            self._rawxy_offset = (off[0] + dx, off[1] + dy)

    @property
    def current_sector(self) -> int:
        return self._highlighted_sector

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        n = len(self._slot_labels)
        if n == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._dismiss_progress >= 0:
            painter.setOpacity(1.0 - _ease_in(self._dismiss_progress))

        if self._dismiss_progress >= 0:
            scale = 1.0 - 0.08 * _ease_in(self._dismiss_progress)
        else:
            scale = 0.85 + 0.15 * _ease_out(self._appear_progress)
        painter.translate(self._center)
        painter.scale(scale, scale)
        painter.translate(-self._center)

        outer_r = self._ring_diameter / 2.0
        inner_r = DEAD_ZONE_RADIUS + _INNER_GAP
        sector_span = 360.0 / n
        gap_half = _GAP_DEG / 2.0

        # outer glow halo
        glow_r = outer_r + 18
        glow_grad = QRadialGradient(self._center, glow_r)
        glow_grad.setColorAt(0.6, _COLOR_OUTER_GLOW_CENTER)
        glow_grad.setColorAt(1.0, _COLOR_OUTER_GLOW_EDGE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_grad)
        painter.drawEllipse(self._center, glow_r, glow_r)

        # sectors
        for i in range(n):
            start_deg = 90.0 - i * sector_span - sector_span / 2.0 + gap_half
            span = sector_span - _GAP_DEG
            path = self._sector_path(self._center, outer_r, inner_r, start_deg, span)

            reveal = self._sector_reveal[i] if i < len(self._sector_reveal) else 1.0
            hl = self._sector_alphas[i] if i < len(self._sector_alphas) else 0.0

            if hl > 0.5 and self._dismiss_progress < 0:
                pulse = 0.85 + 0.15 * math.sin(self._pulse_phase)
            else:
                pulse = 1.0

            if hl > 0.01:
                mid = self._content_position(i, n)
                hl_grad = QRadialGradient(mid, outer_r * 0.6)
                center_c = QColor(
                    _COLOR_SECTOR_HL_CENTER.red(),
                    _COLOR_SECTOR_HL_CENTER.green(),
                    _COLOR_SECTOR_HL_CENTER.blue(),
                    int(_COLOR_SECTOR_HL_CENTER.alpha() * hl * pulse),
                )
                edge_c = QColor(
                    _COLOR_SECTOR_HL_EDGE.red(),
                    _COLOR_SECTOR_HL_EDGE.green(),
                    _COLOR_SECTOR_HL_EDGE.blue(),
                    int(_COLOR_SECTOR_HL_EDGE.alpha() * hl * pulse),
                )
                hl_grad.setColorAt(0.0, center_c)
                hl_grad.setColorAt(1.0, edge_c)

                base_c = QColor(
                    _COLOR_SECTOR.red(), _COLOR_SECTOR.green(),
                    _COLOR_SECTOR.blue(), int(_COLOR_SECTOR.alpha() * reveal),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(base_c)
                painter.drawPath(path)
                painter.setBrush(hl_grad)
                painter.drawPath(path)
            else:
                fill = QColor(
                    _COLOR_SECTOR.red(), _COLOR_SECTOR.green(),
                    _COLOR_SECTOR.blue(), int(_COLOR_SECTOR.alpha() * reveal),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)

            if reveal > 0.01:
                border_pen = QPen(
                    QColor(
                        _COLOR_GLASS_BORDER.red(), _COLOR_GLASS_BORDER.green(),
                        _COLOR_GLASS_BORDER.blue(),
                        int(_COLOR_GLASS_BORDER.alpha() * reveal),
                    ),
                    1.5,
                )
                border_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(border_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)

        # dead zone center
        painter.setPen(QPen(_COLOR_DEAD_ZONE_BORDER, 1.0))
        painter.setBrush(_COLOR_DEAD_ZONE)
        painter.drawEllipse(self._center, DEAD_ZONE_RADIUS, DEAD_ZONE_RADIUS)

        painter.setPen(_COLOR_CENTER_ICON)
        painter.setFont(self._center_font)
        x_char = "×"
        tw = self._center_fm.horizontalAdvance(x_char)
        th = self._center_fm.height()
        painter.drawText(
            QPointF(self._center.x() - tw / 2, self._center.y() + th / 4),
            x_char,
        )

        # labels (word-wrapped, vertically centered in sector)
        painter.setFont(self._label_font)
        max_label_w = outer_r - inner_r - 4
        wrap_flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        for i in range(n):
            reveal = self._sector_reveal[i] if i < len(self._sector_reveal) else 1.0
            if reveal < 0.01:
                continue

            pos = self._content_position(i, n)
            label_text = self._slot_labels[i]

            label_color = QColor(
                _COLOR_LABEL.red(), _COLOR_LABEL.green(),
                _COLOR_LABEL.blue(), int(_COLOR_LABEL.alpha() * reveal),
            )
            painter.setPen(label_color)
            measure_rect = QRectF(0, 0, max_label_w, 200)
            bounding = self._label_fm.boundingRect(measure_rect, wrap_flags, label_text)
            draw_rect = QRectF(
                pos.x() - max_label_w / 2,
                pos.y() - bounding.height() / 2,
                max_label_w,
                bounding.height() + 2,
            )
            painter.drawText(draw_rect, wrap_flags, label_text)

        painter.end()

    @staticmethod
    def _sector_path(
        center: QPointF, outer_r: float, inner_r: float,
        start_deg: float, span_deg: float,
    ) -> QPainterPath:
        path = QPainterPath()
        outer_rect = QRectF(
            center.x() - outer_r, center.y() - outer_r,
            outer_r * 2, outer_r * 2,
        )
        inner_rect = QRectF(
            center.x() - inner_r, center.y() - inner_r,
            inner_r * 2, inner_r * 2,
        )
        # explicitly draw all four edges for a clean annular sector
        s_rad = math.radians(start_deg)
        e_rad = math.radians(start_deg + span_deg)

        path.moveTo(
            center.x() + inner_r * math.cos(s_rad),
            center.y() - inner_r * math.sin(s_rad),
        )
        path.lineTo(
            center.x() + outer_r * math.cos(s_rad),
            center.y() - outer_r * math.sin(s_rad),
        )
        path.arcTo(outer_rect, start_deg, span_deg)
        path.lineTo(
            center.x() + inner_r * math.cos(e_rad),
            center.y() - inner_r * math.sin(e_rad),
        )
        path.arcTo(inner_rect, start_deg + span_deg, -span_deg)
        path.closeSubpath()
        return path

    # -- mouse interaction (toggle mode only) --------------------------------

    def mousePressEvent(self, event) -> None:
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        local = self.mapFromGlobal(event.globalPosition().toPoint())
        dx = local.x() - self._center.x()
        dy = local.y() - self._center.y()
        dist = math.hypot(dx, dy)
        radius = self._ring_diameter / 2.0
        if dist < DEAD_ZONE_RADIUS:
            self.cancelled.emit()
        elif dist <= radius:
            sector = self._cursor_to_sector(event.globalPosition().toPoint())
            if sector >= 0:
                self.action_selected.emit(sector)
            else:
                self.cancelled.emit()
        else:
            self.cancelled.emit()
        event.accept()

    # -- internal helpers ----------------------------------------------------

    def _cursor_to_sector(self, global_pos) -> int:
        local = self.mapFromGlobal(global_pos)
        dx = local.x() - self._center.x()
        dy = local.y() - self._center.y()
        return angle_to_sector(dx, dy, len(self._slot_labels))

    def _content_position(self, sector_index: int, num_sectors: int) -> QPointF:
        sector_span = 360.0 / num_sectors
        mid_angle_deg = sector_index * sector_span
        mid_angle_rad = math.radians(mid_angle_deg)
        inner_r = DEAD_ZONE_RADIUS + _INNER_GAP
        outer_r = self._ring_diameter / 2.0
        mid_r = (inner_r + outer_r) / 2.0
        x = self._center.x() + mid_r * math.sin(mid_angle_rad)
        y = self._center.y() - mid_r * math.cos(mid_angle_rad)
        return QPointF(x, y)

    def _on_tick(self) -> None:
        needs_repaint = False
        self._tick_count += 1

        # cursor poll
        off = self._rawxy_offset
        if off is not None:
            sector = angle_to_sector(off[0], off[1], len(self._slot_labels))
        else:
            sector = self._cursor_to_sector(QCursor.pos())
        if sector != self._target_sector:
            self._target_sector = sector
            self.sector_changed.emit(sector)

        # appear scale
        if self._appear_progress < 1.0:
            self._appear_progress = min(1.0, self._tick_count / _APPEAR_FRAMES)
            needs_repaint = True

        # sector stagger reveal (uses tick_count, not appear_step)
        stagger_frames = max(1.0, _SECTOR_STAGGER_MS / _TICK_MS)
        for i in range(len(self._sector_reveal)):
            if self._sector_reveal[i] < 1.0:
                delay_frames = i * stagger_frames
                effective = self._tick_count - delay_frames
                if effective > 0:
                    self._sector_reveal[i] = min(1.0, effective / 4.0)
                    needs_repaint = True

        # highlight interpolation
        for i in range(len(self._sector_alphas)):
            target = 1.0 if i == self._target_sector else 0.0
            current = self._sector_alphas[i]
            if abs(current - target) > 0.001:
                if current < target:
                    self._sector_alphas[i] = min(target, current + _HIGHLIGHT_SPEED)
                else:
                    self._sector_alphas[i] = max(target, current - _HIGHLIGHT_SPEED)
                needs_repaint = True
        self._highlighted_sector = self._target_sector

        # pulse
        if self._target_sector >= 0 and self._dismiss_progress < 0:
            self._pulse_phase += _PULSE_SPEED
            needs_repaint = True

        # dismiss
        if self._dismiss_progress >= 0:
            self._dismiss_step += 1
            self._dismiss_progress = min(1.0, self._dismiss_step / _DISMISS_FRAMES)
            needs_repaint = True
            if self._dismiss_progress >= 1.0:
                self._tick_timer.stop()
                self._rawxy_offset = None
                self.hide()
                return

        if needs_repaint:
            self.update()
