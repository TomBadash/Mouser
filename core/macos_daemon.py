"""Lightweight macOS daemon using AppKit without importing Qt."""
from __future__ import annotations

from collections import deque
import os
import signal
import subprocess
import sys
import threading
import webbrowser

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

from core.accessibility import is_process_trusted
from core.config import load_config, save_config
from core.engine import Engine
from core.local_control import LocalControlServer, send_control_message
from core.on_demand_ui import RingWorkerClient, launch_screenshot_worker, process_command
from core.process_bridge import DaemonBridgeServer


def _root_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(
            sys,
            "_MEIPASS",
            os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", "Resources")),
        )
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _root_dir()


def _settings_command() -> list[str]:
    return process_command("--settings-process")


class DaemonRuntime:
    def __init__(self):
        self.config = load_config()
        self.engine = Engine()
        self.battery_level = -1
        self.debug_lines = deque(maxlen=500)
        self.settings_process = None
        self.control_server = LocalControlServer("daemon", self._control_message)
        self.ring = RingWorkerClient(
            on_select=self.engine.ring_toggle_select,
            on_cancel=self.engine.ring_toggle_dismiss,
            on_hover=self.engine.ring_hover,
        )
        self.engine.set_battery_callback(self._battery_changed)
        self.engine.set_debug_callback(self._debug_message)
        self.engine.set_status_callback(self._status_message)
        self.engine.set_ring_show_callback(self.ring.show)
        self.engine.set_ring_hide_callback(self.ring.hide)
        self.engine.set_ring_sector_callback(lambda: self.ring.current_sector)
        self.engine.set_ring_move_callback(self.ring.move)
        self.engine.set_debug_enabled(
            bool(self.config.get("settings", {}).get("debug_mode", False))
        )

        from core.key_simulator import set_screenshot_action_handler

        set_screenshot_action_handler(self._screenshot)
        self.bridge = DaemonBridgeServer(
            self.engine,
            on_shutdown=self.request_quit,
            on_config_sync=self._sync_config,
            state_provider=self._state,
        )
        self.delegate = None
        self._engine_started = False
        self._stopped = False
        self._stop_lock = threading.Lock()

    def start(self) -> None:
        self.control_server.start()
        self.bridge.start()

    def start_engine(self) -> None:
        if self._engine_started:
            return
        self._engine_started = True
        self.engine.start()
        print("[Mouser] Accessibility granted -- lightweight engine started")

    def show_settings(self) -> None:
        if send_control_message("settings", "show", timeout=0.2):
            return
        process = self.settings_process
        if process is not None and process.poll() is None:
            return
        self.settings_process = subprocess.Popen(
            _settings_command(),
            cwd=ROOT,
            env=self.bridge.child_environment(),
            close_fds=True,
        )

    def close_settings(self) -> None:
        send_control_message("settings", "quit", timeout=0.2)

    def request_quit(self) -> None:
        delegate = self.delegate
        if delegate is not None:
            AppHelper.callAfter(delegate.terminate)

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        self.close_settings()
        self.ring.close()
        self.bridge.close()
        if self._engine_started:
            self.engine.stop()
        self.control_server.close()
        print("[Mouser] lightweight daemon shut down cleanly")

    def set_enabled(self, enabled: bool) -> None:
        self.engine.set_enabled(enabled)

    def set_debug(self, enabled: bool) -> None:
        self.engine.set_debug_enabled(enabled)
        self.config.setdefault("settings", {})["debug_mode"] = bool(enabled)
        save_config(self.config)

    def _control_message(self, message: str) -> None:
        if message == "quit":
            self.request_quit()
        else:
            AppHelper.callAfter(self.show_settings)

    def _sync_config(self, config) -> None:
        self.config = config
        self.engine.cfg = config

    def _battery_changed(self, level) -> None:
        self.battery_level = int(level)

    def _debug_message(self, message) -> None:
        self.debug_lines.append(str(message))

    @staticmethod
    def _status_message(message) -> None:
        if message:
            print(f"[Mouser] {message}")

    def _state(self) -> dict:
        return {
            "battery_level": self.battery_level,
            "debug_lines": list(self.debug_lines),
        }

    def _screenshot(self, action_id: str) -> None:
        launch_screenshot_worker(action_id, self.bridge.child_environment())


class MouserAppDelegate(NSObject):
    def initWithRuntime_(self, runtime):
        self = objc.super(MouserAppDelegate, self).init()
        if self is None:
            return None
        self.runtime = runtime
        self.status_item = None
        self.menu = None
        self.toggle_item = None
        self.debug_item = None
        self.accessibility_timer = None
        return self

    def applicationDidFinishLaunching_(self, _notification):
        self._install_status_item()
        self.runtime.start()
        if is_process_trusted(prompt=True):
            self.runtime.start_engine()
        else:
            print("[Mouser] Waiting for Accessibility permission")
            self.accessibility_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                2.0,
                self,
                "pollAccessibility:",
                None,
                True,
            )

    def applicationWillTerminate_(self, _notification):
        self.runtime.stop()

    def pollAccessibility_(self, _timer):
        if not is_process_trusted():
            return
        self.accessibility_timer.invalidate()
        self.accessibility_timer = None
        self.runtime.start_engine()

    def openSettings_(self, _sender):
        self.runtime.show_settings()

    def toggleEnabled_(self, _sender):
        self.runtime.set_enabled(not self.runtime.engine.enabled)
        self._refresh_menu()

    def toggleDebug_(self, _sender):
        enabled = not bool(self.runtime.config.get("settings", {}).get("debug_mode", False))
        self.runtime.set_debug(enabled)
        self._refresh_menu()
        if enabled:
            self.runtime.show_settings()

    def openReleases_(self, _sender):
        webbrowser.open("https://github.com/TomBadash/Mouser/releases")

    def quitMouser_(self, _sender):
        self.terminate()

    def menuWillOpen_(self, _menu):
        self._refresh_menu()

    def terminate(self):
        NSApplication.sharedApplication().terminate_(None)

    def _install_status_item(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = self.status_item.button()
        icon_path = os.path.join(ROOT, "images", "logo_icon.png")
        image = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if image is not None:
            image.setSize_((18.0, 18.0))
            image.setTemplate_(True)
            button.setImage_(image)
        else:
            button.setTitle_("M")
        button.setToolTip_("Mouser")

        self.menu = NSMenu.alloc().initWithTitle_("Mouser")
        self.menu.setDelegate_(self)
        self._add_item("Open Settings", "openSettings:")
        self.toggle_item = self._add_item("", "toggleEnabled:")
        self.debug_item = self._add_item("Debug Mode", "toggleDebug:")
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add_item("Latest Release", "openReleases:")
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add_item("Quit Mouser", "quitMouser:")
        self.status_item.setMenu_(self.menu)
        self._refresh_menu()

    def _add_item(self, title: str, selector: str):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title,
            selector,
            "",
        )
        item.setTarget_(self)
        self.menu.addItem_(item)
        return item

    def _refresh_menu(self):
        enabled = self.runtime.engine.enabled
        self.toggle_item.setTitle_("Disable Remapping" if enabled else "Enable Remapping")
        debug_enabled = bool(
            self.runtime.config.get("settings", {}).get("debug_mode", False)
        )
        self.debug_item.setState_(
            NSControlStateValueOn if debug_enabled else NSControlStateValueOff
        )


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if send_control_message("daemon", "show", timeout=0.2):
        return 0

    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    runtime = DaemonRuntime()
    delegate = MouserAppDelegate.alloc().initWithRuntime_(runtime)
    runtime.delegate = delegate
    application.setDelegate_(delegate)
    application.run()
    return 0
