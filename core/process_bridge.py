"""Authenticated loopback RPC between Mouser's daemon and settings UI."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
import secrets
import socket
import threading
import time
from types import SimpleNamespace

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT_ENV = "MOUSER_DAEMON_PORT"
BRIDGE_TOKEN_ENV = "MOUSER_DAEMON_TOKEN"
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def _load_config():
    from core.config import load_config

    return load_config()


class BridgeError(RuntimeError):
    pass


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _read_message(connection):
    chunks = bytearray()
    while True:
        block = connection.recv(65536)
        if not block:
            break
        chunks.extend(block)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise BridgeError("bridge message exceeds size limit")
        if b"\n" in block:
            break
    line, _, _ = bytes(chunks).partition(b"\n")
    if not line:
        raise BridgeError("empty bridge message")
    return json.loads(line.decode("utf-8"))


def _write_message(connection, payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(encoded)


class DaemonBridgeServer:
    _ALLOWED_METHODS = {
        "dump_device_info",
        "play_haptic_waveform",
        "reload_mappings",
        "ring_hover",
        "ring_toggle_dismiss",
        "ring_toggle_select",
        "set_debug_enabled",
        "set_debug_events_enabled",
        "set_dpi",
        "set_enabled",
        "set_force_sensitivity",
        "set_frontend_visible",
        "set_haptic_level",
        "set_smart_shift",
        "set_ui_passthrough",
        "start",
        "stop",
    }

    def __init__(
        self,
        engine,
        *,
        on_shutdown=None,
        on_config_sync=None,
        state_provider=None,
    ):
        self._engine = engine
        self._on_shutdown = on_shutdown
        self._on_config_sync = on_config_sync
        self._state_provider = state_provider
        self._token = secrets.token_urlsafe(32)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((BRIDGE_HOST, 0))
            self._socket.listen(8)
            self._socket.settimeout(0.5)
        except BaseException:
            self._socket.close()
            raise
        self._port = int(self._socket.getsockname()[1])
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name="MouserDaemonBridge",
        )

    @property
    def port(self):
        return self._port

    @property
    def token(self):
        return self._token

    def child_environment(self, base=None):
        environment = dict(os.environ if base is None else base)
        environment[BRIDGE_PORT_ENV] = str(self._port)
        environment[BRIDGE_TOKEN_ENV] = self._token
        return environment

    def start(self):
        self._thread.start()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._socket.close()
        except OSError:
            pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _serve(self):
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(connection,),
                daemon=True,
                name="MouserDaemonRequest",
            ).start()

    def _handle_connection(self, connection):
        with connection:
            try:
                request = _read_message(connection)
                if not secrets.compare_digest(str(request.get("token", "")), self._token):
                    raise BridgeError("authentication failed")
                result = self._dispatch(
                    str(request.get("method", "")),
                    list(request.get("args", [])),
                    dict(request.get("kwargs", {})),
                )
                response = {"ok": True, "result": _json_safe(result)}
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            _write_message(connection, response)

    def _dispatch(self, method, args, kwargs):
        if method == "get_state":
            return self._state()
        if method == "sync_config":
            config = _load_config()
            self._engine.cfg = config
            if self._on_config_sync is not None:
                self._on_config_sync(config)
            return True
        if method == "shutdown_daemon":
            if self._on_shutdown is not None:
                self._on_shutdown()
            return True
        if method not in self._ALLOWED_METHODS:
            raise BridgeError(f"method is not allowed: {method}")
        target = getattr(self._engine, method, None)
        if target is None or not callable(target):
            raise BridgeError(f"engine method is unavailable: {method}")
        return target(*args, **kwargs)

    def _state(self):
        settings = getattr(self._engine, "cfg", {}).get("settings", {})
        force_range = getattr(self._engine, "force_sensing_range", None)
        state = {
            "active_profile": getattr(self._engine, "current_profile", None)
                or getattr(self._engine, "_current_profile", "default"),
            "connected_device": _json_safe(
                getattr(self._engine, "connected_device", None)
            ),
            "device_connected": bool(
                getattr(self._engine, "device_connected", False)
            ),
            "dpi": settings.get("dpi"),
            "enabled": bool(getattr(self._engine, "enabled", True)),
            "force_sensing_range": _json_safe(force_range),
            "force_sensing_supported": bool(
                getattr(self._engine, "force_sensing_supported", False)
            ),
            "haptic_supported": bool(
                getattr(self._engine, "haptic_supported", False)
            ),
            "hid_features_ready": bool(
                getattr(self._engine, "hid_features_ready", False)
            ),
            "smart_shift": {
                "mode": settings.get("smart_shift_mode", "ratchet"),
                "enabled": bool(settings.get("smart_shift_enabled", False)),
                "threshold": int(settings.get("smart_shift_threshold", 25)),
            },
            "smart_shift_supported": bool(
                getattr(self._engine, "smart_shift_supported", False)
            ),
        }
        if self._state_provider is not None:
            state.update(_json_safe(self._state_provider()) or {})
        return state


class RemoteEngine:
    def __init__(self, port, token, *, poll_interval=0.75, timeout=3.0):
        self._port = int(port)
        self._token = str(token)
        self._timeout = float(timeout)
        self._poll_interval = float(poll_interval)
        self._state = {}
        self._state_lock = threading.Lock()
        self._callbacks = {}
        self._closed = threading.Event()
        self._last_error = ""
        self._refresh_state(notify=False)
        self._poll_thread = threading.Thread(
            target=self._poll,
            daemon=True,
            name="MouserSettingsStatePoll",
        )
        self._poll_thread.start()

    @classmethod
    def from_environment(cls):
        port = os.environ.get(BRIDGE_PORT_ENV, "")
        token = os.environ.get(BRIDGE_TOKEN_ENV, "")
        if not port or not token:
            raise BridgeError("settings process was not launched by the Mouser daemon")
        return cls(port, token)

    def close(self):
        self._closed.set()
        if self._poll_thread is not threading.current_thread():
            self._poll_thread.join(timeout=2)

    def _request(self, method, *args, **kwargs):
        request = {
            "token": self._token,
            "method": method,
            "args": list(args),
            "kwargs": kwargs,
        }
        try:
            with socket.create_connection(
                (BRIDGE_HOST, self._port), timeout=self._timeout
            ) as connection:
                connection.settimeout(self._timeout)
                _write_message(connection, request)
                response = _read_message(connection)
        except OSError as exc:
            raise BridgeError(f"daemon is unavailable: {exc}") from exc
        if not response.get("ok"):
            raise BridgeError(str(response.get("error", "daemon request failed")))
        return response.get("result")

    def _poll(self):
        while not self._closed.wait(self._poll_interval):
            try:
                self._refresh_state(notify=True)
                self._last_error = ""
            except BridgeError as exc:
                message = str(exc)
                if message != self._last_error:
                    self._last_error = message
                    self._emit("status", message)

    def _refresh_state(self, *, notify):
        state = self._request("get_state") or {}
        with self._state_lock:
            previous = self._state
            self._state = state
        if not notify or not previous:
            return
        if state.get("active_profile") != previous.get("active_profile"):
            self._emit("profile", state.get("active_profile", "default"))
        if state.get("device_connected") != previous.get("device_connected"):
            self._emit("connection", bool(state.get("device_connected")))
        if state.get("dpi") != previous.get("dpi") and state.get("dpi") is not None:
            self._emit("dpi", int(state["dpi"]))
        if state.get("smart_shift") != previous.get("smart_shift"):
            self._emit("smart_shift", state.get("smart_shift", {}))
        if state.get("battery_level") != previous.get("battery_level"):
            level = state.get("battery_level")
            if level is not None and int(level) >= 0:
                self._emit("battery", int(level))
        debug_lines = list(state.get("debug_lines") or [])
        previous_lines = list(previous.get("debug_lines") or [])
        if debug_lines != previous_lines:
            if previous_lines and debug_lines[:len(previous_lines)] == previous_lines:
                added_lines = debug_lines[len(previous_lines):]
            else:
                added_lines = debug_lines[-1:]
            for line in added_lines:
                self._emit("debug", str(line))

    def _snapshot(self):
        with self._state_lock:
            return dict(self._state)

    def _emit(self, name, *args):
        callback = self._callbacks.get(name)
        if callback is not None:
            callback(*args)

    @property
    def cfg(self):
        return _load_config()

    @cfg.setter
    def cfg(self, _value):
        self._request("sync_config")

    @property
    def connected_device(self):
        value = self._snapshot().get("connected_device")
        return _namespace(value) if value else None

    @property
    def device_connected(self):
        return bool(self._snapshot().get("device_connected", False))

    @property
    def enabled(self):
        return bool(self._snapshot().get("enabled", True))

    @property
    def force_sensing_range(self):
        value = self._snapshot().get("force_sensing_range")
        return tuple(value) if isinstance(value, list) else value

    @property
    def force_sensing_supported(self):
        return bool(self._snapshot().get("force_sensing_supported", False))

    @property
    def haptic_supported(self):
        return bool(self._snapshot().get("haptic_supported", False))

    @property
    def hid_features_ready(self):
        return bool(self._snapshot().get("hid_features_ready", False))

    @property
    def smart_shift_supported(self):
        return bool(self._snapshot().get("smart_shift_supported", False))

    def _set_callback(self, name, callback):
        self._callbacks[name] = callback

    def set_profile_change_callback(self, callback):
        self._set_callback("profile", callback)

    def set_connection_change_callback(self, callback):
        self._set_callback("connection", callback)

    def set_dpi_read_callback(self, callback):
        self._set_callback("dpi", callback)

    def set_smart_shift_read_callback(self, callback):
        self._set_callback("smart_shift", callback)

    def set_status_callback(self, callback):
        self._set_callback("status", callback)

    def set_battery_callback(self, callback):
        self._set_callback("battery", callback)

    def set_debug_callback(self, callback):
        self._set_callback("debug", callback)

    def set_gesture_event_callback(self, callback):
        self._set_callback("gesture", callback)

    def set_ring_show_callback(self, callback):
        self._set_callback("ring_show", callback)

    def set_ring_hide_callback(self, callback):
        self._set_callback("ring_hide", callback)

    def set_ring_sector_callback(self, callback):
        self._set_callback("ring_sector", callback)

    def set_ring_move_callback(self, callback):
        self._set_callback("ring_move", callback)

    def shutdown_daemon(self):
        return self._request("shutdown_daemon")

    def __getattr__(self, name):
        if name in DaemonBridgeServer._ALLOWED_METHODS:
            return lambda *args, **kwargs: self._request(name, *args, **kwargs)
        raise AttributeError(name)


def wait_for_bridge(port, token, timeout=5.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            remote = RemoteEngine(port, token, poll_interval=60)
            remote.close()
            return True
        except BridgeError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
    return False
