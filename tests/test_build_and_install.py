import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_and_install as installer
from scripts import windows_install


def normalize_path(path: Path) -> str:
    return os.path.normpath(str(path)).replace("\\", "/")


class BuildAndInstallTests(unittest.TestCase):
    def test_resolve_macos_sign_identity_requires_team_or_identity(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                installer.resolve_macos_sign_identity()

    def test_load_env_local_sets_defaults_without_overriding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env.local"
            env_file.write_text(
                'export MOUSER_INSTALL_DIR="/tmp/custom"\n'
                'MOUSER_TEAM_ID="TEAM123"\n',
                encoding="utf-8",
            )
            with mock.patch.object(installer, "ROOT", root):
                with mock.patch.dict(
                    os.environ,
                    {"MOUSER_INSTALL_DIR": "/existing"},
                    clear=False,
                ):
                    installer.load_env_local()
                    self.assertEqual(os.environ["MOUSER_INSTALL_DIR"], "/existing")
                    self.assertEqual(os.environ["MOUSER_TEAM_ID"], "TEAM123")

    def test_resolve_install_dir_honors_override(self):
        with mock.patch.dict(os.environ, {"MOUSER_INSTALL_DIR": "~/Apps/Mouser"}, clear=False):
            resolved = installer.resolve_install_dir(Path("/Applications"))
        self.assertEqual(resolved, Path("~/Apps/Mouser").expanduser())

    def test_python_from_env_dir_prefers_windows_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_dir = Path(tmp)
            scripts = env_dir / "Scripts"
            scripts.mkdir()
            python_exe = scripts / "python.exe"
            python_exe.write_text("stub", encoding="utf-8")
            self.assertEqual(installer.python_from_env_dir(env_dir), python_exe)

    def test_python_from_env_dir_falls_back_to_unix_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_dir = Path(tmp)
            bin_dir = env_dir / "bin"
            bin_dir.mkdir()
            python3 = bin_dir / "python3"
            python3.write_text("#!/bin/sh\n", encoding="utf-8")
            python3.chmod(python3.stat().st_mode | stat.S_IXUSR)
            self.assertEqual(installer.python_from_env_dir(env_dir), python3)

    def test_resolve_python_prefers_mouser_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "python3"
            custom.write_text("#!/bin/sh\n", encoding="utf-8")
            custom.chmod(custom.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"MOUSER_PYTHON": str(custom)}, clear=False):
                resolved, source = installer.resolve_python()
            self.assertEqual(resolved, custom)
            self.assertEqual(source, "MOUSER_PYTHON")

    def test_default_macos_install_dir(self):
        self.assertEqual(
            installer.DEFAULT_MACOS_INSTALL_DIR,
            Path("/Applications"),
        )

    def test_main_rejects_unsupported_platform(self):
        with mock.patch.object(installer.sys, "platform", "linux"):
            with self.assertRaises(SystemExit) as ctx:
                installer.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_build_and_install_windows_verifies_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist = root / "dist" / installer.WINDOWS_APP_DIR
            dist.mkdir(parents=True)
            (dist / "Mouser.exe").write_text("exe", encoding="utf-8")
            (dist / "_internal").mkdir()

            install_root = root / "install"
            python = root / "python"
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            python.chmod(python.stat().st_mode | stat.S_IXUSR)

            def fake_run_command(args, **kwargs):
                if "PyInstaller" in [str(arg) for arg in args]:
                    dist.mkdir(parents=True, exist_ok=True)
                    (dist / "Mouser.exe").write_text("exe", encoding="utf-8")
                    (dist / "_internal").mkdir(exist_ok=True)

            def fake_run(args, **kwargs):
                if args[:3] == [str(python), "-c", "import hid; print('[*] hidapi:', hid.__file__)"]:
                    return mock.Mock(returncode=0)
                raise AssertionError(f"unexpected subprocess.run: {args}")

            def fake_finalize(install_root, *, scope=None):
                script = install_root / windows_install.UNINSTALL_SCRIPT_NAME
                script.write_text("@echo off\r\n", encoding="utf-8")
                return {
                    "install_root": install_root,
                    "start_menu_shortcut": install_root / "Mouser.lnk",
                    "uninstall_script": script,
                }

            with mock.patch.object(installer, "ROOT", root):
                with mock.patch.dict(
                    os.environ,
                    {"MOUSER_INSTALL_DIR": str(install_root), "MOUSER_INSTALL_SCOPE": "user"},
                    clear=False,
                ):
                    with mock.patch.object(
                        installer,
                        "resolve_python",
                        return_value=(python, "test"),
                    ):
                        with mock.patch.object(installer, "require_pyinstaller"):
                            with mock.patch.object(installer, "log_python_provenance"):
                                with mock.patch.object(
                                    installer,
                                    "run_command",
                                    side_effect=fake_run_command,
                                ):
                                    with mock.patch(
                                        "scripts.build_and_install.subprocess.run",
                                        side_effect=fake_run,
                                    ):
                                        with mock.patch.object(
                                            windows_install,
                                            "cleanup_all_windows_installs",
                                        ):
                                            with mock.patch.object(
                                                windows_install,
                                                "stop_running_mouser_instances",
                                            ):
                                                with mock.patch.object(
                                                    windows_install,
                                                    "finalize_windows_install",
                                                    side_effect=fake_finalize,
                                                ):
                                                    installer.build_and_install_windows()

            self.assertTrue((install_root / "Mouser.exe").is_file())
            self.assertTrue((install_root / "_internal").is_dir())
            self.assertTrue((install_root / windows_install.UNINSTALL_SCRIPT_NAME).is_file())


class WindowsInstallTests(unittest.TestCase):
    def test_default_install_root_uses_program_files_for_machine_scope(self):
        with mock.patch.dict(
            os.environ,
            {"ProgramFiles": r"C:\Program Files", "MOUSER_INSTALL_SCOPE": "machine"},
            clear=False,
        ):
            self.assertEqual(
                normalize_path(windows_install.default_install_root()),
                normalize_path(Path(r"C:\Program Files\Mouser")),
            )

    def test_default_install_root_uses_local_programs_for_user_scope(self):
        with mock.patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": r"C:\Users\example\AppData\Local",
                "MOUSER_INSTALL_SCOPE": "user",
            },
            clear=False,
        ):
            self.assertEqual(
                normalize_path(windows_install.default_install_root()),
                normalize_path(Path(r"C:\Users\example\AppData\Local\Programs\Mouser")),
            )

    def test_resolve_install_scope_falls_back_when_program_files_not_writable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(windows_install, "_can_install_machine", return_value=False):
                self.assertEqual(windows_install.resolve_install_scope(), "user")


if __name__ == "__main__":
    unittest.main()
