"""Source guards for the Windows hook, which cannot be imported off Windows.

Both crash reports in issues #252 and #253 trace to one line: ``dwExtraInfo``
is a ULONG_PTR *value*, but the struct declared it as a pointer and the debug
path read ``.contents``, dereferencing whatever number the sender attached.
Any event carrying a non-zero value killed the process outright -- silently,
with nothing in the log -- whenever debug mode was on.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_HOOK = (ROOT / "core" / "mouse_hook_windows.py").read_text(encoding="utf-8")
KEY_CAPTURE = (ROOT / "core" / "key_capture.py").read_text(encoding="utf-8")


class ExtraInfoIsAValueNotAPointerTests(unittest.TestCase):
    def test_mouse_hook_struct_declares_extra_info_as_a_value(self):
        self.assertIn('("dwExtraInfo", wintypes.WPARAM)', WINDOWS_HOOK)

    def test_key_capture_struct_declares_extra_info_as_a_value(self):
        self.assertIn('("dwExtraInfo", wintypes.WPARAM)', KEY_CAPTURE)

    def test_no_hook_dereferences_extra_info(self):
        for name, source in (
            ("mouse_hook_windows", WINDOWS_HOOK),
            ("key_capture", KEY_CAPTURE),
        ):
            with self.subTest(module=name):
                self.assertNotIn("dwExtraInfo.contents", source)


class HookLibraryHandlesArePrivateTests(unittest.TestCase):
    """`ctypes.windll` handed both hooks the same `CallNextHookEx` object.

    The loader caches one WinDLL per library and one function object per name,
    so the mouse hook's ``argtypes`` (a ``MSLLHOOKSTRUCT`` pointer) and the
    recorder's (a ``KBDLLHOOKSTRUCT`` pointer) landed on the same object.
    Arming the recorder therefore broke the mouse hook: every event raised
    ``ctypes.ArgumentError``, the hook procedure blew past Windows' low-level
    hook timeout, and the cursor froze while the Custom Shortcut dialog was
    open -- keyboard still live, mouse dead, app only killable from outside.
    """

    def test_neither_hook_binds_calls_through_the_shared_windll_cache(self):
        for name, source in (
            ("mouse_hook_windows", WINDOWS_HOOK),
            ("key_capture", KEY_CAPTURE),
        ):
            with self.subTest(module=name):
                # The trailing dot is the binding itself, so prose naming the
                # cache to explain the hazard does not trip this.
                for call in ("windll.user32.", "windll.kernel32."):
                    self.assertNotIn(call, source)

    def test_both_hooks_load_their_own_handles(self):
        for name, source in (
            ("mouse_hook_windows", WINDOWS_HOOK),
            ("key_capture", KEY_CAPTURE),
        ):
            with self.subTest(module=name):
                self.assertIn("load_private_dll", source)

    def test_hook_procedure_recovery_cannot_raise_out_of_the_callback(self):
        # An exception escaping a ctypes callback costs a printed traceback per
        # event -- the freeze mechanism itself, whatever first went wrong.
        self.assertIn(
            "            try:\n"
            "                return CallNextHookEx(self._hook, nCode, wParam, lParam)\n"
            "            except Exception:\n",
            WINDOWS_HOOK,
        )


class DebugLoggingIsRateLimitedTests(unittest.TestCase):
    def test_wheel_bursts_are_coalesced(self):
        # A hi-res wheel emits ~15 messages per detent; one debug line each
        # costs a Qt signal plus a QML list rebuild.
        self.assertIn("_DEBUG_BURST_MESSAGES", WINDOWS_HOOK)
        self.assertIn("def _debug_event_allowed", WINDOWS_HOOK)

    def test_debug_path_skips_mouse_moves_before_formatting(self):
        self.assertIn(
            "if self.debug_mode and self._debug_callback and wParam != WM_MOUSEMOVE:",
            WINDOWS_HOOK,
        )


if __name__ == "__main__":
    unittest.main()
