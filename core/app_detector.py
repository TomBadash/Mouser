"""
Foreground application detector — watches the active window and fires
a callback when the foreground app changes.
Windows: GetForegroundWindow + QueryFullProcessImageNameW (with UWP resolution).
macOS:   NSWorkspace activation notifications.
"""

import functools
import os
import plistlib
import sys
import threading
import time
import weakref


_IS_MACOS = sys.platform == "darwin"


# ── Windows explorer.exe window triage (platform-independent policy) ─────────
# explorer.exe owns both real applications' surfaces and a stream of transient
# shell windows. Telling them apart matters because the UWP resolution below is
# expensive: it enumerates every top-level window and opens each owning process.
# Running that several times a second -- which is what happened while a taskbar
# preview, Alt-Tab or a context menu held the foreground -- froze the app hard
# enough to take the mouse hook down with it (issue #252).

# Genuine Explorer usage: explorer.exe *is* the foreground app.
EXPLORER_SHELL_CLASSES = frozenset({
    "CabinetWClass",           # File Explorer windows
    "Shell_TrayWnd",           # Taskbar
    "Shell_SecondaryTrayWnd",  # Taskbar on secondary monitors
    "Progman",                 # Desktop
    "WorkerW",                 # Desktop worker
})

# Shell surfaces that appear and vanish constantly. They are never an app worth
# switching profiles for, so they are skipped before any resolution work.
TRANSIENT_EXPLORER_CLASSES = frozenset({
    "TaskListThumbnailWnd",          # taskbar thumbnail preview
    "ForegroundStaging",             # transient window during foreground swaps
    "XamlExplorerHostIslandWindow",  # Alt-Tab / Task View
    "Xaml_WindowedPopupClass",       # Windows 11 shell popups / context menus
    "#32768",                        # classic context menu
    "TaskSwitcherWnd",
    "TaskSwitcherOverlayWnd",
    "MultitaskingViewFrame",
    "Windows.UI.Core.CoreWindow",    # Start, Search and other shell surfaces
    "Shell_InputSwitchTopLevelWindow",
    "tooltips_class32",
})


def classify_explorer_window(window_class, window_key=None, last_unresolved_key=None):
    """Decide what to do with an explorer.exe foreground window.

    Returns one of:
      ``"explorer"`` -- genuine Explorer/desktop/taskbar; treat explorer.exe
        itself as the foreground app.
      ``"skip"`` -- a transient shell surface, or a window we already scanned
        without finding an app behind it; keep the current profile and do no
        work. Re-scanning the same window on every poll is what caused the
        freeze, so the caller memoises the last unresolved window key (handle
        plus class, since Windows recycles handles).
      ``"resolve"`` -- worth the expensive UWP lookup.
    """
    if window_class in EXPLORER_SHELL_CLASSES:
        return "explorer"
    if window_class in TRANSIENT_EXPLORER_CLASSES:
        return "skip"
    if window_key and last_unresolved_key and window_key == last_unresolved_key:
        return "skip"
    return "resolve"


def _path_from_nsurl(url) -> str | None:
    if url is None:
        return None
    try:
        path_attr = getattr(url, "path", None)
        path = path_attr() if callable(path_attr) else path_attr
        return str(path) if path else None
    except Exception:
        return None


def _call_ns_method(obj, name: str):
    try:
        attr = getattr(obj, name, None)
        return attr() if callable(attr) else attr
    except Exception:
        return None


def _dedupe_keep_order(values) -> tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def _single_identity(value: str | None) -> tuple[str, ...]:
    return (value,) if value else ()


def _macos_app_bundles_in_path(path: str | None) -> tuple[str, ...]:
    """Return containing .app bundles ordered inner-most to outer-most."""
    if not path:
        return ()

    normalized = os.path.abspath(path)
    parts = normalized.split(os.sep)
    bundles = []
    for idx, part in enumerate(parts):
        if part.endswith(".app"):
            if normalized.startswith(os.sep):
                bundles.append(os.path.join(os.sep, *parts[1:idx + 1]))
            else:
                bundles.append(os.path.join(*parts[:idx + 1]))
    return tuple(reversed(bundles))


@functools.lru_cache(maxsize=256)
def _read_macos_bundle_identifier(app_path: str | None) -> str | None:
    if not app_path:
        return None
    info_path = os.path.join(app_path, "Contents", "Info.plist")
    try:
        with open(info_path, "rb") as f:
            info = plistlib.load(f)
        ident = info.get("CFBundleIdentifier")
        return str(ident) if ident else None
    except (OSError, ValueError, TypeError):
        return None


def _macos_running_app_identities(app) -> tuple[str, ...]:
    """Return profile-matching identities, ordered most-specific first."""
    bundle_path = _path_from_nsurl(_call_ns_method(app, "bundleURL"))
    executable_path = _path_from_nsurl(_call_ns_method(app, "executableURL"))
    ident = _call_ns_method(app, "bundleIdentifier")
    localized_name = _call_ns_method(app, "localizedName")

    identities = []
    if ident:
        identities.append(str(ident))

    bundles = _dedupe_keep_order([
        *_macos_app_bundles_in_path(bundle_path),
        *_macos_app_bundles_in_path(executable_path),
    ])
    for app_path in bundles:
        bundle_ident = _read_macos_bundle_identifier(app_path)
        if bundle_ident:
            identities.append(bundle_ident)
        identities.append(app_path)
        identities.append(os.path.basename(app_path))
        identities.append(os.path.splitext(os.path.basename(app_path))[0])

    if executable_path:
        identities.append(executable_path)
        identities.append(os.path.basename(executable_path))
    if localized_name:
        identities.append(str(localized_name))

    return _dedupe_keep_order(identities)


# ==================================================================
# Platform-specific foreground app identity resolution
# ==================================================================

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    MAX_PATH = 260

    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD

    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD,
        ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

    user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowExW.restype = wt.HWND

    user32.GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
    user32.EnumChildWindows.restype = wt.BOOL
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int

    def _get_window_title(hwnd) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def _path_from_pid(pid: int) -> str | None:
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hproc:
            return None
        try:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            size = wt.DWORD(MAX_PATH)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(hproc)
        return None

    def _resolve_uwp_child(hwnd) -> str | None:
        host_pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(host_pid))
        result = [None]

        def _enum_cb(child_hwnd, _lparam):
            child_pid = wt.DWORD()
            user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(child_pid))
            if child_pid.value != host_pid.value:
                exe_path = _path_from_pid(child_pid.value)
                if exe_path and os.path.basename(exe_path).lower() != "applicationframehost.exe":
                    result[0] = exe_path
                    return False
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum_cb), 0)
        return result[0]

    # Last explorer.exe window that was scanned without a real app behind it,
    # keyed by (handle, class). Mutable single-slot cache: only the detector's
    # poll thread touches it.
    _unresolved_explorer_key = [None]

    def _get_window_class(hwnd) -> str:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        return cls.value

    def _find_uwp_app_global() -> str | None:
        """Enumerate all top-level windows to find a UWP app behind an overlay."""
        result = [None]

        def _enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            exe_path = _path_from_pid(pid.value)
            if exe_path and os.path.basename(exe_path).lower() == "applicationframehost.exe":
                real = _resolve_uwp_child(hwnd)
                if real:
                    result[0] = real
                    return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        return result[0]

    def get_foreground_app_identity() -> tuple[str, ...]:
        """Return the foreground app path on Windows, or an empty tuple."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ()
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return ()
        exe_path = _path_from_pid(pid.value)
        if not exe_path:
            return ()
        exe_lower = os.path.basename(exe_path).lower()
        if exe_lower == "applicationframehost.exe":
            real = _resolve_uwp_child(hwnd)
            # If we can't resolve the real app (e.g. fullscreen UWP), return
            # an empty tuple so the detector keeps the last known profile.
            return _single_identity(real)
        if exe_lower == "explorer.exe":
            wc = _get_window_class(hwnd)
            window_key = (hwnd, wc)
            verdict = classify_explorer_window(
                wc, window_key, _unresolved_explorer_key[0]
            )
            if verdict == "skip":
                # Keep the current profile; nothing here is an app.
                return ()
            if verdict == "resolve":
                title = _get_window_title(hwnd)
                print(f"[AppDetect] FG: explorer.exe class={wc} title='{title}'")
                real = _resolve_uwp_child(hwnd)
                if not real:
                    real = _find_uwp_app_global()
                if not real:
                    # Remember it so the next poll skips the scan entirely.
                    _unresolved_explorer_key[0] = window_key
                return _single_identity(real)
        return _single_identity(exe_path)

elif sys.platform == "darwin":
    try:
        import objc as _objc
    except ImportError as exc:
        raise ImportError(
            "PyObjC is required on macOS. Run "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    def _autoreleased(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _objc.autorelease_pool():
                return fn(*args, **kwargs)
        return wrapper

    @_autoreleased
    def get_foreground_app_identity() -> tuple[str, ...]:
        """Return stable frontmost app identities on macOS."""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return ()
            return _macos_running_app_identities(app)
        except Exception:
            return ()

    class _MacOSWorkspaceObserver:
        """Deliver foreground-app changes without repeatedly polling AppKit."""

        def __init__(self, on_change):
            self._on_change = on_change
            self._notification_center = None
            self._observer_token = None
            self._notification_handler = None

        def start(self):
            if self._observer_token is not None:
                return

            from AppKit import (
                NSWorkspace,
                NSWorkspaceApplicationKey,
                NSWorkspaceDidActivateApplicationNotification,
            )

            notification_center = NSWorkspace.sharedWorkspace().notificationCenter()
            observer_ref = weakref.ref(self)

            def _handle_activation(notification):
                observer = observer_ref()
                if observer is None:
                    return
                try:
                    with _objc.autorelease_pool():
                        user_info = notification.userInfo()
                        if hasattr(user_info, "objectForKey_"):
                            app = user_info.objectForKey_(NSWorkspaceApplicationKey)
                        else:
                            app = user_info.get(NSWorkspaceApplicationKey)
                        if app is not None:
                            observer._on_change(_macos_running_app_identities(app))
                except Exception:
                    # Do not let Python exceptions escape through an ObjC block.
                    pass

            token = notification_center.addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidActivateApplicationNotification,
                None,
                None,
                _handle_activation,
            )
            if token is None:
                raise RuntimeError("NSWorkspace activation observer returned no token")

            self._notification_center = notification_center
            self._observer_token = token
            # PyObjC blocks must remain strongly referenced for the observer lifetime.
            self._notification_handler = _handle_activation

        def stop(self):
            if self._observer_token is not None and self._notification_center is not None:
                self._notification_center.removeObserver_(self._observer_token)
            self._observer_token = None
            self._notification_center = None
            self._notification_handler = None

elif sys.platform == "linux":
    import subprocess as _subprocess

    _WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    _KDE = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    def _pid_to_exe(pid: int) -> str | None:
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None

    def _get_foreground_xdotool() -> str | None:
        """X11: use xdotool."""
        try:
            result = _subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=1,
            )
            if result.returncode == 0 and result.stdout.strip():
                return _pid_to_exe(int(result.stdout.strip()))
        except (FileNotFoundError, ValueError, OSError, _subprocess.TimeoutExpired):
            pass
        return None

    def _get_foreground_kdotool() -> str | None:
        """KDE Wayland: use kdotool."""
        try:
            result = _subprocess.run(
                ["kdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=1,
            )
            if result.returncode == 0 and result.stdout.strip():
                return _pid_to_exe(int(result.stdout.strip()))
        except (FileNotFoundError, ValueError, OSError, _subprocess.TimeoutExpired):
            pass
        return None

    def get_foreground_app_identity() -> tuple[str, ...]:
        """Return the foreground app executable path on Linux."""
        if _WAYLAND:
            if _KDE:
                exe = _get_foreground_kdotool()
                if exe:
                    return _single_identity(exe)
                # Fall back to xdotool so XWayland apps still work when
                # kdotool is unavailable or cannot resolve the active window.
                exe = _get_foreground_xdotool()
                return _single_identity(exe)
            # GNOME / other Wayland compositors: not yet supported
            return ()
        exe = _get_foreground_xdotool()
        return _single_identity(exe)

else:
    def get_foreground_app_identity() -> tuple[str, ...]:
        return ()


class AppDetector:
    """
    Watches the foreground application for changes.

    macOS uses NSWorkspace activation notifications to avoid native objects
    retained by repeated ``frontmostApplication()`` calls. Other platforms,
    and macOS when observer registration fails, poll every *interval* seconds.
    Calls ``on_change(app_identity)`` when the foreground app changes.
    """

    def __init__(self, on_change, interval: float = 0.3):
        self._on_change = on_change
        self._interval = interval
        self._last_app_identity: tuple[str, ...] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._macos_observer = None

    def start(self):
        if self._macos_observer is not None:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        if _IS_MACOS:
            observer = None
            try:
                observer = _MacOSWorkspaceObserver(self._handle_app_change)
                observer.start()
            except Exception as exc:
                if observer is not None:
                    observer.stop()
                print(
                    "[AppDetector] NSWorkspace observer unavailable; "
                    f"falling back to polling: {exc}"
                )
            else:
                self._macos_observer = observer
                try:
                    self._handle_app_change(get_foreground_app_identity())
                except Exception:
                    pass
                return

        self._thread = threading.Thread(target=self._poll, daemon=True, name="AppDetector")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._macos_observer is not None:
            self._macos_observer.stop()
            self._macos_observer = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _handle_app_change(self, app_identity):
        if app_identity and app_identity != self._last_app_identity:
            self._last_app_identity = app_identity
            self._on_change(app_identity)

    # ------------------------------------------------------------------
    def _poll(self):
        while not self._stop.is_set():
            try:
                self._handle_app_change(get_foreground_app_identity())
            except Exception:
                pass
            self._stop.wait(self._interval)
