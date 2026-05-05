"""
Schema-first config validation helpers shared by config import paths.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from core.config import (
    DEFAULT_CONFIG,
    PROFILE_BUTTON_NAMES,
    _merge_defaults,
    _migrate,
    _validate_types,
)
from core.device_layouts import get_manual_layout_choices
from core.logi_devices import DEFAULT_DPI_MAX, DEFAULT_DPI_MIN

_VALID_BUTTON_KEYS = set(PROFILE_BUTTON_NAMES)
_VALID_LAYOUT_OVERRIDE_KEYS = {
    choice["key"] for choice in get_manual_layout_choices() if choice["key"]
}


class ConfigValidationError(ValueError):
    """Human-readable config validation error."""


def _schema_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "active_profile", "profiles", "settings"],
    "properties": {
        "version": {"type": "integer", "minimum": 1},
        "active_profile": {"type": "string", "minLength": 1},
        "profiles": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "apps", "mappings"],
                "properties": {
                    "label": {"type": "string", "minLength": 1},
                    "apps": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "mappings": {
                        "type": "object",
                        "additionalProperties": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "settings": {
            "type": "object",
            "additionalProperties": False,
            "required": list(DEFAULT_CONFIG["settings"].keys()),
            "properties": {
                "start_minimized": {"type": "boolean"},
                "start_at_login": {"type": "boolean"},
                "hscroll_threshold": {"type": "number", "minimum": 0},
                "hscroll_cooldown_ms": {"type": "number", "minimum": 0},
                "invert_hscroll": {"type": "boolean"},
                "invert_vscroll": {"type": "boolean"},
                "dpi": {
                    "type": "integer",
                    "minimum": DEFAULT_DPI_MIN,
                    "maximum": DEFAULT_DPI_MAX,
                },
                "smart_shift_mode": {
                    "type": "string",
                    "enum": ["ratchet", "freespin"],
                },
                "smart_shift_enabled": {"type": "boolean"},
                "smart_shift_threshold": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
                "gesture_threshold": {"type": "integer", "minimum": 5},
                "gesture_deadzone": {"type": "integer", "minimum": 0},
                "gesture_timeout_ms": {"type": "integer", "minimum": 250},
                "gesture_cooldown_ms": {"type": "integer", "minimum": 0},
                "appearance_mode": {
                    "type": "string",
                    "enum": ["system", "light", "dark"],
                },
                "debug_mode": {"type": "boolean"},
                "device_layout_overrides": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "minLength": 1},
                },
                "language": {"type": "string", "minLength": 1},
                "ignore_trackpad": {"type": "boolean"},
                "dpi_presets": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "integer",
                        "minimum": DEFAULT_DPI_MIN,
                        "maximum": DEFAULT_DPI_MAX,
                    },
                },
            },
        },
    },
}


def _display_path(path: str) -> str:
    return path or "config"


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(CONFIG_SCHEMA)


def _error_path(error) -> str:
    parts: list[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{part}]"
            else:
                parts.append(f"[{part}]")
        else:
            parts.append(str(part))
    return ".".join(parts)


def _format_schema_error(error) -> str:
    path = _display_path(_error_path(error))
    validator = error.validator

    if validator == "additionalProperties":
        extras = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        if extras:
            return f"Unknown key at {_schema_path(_error_path(error), extras[0])}"

    if validator == "required":
        missing = error.message.split("'")[1]
        return f"{path} is missing required key '{missing}'"

    if validator == "type":
        return f"{path} must be a {error.validator_value}"

    if validator == "enum":
        allowed = ", ".join(repr(item) for item in error.validator_value)
        return f"{path} must be one of: {allowed}"

    if validator == "minLength":
        if error.validator_value == 1:
            return f"{path} must not be empty"
        return f"{path} must be at least {error.validator_value} characters"

    if validator == "minimum":
        return f"{path} must be >= {error.validator_value}"

    if validator == "maximum":
        return f"{path} must be <= {error.validator_value}"

    if validator == "minItems":
        return (
            f"{path} must contain at least {error.validator_value} item"
            f"{'' if error.validator_value == 1 else 's'}"
        )

    if validator == "minProperties":
        return (
            f"{path} must contain at least {error.validator_value} entr"
            f"{'y' if error.validator_value == 1 else 'ies'}"
        )

    return error.message


@lru_cache(maxsize=1)
def _action_metadata() -> tuple[set[str], set[str]]:
    from core.key_simulator import ACTIONS, valid_custom_key_names

    return set(ACTIONS), set(valid_custom_key_names())


def _validate_custom_action(action_id: str, path: str) -> None:
    _, valid_custom_keys = _action_metadata()
    parts = [part.strip().lower() for part in action_id[7:].split("+")]
    if not parts or any(not part for part in parts):
        raise ConfigValidationError(
            f"{path} must contain at least one valid key in custom shortcut"
        )
    invalid = [part for part in parts if part not in valid_custom_keys]
    if invalid:
        raise ConfigValidationError(
            f"{path} contains unknown custom key(s): {', '.join(sorted(set(invalid)))}"
        )


def _validate_action_id(action_id: str, path: str) -> None:
    valid_action_ids, _ = _action_metadata()
    if action_id.startswith("custom:"):
        _validate_custom_action(action_id, path)
        return
    if action_id not in valid_action_ids:
        raise ConfigValidationError(f"{path} has unknown action '{action_id}'. Did you mean 'custom:{action_id}'?")


def validate_config(cfg: dict[str, Any]) -> None:
    errors = sorted(_schema_validator().iter_errors(cfg), key=lambda e: (list(e.absolute_path), e.validator))
    if errors:
        raise ConfigValidationError(_format_schema_error(errors[0]))

    active_profile = cfg["active_profile"]
    profiles = cfg["profiles"]
    if "default" not in profiles:
        raise ConfigValidationError("Config must define a `default` profile")
    if active_profile not in profiles:
        raise ConfigValidationError(
            f"Active profile '{active_profile}' not found in profiles"
        )

    for profile_name, profile in profiles.items():
        mappings = profile["mappings"]
        for button_key, action_id in mappings.items():
            if button_key not in _VALID_BUTTON_KEYS:
                raise ConfigValidationError(
                    f"profiles.{profile_name}.mappings.{button_key} is not a valid button mapping"
                )
            _validate_action_id(
                action_id,
                f"profiles.{profile_name}.mappings.{button_key}",
            )

    overrides = cfg["settings"]["device_layout_overrides"]
    for device_key, layout_key in overrides.items():
        if layout_key not in _VALID_LAYOUT_OVERRIDE_KEYS:
            raise ConfigValidationError(
                f"settings.device_layout_overrides.{device_key} has unknown layout '{layout_key}'"
            )


def normalize_config(raw_cfg: Any) -> dict[str, Any]:
    """Return a migrated, default-filled, strictly validated config dict."""
    if not isinstance(raw_cfg, dict):
        raise ConfigValidationError("Config document must be an object")
    cfg = json.loads(json.dumps(raw_cfg))
    profiles = cfg.get("profiles")
    if isinstance(profiles, dict) and "default" not in profiles:
        raise ConfigValidationError("Config must define a `default` profile")
    if "version" not in cfg:
        cfg["version"] = DEFAULT_CONFIG["version"]
    cfg = _migrate(cfg)
    cfg = _merge_defaults(cfg, DEFAULT_CONFIG)
    validate_config(cfg)
    cfg = _validate_types(cfg, DEFAULT_CONFIG)
    return cfg


def assemble_full_config(config: dict[str, Any]) -> dict[str, Any]:
    active_profile = config.get("active_profile")
    profiles = config.get("profiles")
    if active_profile is None or not isinstance(profiles, dict):
        raise ConfigValidationError("Config must specify an `active_profile`")
    if active_profile not in profiles:
        raise ConfigValidationError(
            f"Active profile '{active_profile}' not found in profiles"
        )
    if "default" not in profiles:
        raise ConfigValidationError("Config must define a `default` profile")
    if profiles["default"].get("apps") != []:
        raise ConfigValidationError("Default profile must have an empty `apps` list")

    default_mappings = profiles["default"]["mappings"]
    for profile_name, profile in profiles.items():
        if profile_name == "default":
            continue
        for mapping in default_mappings:
            if mapping not in profile["mappings"]:
                profile["mappings"][mapping] = default_mappings[mapping]
    return config
