"""
Unsupported-platform device hook stub.
"""

import sys

from core.device_hook_base import BaseDeviceHook


class DeviceHook(BaseDeviceHook):
    """Stub for unsupported platforms."""

    def __init__(self):
        super().__init__()
        print(f"[DeviceHook] Platform '{sys.platform}' not supported")

    def start(self):
        return False

    def stop(self):
        return None


__all__ = ["DeviceHook"]
