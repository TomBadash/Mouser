"""
Foreground application detector — polls the active window and fires
a callback when the foreground app changes.

Windows: uses Win32 GetForegroundWindow + GetWindowThreadProcessId + OpenProcess.
         Resolves UWP apps hosted inside ApplicationFrameHost.exe by inspecting
         the CoreWindow child to find the real packaged process.

macOS:   uses AppKit.NSWorkspace.sharedWorkspace().frontmostApplication.
"""

import os
import sys
import threading
import time


# ══════════════════════════════════════════════════════════════════
# Windows implementation
# ══════════════════════════════════════════════════════════════════

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    MAX_PATH = 260
    GW_CHILD = 5

    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD

    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

    user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowExW.restype = wt.HWND

    user32.GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
    user32.EnumChildWindows.restype = wt.BOOL

    def _exe_from_pid(pid: int) -> str | None:
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hproc:
            return None
        try:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            size = wt.DWORD(MAX_PATH)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(hproc)
        return None

    def _resolve_uwp_child(hwnd) -> str | None:
        host_pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(host_pid))

        result = [None]

        def _enum_cb(child_hwnd, _lparam):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls, 256)
            if cls.value == "Windows.UI.Core.CoreWindow":
                child_pid = wt.DWORD()
                user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(child_pid))
                if child_pid.value != host_pid.value:
                    exe = _exe_from_pid(child_pid.value)
                    if exe:
                        result[0] = exe
                        return False
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum_cb), 0)
        return result[0]

    def get_foreground_exe() -> str | None:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None
        exe = _exe_from_pid(pid.value)
        if not exe:
            return None
        if exe.lower() == "applicationframehost.exe":
            real = _resolve_uwp_child(hwnd)
            if real:
                return real
        return exe


# ══════════════════════════════════════════════════════════════════
# macOS implementation
# ══════════════════════════════════════════════════════════════════

elif sys.platform == "darwin":
    try:
        import AppKit
        _APPKIT_OK = True
    except ImportError:
        _APPKIT_OK = False
        print("[AppDetector] pyobjc-framework-Cocoa not installed — "
              "pip install pyobjc-framework-Cocoa")

    def get_foreground_exe() -> str | None:
        """Return the bundle executable name of the frontmost application."""
        if not _APPKIT_OK:
            return None
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication()
            if app is None:
                return None
            # bundleIdentifier gives e.g. "com.apple.Safari"
            # executableURL gives the path to the actual binary
            url = app.executableURL()
            if url:
                return os.path.basename(str(url.path()))
            bundle_id = app.bundleIdentifier()
            if bundle_id:
                # Fall back to the last component of the bundle ID
                return bundle_id.split(".")[-1]
        except Exception as e:
            print(f"[AppDetector] get_foreground_exe error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# Unsupported platform stub
# ══════════════════════════════════════════════════════════════════

else:
    def get_foreground_exe() -> str | None:
        return None


# ══════════════════════════════════════════════════════════════════
# Shared: AppDetector (platform-neutral)
# ══════════════════════════════════════════════════════════════════

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
