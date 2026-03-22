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
from urllib.parse import parse_qs, unquote

# Ensure project root on path — works for both normal Python and PyInstaller
if getattr(sys, "frozen", False):
    ROOT = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Set Material theme before any Qt imports
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_ACCENT"] = "#00d4aa"

_t1 = _time.perf_counter()
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileIconProvider, QMessageBox
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import QObject, Property, QCoreApplication, QRectF, Qt, QUrl, Signal, QFileInfo
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
from core.hid_gesture import set_backend_preference as set_hid_backend_preference
from ui.backend import Backend
_t4 = _time.perf_counter()

def _print_startup_times():
    print(f"[Startup] Env setup:        {(_t1-_t0)*1000:7.1f} ms")
    print(f"[Startup] PySide6 imports:  {(_t2-_t1)*1000:7.1f} ms")
    print(f"[Startup] Core imports:     {(_t4-_t3)*1000:7.1f} ms")
    print(f"[Startup] Total imports:    {(_t4-_t0)*1000:7.1f} ms")


def _parse_cli_args(argv):
    qt_argv = [argv[0]]
    hid_backend = None
    start_hidden = False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--hid-backend":
            if i + 1 >= len(argv):
                raise SystemExit("Missing value for --hid-backend (expected: auto, hidapi, iokit)")
            hid_backend = argv[i + 1].strip().lower()
            i += 2
            continue
        if arg.startswith("--hid-backend="):
            hid_backend = arg.split("=", 1)[1].strip().lower()
            i += 1
            continue
        if arg == "--start-hidden":
            start_hidden = True
            i += 1
            continue
        qt_argv.append(arg)
        i += 1
    return qt_argv, hid_backend, start_hidden


def _app_icon() -> QIcon:
    if sys.platform == "darwin":
        icon = QIcon()
        source = QPixmap(os.path.join(ROOT, "images", "logo_icon.png"))
        if not source.isNull():
            for size in (16, 32, 64, 128, 256):
                icon.addPixmap(
                    source.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        return icon
    return QIcon(os.path.join(ROOT, "images", "logo.ico"))


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
    icon = QIcon()
    # Provide both Normal (black, for light menu bar) and Selected (white,
    # for dark menu bar) modes so macOS always picks the correct contrast.
    for size in (18, 36):
        icon.addPixmap(
            _render_svg_pixmap(tray_svg, QColor("#000000"), size),
            QIcon.Mode.Normal)
        icon.addPixmap(
            _render_svg_pixmap(tray_svg, QColor("#FFFFFF"), size),
            QIcon.Mode.Selected)
    icon.setIsMask(True)
    return icon


def _configure_macos_app_mode():
    if sys.platform != "darwin":
        return
    try:
        import AppKit
        AppKit.NSApp.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )
    except Exception as exc:
        print(f"[Mouser] Failed to configure macOS app mode: {exc}")


def _activate_macos_window():
    if sys.platform != "darwin":
        return
    try:
        import AppKit
        AppKit.NSApp.activateIgnoringOtherApps_(True)
    except Exception as exc:
        print(f"[Mouser] Failed to activate macOS window: {exc}")


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


class SystemIconProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)
        self._provider = QFileIconProvider()

    def requestPixmap(self, icon_id, size, requested_size):
        encoded_path, _, query_string = icon_id.partition("?")
        app_path = unquote(encoded_path)
        params = parse_qs(query_string)
        logical_size = requested_size.width() if requested_size.width() > 0 else 24
        if "size" in params:
            try:
                logical_size = max(12, int(params["size"][0]))
            except ValueError:
                logical_size = max(12, logical_size)

        pixmap = QPixmap()
        if app_path:
            icon = self._provider.icon(QFileInfo(app_path))
            if not icon.isNull():
                pixmap = icon.pixmap(logical_size, logical_size)

        if size is not None:
            size.setWidth(logical_size)
            size.setHeight(logical_size)
        return pixmap


def _check_accessibility() -> bool:
    """On macOS, check if Accessibility permission is granted.

    Uses AXIsProcessTrustedWithOptions to trigger the native macOS prompt
    that asks the user to grant Accessibility access.  Returns True if
    already trusted, False otherwise.
    """
    if sys.platform != "darwin":
        return True
    try:
        import ApplicationServices
        import CoreFoundation
        options = {CoreFoundation.kAXTrustedCheckOptionPrompt: True}
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(options)
        if not trusted:
            print("[Mouser] Accessibility permission not granted")
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Accessibility Permission Required")
            msg.setText(
                "Mouser needs Accessibility permission to intercept "
                "mouse button events.\n\n"
                "macOS should have opened the System Settings prompt.\n"
                "Please grant permission, then restart Mouser."
            )
            msg.setInformativeText(
                "System Settings -> Privacy & Security -> Accessibility"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        return bool(trusted)
    except ImportError:
        print(
            "[Mouser] pyobjc-framework-ApplicationServices not available - "
            "skipping accessibility check"
        )
        return True
    except Exception as exc:
        print(f"[Mouser] Accessibility check failed: {exc}")
        return True


def main():
    _print_startup_times()
    _t5 = _time.perf_counter()
    argv, hid_backend, start_hidden = _parse_cli_args(sys.argv)
    if hid_backend:
        try:
            set_hid_backend_preference(hid_backend)
        except ValueError as exc:
            raise SystemExit(f"Invalid --hid-backend setting: {exc}") from exc

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(argv)
    app.setApplicationName("Mouser")
    app.setOrganizationName("Mouser")
    app.setWindowIcon(_app_icon())
    app.setQuitOnLastWindowClosed(False)
    _configure_macos_app_mode()
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
    ui_state.appearanceMode = backend.appearanceMode
    backend.settingsChanged.connect(
        lambda: setattr(ui_state, "appearanceMode", backend.appearanceMode)
    )

    # ── QML Engine ─────────────────────────────────────────────
    qml_engine = QQmlApplicationEngine()
    qml_engine.addImageProvider("appicons", AppIconProvider(ROOT))
    qml_engine.addImageProvider("systemicons", SystemIconProvider())
    qml_engine.rootContext().setContextProperty("backend", backend)
    qml_engine.rootContext().setContextProperty("uiState", ui_state)
    qml_engine.rootContext().setContextProperty("launchHidden", start_hidden)
    qml_engine.rootContext().setContextProperty(
        "applicationDirPath", ROOT.replace("\\", "/"))

    qml_path = os.path.join(ROOT, "ui", "qml", "Main.qml")
    qml_engine.load(QUrl.fromLocalFile(qml_path))
    _t8 = _time.perf_counter()

    if not qml_engine.rootObjects():
        print("[Mouser] FATAL: Failed to load QML")
        sys.exit(1)

    root_window = qml_engine.rootObjects()[0]

    def show_main_window():
        root_window.show()
        root_window.raise_()
        root_window.requestActivate()
        _activate_macos_window()

    print(f"[Startup] QApp create:      {(_t6-_t5)*1000:7.1f} ms")
    print(f"[Startup] Engine create:    {(_t7-_t6)*1000:7.1f} ms")
    print(f"[Startup] QML load:         {(_t8-_t7)*1000:7.1f} ms")
    print(f"[Startup] TOTAL to window:  {(_t8-_t0)*1000:7.1f} ms")

    # ── Accessibility check (macOS) ──────────────────────────────
    _check_accessibility()

    # ── Start engine AFTER window is ready (deferred) ──────────
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: (
        engine.start(),
        print("[Mouser] Engine started — remapping is active"),
    ))

    # ── System Tray ────────────────────────────────────────────
    tray = QSystemTrayIcon(_tray_icon(), app)
    tray.setToolTip("Mouser")

    tray_menu = QMenu()

    open_action = QAction("Open Settings", tray_menu)
    open_action.triggered.connect(show_main_window)
    tray_menu.addAction(open_action)

    toggle_action = QAction("Disable Remapping", tray_menu)

    def toggle_remapping():
        enabled = not engine.enabled
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
            show_main_window()

    debug_action.triggered.connect(toggle_debug_mode)
    tray_menu.addAction(debug_action)
    backend.settingsChanged.connect(sync_debug_action)
    sync_debug_action()

    tray_menu.addSeparator()

    quit_action = QAction("Quit Mouser", tray_menu)

    def quit_app():
        engine.stop()
        tray.hide()
        app.quit()

    quit_action.triggered.connect(quit_app)
    tray_menu.addAction(quit_action)

    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: (
        show_main_window()
    ) if reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
    ) else None)
    tray.show()

    # ── Run ────────────────────────────────────────────────────
    try:
        sys.exit(app.exec())
    finally:
        engine.stop()
        print("[Mouser] Shut down cleanly")


if __name__ == "__main__":
    main()
