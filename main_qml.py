"""
Mouser — QML Entry Point
==============================
Launches the Qt Quick / QML UI with PySide6.
Replaces the old tkinter-based main.py.
Run with:   python main_qml.py
"""

import time as _time
_t0 = _time.perf_counter()          # ◄ startup clock

import sys
import os
import signal
from urllib.parse import parse_qs

# Ensure project root on path — works for both normal Python and PyInstaller
if getattr(sys, "frozen", False):
    # PyInstaller 6.x: data files are in _internal/ next to the exe
    ROOT = os.path.join(os.path.dirname(sys.executable), "_internal")
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Set Material theme before any Qt imports
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_ACCENT"] = "#00d4aa"

_t1 = _time.perf_counter()
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import QObject, Property, QCoreApplication, QRectF, Qt, QUrl, Signal
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer
_t2 = _time.perf_counter()

# Ensure PySide6 QML plugins are found
import PySide6
_pyside_dir = os.path.dirname(PySide6.__file__)
os.environ.setdefault("QML2_IMPORT_PATH", os.path.join(_pyside_dir, "qml"))
os.environ.setdefault("QT_PLUGIN_PATH", os.path.join(_pyside_dir, "plugins"))

_t3 = _time.perf_counter()
from core.engine import Engine
from ui.backend import Backend
_t4 = _time.perf_counter()

def _print_startup_times():
    print(f"[Startup] Env setup:        {(_t1-_t0)*1000:7.1f} ms")
    print(f"[Startup] PySide6 imports:  {(_t2-_t1)*1000:7.1f} ms")
    print(f"[Startup] Core imports:     {(_t4-_t3)*1000:7.1f} ms")
    print(f"[Startup] Total imports:    {(_t4-_t0)*1000:7.1f} ms")


def _app_icon() -> QIcon:
    """Load the app icon from the pre-cropped .ico file."""
    ico = os.path.join(ROOT, "images", "logo.ico")
    return QIcon(ico)


def _render_svg_pixmap(path: str, color: QColor, size: int) -> QPixmap:
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return QPixmap()

    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    pixel_size = max(size, int(round(size * dpr)))

    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return pixmap


def _tray_icon() -> QIcon:
    if sys.platform != "darwin":
        return _app_icon()

    tray_svg = os.path.join(ROOT, "images", "icons", "mouse-simple.svg")
    icon = QIcon(_render_svg_pixmap(tray_svg, QColor("#000000"), 18))
    icon.setIsMask(True)
    return icon


class UiState(QObject):
    appearanceModeChanged = Signal()
    systemAppearanceChanged = Signal()
    darkModeChanged = Signal()

    def __init__(self, app: QApplication, parent=None):
        super().__init__(parent)
        self._app = app
        self._appearance_mode = "system"
        self._font_family = app.font().family()
        if self._font_family in {"", "Sans Serif"}:
            if sys.platform == "darwin":
                self._font_family = ".AppleSystemUIFont"
            elif sys.platform == "win32":
                self._font_family = "Segoe UI"
            else:
                self._font_family = "Noto Sans"
        self._system_dark_mode = False
        self._sync_system_appearance()

        style_hints = app.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(
                lambda *_: self._sync_system_appearance()
            )

    def _sync_system_appearance(self):
        is_dark = self._app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        if is_dark == self._system_dark_mode:
            return
        self._system_dark_mode = is_dark
        self.systemAppearanceChanged.emit()
        self.darkModeChanged.emit()

    @Property(str, notify=appearanceModeChanged)
    def appearanceMode(self):
        return self._appearance_mode

    @appearanceMode.setter
    def appearanceMode(self, mode):
        normalized = mode if mode in {"system", "light", "dark"} else "system"
        if normalized == self._appearance_mode:
            return
        self._appearance_mode = normalized
        self.appearanceModeChanged.emit()
        self.darkModeChanged.emit()

    @Property(bool, notify=systemAppearanceChanged)
    def systemDarkMode(self):
        return self._system_dark_mode

    @Property(bool, notify=darkModeChanged)
    def darkMode(self):
        if self._appearance_mode == "dark":
            return True
        if self._appearance_mode == "light":
            return False
        return self._system_dark_mode

    @Property(str, constant=True)
    def fontFamily(self):
        return self._font_family


class AppIconProvider(QQuickImageProvider):
    def __init__(self, root_dir: str):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)
        self._icon_dir = os.path.join(root_dir, "images", "icons")

    def requestPixmap(self, icon_id, size, requested_size):
        name, _, query_string = icon_id.partition("?")
        params = parse_qs(query_string)
        color = QColor(params.get("color", ["#000000"])[0])
        logical_size = requested_size.width() if requested_size.width() > 0 else 24
        if "size" in params:
            try:
                logical_size = max(12, int(params["size"][0]))
            except ValueError:
                logical_size = max(12, logical_size)

        icon_name = name if name.endswith(".svg") else f"{name}.svg"
        icon_path = os.path.join(self._icon_dir, icon_name)
        pixmap = _render_svg_pixmap(icon_path, color, logical_size)
        if size is not None:
            size.setWidth(logical_size)
            size.setHeight(logical_size)
        return pixmap


def main():
    _print_startup_times()
    _t5 = _time.perf_counter()

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Mouser")
    app.setOrganizationName("Mouser")
    app.setWindowIcon(_app_icon())
    ui_state = UiState(app)

    # macOS: allow Ctrl+C in terminal to quit the app
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == "darwin":
        # SIGUSR1 thread dump (useful for debugging on macOS)
        import traceback
        def _dump_threads(sig, frame):
            import threading
            for t in threading.enumerate():
                print(f"\n--- {t.name} ---")
                if t.ident:
                    traceback.print_stack(sys._current_frames().get(t.ident))
        signal.signal(signal.SIGUSR1, _dump_threads)

    _t6 = _time.perf_counter()
    # ── Engine (created but started AFTER UI is visible) ───────
    engine = Engine()

    _t7 = _time.perf_counter()
    # ── QML Backend ────────────────────────────────────────────
    backend = Backend(engine)

    # ── QML Engine ─────────────────────────────────────────────
    qml_engine = QQmlApplicationEngine()
    qml_engine.addImageProvider("appicons", AppIconProvider(ROOT))
    qml_engine.rootContext().setContextProperty("backend", backend)
    qml_engine.rootContext().setContextProperty("uiState", ui_state)
    qml_engine.rootContext().setContextProperty(
        "applicationDirPath", ROOT.replace("\\", "/"))

    qml_path = os.path.join(ROOT, "ui", "qml", "Main.qml")
    qml_engine.load(QUrl.fromLocalFile(qml_path))
    _t8 = _time.perf_counter()

    if not qml_engine.rootObjects():
        print("[Mouser] FATAL: Failed to load QML")
        sys.exit(1)

    root_window = qml_engine.rootObjects()[0]

    print(f"[Startup] QApp create:      {(_t6-_t5)*1000:7.1f} ms")
    print(f"[Startup] Engine create:    {(_t7-_t6)*1000:7.1f} ms")
    print(f"[Startup] QML load:         {(_t8-_t7)*1000:7.1f} ms")
    print(f"[Startup] TOTAL to window:  {(_t8-_t0)*1000:7.1f} ms")

    # ── Start engine AFTER window is ready (deferred) ──────────
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: (
        engine.start(),
        print("[Mouser] Engine started — remapping is active"),
    ))

    # ── System Tray ────────────────────────────────────────────
    tray = QSystemTrayIcon(_tray_icon(), app)
    tray.setToolTip("Mouser")

    def _update_tray_tooltip():
        name = backend.deviceName or "MX Master 3S"
        tray.setToolTip(f"Mouser — {name}")

    backend.deviceChanged.connect(_update_tray_tooltip)
    _update_tray_tooltip()

    tray_menu = QMenu()

    open_action = QAction("Open Settings", tray_menu)
    open_action.triggered.connect(lambda: (
        root_window.show(),
        root_window.raise_(),
        root_window.requestActivate(),
    ))
    tray_menu.addAction(open_action)

    toggle_action = QAction("Disable Remapping", tray_menu)

    def toggle_remapping():
        enabled = not engine._enabled
        engine.set_enabled(enabled)
        toggle_action.setText(
            "Disable Remapping" if enabled else "Enable Remapping")

    toggle_action.triggered.connect(toggle_remapping)
    tray_menu.addAction(toggle_action)

    debug_action = QAction("Enable Debug Mode", tray_menu)

    def sync_debug_action():
        debug_enabled = bool(backend.debugMode)
        debug_action.setText(
            "Disable Debug Mode" if debug_enabled else "Enable Debug Mode"
        )

    def toggle_debug_mode():
        backend.setDebugMode(not backend.debugMode)
        sync_debug_action()
        if backend.debugMode:
            root_window.show()
            root_window.raise_()
            root_window.requestActivate()

    debug_action.triggered.connect(toggle_debug_mode)
    tray_menu.addAction(debug_action)
    backend.settingsChanged.connect(sync_debug_action)
    sync_debug_action()

    tray_menu.addSeparator()

    quit_action = QAction("Quit Mouser", tray_menu)

    def quit_app():
        engine.hook.stop()
        engine._app_detector.stop()
        tray.hide()
        app.quit()

    quit_action.triggered.connect(quit_app)
    tray_menu.addAction(quit_action)

    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: (
        root_window.show(),
        root_window.raise_(),
        root_window.requestActivate(),
    ) if reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
    ) else None)
    tray.show()

    # ── Run ────────────────────────────────────────────────────
    try:
        sys.exit(app.exec())
    finally:
        engine.hook.stop()
        engine._app_detector.stop()
        print("[Mouser] Shut down cleanly")


if __name__ == "__main__":
    main()
