import importlib
import os
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch


def _unload_app_detector():
    sys.modules.pop("core.app_detector", None)
    core_module = sys.modules.get("core")
    if core_module is not None and hasattr(core_module, "app_detector"):
        delattr(core_module, "app_detector")


def _load_app_detector(platform: str, env: dict[str, str] | None = None):
    _unload_app_detector()
    with (
        patch.object(sys, "platform", platform),
        patch.dict(os.environ, env or {}, clear=False),
    ):
        return importlib.import_module("core.app_detector")


class AppDetectorLinuxTests(unittest.TestCase):
    def _reload_for_linux(self, session_type: str, desktop: str):
        self.addCleanup(_unload_app_detector)
        return _load_app_detector(
            "linux",
            {
                "XDG_SESSION_TYPE": session_type,
                "XDG_CURRENT_DESKTOP": desktop,
            },
        )

    def test_kde_wayland_prefers_kdotool(self):
        module = self._reload_for_linux("wayland", "KDE")

        with (
            patch.object(module, "_get_foreground_kdotool", return_value="/tmp/kde-app"),
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11-app") as xdotool,
        ):
            self.assertEqual(module.get_foreground_app_identity(), ("/tmp/kde-app",))
            xdotool.assert_not_called()

    def test_kde_wayland_falls_back_to_xdotool(self):
        module = self._reload_for_linux("wayland", "KDE")

        with (
            patch.object(module, "_get_foreground_kdotool", return_value=None),
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/xwayland-app") as xdotool,
        ):
            self.assertEqual(module.get_foreground_app_identity(), ("/tmp/xwayland-app",))
            xdotool.assert_called_once_with()

    def test_non_kde_wayland_returns_none(self):
        module = self._reload_for_linux("wayland", "GNOME")

        with (
            patch.object(module, "_get_foreground_gnome_watcher", return_value=None),
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11-app") as xdotool,
        ):
            self.assertEqual(module.get_foreground_app_identity(), ())
            xdotool.assert_not_called()

    def test_gnome_wayland_uses_focus_watcher_extension(self):
        module = self._reload_for_linux("wayland", "GNOME")

        with (
            patch.object(
                module, "_get_foreground_gnome_watcher", return_value="/usr/bin/firefox"
            ),
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11") as xdotool,
        ):
            self.assertEqual(
                module.get_foreground_app_identity(), ("/usr/bin/firefox",)
            )
            xdotool.assert_not_called()

    def test_gnome_wayland_falls_back_when_extension_unavailable(self):
        module = self._reload_for_linux("wayland", "GNOME")

        with (
            patch.object(module, "_get_foreground_gnome_watcher", return_value=None),
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11") as xdotool,
        ):
            self.assertEqual(module.get_foreground_app_identity(), ())
            xdotool.assert_not_called()

    def test_gnome_x11_keeps_using_xdotool(self):
        module = self._reload_for_linux("x11", "GNOME")

        with (
            patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11-app") as xdotool,
            patch.object(module, "_get_foreground_gnome_watcher") as gnome_watcher,
        ):
            self.assertEqual(module.get_foreground_app_identity(), ("/tmp/x11-app",))
            gnome_watcher.assert_not_called()

    def test_x11_uses_xdotool(self):
        module = self._reload_for_linux("x11", "KDE")

        with patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11-app") as xdotool:
            self.assertEqual(module.get_foreground_app_identity(), ("/tmp/x11-app",))
            xdotool.assert_called_once_with()


class AppDetectorMacOSTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload_app_detector)
        self.module = _load_app_detector(
            "linux",
            {
                "XDG_SESSION_TYPE": "x11",
                "XDG_CURRENT_DESKTOP": "KDE",
            },
        )

    def _write_bundle_info(self, app_path: str, bundle_id: str):
        info_dir = os.path.join(app_path, "Contents")
        os.makedirs(info_dir, exist_ok=True)
        with open(os.path.join(info_dir, "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleIdentifier": bundle_id}, f)

    def test_nested_app_identities_include_inner_then_outer_app(self):
        class FakeURL:
            def __init__(self, path):
                self._path = path

            def path(self):
                return self._path

        class FakeRunningApplication:
            def __init__(self, bundle_path):
                self._bundle_path = bundle_path

            def bundleURL(self):
                return FakeURL(self._bundle_path)

            def bundleIdentifier(self):
                return "com.example.Editor.helper"

            def executableURL(self):
                return None

            def localizedName(self):
                return "Editor Helper"

        with tempfile.TemporaryDirectory() as tmp:
            outer_app = os.path.join(tmp, "Editor.app")
            helper_app = os.path.join(
                outer_app,
                "Contents",
                "Frameworks",
                "Editor Helper.app",
            )
            self._write_bundle_info(outer_app, "com.example.Editor")
            self._write_bundle_info(helper_app, "com.example.Editor.helper")

            self.assertEqual(
                self.module._macos_running_app_identities(
                    FakeRunningApplication(helper_app)
                ),
                (
                    "com.example.Editor.helper",
                    helper_app,
                    "Editor Helper.app",
                    "Editor Helper",
                    "com.example.Editor",
                    outer_app,
                    "Editor.app",
                    "Editor",
                ),
            )


class ExplorerWindowTriageTests(unittest.TestCase):
    """Issue #252: resolving every explorer.exe popup froze the app.

    A taskbar preview or context menu holding the foreground made the detector
    enumerate every top-level window and open each owning process, three times
    a second, until the mouse hook starved.
    """

    def setUp(self):
        from core import app_detector

        self.classify = app_detector.classify_explorer_window

    def test_real_explorer_surfaces_are_the_foreground_app(self):
        for window_class in (
            "CabinetWClass", "Shell_TrayWnd", "Progman", "WorkerW",
        ):
            with self.subTest(window_class=window_class):
                self.assertEqual(self.classify(window_class), "explorer")

    def test_transient_shell_surfaces_are_skipped_without_any_work(self):
        for window_class in (
            "TaskListThumbnailWnd",          # from the issue #252 log
            "ForegroundStaging",             # from the issue #252 log
            "XamlExplorerHostIslandWindow",  # from the issue #252 log
            "Xaml_WindowedPopupClass",
            "#32768",
        ):
            with self.subTest(window_class=window_class):
                self.assertEqual(self.classify(window_class), "skip")

    def test_unknown_window_is_resolved_once(self):
        key = (0x1234, "SomeNewShellClass")

        self.assertEqual(self.classify("SomeNewShellClass", key, None), "resolve")

    def test_window_that_resolved_to_nothing_is_not_rescanned(self):
        key = (0x1234, "SomeNewShellClass")

        self.assertEqual(self.classify("SomeNewShellClass", key, key), "skip")

    def test_memo_is_keyed_by_class_too_so_recycled_handles_still_resolve(self):
        stale = (0x1234, "SomeNewShellClass")
        recycled = (0x1234, "ADifferentClass")

        self.assertEqual(self.classify("ADifferentClass", recycled, stale), "resolve")


if __name__ == "__main__":
    unittest.main()


class AppDetectorEventModeTests(unittest.TestCase):
    """Tests for the event-driven (dbus-fast) mode of AppDetector."""

    def _reload_for_linux(self, session_type: str, desktop: str):
        self.addCleanup(_unload_app_detector)
        return _load_app_detector(
            "linux",
            {
                "XDG_SESSION_TYPE": session_type,
                "XDG_CURRENT_DESKTOP": desktop,
            },
        )

    def test_event_mode_eligible_on_gnome_wayland(self):
        module = self._reload_for_linux("wayland", "GNOME")
        with patch.object(
            module._gnome_focus, "gnome_focus_watcher_supported", return_value=True
        ):
            self.assertTrue(module._use_gnome_event_mode())

    def test_event_mode_not_eligible_on_gnome_x11(self):
        module = self._reload_for_linux("x11", "GNOME")
        self.assertFalse(module._use_gnome_event_mode())

    def test_event_mode_not_eligible_when_shell_unsupported(self):
        module = self._reload_for_linux("wayland", "GNOME")
        with patch.object(
            module._gnome_focus, "gnome_focus_watcher_supported", return_value=False
        ):
            self.assertFalse(module._use_gnome_event_mode())

    def test_event_mode_not_eligible_on_kde_wayland(self):
        module = self._reload_for_linux("wayland", "KDE")
        self.assertFalse(module._use_gnome_event_mode())

    def test_start_uses_event_thread_on_gnome_wayland(self):
        module = self._reload_for_linux("wayland", "GNOME")
        with patch.object(module, "_use_gnome_event_mode", return_value=True):
            detector = module.AppDetector(on_change=lambda _id: None)
            detector.start()
            try:
                self.assertIsNotNone(detector._event_thread)
                self.assertIsNone(detector._thread)
            finally:
                detector.stop()

    def test_start_uses_poll_thread_when_event_mode_off(self):
        module = self._reload_for_linux("x11", "GNOME")
        detector = module.AppDetector(on_change=lambda _id: None)
        detector.start()
        try:
            self.assertIsNotNone(detector._thread)
            self.assertIsNone(detector._event_thread)
        finally:
            detector.stop()

    def test_notify_payload_fires_on_change_and_dedups(self):
        module = self._reload_for_linux("x11", "KDE")
        changes = []
        detector = module.AppDetector(on_change=changes.append)

        detector._notify_payload({"executable": "/usr/bin/firefox", "wm_class": "Firefox"})
        detector._notify_payload({"executable": "/usr/bin/firefox", "wm_class": "Firefox"})
        detector._notify_payload({"executable": "/usr/bin/kitty", "wm_class": "kitty"})

        self.assertEqual(changes, [("/usr/bin/firefox",), ("/usr/bin/kitty",)])

    def test_focus_changed_payload_parses_json_string(self):
        module = self._reload_for_linux("x11", "KDE")
        changes = []
        detector = module.AppDetector(on_change=changes.append)

        detector._on_focus_changed_payload('{"executable": "/usr/bin/foo"}')
        self.assertEqual(changes, [("/usr/bin/foo",)])

        # Bad JSON should be ignored (no new change fired).
        detector._on_focus_changed_payload("not-json")
        self.assertEqual(changes, [("/usr/bin/foo",)])

    def test_notify_payload_ignores_empty_executable(self):
        module = self._reload_for_linux("x11", "KDE")
        changes = []
        detector = module.AppDetector(on_change=changes.append)

        detector._notify_payload({"executable": "", "wm_class": "X"})
        self.assertEqual(changes, [])

    def test_run_mode_also_detected(self):
        """Verify that start() also works on platforms where gnome_event_mode is False."""
        module = _load_app_detector(
            "linux",
            {
                "XDG_SESSION_TYPE": "x11",
                "XDG_CURRENT_DESKTOP": "KDE",
            },
        )
        detector = module.AppDetector(on_change=lambda _id: None)
        detector.start()
        try:
            self.assertTrue(detector._running())
        finally:
            detector.stop()
        self.assertFalse(detector._running())


if __name__ == "__main__":
    unittest.main()
