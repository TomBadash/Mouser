"""
Foreground application detector — fires a callback when the foreground app
changes.

Two modes:
* **Event-driven** (GNOME/Wayland with the bundled focus-watcher extension):
  a background asyncio thread subscribes to the extension's ``FocusChanged``
  D-Bus signal via dbus-fast, so no polling is needed. Reconnects with a
  backoff while the extension is unavailable (e.g. not yet enabled).
* **Polling** (every other platform): polls the active window every
  ``interval`` seconds.

Windows: GetForegroundWindow + QueryFullProcessImageNameW (with UWP resolution).
macOS:   NSWorkspace.sharedWorkspace().frontmostApplication().
"""

import asyncio
import functools
import json
import os
import plistlib
import sys
import threading
import time

import core.gnome_focus as _gnome_focus


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

elif sys.platform == "linux":
    import subprocess as _subprocess

    _WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    _KDE = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    _GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    def _pid_to_exe(pid: int) -> str | None:
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None

    def _get_foreground_gnome_watcher() -> str | None:
        """GNOME: use the Mouser focus-watcher extension via D-Bus.

        The extension (shipped in packaging/linux/gnome-focus-watcher/) is the
        only way to see the focused window on GNOME/Wayland. Only attempted when
        the desktop is GNOME and the shell version is supported, since the
        extension simply does not exist on other setups.
        """
        if not _GNOME or not _gnome_focus.gnome_focus_watcher_supported():
            return None
        return _gnome_focus.focus_app_executable()

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
            if _GNOME:
                # GNOME Wayland: use the Mouser focus-watcher extension.
                exe = _get_foreground_gnome_watcher()
                return _single_identity(exe)
            # Other Wayland compositors: not yet supported
            return ()
        exe = _get_foreground_xdotool()
        return _single_identity(exe)

else:
    def get_foreground_app_identity() -> tuple[str, ...]:
        return ()


def _use_gnome_event_mode() -> bool:
    """True when the event-driven GNOME focus-watcher path should be used.

    Requires GNOME/Wayland, a supported shell version, and dbus-fast being
    importable. On any other setup we keep the polling loop.
    """
    if sys.platform != "linux":
        return False
    if not _WAYLAND or not _GNOME:
        return False
    if not _gnome_focus.gnome_focus_watcher_supported():
        return False
    try:
        import dbus_fast  # noqa: F401
    except ImportError:
        return False
    return True


class AppDetector:
    """
    Detects foreground-app changes and fires ``on_change(app_identity)``.

    Two modes:

    * **Event-driven** (GNOME/Wayland with the bundled focus-watcher
      extension): a background asyncio thread subscribes to the extension's
      ``FocusChanged`` D-Bus signal through dbus-fast. There is no polling —
      the shell pushes each focus change to us. If the extension is not yet
      reachable (e.g. freshly installed, shell not restarted) the thread
      retries in the background, so enabling the extension later is picked up
      without restarting Mouser.
    * **Polling** (every other platform): polls the foreground window every
      *interval* seconds.
    """

    def __init__(self, on_change, interval: float = 0.3):
        self._on_change = on_change
        self._interval = interval
        self._last_app_identity: tuple[str, ...] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None        # polling thread
        self._event_thread: threading.Thread | None = None  # asyncio/DBus thread
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus = None                                   # live DBus connection

    def start(self):
        if self._running():
            return
        self._stop.clear()
        if _use_gnome_event_mode():
            # The loop is created here (not inside the thread) so that stop()
            # always has a handle to interrupt a blocking wait_for_disconnect.
            self._loop = asyncio.new_event_loop()
            self._event_thread = threading.Thread(
                target=self._event_loop_thread,
                daemon=True,
                name="AppDetectorEvent",
            )
            self._event_thread.start()
        else:
            self._start_poll_thread()

    def stop(self):
        self._stop.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._request_event_shutdown)
            except RuntimeError:
                pass
        if self._event_thread:
            self._event_thread.join(timeout=2)
        if self._thread:
            self._thread.join(timeout=2)

    def _running(self) -> bool:
        return bool(
            (self._event_thread and self._event_thread.is_alive())
            or (self._thread and self._thread.is_alive())
        )

    def _start_poll_thread(self):
        self._thread = threading.Thread(target=self._poll, daemon=True, name="AppDetector")
        self._thread.start()

    # ------------------------------------------------------------------
    # Event-driven mode (GNOME/Wayland, dbus-fast + FocusChanged signal)
    # ------------------------------------------------------------------
    def _event_loop_thread(self):
        """Run the asyncio event loop for the DBus watcher in this thread."""
        loop = self._loop
        if loop is None:
            # Defensive: start() always creates the loop, but never crash the
            # thread if stop() raced ahead of it.
            return
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._event_main())
        except Exception:
            # The loop thread must never die with an unhandled traceback;
            # _event_main already contains its own error handling.
            pass
        finally:
            try:
                loop.close()
            except Exception:
                # Best effort: loop teardown must not raise on shutdown.
                pass
            self._loop = None

    async def _event_main(self):
        """Keep a watcher connection alive until stopped, reconnecting on loss."""
        while not self._stop.is_set():
            try:
                bus = await asyncio.wait_for(
                    _gnome_focus._connect_watcher_bus(), timeout=5
                )
            except Exception:
                # Extension not reachable yet (not installed, or the shell has
                # not restarted since install): back off and retry rather than
                # falling back to polling, which yields nothing on Wayland
                # anyway. Enabling the extension later is picked up here.
                await self._sleep_until_stop(5.0)
                continue
            self._bus = bus
            try:
                await self._run_watcher_session(bus)
            except Exception:
                # Session errored (service vanished, introspection failed):
                # fall through to reconnect instead of killing the thread.
                pass
            finally:
                try:
                    bus.disconnect()
                except Exception:
                    # Best effort cleanup — closing is idempotent.
                    pass
                self._bus = None
            if self._stop.is_set():
                return
            # Connection dropped — pause briefly so the extension/shell has
            # time to come back before reconnecting.
            await self._sleep_until_stop(5.0)

    async def _run_watcher_session(self, bus):
        """Seed the current focus, then listen for ``FocusChanged`` signals."""
        try:
            payload = await asyncio.wait_for(
                _gnome_focus._get_focus_app_payload_from_bus(bus), timeout=5
            )
        except Exception:
            payload = None
        if payload is not None:
            self._notify_payload(payload)

        proxy = bus.get_proxy_object(
            _gnome_focus.DBUS_SERVICE,
            _gnome_focus.DBUS_PATH,
            _gnome_focus.WATCHER_INTROSPECTION,
        )
        interface = proxy.get_interface(_gnome_focus.DBUS_INTERFACE)

        def _on_focus_changed(window_payload):
            self._on_focus_changed_payload(window_payload)

        interface.on_focus_changed(_on_focus_changed)
        await bus.wait_for_disconnect()

    def _request_event_shutdown(self):
        """Runs on the event loop thread: close the bus so ``wait_for_disconnect``
        returns and the thread unwinds."""
        asyncio.ensure_future(self._shutdown_bus())

    async def _shutdown_bus(self):
        bus = self._bus
        self._bus = None
        if bus is not None:
            try:
                bus.disconnect()
            except Exception:
                # Best effort: the bus may already be closing.
                pass

    async def _sleep_until_stop(self, seconds: float):
        """Sleep in small steps so stop() is honored promptly."""
        remaining = seconds
        while remaining > 0 and not self._stop.is_set():
            step = min(0.25, remaining)
            await asyncio.sleep(step)
            remaining -= step

    def _on_focus_changed_payload(self, payload):
        parsed = payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except (ValueError, TypeError):
                parsed = None
        self._notify_payload(parsed)

    def _notify_payload(self, payload):
        if not isinstance(payload, dict):
            return
        exe = payload.get("executable") or ""
        identity = _single_identity(str(exe)) if exe else ()
        if identity and identity != self._last_app_identity:
            self._last_app_identity = identity
            try:
                self._on_change(identity)
            except Exception:
                # A consumer callback failure must not kill the detector.
                pass

    # ------------------------------------------------------------------
    # Polling mode (all other platforms)
    # ------------------------------------------------------------------
    def _poll(self):
        while not self._stop.is_set():
            try:
                app_identity = get_foreground_app_identity()
                if app_identity and app_identity != self._last_app_identity:
                    self._last_app_identity = app_identity
                    self._on_change(app_identity)
            except Exception:
                pass
            self._stop.wait(self._interval)
