"""
Simple command-line interface for exporting and loading Mouser configs.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import Quartz
import yaml

from core.config import (
    load_config,
    save_config,
)
from core.config_validation import (
    ConfigValidationError,
    assemble_full_config,
    normalize_config,
)
from core.log_setup import setup_logging

CLI_SERVICE_LABEL = "io.github.tombadash.mouser.headless"
CLI_SERVICE_PLIST_NAME = f"{CLI_SERVICE_LABEL}.plist"


def export_config(*, stdout=None) -> int:
    stdout = stdout or sys.stdout
    json.dump(load_config(), stdout, indent=2)
    stdout.write("\n")
    return 0


def _read_config_json(path: str, ft: str=None) -> dict[str, Any]:
    ft = ft or (Path(path).suffix.lower().lstrip(".") if path != "-" else "json")
    if ft not in ("json", "yaml"):
        raise ValueError(f"Unsupported config file type: {ft}")

    if path == "-":
        raw = sys.stdin
        if ft == "json":
            processed = json.load(raw)
        elif ft == "yaml":
            processed = yaml.safe_load(raw)
    else:
        with open(path, "r", encoding="utf-8") as raw:
            if ft == "json":
                processed = json.load(raw)
            elif ft == "yaml":
                processed = yaml.safe_load(raw)

    return normalize_config(processed)


def _format_cli_error(exc: Exception) -> str:
    if isinstance(exc, ConfigValidationError):
        return str(exc)
    if isinstance(exc, json.JSONDecodeError):
        return f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    yaml_error = getattr(yaml, "YAMLError", None)
    if yaml_error and isinstance(exc, yaml_error):
        return f"Invalid YAML: {exc}"
    if isinstance(exc, FileNotFoundError):
        return f"File not found: {exc.filename}"
    if isinstance(exc, OSError):
        return str(exc)
    return str(exc) or exc.__class__.__name__


def run_headless_instance(*, stop_event: threading.Event | None = None, engine_factory=None) -> int:
    if engine_factory is None:
        from core.engine import Engine

        engine_factory = Engine

    stop_event = stop_event or threading.Event()
    engine = engine_factory()

    def _request_stop(_signum, _frame):
        stop_event.set()

    previous_handlers: list[tuple[int, Any]] = []
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            previous_handlers.append((sig, signal.getsignal(sig)))
            signal.signal(sig, _request_stop)
        except (AttributeError, ValueError):
            continue

    try:
        engine.start()
        while not stop_event.is_set():
            _wait_for_headless_activity(stop_event, timeout_s=0.5)
        return 0
    finally:
        engine.stop()
        for sig, previous in previous_handlers:
            try:
                signal.signal(sig, previous)
            except (AttributeError, ValueError):
                pass


def _wait_for_headless_activity(
    stop_event: threading.Event,
    *,
    timeout_s: float,
) -> None:
    """Keep the process responsive while the headless engine is running.

    On macOS, the mouse hook installs a CGEventTap onto the current CFRunLoop.
    The Qt app naturally pumps that run loop, but the CLI path does not, so the
    tap would otherwise remain idle even when Accessibility permission is
    granted.
    """
    remaining = max(float(timeout_s), 0.0)
    slice_s = 0.1
    while remaining > 0 and not stop_event.is_set():
        step = min(slice_s, remaining)
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, step, False)
        remaining -= step


def load_config_and_start(
    path: str,
    *,
    filetype: str | None = None,
) -> int:
    cfg = _read_config_json(path, ft=filetype)
    cfg = assemble_full_config(cfg)
    save_config(cfg)
    return start_background_service()


def _service_program_arguments() -> list[str]:
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return [exe, "run"]
    return [exe, os.path.abspath(__file__), "run"]


def _service_plist_path() -> str:
    return os.path.expanduser(os.path.join("~/Library/LaunchAgents", CLI_SERVICE_PLIST_NAME))


def _launchctl_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def start_background_service() -> int:
    plist_path = _service_plist_path()
    launch_agents_dir = os.path.dirname(plist_path)
    domain = f"gui/{os.getuid()}"

    os.makedirs(launch_agents_dir, exist_ok=True)
    if os.path.isfile(plist_path):
        _launchctl_run(["launchctl", "bootout", domain, plist_path])

    payload = {
        "Label": CLI_SERVICE_LABEL,
        "ProgramArguments": _service_program_arguments(),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
    }
    with open(plist_path, "wb") as f:
        plistlib.dump(payload, f, fmt=plistlib.FMT_XML)

    result = _launchctl_run(["launchctl", "bootstrap", domain, plist_path])
    if result.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    return 0


def stop_background_service() -> int:
    plist_path = _service_plist_path()
    domain = f"gui/{os.getuid()}"

    if os.path.isfile(plist_path):
        _launchctl_run(["launchctl", "bootout", domain, plist_path])
        try:
            os.remove(plist_path)
        except OSError:
            pass
    else:
        _launchctl_run(["launchctl", "bootout", domain, CLI_SERVICE_LABEL])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mouser command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "export",
        help="Print the current Mouser config as JSON",
    )

    load_parser = subparsers.add_parser(
        "load",
        help="Load a config and delegate startup to the background service",
    )

    load_parser.add_argument(
        "config",
        help="Path to a Mouser config JSON file, or '-' to read from stdin",
    )
    load_parser.add_argument(
        "-t",
        "--filetype",
        choices=["json", "yaml"],
        help="Override config file type detection",
    )

    subparsers.add_parser(
        "start",
        help="Start Mouser headlessly in the background",
    )

    subparsers.add_parser(
        "stop",
        help="Stop the background Mouser headless service",
    )

    subparsers.add_parser(
        "run",
        help="Run the headless Mouser engine in the foreground (for testing and debugging)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "darwin":
        raise NotImplementedError("stop is currently only supported on macOS")

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            return export_config()
        setup_logging()
        if args.command == "load":
            return load_config_and_start(args.config, filetype=args.filetype)
        if args.command == "start":
            return start_background_service()
        if args.command == "stop":
            return stop_background_service()
        if args.command == "run":
            return run_headless_instance()
        parser.error(f"Unknown command: {args.command}")
    except (ConfigValidationError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        print(f"Error: {_format_cli_error(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:
        yaml_error = getattr(yaml, "YAMLError", None)
        if yaml_error and isinstance(exc, yaml_error):
            print(f"Error: {_format_cli_error(exc)}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
