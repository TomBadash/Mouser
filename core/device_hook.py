"""
Platform dispatcher shim for device hook implementations.
"""

import sys
import types

from core.device_hook_types import DeviceEvent

if sys.platform == "win32":
    from core import device_hook_windows as _platform
elif sys.platform == "darwin":
    from core import device_hook_macos as _platform
elif sys.platform == "linux":
    from core import device_hook_linux as _platform
else:
    from core import device_hook_stub as _platform

DeviceHook = _platform.DeviceHook

_RESERVED = {
    "DeviceHook",
    "DeviceEvent",
    "_platform",
    "_DeviceHookModule",
    "_RESERVED",
    "__all__",
    "__class__",
    "__doc__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
    "__cached__",
    "__builtins__",
}


def _should_forward(name):
    return name not in _RESERVED


class _DeviceHookModule(types.ModuleType):
    def __getattr__(self, name):
        if name == "DeviceEvent":
            return DeviceEvent
        try:
            return getattr(_platform, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc

    def __setattr__(self, name, value):
        if _should_forward(name):
            setattr(_platform, name, value)
            return
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if _should_forward(name) and hasattr(_platform, name):
            delattr(_platform, name)
            return
        super().__delattr__(name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(dir(_platform)) | {"DeviceEvent"})


module = sys.modules[__name__]
module.__class__ = _DeviceHookModule
module.DeviceHook = DeviceHook
module.DeviceEvent = DeviceEvent
module.__all__ = ["DeviceHook", "DeviceEvent"] + list(getattr(_platform, "__all__", []))
