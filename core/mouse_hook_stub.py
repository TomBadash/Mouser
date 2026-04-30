"""
Unsupported-platform mouse hook stub.
"""

import sys

from core.mouse_hook_base import BaseMouseHook


class MouseHook(BaseMouseHook):
    """Stub for unsupported platforms."""

    def __init__(self):
        super().__init__()
        print(f"[MouseHook] Platform '{sys.platform}' not supported")

    def start(self):
        return False

    def stop(self):
        return None


__all__ = ["MouseHook"]
