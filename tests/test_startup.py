import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, mock_open, patch

from core import startup as st


class BuildRunCommandTests(unittest.TestCase):
    def test_frozen_uses_executable_only(self):
        with (
            patch.object(sys, "executable", r"C:\Apps\Mouser App\Mouser.exe"),
            patch.object(sys, "frozen", True, create=True),
            patch("os.path.abspath", side_effect=lambda p: p),
        ):
            cmd = st.build_run_command()
        self.assertEqual(cmd, r'"C:\Apps\Mouser App\Mouser.exe"')

    def test_script_appends_quoted_argv0(self):
        with (
            patch.object(sys, "executable", r"C:\Python\python.exe"),
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "argv", ["main_qml.py", "extra"]),
            patch(
                "os.path.abspath",
                side_effect=lambda p: {
                    r"C:\Python\python.exe": r"C:\Python\python.exe",
                    "main_qml.py": r"C:\proj\main_qml.py",
                }.get(p, p),
            ),
        ):
            cmd = st.build_run_command()
        self.assertEqual(cmd, r"C:\Python\python.exe C:\proj\main_qml.py")

    def test_script_quotes_paths_with_spaces(self):
        with (
            patch.object(sys, "executable", r"C:\Program Files\Python\python.exe"),
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "argv", [r"C:\My Project\main_qml.py"]),
            patch("os.path.abspath", side_effect=lambda p: p),
        ):
            cmd = st.build_run_command()
        self.assertEqual(
            cmd,
            r'"C:\Program Files\Python\python.exe" "C:\My Project\main_qml.py"',
        )

    def test_path_without_spaces_unquoted(self):
        with (
            patch.object(sys, "executable", r"C:\Python\python.exe"),
            patch.object(sys, "frozen", True, create=True),
            patch("os.path.abspath", side_effect=lambda p: p),
        ):
            cmd = st.build_run_command()
        self.assertEqual(cmd, r"C:\Python\python.exe")


class ApplyLoginStartupWindowsTests(unittest.TestCase):
    def test_noop_when_unsupported(self):
        with (
            patch.object(st, "supports_login_startup", return_value=False),
            patch.object(st, "_get_winreg") as mock_get,
        ):
            st.apply_login_startup(True)
        mock_get.assert_not_called()

    def test_enabled_sets_registry_value(self):
        mock_wr = MagicMock()
        mock_key = MagicMock()
        mock_wr.HKEY_CURRENT_USER = 1
        mock_wr.KEY_SET_VALUE = 2
        mock_wr.REG_SZ = 1
        mock_wr.OpenKey.return_value = mock_key

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_get_winreg", return_value=mock_wr),
            patch.object(st, "build_run_command", return_value="THE_CMD"),
        ):
            st.apply_login_startup(True)

        mock_wr.OpenKey.assert_called_once()
        mock_wr.SetValueEx.assert_called_once_with(
            mock_key, st.RUN_VALUE_NAME, 0, mock_wr.REG_SZ, "THE_CMD"
        )
        mock_wr.DeleteValue.assert_not_called()
        mock_wr.CloseKey.assert_called_once_with(mock_key)

    def test_disabled_deletes_registry_value(self):
        mock_wr = MagicMock()
        mock_key = MagicMock()
        mock_wr.HKEY_CURRENT_USER = 1
        mock_wr.KEY_SET_VALUE = 2
        mock_wr.REG_SZ = 1
        mock_wr.OpenKey.return_value = mock_key

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_get_winreg", return_value=mock_wr),
        ):
            st.apply_login_startup(False)

        mock_wr.SetValueEx.assert_not_called()
        mock_wr.DeleteValue.assert_called_once_with(mock_key, st.RUN_VALUE_NAME)
        mock_wr.CloseKey.assert_called_once_with(mock_key)

    def test_disabled_ignores_missing_value(self):
        mock_wr = MagicMock()
        mock_key = MagicMock()
        mock_wr.OpenKey.return_value = mock_key
        mock_wr.DeleteValue.side_effect = FileNotFoundError()

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_get_winreg", return_value=mock_wr),
        ):
            st.apply_login_startup(False)

        mock_wr.CloseKey.assert_called_once_with(mock_key)


class ApplyLoginStartupMacTests(unittest.TestCase):
    def test_program_arguments_use_interpreter_and_script_in_source_mode(self):
        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "executable", "/opt/homebrew/bin/python3"),
            patch.object(sys, "argv", ["/tmp/Mouser/main_qml.py"]),
            patch("os.path.abspath", side_effect=lambda p: p),
        ):
            args = st._program_arguments()

        self.assertEqual(
            args,
            ["/opt/homebrew/bin/python3", "/tmp/Mouser/main_qml.py"],
        )

    def test_program_arguments_use_bundle_executable_when_frozen(self):
        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/Applications/Mouser.app/Contents/MacOS/Mouser"),
            patch("os.path.abspath", side_effect=lambda p: p),
        ):
            args = st._program_arguments()

        self.assertEqual(args, ["/Applications/Mouser.app/Contents/MacOS/Mouser"])

    def test_macos_plist_path_uses_canonical_launch_agent_name(self):
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", "/Users/test")):
            plist_path = st._macos_plist_path()

        self.assertEqual(
            plist_path,
            "/Users/test/Library/LaunchAgents/io.github.tombadash.mouser.plist",
        )

    def test_macos_enable_writes_plist_and_bootstraps(self):
        plist = "/tmp/io.github.tombadash.mouser.plist"
        domain = "gui/501"

        with (
            patch.object(sys, "platform", "darwin"),
            patch("core.startup.os.getuid", return_value=501, create=True),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_macos_plist_path", return_value=plist),
            patch.object(st, "_program_arguments", return_value=["/X/Mouser"]),
            patch.object(st, "_launchctl_run") as m_lc,
            patch("os.makedirs") as m_makedirs,
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", mock_open()) as m_open,
            patch("core.startup.plistlib.dump"),
        ):
            m_lc.return_value = MagicMock(returncode=0)
            st.apply_login_startup(True)

        m_makedirs.assert_called_once()
        m_open.assert_called_once_with(plist, "wb")
        self.assertEqual(m_lc.call_count, 1)
        m_lc.assert_called_with(
            ["launchctl", "bootstrap", domain, plist]
        )

    def test_macos_disable_bootout_and_remove_when_plist_exists(self):
        plist = "/tmp/io.github.tombadash.mouser.plist"
        domain = "gui/501"

        with (
            patch.object(sys, "platform", "darwin"),
            patch("core.startup.os.getuid", return_value=501, create=True),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_macos_plist_path", return_value=plist),
            patch.object(st, "_launchctl_run") as m_lc,
            patch("os.path.isfile", return_value=True),
            patch("os.remove") as m_remove,
        ):
            m_lc.return_value = MagicMock(returncode=0)
            st.apply_login_startup(False)

        self.assertEqual(m_lc.call_count, 1)
        m_lc.assert_called_with(
            ["launchctl", "bootout", domain, plist]
        )
        m_remove.assert_called_once_with(plist)

    def test_macos_disable_uses_label_bootout_when_no_plist(self):
        plist = "/tmp/io.github.tombadash.mouser.plist"
        domain = "gui/501"

        with (
            patch.object(sys, "platform", "darwin"),
            patch("core.startup.os.getuid", return_value=501, create=True),
            patch.object(st, "supports_login_startup", return_value=True),
            patch.object(st, "_macos_plist_path", return_value=plist),
            patch.object(st, "_launchctl_run") as m_lc,
            patch("os.path.isfile", return_value=False),
        ):
            m_lc.return_value = MagicMock(returncode=0)
            st.apply_login_startup(False)

        m_lc.assert_called_once_with(
            [
                "launchctl",
                "bootout",
                domain,
                st.MACOS_LAUNCH_AGENT_LABEL,
            ]
        )


class SyncFromConfigTests(unittest.TestCase):
    def test_delegates_to_apply(self):
        with patch.object(st, "apply_login_startup") as mock_apply:
            st.sync_from_config(True)
        mock_apply.assert_called_once_with(True)


class ApplyLoginStartupLinuxTests(unittest.TestCase):
    def test_supports_login_startup_on_linux(self):
        with patch.object(sys, "platform", "linux"):
            self.assertTrue(st.supports_login_startup())

    def test_linux_source_checkout_prefers_project_venv_python(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "executable", "/usr/bin/python"),
            patch.object(sys, "argv", ["/tmp/Mouser/main_qml.py"]),
            patch("os.path.abspath", side_effect=lambda p: p),
            patch("os.path.isfile", side_effect=lambda p: p == "/tmp/Mouser/.venv/bin/python"),
            patch("os.access", side_effect=lambda p, mode: p == "/tmp/Mouser/.venv/bin/python"),
        ):
            args = st._desktop_exec_parts()

        self.assertEqual(
            args,
            ["/tmp/Mouser/.venv/bin/python", "/tmp/Mouser/main_qml.py"],
        )

    def test_linux_desktop_exec_can_force_visible_window(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "executable", "/usr/bin/python"),
            patch.object(sys, "argv", ["/tmp/Mouser/main_qml.py"]),
            patch("os.path.abspath", side_effect=lambda p: p),
            patch("os.path.isfile", return_value=False),
        ):
            args = st._desktop_exec_parts(force_show=True)

        self.assertEqual(
            args,
            ["/usr/bin/python", "/tmp/Mouser/main_qml.py", "--show-window"],
        )

    def test_linux_enable_writes_launcher_and_autostart_entries(self):
        template = """[Desktop Entry]
Name=@APP_NAME@
Exec=@EXEC@
TryExec=@TRY_EXEC@
Path=@WORKDIR@
Icon=@ICON@
X-Mouser-SourcePath=@SOURCE_PATH@
@AUTOSTART_LINES@
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "mouser.desktop.in")
            launcher_path = os.path.join(tmpdir, "applications", st.LINUX_DESKTOP_ENTRY_NAME)
            autostart_path = os.path.join(tmpdir, "autostart", st.LINUX_DESKTOP_ENTRY_NAME)
            with open(template_path, "w", encoding="utf-8") as fh:
                fh.write(template)

            with (
                patch.object(sys, "platform", "linux"),
                patch.object(st, "supports_login_startup", return_value=True),
                patch.object(
                    st,
                    "_desktop_exec_parts",
                    return_value=[
                        "/tmp/Mouser Build/.venv/bin/python",
                        "/tmp/Mouser Build/main_qml.py",
                    ],
                ),
                patch.object(st, "_runtime_root_dir", return_value="/tmp/Mouser Build"),
                patch.object(st, "_linux_icon_path", return_value="/tmp/Mouser Build/images/logo_icon.png"),
                patch.object(st, "_linux_source_path", return_value="/tmp/Mouser Build/main_qml.py"),
                patch.object(st, "_linux_template_path", return_value=template_path),
                patch.object(st, "_linux_desktop_path", return_value=launcher_path),
                patch.object(st, "_linux_autostart_path", return_value=autostart_path),
            ):
                st.apply_login_startup(True)

            with open(launcher_path, "r", encoding="utf-8") as fh:
                launcher_text = fh.read()
            with open(autostart_path, "r", encoding="utf-8") as fh:
                autostart_text = fh.read()

        self.assertIn('Exec="/tmp/Mouser Build/.venv/bin/python" "/tmp/Mouser Build/main_qml.py"', launcher_text)
        self.assertIn("TryExec=/tmp/Mouser Build/.venv/bin/python", launcher_text)
        self.assertIn("Path=/tmp/Mouser Build", launcher_text)
        self.assertIn("X-Mouser-SourcePath=/tmp/Mouser Build/main_qml.py", launcher_text)
        self.assertNotIn("X-GNOME-Autostart-enabled=true", launcher_text)
        self.assertIn("X-GNOME-Autostart-enabled=true", autostart_text)
        self.assertIn(
            f"X-GNOME-Autostart-Delay={st.LINUX_AUTOSTART_DELAY_SECONDS}",
            autostart_text,
        )
        self.assertIn("Hidden=false", autostart_text)

    def test_linux_template_path_prefers_pyinstaller_bundle_resource(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundled_dir = os.path.join(tmpdir, "linux")
            os.makedirs(bundled_dir)
            bundled_template = os.path.join(bundled_dir, st.LINUX_DESKTOP_TEMPLATE_NAME)
            with open(bundled_template, "w", encoding="utf-8") as fh:
                fh.write("[Desktop Entry]\n")

            with (
                patch.object(sys, "platform", "linux"),
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", tmpdir, create=True),
            ):
                self.assertEqual(st._linux_template_path(), bundled_template)

    def test_linux_disable_removes_autostart_but_keeps_launcher(self):
        template = """[Desktop Entry]
Name=@APP_NAME@
Exec=@EXEC@
TryExec=@TRY_EXEC@
Path=@WORKDIR@
Icon=@ICON@
X-Mouser-SourcePath=@SOURCE_PATH@
@AUTOSTART_LINES@
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "mouser.desktop.in")
            launcher_path = os.path.join(tmpdir, "applications", st.LINUX_DESKTOP_ENTRY_NAME)
            autostart_path = os.path.join(tmpdir, "autostart", st.LINUX_DESKTOP_ENTRY_NAME)
            with open(template_path, "w", encoding="utf-8") as fh:
                fh.write(template)
            os.makedirs(os.path.dirname(autostart_path), exist_ok=True)
            with open(autostart_path, "w", encoding="utf-8") as fh:
                fh.write("stale")

            with (
                patch.object(sys, "platform", "linux"),
                patch.object(st, "supports_login_startup", return_value=True),
                patch.object(st, "_desktop_exec_parts", return_value=["/tmp/Mouser/python"]),
                patch.object(st, "_runtime_root_dir", return_value="/tmp/Mouser"),
                patch.object(st, "_linux_icon_path", return_value="/tmp/Mouser/images/logo_icon.png"),
                patch.object(st, "_linux_source_path", return_value="/tmp/Mouser"),
                patch.object(st, "_linux_template_path", return_value=template_path),
                patch.object(st, "_linux_desktop_path", return_value=launcher_path),
                patch.object(st, "_linux_autostart_path", return_value=autostart_path),
            ):
                st.apply_login_startup(False)

            self.assertTrue(os.path.isfile(launcher_path))
            self.assertFalse(os.path.exists(autostart_path))

    def test_linux_disable_removes_autostart_even_when_launcher_template_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = os.path.join(tmpdir, "applications", st.LINUX_DESKTOP_ENTRY_NAME)
            autostart_path = os.path.join(tmpdir, "autostart", st.LINUX_DESKTOP_ENTRY_NAME)
            missing_template = os.path.join(tmpdir, "missing.desktop.in")
            os.makedirs(os.path.dirname(autostart_path), exist_ok=True)
            with open(autostart_path, "w", encoding="utf-8") as fh:
                fh.write("stale")

            with (
                patch.object(sys, "platform", "linux"),
                patch.object(st, "supports_login_startup", return_value=True),
                patch.object(st, "_desktop_exec_parts", return_value=["/tmp/Mouser/python"]),
                patch.object(st, "_runtime_root_dir", return_value="/tmp/Mouser"),
                patch.object(st, "_linux_icon_path", return_value="/tmp/Mouser/images/logo_icon.png"),
                patch.object(st, "_linux_source_path", return_value="/tmp/Mouser"),
                patch.object(st, "_linux_template_path", return_value=missing_template),
                patch.object(st, "_linux_desktop_path", return_value=launcher_path),
                patch.object(st, "_linux_autostart_path", return_value=autostart_path),
            ):
                st.apply_login_startup(False)

            self.assertFalse(os.path.exists(autostart_path))
            self.assertFalse(os.path.exists(launcher_path))


if __name__ == "__main__":
    unittest.main()
