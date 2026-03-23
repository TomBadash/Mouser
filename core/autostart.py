"""
macOS login item helpers.

Uses a per-user LaunchAgent so Mouser can start automatically after login
without requiring the user to launch Python from Terminal.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

APP_NAME = "Mouser"
LAUNCH_AGENT_LABEL = "io.github.tombadash.mouser"


def is_supported() -> bool:
    return sys.platform == "darwin"


def launch_agent_dir(home: str | Path | None = None) -> Path:
    if home is None:
        return Path.home() / "Library" / "LaunchAgents"
    return Path(home) / "Library" / "LaunchAgents"


def launch_agent_path(home: str | Path | None = None) -> Path:
    return launch_agent_dir(home) / f"{LAUNCH_AGENT_LABEL}.plist"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _current_program_arguments(start_hidden: bool = False) -> list[str]:
    args: list[str]

    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        args = [
            sys.executable,
            str((_project_root() / "main_qml.py").resolve()),
        ]

    if start_hidden:
        args.append("--start-hidden")
    return args


def build_launch_agent_payload(start_hidden: bool = False) -> dict:
    program_arguments = _current_program_arguments(start_hidden=start_hidden)
    if getattr(sys, "frozen", False):
        working_dir = os.path.dirname(sys.executable)
    else:
        working_dir = str(_project_root())

    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program_arguments,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "WorkingDirectory": working_dir,
        "LimitLoadToSessionType": ["Aqua"],
    }


def is_launch_at_login_enabled(home: str | Path | None = None) -> bool:
    if not is_supported():
        return False
    return launch_agent_path(home).exists()


def enable_launch_at_login(start_hidden: bool = False, home: str | Path | None = None) -> Path:
    if not is_supported():
        raise NotImplementedError("Launch at login is only implemented for macOS")

    plist_path = launch_agent_path(home)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_launch_agent_payload(start_hidden=start_hidden)

    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)

    return plist_path


def disable_launch_at_login(home: str | Path | None = None) -> None:
    if not is_supported():
        raise NotImplementedError("Launch at login is only implemented for macOS")

    plist_path = launch_agent_path(home)
    if plist_path.exists():
        plist_path.unlink()
