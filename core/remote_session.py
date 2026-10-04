"""Identify the current Windows session without inspecting other users' sessions."""

import ctypes
import sys
from ctypes import wintypes


def is_remote_session():
    """Return True for RDP, False for console/non-Windows, or None if unknown.

    SM_REMOTESESSION alone can incorrectly report a RemoteFX session as local.
    Prefer the current session's WTS protocol and free its allocated buffer.
    """
    if sys.platform != "win32":
        return False
    buffer = ctypes.c_void_p()
    size = wintypes.DWORD()
    try:
        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        query = wts.WTSQuerySessionInformationW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        free = wts.WTSFreeMemory
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        try:
            # WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSClientProtocolType
            if query(None, 0xFFFFFFFF, 16, ctypes.byref(buffer), ctypes.byref(size)):
                if buffer.value and size.value >= ctypes.sizeof(ctypes.c_ushort):
                    protocol = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)).contents.value
                    if protocol in (0, 2):
                        return protocol == 2
        finally:
            if buffer.value:
                free(buffer)
    except (OSError, AttributeError):
        pass
    try:
        if ctypes.windll.user32.GetSystemMetrics(0x1000):
            return True
    except (OSError, AttributeError):
        pass
    return None
