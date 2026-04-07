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

    root.setLevel(logging.DEBUG)

    # Redirect stdout — must come AFTER StreamHandler setup above.
    # StreamHandler uses sys.__stdout__ (original), not sys.stdout, so
    # redirecting sys.stdout here does not create a circular loop.
    sys.stdout = _StreamToLogger(root, logging.INFO)

    return log_path
