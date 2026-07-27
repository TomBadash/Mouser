"""`load_private_dll` exists so no two modules share a ctypes function object.

`ctypes.windll.user32.CallNextHookEx` is one cached object process-wide, so
`argtypes` assigned by one module rewrites the prototype every other module
calls through.  These tests run anywhere: `ctypes.WinDLL` is stubbed out, since
the invariant under test is object identity, not any Win32 behaviour.
"""

import ctypes
import unittest
from unittest.mock import patch

from core import key_capture
from core.win_ctypes import load_private_dll


class FakeWinDLL:
    """Stands in for a loaded library; each instance is its own object."""

    def __init__(self, name):
        self.name = name


class LoadPrivateDllTests(unittest.TestCase):
    def test_every_call_returns_a_separate_handle(self):
        with patch.object(ctypes, "WinDLL", FakeWinDLL, create=True):
            first = load_private_dll("user32")
            second = load_private_dll("user32")
        self.assertIsNot(first, second)
        self.assertEqual(first.name, "user32")

    def test_off_windows_it_fails_as_an_import_error(self):
        # Callers bind their handles at module scope, so importing a
        # Windows-only module on another platform must keep failing the way
        # `from ctypes import windll` did.
        with patch.object(ctypes, "WinDLL", None, create=True):
            with self.assertRaises(ImportError):
                load_private_dll("user32")


class KeyCaptureUsesItsOwnHandlesTests(unittest.TestCase):
    def setUp(self):
        self._saved = (key_capture._USER32, key_capture._KERNEL32)
        key_capture._USER32 = None
        key_capture._KERNEL32 = None

    def tearDown(self):
        key_capture._USER32, key_capture._KERNEL32 = self._saved

    def test_user32_handle_is_loaded_once_and_reused(self):
        with patch.object(
            key_capture, "load_private_dll", side_effect=FakeWinDLL
        ) as loader:
            first = key_capture._user32()
            second = key_capture._user32()
        self.assertIs(first, second)
        loader.assert_called_once_with("user32")

    def test_kernel32_handle_is_distinct_from_the_user32_one(self):
        with patch.object(key_capture, "load_private_dll", side_effect=FakeWinDLL):
            user32 = key_capture._user32()
            kernel32 = key_capture._kernel32()
        self.assertIsNot(user32, kernel32)
        self.assertEqual(kernel32.name, "kernel32")

    def test_the_recorder_never_touches_the_shared_windll_cache(self):
        # The regression: `ctypes.windll.user32` here would be the very object
        # `core/mouse_hook_windows.py` calls `CallNextHookEx` on.
        with patch.object(key_capture, "load_private_dll", side_effect=FakeWinDLL):
            with patch.object(ctypes, "windll", None, create=True):
                self.assertIsInstance(key_capture._user32(), FakeWinDLL)
                self.assertIsInstance(key_capture._kernel32(), FakeWinDLL)


if __name__ == "__main__":
    unittest.main()
