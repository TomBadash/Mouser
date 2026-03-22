"""
macOS accessibility helpers.

Uses direct CoreFoundation/ApplicationServices calls so the trust check works
both in source mode and in packaged builds without depending on PyObjC import
surfaces for these symbols.
"""

from __future__ import annotations

import ctypes
import sys

_APP_SERVICES_PATH = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_CORE_FOUNDATION_PATH = (
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)

_FRAMEWORKS = None


def is_supported() -> bool:
    return sys.platform == "darwin"


def _load_frameworks():
    global _FRAMEWORKS

    if _FRAMEWORKS is not None:
        return _FRAMEWORKS

    if not is_supported():
        _FRAMEWORKS = False
        return _FRAMEWORKS

    try:
        app_services = ctypes.CDLL(_APP_SERVICES_PATH)
        core_foundation = ctypes.CDLL(_CORE_FOUNDATION_PATH)

        app_services.AXIsProcessTrusted.argtypes = []
        app_services.AXIsProcessTrusted.restype = ctypes.c_bool

        if hasattr(app_services, "AXIsProcessTrustedWithOptions"):
            app_services.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
            app_services.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool

        core_foundation.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        core_foundation.CFDictionaryCreate.restype = ctypes.c_void_p
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        core_foundation.CFRelease.restype = None

        _FRAMEWORKS = (app_services, core_foundation)
    except Exception:
        _FRAMEWORKS = False

    return _FRAMEWORKS


def _create_prompt_options(app_services, core_foundation):
    prompt_key = ctypes.c_void_p.in_dll(
        app_services, "kAXTrustedCheckOptionPrompt"
    ).value
    true_value = ctypes.c_void_p.in_dll(core_foundation, "kCFBooleanTrue").value
    keys = (ctypes.c_void_p * 1)(prompt_key)
    values = (ctypes.c_void_p * 1)(true_value)
    return core_foundation.CFDictionaryCreate(None, keys, values, 1, None, None)


def is_process_trusted(prompt: bool = False) -> bool:
    frameworks = _load_frameworks()
    if not frameworks:
        return True

    app_services, core_foundation = frameworks

    try:
        if prompt and hasattr(app_services, "AXIsProcessTrustedWithOptions"):
            options = _create_prompt_options(app_services, core_foundation)
            if options:
                try:
                    return bool(app_services.AXIsProcessTrustedWithOptions(options))
                finally:
                    core_foundation.CFRelease(options)

        return bool(app_services.AXIsProcessTrusted())
    except Exception:
        return True
