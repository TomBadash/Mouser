"""
LogiControl — QML Entry Point
==============================
Launches the Qt Quick / QML UI with PySide6.
Replaces the old tkinter-based main.py.
Run with:   python main_qml.py
"""

import sys
import os
import time
import threading
import traceback
import signal

# Ensure project root on path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

_t0 = time.time()
def _dbg(msg):
    print(f"[DBG {time.time()-_t0:6.2f}s] {msg}", flush=True)

def _dump_threads(sig=None, frame=None):
    """Print a stack trace for every live thread — called via SIGUSR1."""
    print("\n===== THREAD DUMP =====", flush=True)
    frames = sys._current_frames()
    for tid, f in frames.items():
        tname = next((t.name for t in threading.enumerate() if t.ident == tid), f"tid-{tid}")
        print(f"\n--- Thread: {tname} (id={tid}) ---", flush=True)
        traceback.print_stack(f)
    print("===== END DUMP =====\n", flush=True)

# Ctrl+C sets a flag; a Qt timer checks it and triggers a clean quit
_quit_requested = False
def _sigint_handler(sig, frame):
    global _quit_requested
    print("\n[LogiControl] Ctrl+C received — shutting down...", flush=True)
    _quit_requested = True

signal.signal(signal.SIGINT, _sigint_handler)
signal.signal(signal.SIGUSR1, _dump_threads)  # kill -USR1 <pid> → dump

# ── CLI diagnostic flags ───────────────────────────────────────────
NO_HID      = "--no-hid"      in sys.argv   # skip HidGestureListener
NO_MONITORS = "--no-monitors" in sys.argv   # skip NSEvent global monitors
if NO_HID:      _dbg("*** --no-hid: HidGestureListener will be skipped ***")
if NO_MONITORS: _dbg("*** --no-monitors: NSEvent monitors will be skipped ***")

os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_THEME"] = "Dark"
os.environ["QT_QUICK_CONTROLS_MATERIAL_ACCENT"] = "#00d4aa"

_dbg("importing PySide6...")
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMenuBar
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import Qt, QUrl, QCoreApplication, QTimer
from PySide6.QtQml import QQmlApplicationEngine
_dbg("PySide6 imported")

# ── Rename macOS app menu from "Python" to "MouseControl" ──────
if sys.platform == "darwin":
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["CFBundleName"] = "MouseControl"
            info["CFBundleDisplayName"] = "MouseControl"
            _dbg("Set CFBundleName/CFBundleDisplayName to MouseControl")
    except Exception as e:
        _dbg(f"Could not rename app menu: {e}")

def _rename_macos_menu():
    """Rename the first NSApp menu title from 'Python' to 'MouseControl'."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication
        ns_app = NSApplication.sharedApplication()
        main_menu = ns_app.mainMenu()
        if main_menu and main_menu.numberOfItems() > 0:
            app_menu_item = main_menu.itemAtIndex_(0)
            app_menu_item.setTitle_("MouseControl")
            sub = app_menu_item.submenu()
            if sub:
                sub.setTitle_("MouseControl")
            _dbg("Renamed NSApp main menu to MouseControl")
    except Exception as e:
        _dbg(f"Could not rename NSApp menu: {e}")

# Ensure PySide6 QML plugins are found
import PySide6
_pyside_dir = os.path.dirname(PySide6.__file__)
os.environ.setdefault("QML2_IMPORT_PATH", os.path.join(_pyside_dir, "qml"))
os.environ.setdefault("QT_PLUGIN_PATH", os.path.join(_pyside_dir, "plugins"))

_dbg("importing core modules...")
from core.engine import Engine
from ui.backend import Backend
_dbg("core modules imported")

# ── Safety Timer: Auto-kill if mouse freezes ───────────────────
_safety_timeout = 10  # seconds - kill app if no mouse activity
_safety_last_activity = time.time()
_safety_tap = None
_safety_tap_source = None

def _reset_safety_timer():
    """Reset the safety timer - called when mouse activity detected."""
    global _safety_last_activity
    _safety_last_activity = time.time()

def _safety_event_callback(proxy, event_type, cg_event, refcon):
    """Monitor all mouse events to detect activity (pass-through only)."""
    _reset_safety_timer()
    return cg_event  # Always pass through - we're just monitoring

def _check_safety_timeout():
    """Check if mouse has been frozen for too long."""
    elapsed = time.time() - _safety_last_activity
    if elapsed > _safety_timeout:
        print(f"\n{'='*60}", flush=True)
        print("⚠️  SAFETY TIMEOUT: No mouse activity detected!", flush=True)
        print(f"⚠️  Mouse may be frozen - auto-killing application", flush=True)
        print(f"{'='*60}\n", flush=True)
        os._exit(1)  # Hard exit
    elif elapsed > _safety_timeout / 2:
        remaining = _safety_timeout - elapsed
        print(f"⏱  Safety timer: {remaining:.1f}s remaining (move mouse to reset)", flush=True)

def _setup_safety_monitor():
    """Setup a passive event tap to monitor all mouse activity."""
    global _safety_tap, _safety_tap_source
    if sys.platform != "darwin":
        return  # Only needed on macOS
    
    try:
        import Quartz
        print(f"\n{'='*60}", flush=True)
        print("🛡️  SAFETY MONITOR ACTIVE", flush=True)
        print(f"🛡️  Will auto-kill if no mouse activity for {_safety_timeout} seconds", flush=True)
        print(f"🛡️  Move your mouse to reset the timer", flush=True)
        print(f"{'='*60}\n", flush=True)
        
        # Monitor ALL mouse events (move, click, drag, scroll - everything)
        event_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved) |
            Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDragged) |
            Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDragged) |
            Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDragged) |
            Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        )
        
        _safety_tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,  # Listen-only (never blocks)
            event_mask,
            _safety_event_callback,
            None
        )
        
        if _safety_tap is None:
            print("⚠️  Could not create safety monitor tap (Accessibility permission needed)", flush=True)
            return
        
        _safety_tap_source = Quartz.CFMachPortCreateRunLoopSource(None, _safety_tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            _safety_tap_source,
            Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(_safety_tap, True)
        print("✅ Safety monitor installed successfully\n", flush=True)
    except Exception as e:
        print(f"⚠️  Safety monitor setup failed: {e}", flush=True)

def _cleanup_safety_monitor():
    """Remove the safety monitor tap."""
    global _safety_tap, _safety_tap_source
    if sys.platform != "darwin":
        return
    if _safety_tap:
        try:
            import Quartz
            Quartz.CGEventTapEnable(_safety_tap, False)
            if _safety_tap_source:
                Quartz.CFRunLoopRemoveSource(
                    Quartz.CFRunLoopGetCurrent(),
                    _safety_tap_source,
                    Quartz.kCFRunLoopCommonModes
                )
            print("🛡️  Safety monitor removed", flush=True)
        except:
            pass
        _safety_tap = None
        _safety_tap_source = None


def _app_icon() -> QIcon:
    """Load the app icon from the pre-cropped .ico file."""
    ico = os.path.join(ROOT, "images", "logo.ico")
    return QIcon(ico)


def main():
    _dbg("creating QApplication...")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("LogiControl")
    app.setOrganizationName("LogiControl")
    app.setWindowIcon(_app_icon())
    _rename_macos_menu()
    _dbg("QApplication created")

    # ── Engine ─────────────────────────────────────────────────
    _dbg("creating Engine...")
    engine = Engine()
    engine.hook._no_hid      = NO_HID
    engine.hook._no_monitors = NO_MONITORS
    _dbg("Engine created, calling engine.start()...")
    engine.start()
    _dbg("engine.start() returned")
    print("[LogiControl] Engine started — remapping is active")

    # ── Safety Monitor ────────────────────────────────────────
    _setup_safety_monitor()

    # ── QML Backend ────────────────────────────────────────────
    _dbg("creating Backend...")
    backend = Backend(engine)
    _dbg("Backend created")

    # ── QML Engine ─────────────────────────────────────────────
    _dbg("creating QQmlApplicationEngine...")
    qml_engine = QQmlApplicationEngine()
    qml_engine.rootContext().setContextProperty("backend", backend)
    qml_engine.rootContext().setContextProperty(
        "applicationDirPath", ROOT.replace("\\", "/"))

    qml_path = os.path.join(ROOT, "ui", "qml", "Main.qml")
    _dbg(f"loading QML from {qml_path}...")
    qml_engine.load(QUrl.fromLocalFile(qml_path))
    _dbg("QML loaded")

    if not qml_engine.rootObjects():
        print("[LogiControl] FATAL: Failed to load QML")
        sys.exit(1)

    root_window = qml_engine.rootObjects()[0]
    _dbg("root QML window ready")

    # ── System Tray ────────────────────────────────────────────
    tray = QSystemTrayIcon(_app_icon(), app)
    tray.setToolTip("LogiControl — MX Master 3S")

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

    tray_menu.addSeparator()

    quit_action = QAction("Quit LogiControl", tray_menu)

    def quit_app():
        _cleanup_safety_monitor()
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
    ) if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    tray.show()

    # ── macOS Menu Bar ("MouseControl" → Quit) ─────────────────
    menu_bar = QMenuBar()
    app_menu = menu_bar.addMenu("MouseControl")

    quit_menu_action = QAction("Quit MouseControl", menu_bar)
    quit_menu_action.setMenuRole(QAction.MenuRole.QuitRole)
    quit_menu_action.triggered.connect(quit_app)
    app_menu.addAction(quit_menu_action)

    # ── Ctrl+C support: periodically check the signal flag ─────
    def _check_sigint():
        if _quit_requested:
            quit_app()

    sigint_timer = QTimer()
    sigint_timer.timeout.connect(_check_sigint)
    sigint_timer.start(200)

    # ── Safety timeout checker ─────────────────────────────────
    safety_timer = QTimer()
    safety_timer.timeout.connect(_check_safety_timeout)
    safety_timer.start(1000)  # Check every second

    # ── Run ────────────────────────────────────────────────────
    _dbg("entering app.exec() — Qt event loop starting")
    try:
        sys.exit(app.exec())
    finally:
        _cleanup_safety_monitor()
        engine.hook.stop()
        engine._app_detector.stop()
        print("[LogiControl] Shut down cleanly")


if __name__ == "__main__":
    main()
