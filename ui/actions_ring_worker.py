"""Short-lived Qt process hosting the original Actions Ring overlay."""
from __future__ import annotations

import json
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from core.key_simulator import ACTIONS
from ui.actions_ring_overlay import ActionsRingOverlay, _resolve_ring_label


def _write_event(event: str, sector: int | None = None) -> None:
    payload = {"event": event}
    if sector is not None:
        payload["sector"] = int(sector)
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class CommandBus(QObject):
    received = Signal(object)


class RingWorker(QObject):
    def __init__(self, app):
        super().__init__()
        self._app = app
        self._overlay = ActionsRingOverlay()
        self._overlay.action_selected.connect(lambda sector: _write_event("select", sector))
        self._overlay.cancelled.connect(lambda: _write_event("cancel"))
        self._overlay.sector_changed.connect(self._sector_changed)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(5000)
        self._idle_timer.timeout.connect(app.quit)

    @Slot(object)
    def handle(self, message) -> None:
        command = message.get("command")
        if command == "show":
            slots = list(message.get("slots", []))
            labels = [
                _resolve_ring_label(slot, ACTIONS.get(slot, {}).get("label", slot))
                for slot in slots
            ]
            position = QCursor.pos()
            self._idle_timer.stop()
            self._overlay.show_ring(
                position.x(),
                position.y(),
                labels,
                interactive=bool(message.get("interactive", False)),
            )
        elif command == "move":
            self._overlay.accumulate_rawxy(
                int(message.get("dx", 0)),
                int(message.get("dy", 0)),
            )
        elif command == "hide":
            self._overlay.hide_ring()
            self._idle_timer.start()
        elif command == "quit":
            self._app.quit()

    def _sector_changed(self, sector: int) -> None:
        _write_event("sector", sector)
        _write_event("hover", sector)


def main() -> int:
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    bus = CommandBus()
    worker = RingWorker(app)
    bus.received.connect(worker.handle)

    def read_commands():
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except (TypeError, ValueError):
                continue
            bus.received.emit(message)
        bus.received.emit({"command": "quit"})

    threading.Thread(target=read_commands, daemon=True, name="MouserRingCommands").start()
    return app.exec()
