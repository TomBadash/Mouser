"""Tests for the GNOME Shell focus-watcher extension helpers."""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import gnome_focus


def _gnome_env():
    return {"XDG_CURRENT_DESKTOP": "GNOME"}


class DesktopDetectionTests(unittest.TestCase):
    def test_gnome_desktop_detected(self):
        for desktop in ("GNOME", "ubuntu:GNOME", "GNOME-Flashback", "gnome"):
            with self.subTest(desktop=desktop):
                self.assertTrue(
                    gnome_focus.is_gnome_desktop({"XDG_CURRENT_DESKTOP": desktop})
                )

    def test_non_gnome_desktop_not_detected(self):
        for desktop in ("KDE", "X-Cinnamon", "ubuntu:WAYLAND", ""):
            with self.subTest(desktop=desktop):
                self.assertFalse(
                    gnome_focus.is_gnome_desktop({"XDG_CURRENT_DESKTOP": desktop})
                )

    def test_missing_var_not_detected(self):
        self.assertFalse(gnome_focus.is_gnome_desktop({}))


class ShellVersionTests(unittest.TestCase):
    def test_version_parsed_from_gnome_shell(self):
        result = subprocess.CompletedProcess([], 0, stdout="GNOME Shell 46.2\n")
        with (
            patch.object(gnome_focus.shutil, "which", return_value="/usr/bin/gnome-shell"),
            patch.object(gnome_focus.subprocess, "run", return_value=result),
        ):
            self.assertEqual(gnome_focus.gnome_shell_version(_gnome_env()), 46)

    def test_version_none_when_shell_missing(self):
        with patch.object(gnome_focus.shutil, "which", return_value=None):
            self.assertIsNone(gnome_focus.gnome_shell_version(_gnome_env()))

    def test_version_none_on_failure(self):
        with (
            patch.object(gnome_focus.shutil, "which", return_value="/usr/bin/gnome-shell"),
            patch.object(
                gnome_focus.subprocess,
                "run",
                side_effect=OSError,
            ),
        ):
            self.assertIsNone(gnome_focus.gnome_shell_version(_gnome_env()))

    def test_version_none_on_unparsable(self):
        result = subprocess.CompletedProcess([], 0, stdout="garbage\n")
        with (
            patch.object(gnome_focus.shutil, "which", return_value="/usr/bin/gnome-shell"),
            patch.object(gnome_focus.subprocess, "run", return_value=result),
        ):
            self.assertIsNone(gnome_focus.gnome_shell_version(_gnome_env()))


class SupportedTests(unittest.TestCase):
    def _set_version(self, version):
        result = subprocess.CompletedProcess([], 0, stdout=f"GNOME Shell {version}\n")
        patch_version = patch.object(
            gnome_focus.subprocess, "run", return_value=result
        )
        patch_which = patch.object(
            gnome_focus.shutil, "which", return_value="/usr/bin/gnome-shell"
        )
        return patch_version, patch_which

    def test_supported_at_min_version(self):
        pv, pw = self._set_version(gnome_focus.MIN_SHELL_VERSION)
        with pw, pv:
            self.assertTrue(gnome_focus.gnome_focus_watcher_supported(_gnome_env()))

    def test_unsupported_below_min_version(self):
        pv, pw = self._set_version(gnome_focus.MIN_SHELL_VERSION - 1)
        with pw, pv:
            self.assertFalse(gnome_focus.gnome_focus_watcher_supported(_gnome_env()))

    def test_unsupported_on_kde(self):
        pv, pw = self._set_version(46)
        with pw, pv:
            self.assertFalse(
                gnome_focus.gnome_focus_watcher_supported({"XDG_CURRENT_DESKTOP": "KDE"})
            )


class InstallDirTests(unittest.TestCase):
    def test_uses_xdg_data_home(self):
        with patch.dict(
            os.environ, {"XDG_DATA_HOME": "/custom/data"}, clear=False
        ):
            path = gnome_focus.extension_install_dir()
        self.assertTrue(path.startswith("/custom/data/gnome-shell/extensions/"))
        self.assertTrue(path.endswith(gnome_focus.GNOME_EXTENSION_UUID))

    def test_defaults_to_local_share(self):
        env = dict(os.environ)
        env.pop("XDG_DATA_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            path = gnome_focus.extension_install_dir()
        self.assertTrue(path.endswith(gnome_focus.GNOME_EXTENSION_UUID))


class InstalledCheckTests(unittest.TestCase):
    def test_reports_not_installed_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, XDG_DATA_HOME=tmp)
            install_dir = gnome_focus.extension_install_dir(env)
            os.makedirs(os.path.join(install_dir, ".."), exist_ok=True)
            self.assertFalse(gnome_focus.extension_installed(env))

    def test_reports_installed_when_both_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, XDG_DATA_HOME=tmp)
            install_dir = gnome_focus.extension_install_dir(env)
            os.makedirs(install_dir)
            for name in gnome_focus.EXTENSION_FILES:
                with open(os.path.join(install_dir, name), "w", encoding="utf-8"):
                    pass
            self.assertTrue(gnome_focus.extension_installed(env))


class _FakeBus:
    """Minimal stand-in for a connected dbus-fast MessageBus."""

    def __init__(self):
        self.disconnected = False

    @classmethod
    async def connect(cls):
        return cls()

    def disconnect(self):
        self.disconnected = True


class GetFocusAppTests(unittest.TestCase):
    def _patch_connect(self):
        return patch.object(
            gnome_focus, "_connect_watcher_bus", side_effect=_FakeBus.connect
        )

    def test_returns_payload_on_success(self):
        async def fake_query(bus):
            return {"executable": "/usr/bin/foo", "pid": 123}

        with (
            patch.object(sys, "platform", "linux"),
            self._patch_connect(),
            patch.object(
                gnome_focus,
                "_get_focus_app_payload_from_bus",
                side_effect=fake_query,
            ),
        ):
            payload = gnome_focus.get_focus_app_payload(_gnome_env())
        self.assertEqual(payload, {"executable": "/usr/bin/foo", "pid": 123})

    def test_none_when_bus_connect_fails(self):
        async def fail_connect():
            raise OSError("session bus unreachable")

        with (
            patch.object(sys, "platform", "linux"),
            patch.object(
                gnome_focus, "_connect_watcher_bus", side_effect=fail_connect
            ),
        ):
            self.assertIsNone(gnome_focus.get_focus_app_payload(_gnome_env()))

    def test_none_when_query_raises(self):
        async def fail_query(bus):
            raise OSError("service vanished")

        with (
            patch.object(sys, "platform", "linux"),
            self._patch_connect(),
            patch.object(
                gnome_focus,
                "_get_focus_app_payload_from_bus",
                side_effect=fail_query,
            ),
        ):
            self.assertIsNone(gnome_focus.get_focus_app_payload(_gnome_env()))

    def test_none_on_non_gnome(self):
        with patch.object(sys, "platform", "linux"):
            self.assertIsNone(
                gnome_focus.get_focus_app_payload({"XDG_CURRENT_DESKTOP": "KDE"})
            )

    def test_none_when_dbus_fast_missing(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                sys.modules,
                {"dbus_fast": None, "dbus_fast.aio": None},
            ),
        ):
            self.assertIsNone(gnome_focus.get_focus_app_payload(_gnome_env()))

    def test_focus_app_executable_extracts_exe(self):
        async def fake_query(bus):
            return {"executable": "/usr/bin/foo", "wm_class": "Foo"}

        with (
            patch.object(sys, "platform", "linux"),
            self._patch_connect(),
            patch.object(
                gnome_focus,
                "_get_focus_app_payload_from_bus",
                side_effect=fake_query,
            ),
        ):
            self.assertEqual(
                gnome_focus.focus_app_executable(_gnome_env()), "/usr/bin/foo"
            )

    def test_focus_app_executable_none_when_empty(self):
        async def fake_query(bus):
            return {"executable": "", "wm_class": "Foo"}

        with (
            patch.object(sys, "platform", "linux"),
            self._patch_connect(),
            patch.object(
                gnome_focus,
                "_get_focus_app_payload_from_bus",
                side_effect=fake_query,
            ),
        ):
            self.assertIsNone(gnome_focus.focus_app_executable(_gnome_env()))


class _GetFocusAppPayloadFromBusTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the low-level ``_get_focus_app_payload_from_bus`` helper."""

    @staticmethod
    def _fake_bus(reply_body, message_type=None):
        from dbus_fast import MessageType  # pyright: ignore[reportMissingImports]

        class _Reply:
            def __init__(self, body, msg_type):
                self.message_type = msg_type
                self.body = body

        class _Bus:
            async def call(self, _msg):
                msg_type = (
                    message_type
                    if message_type is not None
                    else MessageType.METHOD_RETURN
                )
                return _Reply(reply_body, msg_type)

        return _Bus()

    async def test_parses_json_object_reply(self):
        bus = self._fake_bus(("{\"executable\": \"/usr/bin/foo\", \"pid\": 123}",))
        payload = await gnome_focus._get_focus_app_payload_from_bus(bus)
        self.assertEqual(payload, {"executable": "/usr/bin/foo", "pid": 123})

    async def test_returns_none_when_not_method_return(self):
        from dbus_fast import MessageType  # pyright: ignore[reportMissingImports]

        bus = self._fake_bus(
            ("{\"executable\": \"/usr/bin/foo\"}",),
            message_type=MessageType.ERROR,
        )
        self.assertIsNone(await gnome_focus._get_focus_app_payload_from_bus(bus))

    async def test_returns_none_when_body_empty(self):
        bus = self._fake_bus(())
        self.assertIsNone(await gnome_focus._get_focus_app_payload_from_bus(bus))

    async def test_returns_none_when_body_not_string(self):
        bus = self._fake_bus((42,))
        self.assertIsNone(await gnome_focus._get_focus_app_payload_from_bus(bus))

    async def test_returns_none_when_json_is_not_object(self):
        bus = self._fake_bus(("\"a string\"",))
        self.assertIsNone(await gnome_focus._get_focus_app_payload_from_bus(bus))

    async def test_returns_none_when_json_bad(self):
        bus = self._fake_bus(("not-json",))
        self.assertIsNone(await gnome_focus._get_focus_app_payload_from_bus(bus))

    def test_placeholder(self):
        self.assertTrue(True)


class SourceDirResolutionTests(unittest.TestCase):
    def test_resolves_bundled_source_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets_root = os.path.join(tmp, "linux")
            source_dir = os.path.join(
                assets_root, gnome_focus.GNOME_EXTENSION_SOURCE_DIR_NAME
            )
            os.makedirs(source_dir)
            with patch.object(
                gnome_focus, "_linux_assets_root", return_value=assets_root
            ):
                self.assertEqual(
                    gnome_focus.resolve_extension_source_dir(), source_dir
                )

    def test_empty_when_no_assets_root(self):
        with patch.object(gnome_focus, "_linux_assets_root", return_value=""):
            self.assertEqual(gnome_focus.resolve_extension_source_dir(), "")

    def test_assets_root_falls_back_to_source_checkout(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(
            gnome_focus._linux_assets_root(),
            os.path.join(repo_root, "packaging", "linux"),
        )


class InstallEnableTests(unittest.TestCase):
    def test_install_copies_extension_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            fake_bundle = os.path.join(src, "gnome-focus-watcher")
            os.makedirs(fake_bundle)
            for name in gnome_focus.EXTENSION_FILES:
                with open(os.path.join(fake_bundle, name), "w", encoding="utf-8") as fh:
                    fh.write(name)

            data_home = os.path.join(tmp, "data")
            with (
                patch.object(sys, "platform", "linux"),
                patch.object(
                    gnome_focus, "resolve_extension_source_dir", return_value=fake_bundle
                ),
                patch.dict(os.environ, {"XDG_DATA_HOME": data_home}, clear=False),
            ):
                self.assertTrue(gnome_focus.install_extension())
                install_dir = gnome_focus.extension_install_dir()
                self.assertTrue(gnome_focus.extension_installed())

    def test_install_overwrites_existing_and_removes_stale_files(self):
        """Reinstall must fully overwrite: stale files from an older version
        are removed and the new files replace the old ones."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_bundle = os.path.join(tmp, "src", "gnome-focus-watcher")
            os.makedirs(fake_bundle)
            for name in gnome_focus.EXTENSION_FILES:
                with open(os.path.join(fake_bundle, name), "w", encoding="utf-8") as fh:
                    fh.write("new:" + name)

            data_home = os.path.join(tmp, "data")
            with (
                patch.object(sys, "platform", "linux"),
                patch.object(
                    gnome_focus, "resolve_extension_source_dir", return_value=fake_bundle
                ),
                patch.dict(os.environ, {"XDG_DATA_HOME": data_home}, clear=False),
            ):
                install_dir = gnome_focus.extension_install_dir()
                os.makedirs(install_dir)

                # Simulate an older install: an outdated metadata.json plus a
                # stale helper file that is no longer part of the bundle.
                with open(os.path.join(install_dir, "metadata.json"), "w") as fh:
                    fh.write("old")
                with open(os.path.join(install_dir, "legacy_helper.js"), "w") as fh:
                    fh.write("stale")

                self.assertTrue(gnome_focus.install_extension())

                # New contents replaced the old file.
                with open(os.path.join(install_dir, "metadata.json"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "new:metadata.json")
                # Extension files exist and are up-to-date.
                self.assertTrue(gnome_focus.extension_installed())
                # The stale file from the previous version is gone.
                self.assertFalse(
                    os.path.exists(os.path.join(install_dir, "legacy_helper.js"))
                )

    def test_install_preserves_existing_install_when_bundle_incomplete(self):
        """A partial bundle must not wipe the existing install."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_bundle = os.path.join(tmp, "src", "gnome-focus-watcher")
            os.makedirs(fake_bundle)
            with open(
                os.path.join(fake_bundle, "extension.js"), "w", encoding="utf-8"
            ) as fh:
                fh.write("partial")

            data_home = os.path.join(tmp, "data")
            with (
                patch.object(sys, "platform", "linux"),
                patch.object(
                    gnome_focus, "resolve_extension_source_dir", return_value=fake_bundle
                ),
                patch.dict(os.environ, {"XDG_DATA_HOME": data_home}, clear=False),
            ):
                install_dir = gnome_focus.extension_install_dir()
                os.makedirs(install_dir)
                with open(os.path.join(install_dir, "extension.js"), "w") as fh:
                    fh.write("existing-good")

                self.assertFalse(gnome_focus.install_extension())
                # Existing install is untouched.
                with open(os.path.join(install_dir, "extension.js"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "existing-good")

    def test_install_noop_on_non_linux(self):
        with patch.object(sys, "platform", "darwin"):
            self.assertFalse(gnome_focus.install_extension())

    def test_install_fails_when_source_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(sys, "platform", "linux"),
                patch.object(gnome_focus, "resolve_extension_source_dir", return_value=""),
                patch.dict(os.environ, {"XDG_DATA_HOME": tmp}, clear=False),
            ):
                self.assertFalse(gnome_focus.install_extension())

    def test_enable_runs_gnome_extensions(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.object(
                gnome_focus.shutil, "which", return_value="/usr/bin/gnome-extensions"
            ),
            patch.object(
                gnome_focus.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout=""),
            ) as run,
        ):
            self.assertTrue(gnome_focus.enable_extension())
            self.assertEqual(run.call_args[0][0][0], "/usr/bin/gnome-extensions")
            self.assertIn("enable", run.call_args[0][0])
            self.assertIn(gnome_focus.GNOME_EXTENSION_UUID, run.call_args[0][0])

    def test_enable_noop_when_tool_missing(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.object(gnome_focus.shutil, "which", return_value=None),
        ):
            self.assertFalse(gnome_focus.enable_extension())


if __name__ == "__main__":
    unittest.main()
