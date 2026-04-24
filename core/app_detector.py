"""
Foreground application detector — polls the active window and fires
a callback when the foreground app changes.
Windows: GetForegroundWindow + QueryFullProcessImageNameW (with UWP resolution).
macOS:   NSWorkspace.sharedWorkspace().frontmostApplication().
"""

import os
import sys
import threading
import time


# ==================================================================
# Platform-specific get_foreground_exe()
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

    # Window classes that belong to genuine explorer.exe usage
    _EXPLORER_CLASSES = frozenset({
        "CabinetWClass",           # File Explorer windows
        "Shell_TrayWnd",           # Taskbar
        "Shell_SecondaryTrayWnd",  # Taskbar on secondary monitors
        "Progman",                 # Desktop
        "WorkerW",                 # Desktop worker
    })

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

    def get_foreground_exe() -> str | None:
        """Return the foreground app path on Windows, or None."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None
        exe_path = _path_from_pid(pid.value)
        if not exe_path:
            return None
        exe_lower = os.path.basename(exe_path).lower()
        if exe_lower == "applicationframehost.exe":
            real = _resolve_uwp_child(hwnd)
            # If we can't resolve the real app (e.g. fullscreen UWP),
            # return None so the detector keeps the last known profile.
            return real
        if exe_lower == "explorer.exe":
            wc = _get_window_class(hwnd)
            if wc not in _EXPLORER_CLASSES:
                title = _get_window_title(hwnd)
                print(f"[AppDetect] FG: explorer.exe class={wc} title='{title}'")
                real = _resolve_uwp_child(hwnd)
                if real:
                    return real
                real = _find_uwp_app_global()
                return real  # None keeps last profile
        return exe_path

elif sys.platform == "darwin":
    import functools

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
    def get_foreground_exe() -> str | None:
        """Return a stable app identifier for the frontmost app on macOS."""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return None
            ident = app.bundleIdentifier()
            if ident:
                return ident
            url = app.executableURL()
            if url:
                return os.path.basename(url.path())
            return app.localizedName()
        except Exception:
            return None

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

    def get_foreground_exe() -> str | None:
        """Return the foreground app executable path on Linux."""
        if _WAYLAND:
            if _KDE:
                exe = _get_foreground_kdotool()
                if exe:
                    return exe
                # Fall back to xdotool so XWayland apps still work when
                # kdotool is unavailable or cannot resolve the active window.
                return _get_foreground_xdotool()
            # GNOME / other Wayland compositors: not yet supported
            return None
        return _get_foreground_xdotool()

else:
    def get_foreground_exe() -> str | None:
        return None


class AppDetector:
    """
    Polls the foreground window every *interval* seconds.
    Calls ``on_change(exe_name: str)`` when the foreground app changes.
    """

    def __init__(self, on_change, interval: float = 0.3):
        self._on_change = on_change
        self._interval = interval
        self._last_exe: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True, name="AppDetector")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------
    def _poll(self):
        while not self._stop.is_set():
            try:
                exe = get_foreground_exe()
                if exe and exe != self._last_exe:
                    self._last_exe = exe
                    self._on_change(exe)
            except Exception:
                pass
            self._stop.wait(self._interval)
