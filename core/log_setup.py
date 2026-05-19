"""
log_setup.py — Redirect all print() output to a rotating log file.

Call setup_logging() once, early in main_qml.py, before Qt and core imports.
"""
import io
import logging
import logging.handlers
import os
import sys
import threading
from collections import deque


def _get_log_dir() -> str:
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Logs", "Mouser")
    elif sys.platform == "linux":
        xdg_state = os.environ.get(
            "XDG_STATE_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "state"),
        )
        return os.path.join(xdg_state, "Mouser", "logs")
    else:  # Windows
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "Mouser", "logs")


class _StreamToLogger:
    """Forward writes to a Logger. Thread-safe via threading.local buffer."""

    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self._logger = logger
        self._level = level
        self._local = threading.local()

    def write(self, msg: str) -> int:
        if not hasattr(self._local, "buf"):
            self._local.buf = ""
        self._local.buf += msg
        while "\n" in self._local.buf:
            line, self._local.buf = self._local.buf.split("\n", 1)
            if line:
                self._logger.log(self._level, line)
        return len(msg)

    def flush(self) -> None:
        if hasattr(self._local, "buf") and self._local.buf:
            self._logger.log(self._level, self._local.buf)
            self._local.buf = ""

    def fileno(self):
        raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"

    def isatty(self):
        return False


# ── In-memory log buffer ──────────────────────────────────────────────
# A bounded ring of recent formatted log lines, plus fan-out to live
# subscribers, so the UI can show the same console output that goes to
# mouser.log. Capture is always on (it is cheap); the UI only displays it
# while debug mode is enabled.
_LOG_BUFFER_CAPACITY = 1000
_log_buffer = deque(maxlen=_LOG_BUFFER_CAPACITY)
_log_listeners = []
_log_lock = threading.Lock()
_log_reentry = threading.local()


class _BufferLogHandler(logging.Handler):
    """Keep the most recent formatted log lines in memory and notify
    subscribers as each new line arrives.

    Subscriber callbacks run on whichever thread emitted the log record, so
    they must be fast, non-blocking, and must not log or print themselves —
    a re-entrancy guard drops nested notifications if one does anyway.
    """

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:  # pragma: no cover - logging must never crash
            return
        with _log_lock:
            _log_buffer.append(line)
            listeners = list(_log_listeners)
        if getattr(_log_reentry, "active", False):
            return
        _log_reentry.active = True
        try:
            for listener in listeners:
                try:
                    listener(line)
                except Exception:
                    pass
        finally:
            _log_reentry.active = False


def get_recent_logs() -> list:
    """Return a snapshot of the most recent captured log lines."""
    with _log_lock:
        return list(_log_buffer)


def add_log_listener(callback) -> list:
    """Register a callback to be invoked with each new formatted log line.

    Returns a snapshot of the lines already buffered, taken atomically with
    the subscription so the caller sees every line exactly once — none
    missed between the snapshot and the subscription, none delivered twice.
    """
    with _log_lock:
        _log_listeners.append(callback)
        return list(_log_buffer)


def remove_log_listener(callback) -> None:
    """Unregister a log listener added via add_log_listener (no-op if absent)."""
    with _log_lock:
        try:
            _log_listeners.remove(callback)
        except ValueError:
            pass


def setup_logging() -> str:
    """
    Configure rotating file log and redirect stdout to it.
    Returns the log file path. Idempotent (safe to call multiple times).

    Only sys.stdout is redirected (all app output uses print()). sys.stderr
    is left untouched to avoid a recursion: logging handler errors call
    handleError() which writes to sys.stderr — redirecting it through the
    logger would create an infinite loop.
    """
    root = logging.getLogger()
    if root.handlers:
        return ""  # already configured

    log_dir = _get_log_dir()
    fmt = logging.Formatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    log_path = ""
    try:
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        log_path = os.path.join(log_dir, "mouser.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=5,              # 25 MB total ceiling
            encoding="utf-8",
            delay=False,                # create file immediately on startup
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:
        log_path = ""
        # Fall back to console-only — app must not crash due to logging failure
        print(f"[Logging] Cannot create log dir {log_dir}: {exc}", file=sys.__stderr__)

    # Terminal output: only when NOT running as a frozen bundle.
    # getattr(sys, "frozen", False) is set by PyInstaller (same pattern used
    # in main_qml.py for ROOT path resolution). When frozen with console=False,
    # sys.stdout is /dev/null, so we skip the StreamHandler.
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    # In-memory ring buffer feeding the UI's "Application Log" view. Added
    # unconditionally — it needs no file and works even if the log dir failed.
    buffer_handler = _BufferLogHandler()
    buffer_handler.setFormatter(fmt)
    root.addHandler(buffer_handler)

    root.setLevel(logging.DEBUG)

    # Redirect stdout — must come AFTER StreamHandler setup above.
    # StreamHandler uses sys.__stdout__ (original), not sys.stdout, so
    # redirecting sys.stdout here does not create a circular loop.
    sys.stdout = _StreamToLogger(root, logging.INFO)

    return log_path
