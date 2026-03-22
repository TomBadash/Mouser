import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

from core import startup as st


class BuildRunCommandTests(unittest.TestCase):
    def test_frozen_uses_executable_only(self):
        with (
            patch.object(sys, "executable", r"C:\Apps\Mouser App\Mouser.exe"),
            patch.object(sys, "frozen", True, create=True),
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
    def test_macos_enable_writes_plist_and_bootstraps(self):
        plist = "/tmp/com.mouser.startup.plist"
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
        plist = "/tmp/com.mouser.startup.plist"
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
        plist = "/tmp/com.mouser.startup.plist"
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


if __name__ == "__main__":
    unittest.main()
