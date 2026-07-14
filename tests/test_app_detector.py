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


if __name__ == "__main__":
    unittest.main()
