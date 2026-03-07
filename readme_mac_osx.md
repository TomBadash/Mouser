# LogiControl — Mac OS X Sequoia Port

<p align="center">
  <img src="images/logo_icon.png" width="128" alt="LogiControl logo" />
</p>

This document describes the changes made to port **LogiControl** from Windows to
**Mac OS X Sequoia** (macOS 15). The core feature set — button remapping,
per-app profiles, DPI control, and the Qt Quick UI — is preserved.

---

## macOS-Specific Changes

### Mouse Hook (`mouse_hook.py`)

The Windows low-level mouse hook (`SetWindowsHookExW` + Raw Input) is replaced
with **Quartz CGEventTap** on macOS:

- `kCGEventOtherMouseDown` / `kCGEventOtherMouseUp` — side buttons (back, forward) and middle click
- `kCGEventScrollWheel` — horizontal and vertical scroll
- Button numbers follow macOS HID convention: middle = 2, back = 3, forward = 4

CGEventTap provides **active event filtering** — when an event is remapped and
blocked, it is completely suppressed and does NOT reach the target application.
The tap callback returns `None` to suppress events or passes the event through
when no remapping is configured.

**Important:** CGEventTap requires Accessibility permission. Grant access to
your terminal app (or the Python executable) in System Settings → Privacy &
Security → Accessibility.

### Key Simulator (`key_simulator.py`)

Windows `SendInput` is replaced with **Quartz CGEvent** functions:

| Function | Purpose |
|---|---|
| `CGEventCreateKeyboardEvent()` | Inject key press / release |
| `CGEventSetFlags()` | Set modifier keys (⌘ Cmd, ⌥ Option, ⌃ Control, ⇧ Shift) |
| `CGEventPost()` | Post events at `kCGSessionEventTap` |
| `CGEventCreateScrollWheelEvent()` | Inject scroll events |

Media keys (volume, play/pause, next/prev track) use **NSEvent system-defined
events** with NX key types, posted through `CGEventPost`.

Key mappings use macOS-native CGKeyCode values and modifier flags rather than
Windows VK_* constants. For example, Alt+Tab becomes **⌘ Cmd+Tab** (Mission Control).

### App Detector (`app_detector.py`)

Windows `GetForegroundWindow` → `GetWindowThreadProcessId` is replaced with:

```python
AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
```

This returns the active application's bundle info. The detector resolves the
executable name via `executableURL()` with a fallback to the bundle identifier's
last component.

### HID Gesture Button (`hid_gesture.py`)

On macOS, `hidapi` opens HID devices with `kIOHIDOptionsTypeSeizeDevice` by
default, which grabs exclusive access to the Bluetooth transport. For the
MX Master 3S this **freezes the mouse cursor entirely**.

The fix calls the native C function directly via ctypes before any device is
opened:

```python
hid_darwin_set_open_exclusive(0)
```

This allows the OS mouse driver and LogiControl's HID++ communication to
coexist without cursor freezing.

### Application Entry Point (`main_qml.py`)

| Feature | Implementation |
|---|---|
| **Ctrl+C clean exit** | `SIGINT` handler sets a flag; a `QTimer` (200 ms) polls it and calls `quit_app()` inside the Qt event loop |
| **Menu bar** | A parentless `QMenuBar` with a "MouseControl" menu and "Quit MouseControl" action (`QuitRole` → ⌘Q) |
| **App menu rename** | `NSBundle.mainBundle()` info dictionary patched with `CFBundleName` / `CFBundleDisplayName` = "MouseControl" |
| **System tray** | Same as Windows — Open Settings, Disable/Enable Remapping, Quit |
| **Close to tray** | Window hides on close; double-click tray icon to reopen |

### Diagnostic Flags

Two CLI flags are available for troubleshooting macOS-specific issues:

```bash
python main_qml.py --no-hid        # Skip HidGestureListener (no gesture button / DPI)
python main_qml.py --no-monitors   # Skip NSEvent global monitors (no button remapping)
```

A thread dump can be triggered at any time with:

```bash
kill -USR1 <pid>
```

---

## Installation

### Prerequisites

- **Mac OS X Sequoia** (macOS 15) — tested on Apple Intel
- **Python 3.10+** (tested with 3.14)
- **Logitech MX Master 3S** paired via Bluetooth
- **Logitech Options+ must NOT be running** (conflicts with HID++ access)
- **Accessibility permission** — System Settings → Privacy & Security → Accessibility: grant access to Terminal (or your terminal app) so Quartz can inject keyboard events

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/logi-control.git
cd logi-control

# 2. Create a virtual environment
python3 -m venv .venv

# 3. Activate it
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---|---|
| `PySide6` | Qt Quick / QML UI framework |
| `hidapi` | HID++ communication with the mouse (gesture button, DPI) |
| `Pillow` | Image processing for icon generation |
| `pyobjc-framework-Quartz` | Quartz CGEvent key injection and scroll events |
| `pyobjc-framework-Cocoa` | AppKit NSEvent monitors, NSWorkspace app detection, menu renaming |

> The pyobjc packages are automatically installed on macOS via the platform
> markers in `requirements.txt`.

### Running

```bash
# Run from the activated virtual environment
python main_qml.py
```

- The UI window opens with the MX Master 3S button remapping interface.
- Closing the window hides to the system tray — double-click the tray icon to reopen.
- Press **Ctrl+C** in the terminal to shut down cleanly.
- Use **⌘Q** or the **MouseControl → Quit MouseControl** menu to exit.

---

## Architecture Differences (Windows vs. macOS)

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Mouse HW   │────▶│ Mouse Hook       │────▶│ Engine         │
│ (MX Master) │     │ (NSEvent global  │     │ (orchestrator) │
└─────────────┘     │  monitors)       │     └───────┬────────┘
                    └──────────────────┘             │
                                                ┌────▼────────┐
┌─────────────┐     ┌──────────────────┐        │ Key         │
│ QML UI      │◀───▶│ Backend          │        │ Simulator   │
│ (PySide6)   │     │ (QObject bridge) │        │ (CGEvent)   │
└─────────────┘     └──────────────────┘        └─────────────┘
                         ▲
                    ┌────┴────────────┐
                    │ App Detector    │
                    │ (NSWorkspace)   │
                    └─────────────────┘
```

| Component | Windows | macOS |
|---|---|---|
| Mouse Hook | `SetWindowsHookExW` WH_MOUSE_LL + Raw Input | Quartz `CGEventTap` with active filtering |
| Key Injection | `SendInput` API | Quartz `CGEventCreateKeyboardEvent` + `CGEventPost` |
| Media Keys | Extended virtual keys (VK_VOLUME_UP, etc.) | NSEvent system-defined NX key types |
| App Detection | `GetForegroundWindow` + PID lookup | `NSWorkspace.frontmostApplication()` |
| HID Access | Standard hidapi open | `hid_darwin_set_open_exclusive(0)` to prevent cursor freeze |
| Key Codes | Virtual Key (VK_*) | CGKeyCode hardware-independent codes |

---

## Known Limitations (macOS)

- **Accessibility permission required** — CGEventTap requires the terminal or app to be granted Accessibility access in System Settings → Privacy & Security → Accessibility. Without this permission, the event tap cannot be created.
- **MX Master 3S only** — HID++ feature indices and CIDs are hardcoded for this device (PID `0xB034`).
- **Bluetooth recommended** — Gesture button divert via HID++ works best over Bluetooth.
- **Conflicts with Logitech Options+** — both apps fight over HID++ access; quit Options+ first.

---

## Files Modified for macOS Support

| File | Changes |
|---|---|
| `main_qml.py` | Ctrl+C signal handling, MouseControl menu bar, NSBundle app name patch, diagnostic flags |
| `core/mouse_hook.py` | Full macOS `MouseHook` using NSEvent global monitors (alongside existing Windows code) |
| `core/key_simulator.py` | Quartz CGEvent key/scroll injection, NSEvent media keys, macOS action table |
| `core/app_detector.py` | AppKit NSWorkspace foreground app detection |
| `core/hid_gesture.py` | `hid_darwin_set_open_exclusive(0)` to prevent Bluetooth cursor freeze |
| `requirements.txt` | Added `pyobjc-framework-Quartz` and `pyobjc-framework-Cocoa` with platform markers |

---

**LogiControl** is not affiliated with or endorsed by Logitech. "Logitech", "MX Master", and "Options+" are trademarks of Logitech International S.A.
