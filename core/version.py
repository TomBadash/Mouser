"""Canonical Mouser version and build metadata."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


_DEFAULT_APP_VERSION = "3.6.0"
_BUILD_INFO_FILENAME = "mouser_build_info.json"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _normalize_version(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return _DEFAULT_APP_VERSION
    return value[1:] if value.startswith("v") else value


def _parse_bool(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _load_bundled_build_info() -> dict[str, object]:
    if not getattr(sys, "frozen", False):
        return {}

    candidate_roots = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(getattr(sys, "executable", "")).resolve().parent,
    ]
    for root in candidate_roots:
        if not root:
            continue
        path = root / _BUILD_INFO_FILENAME
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.4,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=_REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


_BUNDLED_BUILD_INFO = _load_bundled_build_info()
APP_VERSION = _normalize_version(
    str(
        _BUNDLED_BUILD_INFO.get("version")
        or os.environ.get("MOUSER_VERSION", _DEFAULT_APP_VERSION)
    )
)

_APP_COMMIT_FULL = str(
    _BUNDLED_BUILD_INFO.get("commit")
    or os.environ.get("MOUSER_GIT_COMMIT", "")
    or _run_git(["rev-parse", "HEAD"])
).strip()
APP_COMMIT = _APP_COMMIT_FULL
APP_COMMIT_SHORT = _APP_COMMIT_FULL[:12] if _APP_COMMIT_FULL else ""

_DIRTY_OVERRIDE = _parse_bool(os.environ.get("MOUSER_GIT_DIRTY"))
if "dirty" in _BUNDLED_BUILD_INFO:
    APP_COMMIT_DIRTY = bool(_BUNDLED_BUILD_INFO.get("dirty"))
elif _DIRTY_OVERRIDE is not None:
    APP_COMMIT_DIRTY = _DIRTY_OVERRIDE
else:
    APP_COMMIT_DIRTY = _git_dirty()

APP_BUILD_MODE = "Packaged app" if getattr(sys, "frozen", False) else "Source checkout"
APP_COMMIT_DISPLAY = (
    f"{APP_COMMIT_SHORT} (dirty)" if APP_COMMIT_SHORT and APP_COMMIT_DIRTY
    else APP_COMMIT_SHORT or "Unavailable"
)
