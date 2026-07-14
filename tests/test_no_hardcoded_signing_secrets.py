"""Repo-wide guard: code-signing identities must only come from the environment.

These tests scan every git-tracked text file so that a hardcoded Apple Team
ID, a codesigning identity hash, or a baked-in fallback default can never be
reintroduced. Signing configuration belongs in .env.local (gitignored) or the
caller's environment.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Built at runtime so this file never contains the literal itself.
_PREVIOUSLY_LEAKED_TEAM_ID = "MVDT65" + "NPA4"

# Shell parameter expansion with a non-empty default, e.g.
# ${MOUSER_TEAM_ID:-ABC123}, ${MOUSER_TEAM_ID-ABC123}, or ${MOUSER_TEAM_ID:=ABC123}.
_SHELL_DEFAULT = re.compile(
    r"\$\{MOUSER_(?:TEAM_ID|SIGN_IDENTITY)(?::?[-=])[^}]+\}"
)

# Python env lookup with a non-empty default, e.g. os.environ.get("MOUSER_TEAM_ID", "ABC"),
# os.getenv("MOUSER_TEAM_ID", "ABC"), or env.get("MOUSER_TEAM_ID", "ABC").
_PYTHON_DEFAULT = re.compile(
    r"""(?:os\.getenv|(?:[A-Za-z_][A-Za-z0-9_]*\.)?environ\.get|[A-Za-z_][A-Za-z0-9_\.]*\.get)\(\s*["']MOUSER_(?:TEAM_ID|SIGN_IDENTITY)["']\s*,\s*["'][^"']+["']"""
)

# A literal SHA-1 codesigning identity (uppercase 40 hex chars).
_IDENTITY_HASH = re.compile(r"\b[A-F0-9]{40}\b")


def _tracked_text_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, text=True
    )
    files = []
    for rel in output.split("\0"):
        if not rel:
            continue
        path = ROOT / rel
        if path.is_file():
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable: not a place secrets hide as text


class NoHardcodedSigningSecretsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.files = _tracked_text_files()
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise unittest.SkipTest("git not available; cannot enumerate tracked files")

    def _scan(self, predicate, description: str) -> None:
        offenders = []
        for path in self.files:
            if path == Path(__file__).resolve():
                continue
            text = _read_text(path)
            if text is None:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if predicate(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            f"{description} found in tracked files:\n" + "\n".join(offenders),
        )

    def test_no_leaked_team_id_literal(self):
        self._scan(
            lambda line: _PREVIOUSLY_LEAKED_TEAM_ID in line,
            "Hardcoded Apple Team ID",
        )

    def test_no_shell_fallback_defaults_for_signing_vars(self):
        self._scan(
            lambda line: _SHELL_DEFAULT.search(line),
            "Shell fallback default for MOUSER_TEAM_ID/MOUSER_SIGN_IDENTITY",
        )

    def test_no_python_fallback_defaults_for_signing_vars(self):
        self._scan(
            lambda line: _PYTHON_DEFAULT.search(line),
            "Python fallback default for MOUSER_TEAM_ID/MOUSER_SIGN_IDENTITY",
        )

    def test_shell_guard_covers_common_default_variants(self):
        examples = (
            "${MOUSER_TEAM_ID:-ABC123}",
            "${MOUSER_TEAM_ID-ABC123}",
            "${MOUSER_SIGN_IDENTITY:=ABC123}",
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertIsNotNone(_SHELL_DEFAULT.search(example))

    def test_python_guard_covers_common_default_variants(self):
        examples = (
            'os.environ.get("MOUSER_TEAM_ID", "ABC123")',
            'os.getenv("MOUSER_SIGN_IDENTITY", "ABC123")',
            'env.get("MOUSER_TEAM_ID", "ABC123")',
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertIsNotNone(_PYTHON_DEFAULT.search(example))

    def test_no_literal_codesigning_identity_hashes(self):
        self._scan(
            lambda line: _IDENTITY_HASH.search(line),
            "Literal codesigning identity hash (uppercase 40-hex)",
        )

    def test_env_local_is_gitignored_and_example_is_not(self):
        for name in (".env.local", ".env"):
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", name],
                cwd=ROOT,
            )
            self.assertEqual(ignored.returncode, 0, f"{name} must be gitignored")

        example = subprocess.run(
            ["git", "check-ignore", "-q", ".env.local.example"],
            cwd=ROOT,
        )
        self.assertNotEqual(
            example.returncode, 0, ".env.local.example must be tracked, not ignored"
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
