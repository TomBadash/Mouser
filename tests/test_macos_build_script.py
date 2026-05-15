import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_macos_app.sh"


@unittest.skipUnless(shutil.which("zsh"), "zsh is required for build script tests")
class MacOSBuildScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.log = self.root / "commands.log"
        self.bin_dir = self.root / "fake-bin"
        self.tool_dir = self.root / "tool-bin"
        self.bin_dir.mkdir()
        self.tool_dir.mkdir()

        shutil.copy2(SCRIPT, self.root / "build_macos_app.sh")
        (self.root / "build_macos_app.sh").chmod(0o755)
        (self.root / "images").mkdir()
        (self.root / "images" / "AppIcon.icns").write_text("icon", encoding="utf-8")
        (self.root / "build_resources").mkdir()
        (self.root / "build_resources" / "Mouser.entitlements").write_text(
            "<plist/>", encoding="utf-8"
        )
        (self.root / "Mouser-mac.spec").write_text("# fake spec", encoding="utf-8")

        self._write_command("uname", "printf 'Darwin\\n'\n")
        self._write_codesign()
        self._write_shasum()
        self._write_manager("pyenv")
        self._write_manager("conda")
        self._write_manager("uv")
        self._write_manager("asdf")
        self._write_python(self.bin_dir / "python3", "path-python3")
        self._write_python(self.bin_dir / "python", "path-python")
        for tool in ("dirname", "pwd", "mkdir", "find", "awk", "touch"):
            resolved = shutil.which(tool)
            if resolved:
                os.symlink(resolved, self.tool_dir / tool)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_executable(self, path: Path, body: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _write_command(self, name: str, body: str):
        self._write_executable(self.bin_dir / name, body)

    def _write_manager(self, name: str):
        self._write_command(
            name,
            textwrap.dedent(
                f"""
                printf 'manager\\t{name}\\n' >> "$MOUSER_TEST_LOG"
                exit 47
                """
            ),
        )

    def _write_shasum(self):
        self._write_command(
            "shasum",
            "printf 'deadbeef  %s\\n' \"${3:-}\"\n",
        )

    def _write_codesign(self):
        self._write_command(
            "codesign",
            textwrap.dedent(
                """
                printf 'codesign\\t%s\\n' "$*" >> "$MOUSER_TEST_LOG"
                case "$*" in
                  *"--verify"*)
                    if [ "${MOUSER_CODESIGN_VERIFY_FAIL:-0}" = "1" ]; then
                      exit 31
                    fi
                    ;;
                esac
                exit 0
                """
            ),
        )

    def _write_python(self, path: Path, label: str):
        self._write_executable(
            path,
            textwrap.dedent(
                f"""
                label={label!r}
                printf 'python\\t%s\\t%s\\t%s\\n' "$label" "${{PYTHONHASHSEED:-}}" "$*" >> "$MOUSER_TEST_LOG"
                if [ "${{1:-}}" = "-c" ]; then
                  case "${{2:-}}" in
                    *"import PyInstaller; print"*)
                      printf '6.20.0\\n'
                      exit 0
                      ;;
                    *"import PyInstaller"*)
                      if [ "${{MOUSER_FAKE_NO_PYINSTALLER:-}}" = "$label" ]; then
                        exit 13
                      fi
                      exit 0
                      ;;
                    *"platform.python_version"*)
                      printf '3.12.13\\n'
                      exit 0
                      ;;
                    *"platform.machine"*)
                      printf 'arm64\\n'
                      exit 0
                      ;;
                  esac
                fi
                if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "PyInstaller" ]; then
                  printf 'pyinstaller\\t%s\\t%s\\t%s\\n' "$label" "${{PYTHONHASHSEED:-}}" "$*" >> "$MOUSER_TEST_LOG"
                  app="$MOUSER_TEST_ROOT/dist/Mouser.app"
                  frameworks="$app/Contents/Frameworks"
                  mkdir -p "$frameworks/Outer.framework/Frameworks/Inner.framework"
                  touch "$frameworks/libRoot.dylib"
                  touch "$frameworks/package.so"
                  touch "$frameworks/Outer.framework/libOuter.dylib"
                  touch "$frameworks/Outer.framework/Frameworks/Inner.framework/libInner.dylib"
                  exit 0
                fi
                exit 0
                """
            ),
        )

    def _run_script(self, restricted_path=False, **overrides):
        env = os.environ.copy()
        if restricted_path:
            env["PATH"] = f"{self.bin_dir}{os.pathsep}{self.tool_dir}"
        else:
            env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["MOUSER_TEST_LOG"] = str(self.log)
        env["MOUSER_TEST_ROOT"] = str(self.root)
        for key in (
            "MOUSER_PYTHON",
            "MOUSER_SIGN_IDENTITY",
            "MOUSER_FAKE_NO_PYINSTALLER",
            "MOUSER_CODESIGN_VERIFY_FAIL",
            "MOUSER_PREFER_PYENV",
            "PYINSTALLER_TARGET_ARCH",
            "VIRTUAL_ENV",
        ):
            env.pop(key, None)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return subprocess.run(
            [shutil.which("zsh") or "zsh", str(self.root / "build_macos_app.sh")],
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _log_lines(self):
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def _pyinstaller_labels(self):
        return [
            line.split("\t")[1]
            for line in self._log_lines()
            if line.startswith("pyinstaller\t")
        ]

    def _codesign_lines(self):
        return [
            line.split("\t", 1)[1]
            for line in self._log_lines()
            if line.startswith("codesign\t")
        ]

    def test_mouser_python_wins_and_bad_override_fails(self):
        custom = self.root / "custom-python"
        self._write_python(custom, "mouser-python")
        (self.root / ".venv" / "bin").mkdir(parents=True)
        self._write_python(self.root / ".venv" / "bin" / "python3", "repo-python3")

        result = self._run_script(MOUSER_PYTHON=custom)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source: MOUSER_PYTHON", result.stdout)
        self.assertEqual(self._pyinstaller_labels(), ["mouser-python"])

        self.log.unlink()
        result = self._run_script(MOUSER_PYTHON=self.root / "missing-python")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MOUSER_PYTHON is set but is not executable", result.stderr)
        self.assertEqual(self._pyinstaller_labels(), [])

    def test_active_virtualenv_wins_over_repo_venv(self):
        active = self.root / "external-venv"
        self._write_python(active / "bin" / "python3", "active-venv-python3")
        self._write_python(self.root / ".venv" / "bin" / "python3", "repo-python3")

        result = self._run_script(VIRTUAL_ENV=active)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source: VIRTUAL_ENV", result.stdout)
        self.assertEqual(self._pyinstaller_labels(), ["active-venv-python3"])

    def test_repo_venv_wins_over_path_and_bin_python_fallback_works(self):
        self._write_python(self.root / ".venv" / "bin" / "python", "repo-python")

        result = self._run_script(restricted_path=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source: repo .venv", result.stdout)
        self.assertEqual(self._pyinstaller_labels(), ["repo-python"])

    def test_path_fallbacks_and_no_manager_commands_are_invoked(self):
        result = self._run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source: PATH python3", result.stdout)
        self.assertEqual(self._pyinstaller_labels(), ["path-python3"])
        self.assertFalse(
            [line for line in self._log_lines() if line.startswith("manager\t")]
        )

        self.log.unlink()
        (self.bin_dir / "python3").unlink()
        result = self._run_script(restricted_path=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source: PATH python", result.stdout)
        self.assertEqual(self._pyinstaller_labels(), ["path-python"])

    def test_missing_pyinstaller_names_selected_interpreter(self):
        repo_python = self.root / ".venv" / "bin" / "python3"
        self._write_python(repo_python, "repo-python3")

        result = self._run_script(MOUSER_FAKE_NO_PYINSTALLER="repo-python3")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"PyInstaller not installed in {repo_python}", result.stderr)
        self.assertIn(f"{repo_python} -m pip install -r", result.stderr)
        self.assertEqual(self._pyinstaller_labels(), [])

    def test_pyinstaller_receives_hash_seed_zero(self):
        result = self._run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        pyinstaller_lines = [
            line for line in self._log_lines() if line.startswith("pyinstaller\t")
        ]
        self.assertEqual(len(pyinstaller_lines), 1)
        self.assertIn("\t0\t", pyinstaller_lines[0])

    def test_ad_hoc_signing_path(self):
        result = self._run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        codesign = self._codesign_lines()
        self.assertEqual(len(codesign), 1)
        self.assertIn("--force --deep --sign -", codesign[0])

    def test_identity_signing_order_and_verify_failure(self):
        result = self._run_script(MOUSER_SIGN_IDENTITY="IDENTITY")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Entitlements:", result.stdout)
        self.assertIn("deadbeef", result.stdout)
        codesign = self._codesign_lines()

        def index_containing(fragment):
            for index, line in enumerate(codesign):
                if fragment in line:
                    return index
            self.fail(f"missing codesign call containing {fragment!r}: {codesign}")

        def index_ending(fragment):
            for index, line in enumerate(codesign):
                if line.endswith(fragment):
                    return index
            self.fail(f"missing codesign call ending with {fragment!r}: {codesign}")

        inner_dylib = index_containing("Inner.framework/libInner.dylib")
        inner_framework = index_ending("Inner.framework")
        outer_dylib = index_containing("Outer.framework/libOuter.dylib")
        outer_framework = index_ending("Outer.framework")
        outer_app = index_containing("--entitlements")
        verify = index_containing("--verify --deep --strict")

        self.assertLess(inner_dylib, inner_framework)
        self.assertLess(inner_framework, outer_framework)
        self.assertLess(outer_dylib, outer_framework)
        self.assertLess(outer_framework, outer_app)
        self.assertLess(outer_app, verify)
        self.assertEqual(verify, len(codesign) - 1)

        self.log.unlink()
        result = self._run_script(
            MOUSER_SIGN_IDENTITY="IDENTITY",
            MOUSER_CODESIGN_VERIFY_FAIL="1",
        )

        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
