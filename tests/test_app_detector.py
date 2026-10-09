from contextlib import nullcontext
import importlib
import os
import plistlib
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


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

        with patch.object(module, "_get_foreground_xdotool", return_value="/tmp/x11-app") as xdotool:
            self.assertEqual(module.get_foreground_app_identity(), ())
            xdotool.assert_not_called()

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


class AppDetectorMacOSObserverTests(unittest.TestCase):
    class FakeURL:
        def __init__(self, path):
            self._path = path

        def path(self):
            return self._path

    class FakeRunningApplication:
        def __init__(self, bundle_id, bundle_path, name):
            self._bundle_id = bundle_id
            self._bundle_path = bundle_path
            self._name = name

        def bundleURL(self):
            return AppDetectorMacOSObserverTests.FakeURL(self._bundle_path)

        def bundleIdentifier(self):
            return self._bundle_id

        def executableURL(self):
            return None

        def localizedName(self):
            return self._name

    class FakeUserInfo(dict):
        def objectForKey_(self, key):
            return self.get(key)

    class FakeNotification:
        def __init__(self, key, app):
            self._user_info = AppDetectorMacOSObserverTests.FakeUserInfo({key: app})

        def userInfo(self):
            return self._user_info

    class FakeNotificationCenter:
        def __init__(self):
            self.handler = None
            self.token = object()
            self.removed = []

        def addObserverForName_object_queue_usingBlock_(
            self, name, observed_object, queue, handler
        ):
            self.registration = (name, observed_object, queue)
            self.handler = handler
            return self.token

        def removeObserver_(self, token):
            self.removed.append(token)

    def setUp(self):
        self.addCleanup(_unload_app_detector)
        self.center = self.FakeNotificationCenter()
        self.initial_app = self.FakeRunningApplication(
            "com.example.Initial", "/Applications/Initial.app", "Initial"
        )
        center = self.center
        initial_app = self.initial_app

        class FakeWorkspace:
            @classmethod
            def sharedWorkspace(cls):
                return cls()

            def notificationCenter(self):
                return center

            def frontmostApplication(self):
                return initial_app

        appkit = types.ModuleType("AppKit")
        appkit.NSWorkspace = FakeWorkspace
        appkit.NSWorkspaceApplicationKey = "application"
        appkit.NSWorkspaceDidActivateApplicationNotification = "did-activate"
        objc = types.ModuleType("objc")
        objc.autorelease_pool = nullcontext

        module_patch = patch.dict(sys.modules, {"AppKit": appkit, "objc": objc})
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.module = _load_app_detector("darwin")

    def test_uses_workspace_notifications_and_deduplicates_app_changes(self):
        on_change = Mock()
        detector = self.module.AppDetector(on_change)

        detector.start()

        self.assertEqual(self.center.registration, ("did-activate", None, None))
        on_change.assert_called_once()
        self.assertEqual(on_change.call_args.args[0][0], "com.example.Initial")
        self.assertIsNone(detector._thread)

        same_app = self.FakeNotification("application", self.initial_app)
        self.center.handler(same_app)
        on_change.assert_called_once()

        next_app = self.FakeRunningApplication(
            "com.example.Next", "/Applications/Next.app", "Next"
        )
        self.center.handler(self.FakeNotification("application", next_app))
        self.assertEqual(on_change.call_count, 2)
        self.assertEqual(on_change.call_args.args[0][0], "com.example.Next")

    def test_stop_unregisters_workspace_observer(self):
        detector = self.module.AppDetector(Mock())
        detector.start()

        detector.stop()

        self.assertEqual(self.center.removed, [self.center.token])
        self.assertIsNone(detector._macos_observer)

    def test_initial_callback_failure_keeps_workspace_observer(self):
        on_change = Mock(side_effect=RuntimeError("profile switch failed"))
        detector = self.module.AppDetector(on_change)

        detector.start()

        self.assertIsNotNone(detector._macos_observer)
        self.assertIsNone(detector._thread)
        self.assertEqual(self.center.removed, [])

    def test_registration_failure_falls_back_to_polling(self):
        detector = self.module.AppDetector(Mock())
        observer = Mock()
        observer.start.side_effect = RuntimeError("registration failed")

        with (
            patch.object(self.module, "_MacOSWorkspaceObserver", return_value=observer),
            patch.object(self.module.threading, "Thread") as thread_type,
        ):
            thread = thread_type.return_value
            thread.is_alive.return_value = False
            detector.start()

        observer.stop.assert_called_once_with()
        thread_type.assert_called_once_with(
            target=detector._poll,
            daemon=True,
            name="AppDetector",
        )
        thread.start.assert_called_once_with()


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
