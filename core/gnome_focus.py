"""
GNOME Shell Focus Watcher extension helpers.

The bundled ``focus-watcher@mouser.app`` GNOME Shell extension (shipped in
``packaging/linux/gnome-focus-watcher/``) lets Mouser learn the focused window
on GNOME/Wayland — something the platform window APIs cannot see. This module
collects the shared, testable bits used by both the configuration UI (backend)
and the foreground-app detector (``core/app_detector.py``):

* desktop / shell-version gating (the extension only targets GNOME 45+),
* locating and installing the extension into the user's GNOME Shell dir,
* enabling it, and
* querying the focused window (and listening for focus changes) over D-Bus,
  via **dbus-fast** (no external ``gdbus`` subprocess).

Every function is safe to call on any platform; the active ones no-op (or
return ``False``/``None``) when not running on a supported GNOME desktop.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping

GNOME_EXTENSION_UUID = "focus-watcher@mouser.app"
GNOME_EXTENSION_DIR_NAME = GNOME_EXTENSION_UUID

# Name of the directory inside the linux assets root that holds the bundled
# extension sources (packaging/linux/gnome-focus-watcher/). Distinct from the
# *install* directory name (the UUID) that GNOME Shell expects.
GNOME_EXTENSION_SOURCE_DIR_NAME = "gnome-focus-watcher"

# The extension's metadata.json lists shell-version 45–50. We gate on the lower
# bound (45) being the first supported major; the extension simply cannot load
# on older shells. The upper bound is forward-looking and is not a hard gate.
MIN_SHELL_VERSION = 45

# Bundled extension assets relative to a resolved "linux assets root".
EXTENSION_FILES = ("extension.js", "metadata.json")

DBUS_SERVICE = "org.gnome.Shell"
DBUS_PATH = "/github/mouser"
DBUS_INTERFACE = "org.mouser.FocusWatcher"
DBUS_METHOD = "GetFocusApp"
DBUS_SIGNAL = "FocusChanged"

# Introspection data matching the interface exported by the bundled extension
# (packaging/linux/gnome-focus-watcher/extension.js). Used by dbus-fast's
# high-level proxy client: it drives both the GetFocusApp method call and the
# FocusChanged signal subscription.
WATCHER_INTROSPECTION = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.mouser.FocusWatcher">
    <method name="GetFocusApp">
      <arg type="s" direction="out" name="window" />
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="window" />
    </signal>
  </interface>
</node>
"""


def is_gnome_desktop(environ: Mapping[str, str] | None = None) -> bool:
    """True when ``XDG_CURRENT_DESKTOP`` names a GNOME session."""
    env = environ if environ is not None else os.environ
    raw = (env.get("XDG_CURRENT_DESKTOP") or "").replace(";", ":")
    names = [part.strip().lower() for part in raw.split(":") if part.strip()]
    return any("gnome" in name for name in names)


def gnome_shell_version(environ: Mapping[str, str] | None = None) -> int | None:
    """Return the GNOME Shell major version, or None if it cannot be detected."""
    env = environ if environ is not None else os.environ
    if not is_gnome_desktop(env):
        return None
    shell = shutil.which("gnome-shell")
    if not shell:
        return None
    try:
        result = subprocess.run(
            [shell, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr or "").strip()
    # e.g. "GNOME Shell 45.4" -> 45
    parts = text.split()
    if not parts:
        return None
    version_str = parts[-1]
    major = version_str.split(".")[0]
    try:
        return int(major)
    except ValueError:
        return None


def gnome_focus_watcher_supported(environ: Mapping[str, str] | None = None) -> bool:
    """True when the Mouser focus-watcher extension can work here:
    a GNOME desktop with a supported (>= 45) shell version."""
    version = gnome_shell_version(environ)
    if version is None:
        return False
    return version >= MIN_SHELL_VERSION


def _data_home(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    xdg = (env.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return os.path.expanduser(xdg)
    return os.path.expanduser(os.path.join("~", ".local", "share"))


def extension_install_dir(environ: Mapping[str, str] | None = None) -> str:
    """User GNOME Shell extensions directory for this extension's UUID."""
    return os.path.join(
        _data_home(environ),
        "gnome-shell",
        "extensions",
        GNOME_EXTENSION_DIR_NAME,
    )


def extension_installed(environ: Mapping[str, str] | None = None) -> bool:
    """True when both extension.js and metadata.json exist in the user dir."""
    install_dir = extension_install_dir(environ)
    return all(
        os.path.isfile(os.path.join(install_dir, name))
        for name in EXTENSION_FILES
    )


def _run(args, timeout=5):
    """Run a CLI command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except (OSError, subprocess.TimeoutExpired):
        return -1, "", ""


def extension_active() -> bool:
    """True when the extension has actually loaded and owns its D-Bus service.

    This is the meaningful "enabled and working" signal: a freshly copied
    extension won't be active until the shell restarts (log out/in on Wayland,
    ``Alt+F2 r`` on X11), regardless of what installation state says.
    """
    payload = get_focus_app_payload()
    return payload is not None


async def _connect_watcher_bus():
    """Open a dbus-fast session-bus connection to the Mouser extension.

    Returns a connected ``dbus_fast.aio.MessageBus``, or raises on failure
    (dbus-fast missing, session bus unreachable, etc). The caller owns the
    returned bus and must disconnect it when done.
    """
    from dbus_fast.aio import MessageBus
    from dbus_fast import BusType

    return await MessageBus(bus_type=BusType.SESSION).connect()


async def _get_focus_app_payload_from_bus(bus) -> dict | None:
    """Call ``GetFocusApp`` on an already-connected watcher bus.

    Returns the parsed payload dict, or ``None`` when the method fails or the
    reply is not a JSON object.
    """
    from dbus_fast import Message, MessageType

    reply = await bus.call(
        Message(
            destination=DBUS_SERVICE,
            path=DBUS_PATH,
            interface=DBUS_INTERFACE,
            member=DBUS_METHOD,
        )
    )
    if reply.message_type != MessageType.METHOD_RETURN or not reply.body:
        return None
    payload = reply.body[0]
    if not isinstance(payload, str):
        return None
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def get_focus_app_payload(environ: Mapping[str, str] | None = None) -> dict | None:
    """Query the extension's D-Bus ``GetFocusApp`` method and return the parsed
    payload dict (with keys like ``executable``, ``wm_class``, ``title``), or
    ``None`` if the service/method is unavailable.

    Uses dbus-fast (not gdbus) under the hood. Runs a short-lived session bus
    connection per call, which is fine for occasional use (extension status
    refresh, polling fallback).
    """
    env = environ if environ is not None else os.environ
    if sys.platform != "linux":
        return None
    if not is_gnome_desktop(env):
        return None
    try:
        from dbus_fast.aio import MessageBus
        from dbus_fast import BusType
    except ImportError:
        return None

    async def _query():
        try:
            bus = await _connect_watcher_bus()
        except Exception:
            return None
        try:
            return await _get_focus_app_payload_from_bus(bus)
        except Exception:
            return None
        finally:
            try:
                bus.disconnect()
            except Exception:
                pass

    try:
        return asyncio.run(_query())
    except Exception:
        return None


def focus_app_executable(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the foreground app's executable path from the extension, or None."""
    payload = get_focus_app_payload(environ)
    if not payload:
        return None
    exe = payload.get("executable") or ""
    return str(exe) if exe else None


def _linux_assets_root() -> str:
    """Locate the bundled ``linux/`` asset directory (frozen or source)."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            candidate = os.path.join(bundle_root, "linux")
            if os.path.isdir(candidate):
                return candidate
        runtime = os.path.dirname(os.path.abspath(sys.executable))
        candidate = os.path.join(runtime, "linux")
        if os.path.isdir(candidate):
            return candidate
    # Source checkout: repo root / packaging/linux
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(repo_root, "packaging", "linux")
    if os.path.isdir(candidate):
        return candidate
    return ""


def resolve_extension_source_dir() -> str:
    """Return the directory holding the bundled extension assets, or ''."""
    assets_root = _linux_assets_root()
    if not assets_root:
        return ""
    candidate = os.path.join(assets_root, GNOME_EXTENSION_SOURCE_DIR_NAME)
    if os.path.isdir(candidate):
        return candidate
    return ""


def install_extension() -> bool:
    """Install (or fully reinstall/overwrite) the bundled extension into the
    user's GNOME Shell dir.

    The install is always a **complete overwrite**: any existing/older install
    is cleared first and the directory is rebuilt to mirror the bundled source
    exactly. Stale files left over from a previous version (e.g. renamed or
    removed helpers) are removed, so re-running this after a Mouser update
    installs the new version cleanly. Cloud-of-dust residue that is not part of
    the bundle never lingers.

    Returns True on success; the extension still needs a shell restart and an
    ``enable`` before it takes effect.
    """
    if sys.platform != "linux":
        return False
    src = resolve_extension_source_dir()
    if not src:
        return False
    install_dir = extension_install_dir()

    # Collect the files we will install up front so we don't wipe the install
    # dir and then discover the bundle is incomplete (which would leave the
    # user with a broken, empty install rather than their previous one).
    install_files = {
        name: os.path.join(src, name)
        for name in EXTENSION_FILES
        if os.path.isfile(os.path.join(src, name))
    }
    if len(install_files) != len(EXTENSION_FILES):
        return False

    try:
        os.makedirs(install_dir, exist_ok=True)
        # Full overwrite: remove anything currently in the install dir so the
        # result is an exact mirror of the bundled source (reinstall-safe).
        for entry in os.listdir(install_dir):
            path = os.path.join(install_dir, entry)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        for name, src_file in install_files.items():
            dest_file = os.path.join(install_dir, name)
            shutil.copyfile(src_file, dest_file)
            try:
                os.chmod(dest_file, 0o644)
            except OSError:
                pass
        return True
    except OSError:
        return False


def enable_extension() -> bool:
    """Ask GNOME Shell to enable the extension via ``gnome-extensions``.

    Usually only succeeds after a shell restart has made the extension visible.
    Returns True on success.
    """
    if sys.platform != "linux":
        return False
    tool = shutil.which("gnome-extensions")
    if not tool:
        return False
    code, _out, _err = _run(
        [tool, "enable", GNOME_EXTENSION_UUID],
        timeout=5,
    )
    return code == 0
