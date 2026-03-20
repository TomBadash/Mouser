# macOS Support

Mouser now supports macOS alongside Windows. This document covers macOS-specific setup and known differences.

## Requirements

- **macOS 12 (Monterey)** or later recommended
- **Python 3.11+** (via Homebrew or python.org)
- **Accessibility permission** — required for CGEventTap to intercept mouse events

### Python Dependencies

```bash
pip install -r requirements.txt
```

On macOS, this will also install:
- `pyobjc-framework-Quartz` — for CGEventTap (mouse hooking) and CGEvent (key simulation)
- `pyobjc-framework-Cocoa` — for NSWorkspace (app detection) and NSEvent (media keys)

## Granting Accessibility Permission

Mouser uses a **CGEventTap** to intercept and suppress mouse button events. macOS requires Accessibility permission for this:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Click the **+** button
3. Add either:
  - **Terminal.app** / **iTerm2** (if running from terminal)
  - The Python binary (e.g. `/usr/local/bin/python3`)
  - The built `.app` bundle (if packaged)
4. Ensure the checkbox is **enabled**
5. Restart Mouser if it was already running

If Accessibility is not granted, Mouser will print:
```
[MouseHook] ERROR: Failed to create CGEventTap!
```

## Platform Differences

| Feature | Windows | macOS |
|---------|---------|-------|
| Mouse hook | SetWindowsHookExW (LL hook) | CGEventTap |
| Key simulation | SendInput (VK codes) | CGEvent (CGKeyCodes) |
| Media keys | VK_MEDIA_* constants | NSEvent (NX key IDs) |
| App detection | GetForegroundWindow | NSWorkspace.frontmostApplication |
| Gesture button | HID++ + Raw Input fallback | HID++ + event-tap movement |
| Scroll inversion | Coalesced SendInput | CGEventCreateScrollWheelEvent |
| Modifier key | Ctrl | Cmd (⌘) |
| Config location | `%APPDATA%\Mouser` | `~/Library/Application Support/Mouser` |
| Auto-reconnect | Device change notification | HID++ reconnect loop |

### Key Mapping Differences

Actions that use **Ctrl** on Windows automatically use **Cmd (⌘)** on macOS:
- Copy → Cmd+C
- Paste → Cmd+V
- Cut → Cmd+X
- Undo → Cmd+Z
- etc.

**Alt+Tab** becomes **Cmd+Tab**, **Win+D** becomes **Ctrl+Up** (Mission Control).

### HID Access

On macOS, the HID gesture listener uses non-exclusive access (`hid_darwin_set_open_exclusive(0)`)
so the mouse continues to function normally while Mouser reads HID++ reports.

## Packaging as a macOS App

To build a self-contained macOS `.app` bundle, simply run:

```bash
pyinstaller Mouser.spec
```

The output will be placed in `dist/Mouser.app`. 
This application package runs silently in the background (as an `LSUIElement`), meaning it will only appear in your Menu Bar and not clutter your Dock. 

*Note: If you encounter permissions issues or the app silent-crashes at startup, ensure you grant the built `Mouser.app` Accessibility permissions in macOS System Settings.*

## Running

```bash
python main_qml.py
```

## Debugging

Send SIGUSR1 to dump all thread stack traces:
```bash
kill -USR1 $(pgrep -f main_qml.py)
```
