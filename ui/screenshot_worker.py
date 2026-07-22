"""Short-lived Qt process for macOS screenshot actions."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config import load_config
from core.key_simulator import execute_screenshot_shortcut
from ui.macos_screenshot import MacScreenshotController
from ui.screenshot_common import (
    SCREENSHOT_CLIPBOARD_ACTIONS,
    screenshot_file_path,
)


def main() -> int:
    try:
        action_id = sys.argv[sys.argv.index("--screenshot-process") + 1]
    except (ValueError, IndexError):
        return 2

    config = load_config()
    custom_directory = config.get("settings", {}).get("screenshot_directory", "")
    if action_id in SCREENSHOT_CLIPBOARD_ACTIONS or not custom_directory:
        return 0 if execute_screenshot_shortcut(action_id) else 1

    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)

    def target_path() -> Path:
        return screenshot_file_path(directory=Path(os.path.expanduser(custom_directory)))

    def finished(message: str) -> None:
        print(f"[Screenshot] {message}")
        QTimer.singleShot(0, app.quit)

    controller = MacScreenshotController(
        status_callback=finished,
        path_factory=target_path,
        has_custom_directory=lambda: True,
        fallback_action=execute_screenshot_shortcut,
        parent=app,
    )
    app._mouser_screenshot_controller = controller
    QTimer.singleShot(0, lambda: controller.request_action(action_id))
    QTimer.singleShot(310000, app.quit)
    return app.exec()
