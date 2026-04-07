# macOS Support

Mouser now supports macOS alongside Windows. This document covers macOS-specific setup and known differences.

## Requirements

- **macOS 12 (Monterey)** or later recommended
- **Python 3.11+** (via Homebrew or python.org)
- **Apple Silicon / M1**: use an `arm64` Python interpreter if you want a native `arm64` app bundle
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

Desktop/navigation actions are also remapped to native macOS behavior:
- **Alt+Tab** becomes **Cmd+Tab**
- Compatibility entries like **Win+D** / **Task View** resolve to native macOS navigation shortcuts
- Mouser also exposes macOS-specific actions such as **Mission Control**, **App Expose**, **Previous Desktop**, **Next Desktop**, **Show Desktop**, and **Launchpad**

### HID Access

On macOS, the HID gesture listener uses non-exclusive access (`hid_darwin_set_open_exclusive(0)`)
so the mouse continues to function normally while Mouser reads HID++ reports.

## Building a Native macOS App

The repository now includes a dedicated macOS bundle flow:

```bash
python3 -m pip install -r requirements.txt pyinstaller
./build_macos_app.sh
```

This produces:

```text
dist/Mouser.app
```

Notes:

- Build on the target architecture. On an M1/M2/M3 Mac, use an `arm64` Python to produce an Apple Silicon app.
- The build flow uses the committed `images/AppIcon.icns` when present; otherwise the script generates an `.icns` icon from `images/logo_icon.png`, runs PyInstaller with `Mouser-mac.spec`, and applies ad-hoc signing via `codesign --sign -`.
- The app can then be moved to `/Applications/Mouser.app` and launched directly from Finder, Spotlight, or Dock.
- `pyinstaller Mouser.spec` remains available as a simpler cross-platform build path, but the dedicated macOS script is the preferred bundle flow.

The packaged app runs as an `LSUIElement`, so it lives in the menu bar instead of showing a Dock icon.

## Running

```bash
python main_qml.py
python main_qml.py --start-hidden
```

Use `--start-hidden` to launch straight into the menu bar without opening the settings window.

## Start at Login

Mouser can now manage **Start at login** from the app UI on macOS.

- The toggle writes a LaunchAgent plist to `~/Library/LaunchAgents/io.github.tombadash.mouser.plist`
- The setting is designed for the packaged `.app`, but it also works in a source checkout by launching the current Python interpreter directly
- If **Start minimized** is enabled in Mouser, the app still launches tray-first after login because that preference is read from config at startup
- Turning **Start at login** back off removes that LaunchAgent plist again

## Accessibility for the Packaged App

If you switch from Terminal-based startup to `Mouser.app`, re-grant Accessibility for the app bundle:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Remove old Terminal / Python entries if needed
3. Add **Mouser.app**
4. Ensure it is enabled
5. Restart Mouser

## Debugging

Send SIGUSR1 to dump all thread stack traces:
```bash
kill -USR1 $(pgrep -f main_qml.py)
```
