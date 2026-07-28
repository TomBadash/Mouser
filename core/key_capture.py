"""Keyboard-capture support for the custom-shortcut recorder.

Recording a shortcut that contains the Windows key is impossible with plain Qt
key events: Windows hands the shell the `LWIN`/`RWIN` key-up, so pressing Win
inside the capture field pops the Start menu and steals focus before a second
key can be recorded.  While the recorder is armed we therefore install a
low-level keyboard hook that swallows the Windows key and tracks its pressed
state ourselves, so the UI can fold it into the recorded combo.

Every other platform leaves its Super/Cmd key alone, so they get the no-op
guard.  The event-classification helpers stay platform-independent to keep the
swallow rules testable from any OS.
"""

from __future__ import annotations

import sys
import threading


WH_KEYBOARD_LL = 13
HC_ACTION = 0

WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

LLKHF_INJECTED = 0x00000010

VK_LWIN = 0x5B
VK_RWIN = 0x5C

_DOWN_MESSAGES = frozenset({WM_KEYDOWN, WM_SYSKEYDOWN})
_UP_MESSAGES = frozenset({WM_KEYUP, WM_SYSKEYUP})

_HOOK_START_TIMEOUT = 2.0
_HOOK_STOP_TIMEOUT = 2.0


def is_super_vk(vk) -> bool:
    """True for the left/right Windows keys."""
    return vk in (VK_LWIN, VK_RWIN)


def classify_key_event(vk, flags, message) -> tuple[bool, bool | None]:
    """Return ``(swallow, super_down)`` for one low-level keyboard event.

    ``super_down`` is ``None`` when the event says nothing about the Windows
    key.  Injected events are always passed through untouched so shortcuts the
    mouse itself fires keep working while the recorder is armed.
    """
    if flags & LLKHF_INJECTED:
        return False, None
    if not is_super_vk(vk):
        return False, None
    if message in _DOWN_MESSAGES:
        return True, True
    if message in _UP_MESSAGES:
        return True, False
    return True, None


class SuperKeyGuard:
    """No-op guard for platforms whose Super/Cmd key does not hijack input."""

    def start(self, on_super_changed=None) -> bool:
        return False

    def stop(self) -> None:
        return None

    @property
    def active(self) -> bool:
        return False

    @property
    def super_held(self) -> bool:
        return False


class WindowsSuperKeyGuard(SuperKeyGuard):
    """Swallow `LWIN`/`RWIN` while a shortcut is being recorded.

    The hook lives on its own thread with a message loop, mirroring
    `core/mouse_hook_windows.py`.  Only the Windows key is swallowed: every
    other key still reaches Qt normally, so a leaked hook can never leave the
    keyboard unusable.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._thread = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._installed = False
        self._stopping = False
        self._super_held = False
        self._on_super_changed = None

    # ── Public API ─────────────────────────────────────────────
    def start(self, on_super_changed=None) -> bool:
        with self._lock:
            self._on_super_changed = on_super_changed
            if self._thread is not None and self._thread.is_alive():
                return self._installed
            self._ready.clear()
            self._installed = False
            self._stopping = False
            self._super_held = False
            thread = threading.Thread(
                target=self._run,
                name="MouserKeyCaptureHook",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        self._ready.wait(_HOOK_START_TIMEOUT)
        with self._lock:
            return self._installed

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            thread_id = self._thread_id
            self._stopping = True
        if thread is None:
            self._reset_super_state()
            return
        if thread_id:
            try:
                _user32().PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        thread.join(_HOOK_STOP_TIMEOUT)
        with self._lock:
            if not thread.is_alive():
                self._thread = None
                self._thread_id = 0
                self._installed = False
        self._reset_super_state()

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._installed)

    @property
    def super_held(self) -> bool:
        with self._lock:
            return bool(self._super_held)

    # ── Internals ──────────────────────────────────────────────
    def _reset_super_state(self) -> None:
        with self._lock:
            changed = self._super_held
            self._super_held = False
            callback = self._on_super_changed
        if changed and callback is not None:
            self._notify(callback, False)

    def _set_super_held(self, held: bool) -> None:
        with self._lock:
            if bool(held) == self._super_held:
                return
            self._super_held = bool(held)
            callback = self._on_super_changed
        if callback is not None:
            self._notify(callback, bool(held))

    @staticmethod
    def _notify(callback, held: bool) -> None:
        # Runs inside the hook proc: never let a UI error stall the hook, or
        # Windows drops us for exceeding the low-level hook timeout.
        try:
            callback(held)
        except Exception:
            pass

    def _run(self) -> None:
        import ctypes
        import ctypes.wintypes as wintypes

        user32 = _user32()

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                # ULONG_PTR value, not an address -- see the note on
                # MSLLHOOKSTRUCT in core/mouse_hook_windows.py.
                ("dwExtraInfo", wintypes.WPARAM),
            ]

        HOOKPROC = ctypes.CFUNCTYPE(
            ctypes.c_long,
            ctypes.c_int,
            wintypes.WPARAM,
            ctypes.POINTER(KBDLLHOOKSTRUCT),
        )

        def _proc(n_code, w_param, l_param):
            if n_code == HC_ACTION:
                try:
                    event = l_param.contents
                    swallow, super_down = classify_key_event(
                        int(event.vkCode), int(event.flags), int(w_param)
                    )
                    if super_down is not None:
                        self._set_super_held(super_down)
                    if swallow:
                        return 1
                except Exception:
                    pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        # Explicit prototypes: the defaults would truncate the 64-bit hook
        # handle to an int and the unhook call would silently fail.
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD,
        ]
        user32.CallNextHookEx.restype = ctypes.c_long
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            ctypes.POINTER(KBDLLHOOKSTRUCT),
        ]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        proc = HOOKPROC(_proc)
        hook = None
        try:
            with self._lock:
                self._thread_id = int(kernel32.GetCurrentThreadId())
            module = kernel32.GetModuleHandleW(None)
            hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, module, 0)
            with self._lock:
                self._installed = bool(hook)
        except Exception:
            with self._lock:
                self._installed = False
        finally:
            self._ready.set()

        if not hook:
            with self._lock:
                self._thread_id = 0
            return

        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            try:
                user32.UnhookWindowsHookEx(hook)
            except Exception:
                pass
            with self._lock:
                self._installed = False
                self._thread_id = 0


def _user32():
    import ctypes

    # Private WinDLL instance, NOT the process-global ctypes.windll.user32.
    # argtypes live on the DLL wrapper; the mouse hook (mouse_hook_windows.py)
    # sets CallNextHookEx/SetWindowsHookExW prototypes for MSLLHOOKSTRUCT on the
    # shared global handle. Reusing it here would overwrite lParam's type with
    # KBDLLHOOKSTRUCT and make every mouse event raise, freezing the pointer.
    return ctypes.WinDLL("user32")


def create_super_key_guard(platform_name: str | None = None) -> SuperKeyGuard:
    """Return the guard suited to ``platform_name`` (defaults to this host)."""
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return WindowsSuperKeyGuard()
    return SuperKeyGuard()
