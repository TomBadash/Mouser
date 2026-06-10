"""
Mouser -- QML Entry Point
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
import hashlib
import getpass
import time
from urllib.parse import parse_qs, unquote

# Ensure project root on path -- works for both normal Python and PyInstaller.
# PyInstaller on Windows/Linux stores bundled data in `_internal/` next to the
# executable, while macOS app bundles expose resources from `Contents/Resources`.
def _resolve_root_dir():
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "darwin":
        resources_dir = os.path.abspath(
            os.path.join(os.path.dirname(sys.executable), "..", "Resources")
        )
        return getattr(sys, "_MEIPASS", resources_dir)
    return getattr(
        sys,
        "_MEIPASS",
        os.path.join(os.path.dirname(sys.executable), "_internal"),
    )


ROOT = _resolve_root_dir()
sys.path.insert(0, ROOT)

from core.log_setup import setup_logging
setup_logging()

# Set Material theme before any Qt imports
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_ACCENT"] = "#00d4aa"

_t1 = _time.perf_counter()
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileIconProvider, QMessageBox
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QWindow
from PySide6.QtCore import QObject, Property, QCoreApplication, QRectF, Qt, QUrl, Signal, QFileInfo, QEvent, QTimer
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QAbstractSocket
_t2 = _time.perf_counter()

# Ensure PySide6 QML plugins are found
import PySide6
_pyside_dir = os.path.dirname(PySide6.__file__)
os.environ.setdefault("QML2_IMPORT_PATH", os.path.join(_pyside_dir, "qml"))
os.environ.setdefault("QT_PLUGIN_PATH", os.path.join(_pyside_dir, "plugins"))

_t3 = _time.perf_counter()
from core.config import load_config, save_config
from core.engine import Engine
from core.hid_gesture import set_backend_preference as set_hid_backend_preference
from core.accessibility import is_process_trusted
from core.version import APP_BUILD_MODE, APP_COMMIT_DISPLAY, APP_VERSION
from ui.backend import Backend
from ui.locale_manager import LocaleManager
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
    force_show = False
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
        if arg == "--show-window":
            force_show = True
            i += 1
            continue
        qt_argv.append(arg)
        i += 1
    return qt_argv, hid_backend, start_hidden, force_show


_SINGLE_INSTANCE_ACTIVATE_MSG = b"show"


def _single_instance_server_name() -> str:
    raw = f"{getpass.getuser()}\0{sys.platform}"
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"mouser_instance_{digest}"


def _try_activate_existing_instance(server_name: str, timeout_ms: int = 500) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(_SINGLE_INSTANCE_ACTIVATE_MSG)
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


def _drain_local_activate_socket(sock: QLocalSocket | None) -> None:
    if not sock:
        return
    sock.waitForReadyRead(300)
    sock.readAll()
    sock.deleteLater()


def _single_instance_acquire(app: QApplication, server_name: str):
    """Return (QLocalServer, None) if this process owns the instance, or (None, exit_code)."""
    if _try_activate_existing_instance(server_name):
        return None, 0
    server = QLocalServer(app)
    QLocalServer.removeServer(server_name)
    if server.listen(server_name):
        return server, None
    if server.serverError() != QAbstractSocket.SocketError.AddressInUseError:
        print(f"[Mouser] single-instance server: {server.errorString()}")
        return None, 1
    for _ in range(3):
        time.sleep(0.05)
        if _try_activate_existing_instance(server_name):
            return None, 0
        QLocalServer.removeServer(server_name)
        server.close()
        if server.listen(server_name):
            return server, None
    print("[Mouser] Could not claim single-instance lock or reach running instance.")
    return None, 1


def _app_icon() -> QIcon:
    """Build the QIcon for the window title bar. On macOS, hand QIcon the
    full-resolution 1024px PNG so AppKit's setApplicationIconImage_
    (called via QApplication.setWindowIcon) renders crisply at the full
    Dock tile size instead of the upscaled-256px blur the pre-scaled
    pixmap path produced. Logs and returns an empty QIcon if the asset
    file is missing.
    """
    icon_name = "logo_icon.png" if sys.platform == "darwin" else "logo.ico"
    icon_path = os.path.join(ROOT, "images", icon_name)
    if not os.path.isfile(icon_path):
        print(f"[Mouser] App icon missing: {icon_path}")
        return QIcon()
    return QIcon(icon_path)


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


_MACOS_RELAUNCH_GUARD = "MOUSER_MACOS_RELAUNCHED"


def _macos_named_executable_path() -> str:
    """Return a stable path for the `Mouser`-named launcher symlink.

    When ``sys.executable`` is in a virtualenv, place the symlink next to
    the venv's python shim so `pyvenv.cfg` discovery still resolves
    site-packages after the re-exec. Otherwise fall back to a path inside
    the project tree so it stays stable across reboots.
    """
    exec_dir = os.path.dirname(sys.executable)
    pyvenv_cfg = os.path.join(os.path.dirname(exec_dir), "pyvenv.cfg")
    if os.path.isfile(pyvenv_cfg):
        return os.path.join(exec_dir, "Mouser")
    return os.path.join(ROOT, "build", "macos", "bin", "Mouser")


def _maybe_relaunch_with_mouser_process_name() -> None:
    """Re-exec the interpreter through a `Mouser`-named symlink.

    macOS reads the user-visible process name from the Mach-O image
    header at execve() time. For a bundle-less launch (``python
    main_qml.py``) that means the Dock tile, Cmd+Tab caption, Force
    Quit, and Activity Monitor all read "python", and there is no
    in-process API to rename the image afterwards. Re-execing through
    a symlink whose basename is `Mouser` is the only reliable fix.

    Returns immediately on non-macOS, on PyInstaller-frozen bundles
    (already correctly named), when the env-var guard shows we already
    relaunched, when the basename already starts with "mouser", or
    when the symlink can't be staged.
    """
    if sys.platform != "darwin":
        return
    if getattr(sys, "frozen", False):
        return
    if os.environ.get(_MACOS_RELAUNCH_GUARD) == "1":
        return
    source_executable = sys.executable
    if not source_executable or not os.path.isfile(source_executable):
        print("[Mouser] sys.executable missing or not a file; skipping relaunch")
        return
    # Important: link the venv shim (`sys.executable`), NOT the underlying
    # interpreter (`os.path.realpath(sys.executable)`). The shim is what
    # holds the venv's identity; the real interpreter has no venv context.
    current_basename = os.path.basename(source_executable)
    if current_basename.lower().startswith("mouser"):
        return
    target = _macos_named_executable_path()
    target_dir = os.path.dirname(target)
    # Stage atomically via a unique temp symlink + os.replace(). This
    # avoids the unlink/symlink TOCTOU window where a concurrent launch
    # could observe `target` missing, and never leaves a moment when the
    # launcher path doesn't resolve to a usable executable.
    staging = f"{target}.staging.{os.getpid()}"
    try:
        os.makedirs(target_dir, exist_ok=True)
        try:
            os.symlink(source_executable, staging)
        except FileExistsError:
            # Crashed prior run left a staging symlink behind. Clear it
            # and retry once; any further failure falls through to the
            # outer except and the in-place fallback.
            os.remove(staging)
            os.symlink(source_executable, staging)
        try:
            os.replace(staging, target)
        except OSError:
            # Best-effort cleanup of our staging entry so we don't leak
            # one per failed relaunch attempt.
            try:
                os.remove(staging)
            except OSError:
                pass
            raise
    except OSError as exc:
        print(f"[Mouser] Could not stage Mouser-named launcher: {exc}")
        return
    os.environ[_MACOS_RELAUNCH_GUARD] = "1"
    new_argv = [target, *sys.argv]
    print(
        f"[Mouser] Re-execing through {target} so the Dock shows 'Mouser' "
        f"instead of '{current_basename}'"
    )
    try:
        os.execv(target, new_argv)
    except OSError as exc:
        # If exec fails for any reason, fall back to in-place launch so
        # the user still gets a working app, just with the wrong label.
        print(f"[Mouser] Re-exec failed: {exc}; continuing with current process")
        os.environ.pop(_MACOS_RELAUNCH_GUARD, None)


def _rename_macos_bundle_for_dock():
    """Override CFBundleName / CFBundleDisplayName before NSApplication
    is constructed. AppKit reads `[NSBundle mainBundle]` once during init
    to populate the application menu, Force Quit, notification banners,
    etc. The Dock label itself is still driven by the relaunch above.
    """
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is None:
            return
        info["CFBundleName"] = "Mouser"
        info["CFBundleDisplayName"] = "Mouser"
        info.setdefault("CFBundleExecutable", "Mouser")
    except Exception as exc:
        print(f"[Mouser] Could not pre-rename bundle for Dock: {exc}")


# Cached AppKit module + Dock-icon NSImage + last-applied activation policy.
# These are populated only after the corresponding AppKit calls succeed so
# a failure path doesn't leave the cached state out of sync with reality.
# Caching matters because `visibilityChanged` can fire repeatedly under
# rapid window state churn (minimize/restore storms, Spaces switches), and
# without a cache each fire would re-decode the 1024px PNG and re-issue
# AppKit calls that are no-ops for the Dock anyway.
_MACOS_APPKIT = None
_MACOS_DOCK_ICON_NSIMAGE = None
_MACOS_ACTIVATION_POLICY_REGULAR: "bool | None" = None
_MACOS_NATIVE_STATUS_ITEM = None
_MACOS_NATIVE_STATUS_TARGET = None
_MACOS_QUIT_FILTER = None
_MACOS_SYSTEM_QUIT_REASONS = {
    "quia",  # kAEQuitAll
    "shut",  # kAEShutDown
    "rest",  # kAERestart
    "rlgo",  # kAEReallyLogOut
    "logo",  # kAELogOut
    "rrst",  # kAEShowRestartDialog
    "rsdn",  # kAEShowShutdownDialog
}


try:
    from Foundation import NSObject as _MacOSNSObject  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - Foundation is only available on macOS
    _MacOSNSObject = None


def _call_objc_value(obj, name, default=None):
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    try:
        return value() if callable(value) else value
    except Exception:
        return default


def _int_const(module, *names, default=0):
    for name in names:
        value = getattr(module, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
    return default


def _four_char_code(value: str) -> int:
    if len(value) != 4:
        raise ValueError("four-character codes must be exactly 4 characters")
    return int.from_bytes(value.encode("mac_roman"), "big")


def _descriptor_code_value(descriptor):
    if descriptor is None:
        return None
    for attr_name in ("enumCodeValue", "typeCodeValue", "int32Value"):
        value = _call_objc_value(descriptor, attr_name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _macos_current_quit_is_system_session_event() -> bool:
    """Return True for logout/restart/shutdown AppleEvent quit reasons."""
    if sys.platform != "darwin":
        return False
    appkit = _macos_appkit()
    if appkit is None:
        return False
    try:
        manager = appkit.NSAppleEventManager.sharedAppleEventManager()
        apple_event = manager.currentAppleEvent()
        if apple_event is None:
            return False
        reason = apple_event.attributeDescriptorForKeyword_(
            _four_char_code("why?")
        )
    except Exception:
        return False
    reason_code = _descriptor_code_value(reason)
    if reason_code is None:
        return False
    return reason_code in {
        _four_char_code(value) for value in _MACOS_SYSTEM_QUIT_REASONS
    }


def _macos_status_event_opens_menu(event, appkit) -> bool:
    """Return True when an NSStatusItem click should open the tray menu."""
    if event is None or appkit is None:
        return False
    event_type = _call_objc_value(event, "type")
    try:
        event_type = int(event_type)
    except (TypeError, ValueError):
        pass

    menu_event_types = {
        _int_const(appkit, "NSRightMouseDown", "NSEventTypeRightMouseDown", default=None),
        _int_const(appkit, "NSOtherMouseDown", "NSEventTypeOtherMouseDown", default=None),
    }
    menu_event_types.discard(None)
    if event_type in menu_event_types:
        return True

    modifiers = _call_objc_value(event, "modifierFlags", 0) or 0
    try:
        modifiers = int(modifiers)
    except (TypeError, ValueError):
        modifiers = 0
    menu_modifiers = (
        _int_const(appkit, "NSControlKeyMask", "NSEventModifierFlagControl")
        | _int_const(appkit, "NSAlternateKeyMask", "NSEventModifierFlagOption")
    )
    return bool(modifiers & menu_modifiers)


def _dispatch_macos_status_item_click(handlers):
    appkit = handlers.get("appkit")
    event = None
    try:
        event = appkit.NSApp.currentEvent()
    except Exception:
        pass
    key = "menu" if _macos_status_event_opens_menu(event, appkit) else "primary"
    handler = handlers.get(key) or handlers.get("primary")
    if handler is not None:
        handler()


if _MacOSNSObject is not None:
    class _MacOSStatusItemTarget(_MacOSNSObject):
        """Objective-C target that forwards NSStatusItem clicks to Python."""

        def setPyHandlers_(self, handlers):  # type: ignore[override]
            self._py_handlers = handlers

        def statusItemClicked_(self, sender):  # type: ignore[override]
            try:
                _dispatch_macos_status_item_click(getattr(self, "_py_handlers", {}))
            except Exception as exc:  # noqa: BLE001
                print(f"[Mouser] status-item click handler raised: {exc}")
else:
    _MacOSStatusItemTarget = None


class _MacOSQuitToTrayFilter(QObject):
    """Intercept app-level quit requests and hide the window instead."""

    def __init__(self, root_window, parent=None):
        super().__init__(parent)
        self._root_window = root_window
        self._allow_quit = False

    def allow_quit(self) -> None:
        self._allow_quit = True

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if self._allow_quit:
            return False
        try:
            if event.type() != QEvent.Type.Quit:
                return False
            if _macos_current_quit_is_system_session_event():
                self.allow_quit()
                return False
            self._root_window.hide()
            if hasattr(event, "ignore"):
                event.ignore()
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[Mouser] Failed to hide on macOS quit event: {exc}")
            return False


def _allow_macos_session_quit_if_requested(quit_filter) -> bool:
    """Allow quit only when the current macOS event is a session shutdown."""
    if quit_filter is None:
        return False
    if not _macos_current_quit_is_system_session_event():
        return False
    quit_filter.allow_quit()
    return True


def _macos_appkit():
    """Lazy-import + cache of the AppKit module. Returns None on import
    failure (logged once) so callers can no-op cleanly."""
    global _MACOS_APPKIT
    if _MACOS_APPKIT is not None:
        return _MACOS_APPKIT
    try:
        import AppKit
    except Exception as exc:
        print(f"[Mouser] Failed to import AppKit: {exc}")
        return None
    _MACOS_APPKIT = AppKit
    return AppKit


def _configure_macos_app_mode():
    """Initial activation policy at launch time. Stays Accessory (menu-bar
    only) until the window opens, at which point we promote to Regular so
    Mouser becomes a real Cmd+Tab-able foreground app."""
    _set_macos_activation_policy(regular=False)


def _install_macos_dock_icon():
    """Replace the Dock / Cmd+Tab / Mission Control icon with Mouser's
    logo. Qt's ``app.setWindowIcon()`` only covers the title bar on
    macOS, so without this override a bare ``python main_qml.py`` shows
    the generic Python launcher icon. The decoded NSImage is cached at
    module scope so repeated calls only re-issue the cheap
    ``setApplicationIconImage_`` syscall.
    """
    global _MACOS_DOCK_ICON_NSIMAGE
    if sys.platform != "darwin":
        return
    appkit = _macos_appkit()
    if appkit is None:
        return
    if _MACOS_DOCK_ICON_NSIMAGE is None:
        icon_path = os.path.join(ROOT, "images", "logo_icon.png")
        if not os.path.isfile(icon_path):
            print(f"[Mouser] Could not load Dock icon from {icon_path}")
            return
        try:
            ns_image = appkit.NSImage.alloc().initWithContentsOfFile_(icon_path)
        except Exception as exc:
            print(f"[Mouser] Failed to decode Dock icon {icon_path}: {exc}")
            return
        if ns_image is None:
            print(f"[Mouser] Could not load Dock icon from {icon_path}")
            return
        # NSImage may flag the image as "template" (auto-tinted to the
        # system colors, which strips our gradient and renders the
        # silhouette in monochrome black/white). Force-disable template
        # mode so the full-color PNG comes through.
        if hasattr(ns_image, "setTemplate_"):
            ns_image.setTemplate_(False)
        size = ns_image.size()
        print(
            f"[Mouser] Dock icon loaded {icon_path} "
            f"size={size.width:.0f}x{size.height:.0f}"
        )
        _MACOS_DOCK_ICON_NSIMAGE = ns_image
    try:
        appkit.NSApp.setApplicationIconImage_(_MACOS_DOCK_ICON_NSIMAGE)
    except Exception as exc:
        print(f"[Mouser] Failed to apply macOS Dock icon: {exc}")


def _set_macos_activation_policy(regular: bool) -> None:
    """Toggle between the Regular (foreground, Dock + Cmd+Tab) and
    Accessory (menu-bar only) policies. On a Regular promotion AppKit
    creates the Dock tile lazily and seeds the icon from the running
    executable's bundle, so this also re-applies the Mouser Dock icon
    after the flip. Skips the AppKit round-trip when the requested
    state already matches the last-applied one, which keeps rapid
    ``visibilityChanged`` storms cheap.
    """
    global _MACOS_ACTIVATION_POLICY_REGULAR
    if sys.platform != "darwin":
        return
    if _MACOS_ACTIVATION_POLICY_REGULAR == regular:
        return
    appkit = _macos_appkit()
    if appkit is None:
        return
    try:
        policy = (
            appkit.NSApplicationActivationPolicyRegular if regular
            else appkit.NSApplicationActivationPolicyAccessory
        )
        appkit.NSApp.setActivationPolicy_(policy)
    except Exception as exc:
        print(f"[Mouser] Failed to set macOS activation policy: {exc}")
        return
    _MACOS_ACTIVATION_POLICY_REGULAR = regular
    if regular:
        _install_macos_dock_icon()


def _activate_macos_window():
    if sys.platform != "darwin":
        return
    try:
        import AppKit
        AppKit.NSApp.activateIgnoringOtherApps_(True)
    except Exception as exc:
        print(f"[Mouser] Failed to activate macOS window: {exc}")


def _install_native_macos_status_item(qmenu, on_left_click):
    """Install a native AppKit ``NSStatusItem`` for the menu-bar.

    Qt's ``QSystemTrayIcon`` uses a fixed square ``NSStatusItem`` on
    macOS. On notched MacBooks, constrained menu-bar space can hide
    status items in ways Apple does not expose through a reliable API.
    Creating the item directly with ``NSVariableStatusItemLength`` keeps
    the icon as narrow as its content and avoids Qt's Cocoa wrapper path.

    The existing Qt ``QMenu`` remains the single source for localized
    labels and action wiring: plain left click shows the window, while
    right-click, control-click, and option-click pop up the menu.

    Returns the retained ``NSStatusItem`` on success, ``None`` on
    any failure -- callers should fall back to ``QSystemTrayIcon``.
    """
    global _MACOS_NATIVE_STATUS_ITEM, _MACOS_NATIVE_STATUS_TARGET
    if sys.platform != "darwin":
        return None
    appkit = _macos_appkit()
    if appkit is None:
        return None
    if _MacOSStatusItemTarget is None:
        print("[Mouser] Foundation.NSObject unavailable; using Qt tray icon")
        return None
    try:
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QPoint
    except Exception as exc:
        print(f"[Mouser] Native status-item bootstrap failed: {exc}")
        return None

    icon_svg = os.path.join(ROOT, "images", "icons", "mouse-simple.svg")
    if not os.path.isfile(icon_svg):
        print(f"[Mouser] mouse-simple.svg not found at {icon_svg}")
        return None

    # Render the SVG into a 22 px square NSImage. 22 is the macOS-
    # idiomatic menu-bar height (matches Apple's own SF Symbols).
    # Drawing at 2x and letting AppKit downsample preserves crisp
    # edges on both retina and non-retina displays.
    icon_png = _render_svg_pixmap(icon_svg, _qcolor_white(), 22)
    if icon_png.isNull():
        print("[Mouser] could not render mouse-simple.svg for status item")
        return None
    icon_bytes = _qpixmap_to_png_bytes(icon_png)
    ns_image = appkit.NSImage.alloc().initWithData_(icon_bytes)
    if ns_image is None or ns_image.isValid() is False:
        print("[Mouser] NSImage failed to decode status-item PNG")
        return None
    ns_image.setTemplate_(True)
    ns_image.setSize_(appkit.NSMakeSize(22, 22))

    status_bar = appkit.NSStatusBar.systemStatusBar()
    # NSVariableStatusItemLength == -1.0; lets AppKit auto-position
    # the item right-of-notch alongside every other modern status app.
    status_item = status_bar.statusItemWithLength_(-1.0)
    button = status_item.button()
    if button is None:
        print("[Mouser] NSStatusItem has no button; bailing")
        status_bar.removeStatusItem_(status_item)
        return None
    button.setImage_(ns_image)
    button.setToolTip_("Mouser")

    # Attach the existing QMenu as the right-click / control-click
    # menu via a tiny NSMenu shim that pops the Qt menu at the
    # status-item's screen position. Qt's QMenu carries all the
    # localised labels, action wiring, and live-update bindings the
    # rest of the app already depends on, so we don't duplicate it
    # into a parallel NSMenu.
    def _open_menu_at_cursor():
        try:
            cursor_pos = QCursor.pos()
        except Exception:  # noqa: BLE001
            cursor_pos = QPoint(0, 0)
        try:
            qmenu.popup(cursor_pos)
        except Exception as exc:  # noqa: BLE001
            print(f"[Mouser] failed to popup tray menu: {exc}")

    target = _MacOSStatusItemTarget.alloc().init()
    target.setPyHandlers_(
        {"primary": on_left_click, "menu": _open_menu_at_cursor, "appkit": appkit}
    )
    button.setTarget_(target)
    button.setAction_(b"statusItemClicked:")
    try:
        click_mask = (
            _int_const(appkit, "NSEventMaskLeftMouseDown")
            | _int_const(appkit, "NSEventMaskRightMouseDown")
            | _int_const(appkit, "NSEventMaskOtherMouseDown")
        )
        button.sendActionOn_(click_mask)
    except Exception as exc:
        print(f"[Mouser] Could not configure status-item click mask: {exc}")
        status_bar.removeStatusItem_(status_item)
        return None

    # Cache the item + target globally so PyObjC doesn't release them
    # while the app keeps running.
    _MACOS_NATIVE_STATUS_ITEM = status_item
    _MACOS_NATIVE_STATUS_TARGET = target
    return status_item


def _qcolor_white():
    """Cached white QColor used to fill the SVG silhouette for the
    template-image rendering path. Module-level cache because the
    cached colour is identity-equal across all callers."""
    from PySide6.QtGui import QColor
    return QColor("#FFFFFF")


def _qpixmap_to_png_bytes(pixmap):
    """Serialise a QPixmap to PNG bytes via an in-memory QBuffer so
    AppKit's ``NSImage.initWithData_`` can consume it without a
    round trip through the filesystem."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


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


def _check_accessibility(locale_mgr: "LocaleManager") -> bool:
    """Verify the macOS Accessibility grant. Returns True only when
    AXIsProcessTrustedWithOptions confirms the grant; any other path
    (no grant, exception during the check) returns False so callers
    fail closed.
    """
    if sys.platform != "darwin":
        return True
    try:
        trusted = is_process_trusted(prompt=True)
    except Exception as exc:
        print(f"[Mouser] Accessibility check failed: {exc}")
        return False
    if not trusted:
        print("[Mouser] Accessibility permission not granted")
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(locale_mgr.tr("accessibility.title"))
        msg.setText(locale_mgr.tr("accessibility.text"))
        msg.setInformativeText(locale_mgr.tr("accessibility.info"))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    return bool(trusted)


def _runtime_launch_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(__file__)


def _schedule_engine_start(engine, *, accessibility_granted: bool) -> bool:
    if not accessibility_granted:
        print("[Mouser] Engine not started -- Accessibility permission is required")
        return False
    QTimer.singleShot(0, lambda: (
        engine.start(),
        print("[Mouser] Engine started -- remapping is active"),
    ))
    return True


def _schedule_tray_minimized_notice(tray, locale_mgr) -> None:
    def _tray_minimized_notice():
        tray.showMessage(
            "Mouser",
            locale_mgr.tr("tray.tray_message"),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    QTimer.singleShot(400, _tray_minimized_notice)


def main():
    # Re-exec through a `Mouser`-named symlink BEFORE anything Qt or
    # AppKit related runs. Necessary because macOS reads the Dock label /
    # Cmd+Tab caption from the executable basename at process creation;
    # there is no in-process API to rename a Mach-O image after the fact.
    # No-op when already relaunched, on non-macOS platforms, or when the
    # symlink can't be created.
    _maybe_relaunch_with_mouser_process_name()

    _print_startup_times()
    _t5 = _time.perf_counter()
    if len(sys.argv) >= 3 and sys.argv[1] == "--mouser-apply-update":
        from core.update_installer import apply_windows_update_from_state

        raise SystemExit(apply_windows_update_from_state(sys.argv[2]))
    argv, hid_backend, start_hidden, force_show = _parse_cli_args(sys.argv)
    cfg = load_config()
    cfg_settings = cfg.get("settings", {})
    launch_hidden = (
        not force_show
        and (start_hidden or bool(cfg_settings.get("start_minimized", False)))
    )
    if hid_backend:
        try:
            set_hid_backend_preference(hid_backend)
        except ValueError as exc:
            raise SystemExit(f"Invalid --hid-backend setting: {exc}") from exc

    # Also: also mutate the bundle's display name keys so
    # surfaces that read from `[NSBundle mainBundle]` (application menu
    # first item, Force Quit, notification banners) say "Mouser" too.
    _rename_macos_bundle_for_dock()

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(argv)
    app.setApplicationName("Mouser")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Mouser")
    app.setWindowIcon(_app_icon())
    app.setQuitOnLastWindowClosed(False)
    _configure_macos_app_mode()
    _install_macos_dock_icon()
    ui_state = UiState(app)

    print(f"[Mouser] Version: {APP_VERSION} ({APP_BUILD_MODE})")
    print(f"[Mouser] Commit: {APP_COMMIT_DISPLAY}")
    print(f"[Mouser] Launch path: {_runtime_launch_path()}")

    # ── Locale Manager ─────────────────────────────────────────
    initial_lang = cfg_settings.get("language", "en")
    locale_mgr = LocaleManager(language=initial_lang)

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

    server_name = _single_instance_server_name()
    single_server, single_exit = _single_instance_acquire(app, server_name)
    if single_exit is not None:
        sys.exit(single_exit)

    _t6 = _time.perf_counter()
    # ── Engine (created but started AFTER UI is visible) ───────
    engine = Engine()

    _t7 = _time.perf_counter()
    # ── QML Backend ────────────────────────────────────────────
    backend = Backend(engine, root_dir=ROOT)
    ui_state.appearanceMode = backend.appearanceMode
    backend.settingsChanged.connect(
        lambda: setattr(ui_state, "appearanceMode", backend.appearanceMode)
    )
    if sys.platform == "win32":
        from core.key_simulator import set_screenshot_action_handler
        from ui.windows_screenshot import WindowsScreenshotController

        screenshot_controller = WindowsScreenshotController(
            status_callback=backend.statusMessage.emit,
            parent=app,
        )
        app._mouser_screenshot_controller = screenshot_controller
        set_screenshot_action_handler(screenshot_controller.request_action)
    elif sys.platform == "linux":
        from core.key_simulator import set_screenshot_action_handler
        from ui.linux_screenshot import LinuxScreenshotController

        screenshot_controller = LinuxScreenshotController(
            status_callback=backend.statusMessage.emit,
            parent=app,
        )
        app._mouser_screenshot_controller = screenshot_controller
        set_screenshot_action_handler(screenshot_controller.request_action)

    # ── QML Engine ─────────────────────────────────────────────
    qml_engine = QQmlApplicationEngine()
    qml_engine.addImageProvider("appicons", AppIconProvider(ROOT))
    qml_engine.addImageProvider("systemicons", SystemIconProvider())
    qml_engine.rootContext().setContextProperty("backend", backend)
    qml_engine.rootContext().setContextProperty("uiState", ui_state)
    qml_engine.rootContext().setContextProperty("lm", locale_mgr)
    qml_engine.rootContext().setContextProperty("launchHidden", launch_hidden)
    qml_engine.rootContext().setContextProperty("appVersion", APP_VERSION)
    qml_engine.rootContext().setContextProperty("appBuildMode", APP_BUILD_MODE)
    qml_engine.rootContext().setContextProperty("appCommit", APP_COMMIT_DISPLAY)
    qml_engine.rootContext().setContextProperty(
        "appLaunchPath", _runtime_launch_path().replace("\\", "/"))

    qml_path = os.path.join(ROOT, "ui", "qml", "Main.qml")
    qml_engine.load(QUrl.fromLocalFile(qml_path))
    _t8 = _time.perf_counter()

    if not qml_engine.rootObjects():
        print("[Mouser] FATAL: Failed to load QML")
        sys.exit(1)

    root_window = qml_engine.rootObjects()[0]

    def show_main_window():
        # Promote BEFORE show so the window registers with WindowServer's
        # foreground-app surfaces (Dock + Cmd+Tab + Mission Control) at
        # creation time on macOS. visibilityChanged below also catches the
        # transition (idempotent), so promotion is correct on the initial
        # launch path where this function is never called.
        _set_macos_activation_policy(regular=True)
        root_window.showNormal()
        root_window.raise_()
        root_window.requestActivate()
        _activate_macos_window()

    def _on_window_visibility_changed(visibility):
        # QWindow.Visibility: Hidden = 0; any other value (Windowed,
        # Maximized, FullScreen, Minimized) means there is an on-screen
        # window. macOS Cmd+Tab / Mission Control / Dock representation
        # depends on the activation policy, which we toggle to mirror
        # whether a window is currently shown:
        #   shown  → Regular   (real foreground app)
        #   hidden → Accessory (menu-bar only)
        # The QML `onClosing { close.accepted = false; root.hide() }`
        # handler in Main.qml turns Cmd+W and the red traffic light into
        # `hide()` calls so window state collapses cleanly to Hidden.
        # `_set_macos_activation_policy` is idempotent, so the storm of
        # visibilityChanged emits during a window state transition
        # collapses to at most one AppKit round-trip per direction.
        is_visible = visibility != QWindow.Visibility.Hidden
        _set_macos_activation_policy(regular=is_visible)
        if is_visible:
            # Window just became visible -- bring the app forward so the
            # user actually sees it (covers initial launch + tray clicks).
            _activate_macos_window()

    if sys.platform == "darwin":
        root_window.visibilityChanged.connect(_on_window_visibility_changed)
        # The window was created visible (QML `visible: !launchHidden`) before
        # this handler was connected, so its initial visibility transition has
        # already fired with no listener. Reconcile the activation policy now
        # so the Dock tile shows on a `--show-window` / non-hidden start.
        _on_window_visibility_changed(root_window.visibility())
        global _MACOS_QUIT_FILTER
        _MACOS_QUIT_FILTER = _MacOSQuitToTrayFilter(root_window, app)
        app.installEventFilter(_MACOS_QUIT_FILTER)
        app.commitDataRequest.connect(
            lambda *_: _allow_macos_session_quit_if_requested(_MACOS_QUIT_FILTER)
        )
        app.saveStateRequest.connect(
            lambda *_: _allow_macos_session_quit_if_requested(_MACOS_QUIT_FILTER)
        )

    def _on_second_instance_activate():
        _drain_local_activate_socket(single_server.nextPendingConnection())
        show_main_window()

    single_server.newConnection.connect(_on_second_instance_activate)

    print(f"[Startup] QApp create:      {(_t6-_t5)*1000:7.1f} ms")
    print(f"[Startup] Engine create:    {(_t7-_t6)*1000:7.1f} ms")
    print(f"[Startup] QML load:         {(_t8-_t7)*1000:7.1f} ms")
    print(f"[Startup] TOTAL to window:  {(_t8-_t0)*1000:7.1f} ms")

    # ── Accessibility check (macOS) ──────────────────────────────
    accessibility_granted = _check_accessibility(locale_mgr)

    # ── Start engine AFTER window is ready (deferred) ──────────
    _schedule_engine_start(engine, accessibility_granted=accessibility_granted)

    # ── System Tray ────────────────────────────────────────────
    tray = QSystemTrayIcon(_tray_icon(), app)
    tray.setToolTip("Mouser")

    tray_menu = QMenu()

    open_action = QAction(locale_mgr.tr("tray.open_settings"), tray_menu)
    open_action.triggered.connect(show_main_window)
    tray_menu.addAction(open_action)

    toggle_action = QAction(locale_mgr.tr("tray.disable_remapping"), tray_menu)

    def toggle_remapping():
        enabled = not engine.enabled
        engine.set_enabled(enabled)
        toggle_action.setText(
            locale_mgr.tr("tray.disable_remapping") if enabled
            else locale_mgr.tr("tray.enable_remapping"))

    toggle_action.triggered.connect(toggle_remapping)
    tray_menu.addAction(toggle_action)

    debug_action = QAction(locale_mgr.tr("tray.enable_debug"), tray_menu)

    def sync_debug_action():
        debug_enabled = bool(backend.debugMode)
        debug_action.setText(
            locale_mgr.tr("tray.disable_debug") if debug_enabled
            else locale_mgr.tr("tray.enable_debug")
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

    check_updates_action = QAction(locale_mgr.tr("tray.check_for_updates"), tray_menu)
    check_updates_action.triggered.connect(backend.manualCheckForUpdates)
    tray_menu.addAction(check_updates_action)

    open_release_action = QAction(locale_mgr.tr("tray.open_latest_release"), tray_menu)
    open_release_action.triggered.connect(backend.openLatestReleasePage)
    tray_menu.addAction(open_release_action)

    tray_menu.addSeparator()

    quit_action = QAction(locale_mgr.tr("tray.quit"), tray_menu)

    def quit_app():
        if _MACOS_QUIT_FILTER is not None:
            _MACOS_QUIT_FILTER.allow_quit()
        engine.stop()
        tray.hide()
        app.quit()

    quit_action.triggered.connect(quit_app)
    tray_menu.addAction(quit_action)

    def _update_tray_texts():
        """Refresh tray menu labels after a language change."""
        open_action.setText(locale_mgr.tr("tray.open_settings"))
        quit_action.setText(locale_mgr.tr("tray.quit"))
        check_updates_action.setText(locale_mgr.tr("tray.check_for_updates"))
        open_release_action.setText(locale_mgr.tr("tray.open_latest_release"))
        sync_debug_action()
        # Re-sync toggle text based on current engine state
        toggle_action.setText(
            locale_mgr.tr("tray.disable_remapping") if engine.enabled
            else locale_mgr.tr("tray.enable_remapping"))

    def _save_language():
        """Persist the selected language to config.json."""
        try:
            saved_cfg = load_config()
            saved_cfg.setdefault("settings", {})["language"] = locale_mgr.language
            save_config(saved_cfg)
        except Exception as exc:
            print(f"[Mouser] Failed to save language preference: {exc}")

    locale_mgr.languageChanged.connect(_update_tray_texts)
    locale_mgr.languageChanged.connect(_save_language)

    backend.updateAvailable.connect(lambda version, url: tray.showMessage(
        "Mouser",
        locale_mgr.tr("tray.update_available").format(version=version),
        QSystemTrayIcon.MessageIcon.Information,
        8000,
    ))

    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: (
        show_main_window()
    ) if reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
    ) else None)
    tray.show()

    # macOS only: install a native NSStatusItem so the menu-bar icon
    # can use AppKit's variable-length item path on notched MacBooks
    # where Qt's square status item can disappear under constrained
    # menu-bar space. We keep QSystemTrayIcon alive for notifications
    # and hide only its icon surface to avoid two menu-bar items.
    if sys.platform == "darwin":
        native_tray = _install_native_macos_status_item(
            tray_menu, show_main_window
        )
        if native_tray is not None:
            tray.setVisible(False)

    if launch_hidden and QSystemTrayIcon.isSystemTrayAvailable():
        _schedule_tray_minimized_notice(tray, locale_mgr)

    # ── Run ────────────────────────────────────────────────────
    try:
        sys.exit(app.exec())
    finally:
        engine.stop()
        print("[Mouser] Shut down cleanly")


if __name__ == "__main__":
    main()
