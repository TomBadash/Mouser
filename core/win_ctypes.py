"""Private ctypes handles for the Win32 libraries.

`ctypes.windll` is a process-wide cache twice over: `ctypes.windll.user32`
always hands back the same `WinDLL` object, and that object caches one function
object per exported name.  `ctypes.windll.user32.CallNextHookEx` is therefore
the *same* object in every module that asks for it, so assigning `argtypes` to
it rewrites the prototype the whole process sees.

Two modules here install low-level hooks and both bind `CallNextHookEx` -- the
mouse hook with a `MSLLHOOKSTRUCT` pointer, the shortcut recorder's keyboard
guard with a `KBDLLHOOKSTRUCT` pointer.  While they shared the function object,
arming the recorder rewrote the mouse hook's prototype, and from that moment
every mouse event raised `ctypes.ArgumentError` inside the hook procedure.  A
low-level hook that answers that slowly makes Windows hold the input queue, so
the cursor froze as soon as the Custom Shortcut dialog opened and the app had
to be killed from outside.

Loading a library through `WinDLL` directly returns a fresh handle with its own
function objects, so every caller can declare the prototypes it needs without
reaching into anybody else's.  Each module keeps its own handle -- sharing one
cached handle from here would recreate the very collision this avoids.
"""

from __future__ import annotations


def load_private_dll(name: str):
    """Return a handle to ``name`` that no other module shares.

    Never use `ctypes.windll.<name>` for a library whose function prototypes
    this process declares: see the module docstring.
    """
    import ctypes

    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        # ImportError, because callers load their handles at import time and
        # off Windows that is exactly what `from ctypes import windll` raised.
        raise ImportError(f"cannot load {name}: ctypes.WinDLL is Windows-only")
    # Matches what ``ctypes.windll`` would build (``use_last_error`` off), so
    # only the object identity changes -- call semantics stay as they were.
    return loader(name)
