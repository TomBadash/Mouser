"""Launch Qt-dependent tools only while they are being used."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading


def process_command(flag: str, *arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        helper = os.path.abspath(
            os.path.join(
                os.path.dirname(sys.executable),
                "..",
                "Helpers",
                "MouserUI.app",
                "Contents",
                "MacOS",
                "MouserUI",
            )
        )
        return [helper, flag, *arguments]
    launcher = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mouser_launcher.py")
    return [sys.executable, launcher, flag, *arguments]


def launch_screenshot_worker(action_id: str, environment=None) -> None:
    subprocess.Popen(
        process_command("--screenshot-process", action_id),
        env=dict(os.environ if environment is None else environment),
        close_fds=True,
    )


class RingWorkerClient:
    def __init__(self, *, on_select, on_cancel, on_hover):
        self._on_select = on_select
        self._on_cancel = on_cancel
        self._on_hover = on_hover
        self._process = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._current_sector = -1

    @property
    def current_sector(self) -> int:
        with self._state_lock:
            return self._current_sector

    def show(self, slots, interactive=False) -> None:
        with self._state_lock:
            self._current_sector = -1
        self._send({"command": "show", "slots": list(slots), "interactive": bool(interactive)})

    def hide(self) -> None:
        self._send({"command": "hide"}, start=False)

    def move(self, dx: int, dy: int) -> None:
        self._send({"command": "move", "dx": int(dx), "dy": int(dy)}, start=False)

    def close(self) -> None:
        self._send({"command": "quit"}, start=False)
        process = self._process
        if process is not None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.terminate()
        self._process = None

    def _ensure_process(self):
        process = self._process
        if process is not None and process.poll() is None:
            return process
        process = subprocess.Popen(
            process_command("--ring-process"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            close_fds=True,
        )
        self._process = process
        threading.Thread(
            target=self._read_events,
            args=(process,),
            daemon=True,
            name="MouserRingEvents",
        ).start()
        return process

    def _send(self, payload, *, start=True) -> None:
        with self._write_lock:
            process = self._ensure_process() if start else self._process
            if process is None or process.poll() is not None or process.stdin is None:
                return
            try:
                process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                self._process = None

    def _read_events(self, process) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            event_name = event.get("event")
            sector = int(event.get("sector", -1))
            if event_name == "sector":
                with self._state_lock:
                    self._current_sector = sector
            elif event_name == "hover":
                self._on_hover(sector)
            elif event_name == "select":
                self._on_select(sector)
            elif event_name == "cancel":
                self._on_cancel()
        if self._process is process:
            self._process = None
