"""Watch the app's own WTS session, with polling when notifications are missed."""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer


class WindowsSessionMonitor(QAbstractNativeEventFilter):
    def __init__(self, engine, window, app):
        super().__init__()
        self._engine = engine
        self._app = app
        self._hwnd = int(window.winId())
        self._registered = False
        try:
            self._wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
            self._wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            self._wts.WTSRegisterSessionNotification.restype = wintypes.BOOL
            self._wts.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
            self._wts.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
            self._registered = bool(self._wts.WTSRegisterSessionNotification(self._hwnd, 0))
        except (OSError, AttributeError):
            pass
        if not self._registered:
            print("[SessionMonitor] WTS notifications unavailable; using periodic checks")
        app.installNativeEventFilter(self)
        self._timer = QTimer(app)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(engine.refresh_remote_session)
        self._timer.start()
        app.aboutToQuit.connect(self.stop)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type).startswith(b"windows"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x02B1 and msg.hWnd == self._hwnd:  # WM_WTSSESSION_CHANGE
                self._engine.refresh_remote_session()
                # A connect notification can precede the updated WTS information.
                QTimer.singleShot(0, self._engine.refresh_remote_session)
        return False, 0

    def stop(self):
        self._timer.stop()
        self._app.removeNativeEventFilter(self)
        if self._registered:
            self._wts.WTSUnRegisterSessionNotification(self._hwnd)
            self._registered = False
