# Mouser — Logitech Mouse Remapper

<p align="center">
  <img src="images/logo_icon.png" width="128" alt="Mouser logo" />
</p>

A lightweight, open-source, fully local alternative to **Logitech Options+** for
remapping Logitech HID++ mice. The current best experience is on the **MX Master**
family, with early detection and fallback UI support for additional Logitech models.

No telemetry. No cloud. No Logitech account required.

---

## Features

- **macOS support** — full macOS compatibility using CGEventTap for mouse hooking, Quartz CGEvent for key simulation, and NSWorkspace for app detection. See [macOS Setup Guide](readme_mac_osx.md) for details.
- **Remap supported programmable controls** — MX Master-family layouts expose middle click, gesture button, back, forward, and horizontal scroll actions
- **Per-application profiles** — automatically switch button mappings when you switch apps (e.g., different bindings for Chrome vs. VS Code)
- **22 built-in actions** across navigation, browser, editing, and media categories
- **DPI / pointer speed control** — slider from 200–8000 DPI with quick presets, synced to the device via HID++
- **Scroll direction inversion** — independent toggles for vertical and horizontal scroll
- **Device-aware HID++ gesture support** — discovers `REPROG_CONTROLS_V4`, ranks gesture candidates per device, and diverts the best control it can find
- **Auto-reconnection** — automatically detects when the mouse is turned off/on or disconnected/reconnected and restores full functionality without restarting the app
- **Live connection status** — the UI shows a real-time "Connected" / "Not Connected" badge that updates as the mouse connects or disconnects
- **Device-aware Qt Quick UI** — interactive MX Master layout today, plus a generic fallback card and experimental manual map picker for other detected devices
- **System tray** — runs in background, hides to tray on close, toggle remapping on/off from tray menu
- **Auto-detect foreground app** — polls the active window and switches profiles instantly
- **Zero external services** — config is a local JSON file, all processing happens on your machine

## Screenshots

<p align="center">
  <img src="images/Screenshot.png" alt="Mouser UI" />
</p>

_The UI is now device-aware. MX Master-family mice get the interactive diagram; other detected Logitech mice fall back to a generic device card with an experimental map override picker._

## Current Device Coverage

| Family / model | Detection + HID++ probing | UI support |
|---|---|---|
| MX Master 3S / 3 / 2S / MX Master | Yes | Dedicated interactive `mx_master` layout |
| MX Anywhere 3S / 3 / 2S | Yes | Generic fallback card, experimental manual override |
| MX Vertical | Yes | Generic fallback card |
| Unknown Logitech HID++ mice | Best effort by PID/name | Generic fallback card |

> **Note:** Only the MX Master family currently has a dedicated visual overlay. Other devices can still be detected, show their model name in the UI, and try the experimental layout override picker, but button positions may not line up until a real overlay is added.

## Default Mappings

| Button | Default Action |
|---|---|
| Back button | Alt + Tab (Switch Windows) |
| Forward button | Alt + Tab (Switch Windows) |
| Middle click | Pass-through |
| Gesture button | Pass-through |
| Horizontal scroll left | Browser Back |
| Horizontal scroll right | Browser Forward |

## Available Actions

| Category | Actions |
|---|---|
| **Navigation** | Alt+Tab, Alt+Shift+Tab, Show Desktop (Win+D), Task View (Win+Tab) |
| **Browser** | Back, Forward, Close Tab (Ctrl+W), New Tab (Ctrl+T) |
| **Editing** | Copy, Paste, Cut, Undo, Select All, Save, Find |
| **Media** | Volume Up, Volume Down, Volume Mute, Play/Pause, Next Track, Previous Track |
| **Other** | Do Nothing (pass-through) |

---

## Download & Run

> **No install required.** Just download, extract, and double-click.

<p align="center">
  <a href="https://github.com/TomBadash/Mouser/releases/latest">
    <img src="https://img.shields.io/badge/Download-Mouser.zip-00d4aa?style=for-the-badge&logo=windows" alt="Download" />
  </a>
  <img src="https://img.shields.io/github/downloads/TomBadash/Mouser/total?style=for-the-badge&color=00d4aa&label=Total%20Downloads" alt="Downloads" />
</p>

### Steps

1. Go to the [**latest release page**](https://github.com/TomBadash/Mouser/releases/latest)
2. Click **Mouser.zip** to download it
3. **Extract** the zip to any folder (Desktop, Documents, wherever you like)
4. **Run** `Mouser.exe`

That's it. The app will open and start remapping your mouse buttons immediately.

### What to expect

- The **settings window** opens showing the current device-aware mouse page
- A **system tray icon** appears near the clock (bottom-right)
- Button remapping is **active immediately**
- Closing the window does not quit the app — it keeps running in the tray
- To fully quit: right-click the tray icon and select **Quit Mouser**

### First-time notes

- **Windows SmartScreen** may show a warning the first time — click **More info** then **Run anyway**
- **Logitech Options+** must not be running (it conflicts with HID++ access and will cause Mouser to malfunction or crash)
- Config is saved automatically to `%APPDATA%\Mouser`

---

## Installation (from source)

### Prerequisites

- **Windows 10/11** or **macOS 12+ (Monterey)**
- **Python 3.10+** (tested with 3.14)
- **A supported Logitech HID++ mouse** paired via Bluetooth or USB receiver. MX Master-family devices currently have the most complete UI support.
- **Logitech Options+ must NOT be running** (it conflicts with HID++ access)
- **macOS only:** Accessibility permission required (System Settings → Privacy & Security → Accessibility)

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/TomBadash/Mouser.git
cd Mouser

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it
.venv\Scripts\activate        # Windows (PowerShell / CMD)
source .venv/bin/activate      # macOS / Linux

# 4. Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---|---|
| `PySide6` | Qt Quick / QML UI framework |
| `hidapi` | HID++ communication with the mouse (gesture button, DPI) |
| `pystray` | System tray icon (legacy, may be removed) |
| `Pillow` | Image processing for icon generation |

### Running

```bash
# Option A: Run directly
python main_qml.py

# Option B: Use the batch file (shows a console window)
Mouser.bat

# Option C: Use the desktop shortcut (no console window)
# Double-click Mouser.lnk
```

> **Tip:** To run without a console window, use `pythonw.exe main_qml.py` or the `.lnk` shortcut.

Temporary macOS transport override for debugging:

```bash
python main_qml.py --hid-backend=iokit
python main_qml.py --hid-backend=hidapi
python main_qml.py --hid-backend=auto
```

Use this only for troubleshooting. On macOS, Mouser now defaults to `iokit`;
`hidapi` and `auto` remain available as manual overrides for debugging. Other
platforms continue to default to `auto`.

### Creating a Desktop Shortcut

A `Mouser.lnk` shortcut is included. To create one manually:

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Mouser.lnk")
$s.TargetPath = "C:\path\to\mouser\.venv\Scripts\pythonw.exe"
$s.Arguments = "main_qml.py"
$s.WorkingDirectory = "C:\path\to\mouser"
$s.IconLocation = "C:\path\to\mouser\images\logo.ico, 0"
$s.Save()
```

### Building the Portable App

To produce a standalone `Mouser.exe` that anyone can download and run without Python:

```bash
# 1. Install PyInstaller (inside your venv)
pip install pyinstaller

# 2. Build using the included spec file
pyinstaller Mouser.spec --noconfirm

# — or simply run the build script —
build.bat
```

The output is in `dist\Mouser\`. Zip that entire folder and distribute it.

---

## How It Works

### Architecture

```
┌────────────────┐     ┌──────────┐     ┌────────────────┐
│ Logitech mouse │────▶│ Mouse    │────▶│ Engine         │
│ / HID++ device │     │ Hook     │     │ (orchestrator) │
└────────────────┘     └──────────┘     └───────┬────────┘
                         ▲                    │
                    block/pass           ┌────▼────────┐
                                         │ Key         │
┌─────────────┐     ┌──────────┐        │ Simulator   │
│ QML UI      │◀───▶│ Backend  │        │ (SendInput) │
│ (PySide6)   │     │ (QObject)│        └─────────────┘
└─────────────┘     └──────────┘
                         ▲
                    ┌────┴────────┐
                    │ App         │
                    │ Detector    │
                    └─────────────┘
```

### Mouse Hook (`mouse_hook.py`)

Mouser uses a platform-specific mouse hook behind a shared `MouseHook` abstraction:

- **Windows** — `SetWindowsHookExW` with `WH_MOUSE_LL` on a dedicated background thread, plus Raw Input for extra mouse data
- **macOS** — `CGEventTap` for mouse interception and Quartz events for key simulation

Both paths feed the same internal event model and intercept:

- `WM_XBUTTONDOWN/UP` — side buttons (back/forward)
- `WM_MBUTTONDOWN/UP` — middle click
- `WM_MOUSEHWHEEL` — horizontal scroll
- `WM_MOUSEWHEEL` — vertical scroll (for inversion)

Intercepted events are either **blocked** (hook returns 1) and replaced with an action, or **passed through** to the application.

### Device Catalog & Layout Registry

- `core/logi_devices.py` resolves known product IDs and model aliases into a `ConnectedDeviceInfo` record with display name, DPI range, preferred gesture CIDs, and default UI layout key
- `core/device_layouts.py` stores image assets, hotspot coordinates, layout notes, and whether a layout is interactive or only a generic fallback
- `ui/backend.py` combines auto-detected device info with any persisted per-device layout override and exposes the effective layout to QML

### Gesture Button Detection

Logitech gesture/thumb buttons do not always appear as standard mouse events. Mouser uses a layered detector:

1. **HID++ 2.0** (primary) — Opens the Logitech HID collection, discovers `REPROG_CONTROLS_V4` (feature `0x1B04`), ranks gesture CID candidates from the device registry plus control-capability heuristics, and diverts the best candidate. When supported, Mouser also enables RawXY movement data.
2. **Raw Input** (Windows fallback) — Registers for raw mouse input and detects extra button bits beyond the standard 5.
3. **Gesture tap/swipe dispatch** — A clean press/release emits `gesture_click`; once movement crosses the configured threshold, Mouser emits directional swipe actions instead.

### App Detector (`app_detector.py`)

Polls the foreground window every 300ms using `GetForegroundWindow` → `GetWindowThreadProcessId` → process name. Handles UWP apps by resolving `ApplicationFrameHost.exe` to the actual child process.

### Engine (`engine.py`)

The central orchestrator. On app change, it performs a **lightweight profile switch** — clears and re-wires hook callbacks without tearing down the hook thread or HID++ connection. This avoids the latency and instability of a full hook restart. The engine also forwards connected-device identity to the backend so QML can render the right model name and layout state.

### Device Reconnection

Mouser handles mouse power-off/on cycles automatically:

- **HID++ layer** — `HidGestureListener` detects device disconnection (read errors) and enters a reconnect loop, retrying every 2–5 seconds until the device is back
- **Hook layer** — `MouseHook` listens for `WM_DEVICECHANGE` notifications and reinstalls the low-level mouse hook when devices are added or removed
- **UI layer** — connection state and device identity flow from HID++ → MouseHook → Engine → Backend (cross-thread safe via Qt signals) → QML, updating the status badge, device name, and active layout in real time

### Configuration

All settings are stored in `%APPDATA%\Mouser\config.json` (Windows) or `~/Library/Application Support/Mouser/config.json` (macOS). The config supports:
- Multiple named profiles with per-profile button mappings, including gesture tap + swipe actions
- Per-profile app associations (list of `.exe` names)
- Global settings: DPI, scroll inversion, gesture tuning, appearance, and debug flags
- Per-device layout override selections for unsupported devices
- Automatic migration from older config versions

---

## Project Structure

```
mouser/
├── main_qml.py              # Application entry point (PySide6 + QML)
├── Mouser.bat               # Quick-launch batch file
├── README.md
├── requirements.txt
├── .gitignore
│
├── core/                    # Backend logic
│   ├── engine.py            # Core engine — wires hook ↔ simulator ↔ config
│   ├── mouse_hook.py        # Low-level mouse hook + HID++ gesture listener
│   ├── hid_gesture.py       # HID++ 2.0 gesture button divert (Bluetooth)
│   ├── logi_devices.py      # Known Logitech device catalog + connected-device metadata
│   ├── device_layouts.py    # Device-family layout registry for QML overlays
│   ├── key_simulator.py     # SendInput-based action simulator (22 actions)
│   ├── config.py            # Config manager (JSON load/save/migrate)
│   └── app_detector.py      # Foreground app polling
│
├── ui/                      # UI layer
│   ├── backend.py           # QML ↔ Python bridge (QObject with properties/slots)
│   └── qml/
│       ├── Main.qml         # App shell (sidebar + page stack + tray toast)
│       ├── MousePage.qml    # Merged mouse diagram + profile manager
│       ├── ScrollPage.qml   # DPI slider + scroll inversion toggles
│       ├── HotspotDot.qml   # Interactive button overlay on mouse image
│       ├── ActionChip.qml   # Selectable action pill
│       └── Theme.js         # Shared colors and constants
│
└── images/
    ├── mouse.png            # MX Master 3S top-down diagram
    ├── icons/mouse-simple.svg # Generic fallback device card artwork
    ├── logo.png             # Mouser logo (source)
    ├── logo.ico             # Multi-size icon for shortcuts
    ├── logo_icon.png        # Square icon with background
    ├── chrom.png            # App icon: Chrome
    ├── VSCODE.png           # App icon: VS Code
    ├── VLC.png              # App icon: VLC
    └── media.webp           # App icon: Windows Media Player
```

## UI Overview

The app has two pages accessible from a slim sidebar:

### Mouse & Profiles (Page 1)

- **Left panel:** List of profiles. The "Default (All Apps)" profile is always present. Per-app profiles show the app icon and name. Select a profile to edit its mappings.
- **Right panel:** Device-aware mouse view. MX Master-family devices get clickable hotspot dots on the image; unsupported layouts fall back to a generic device card with an experimental "try another supported map" picker.
- **Add profile:** ComboBox at the bottom lists known apps (Chrome, Edge, VS Code, VLC, etc.). Click "+" to create a per-app profile.

### Point & Scroll (Page 2)

- **DPI slider:** 200–8000 with quick presets (400, 800, 1000, 1600, 2400, 4000, 6000, 8000). Reads the current DPI from the device on startup.
- **Scroll inversion:** Independent toggles for vertical and horizontal scroll direction.

---

## Known Limitations

- **Windows & macOS only** — Linux is not yet supported
- **Early multi-device support** — only the MX Master family currently has a dedicated interactive overlay; MX Anywhere, MX Vertical, and unknown Logitech mice still use the generic fallback card
- **Per-device mappings are not fully separated yet** — layout overrides are stored per detected device, but profile mappings are still global rather than truly device-specific
- **Bluetooth recommended** — HID++ gesture button divert works best over Bluetooth; USB receiver has partial support
- **Conflicts with Logitech Options+** — both apps fight over HID++ access; quit Options+ before running Mouser
- **Scroll inversion is experimental** — uses coalesced `PostMessage` injection to avoid LL hook deadlocks; may not work perfectly in all apps
- **Admin not required** — but some games or elevated windows may not receive injected keystrokes

## Future Work

- [ ] **Dedicated overlays for more devices** — add real hotspot maps and artwork for MX Anywhere, MX Vertical, and other Logitech families
- [ ] **True per-device config** — separate mappings and layout state cleanly when multiple Logitech mice are used on the same machine
- [ ] **Dynamic button inventory** — build button lists from discovered `REPROG_CONTROLS_V4` controls instead of relying on the current fixed mapping set
- [ ] **Custom key combos** — let users define arbitrary key sequences (e.g., Ctrl+Shift+P)
- [ ] **Start with Windows** — autostart via registry or Task Scheduler
- [ ] **Improved scroll inversion** — explore driver-level or interception-driver approaches
- [ ] **Gesture button actions** — swipe gestures (up/down/left/right) for multi-action gesture button
- [ ] **Per-app profile auto-creation** — detect new apps and prompt to create a profile
- [ ] **Export/import config** — share configurations between machines
- [ ] **Tray icon badge** — show active profile name in tray tooltip
- [x] **macOS support** — added via CGEventTap, Quartz CGEvent, and NSWorkspace
- [ ] **Linux support** — investigate `libevdev` / `evdev` hooks
- [ ] **Plugin system** — allow third-party action providers

## Contributing

Contributions are welcome! To get started:

1. Fork the repo and create a feature branch
2. Set up the dev environment (see [Installation](#installation))
3. Make your changes and test with a supported Logitech HID++ mouse (MX Master family preferred for now)
4. Submit a pull request with a clear description

### Areas where help is needed

- Testing with other Logitech HID++ devices
- Scroll inversion improvements
- Linux porting
- UI/UX polish and accessibility

## Support the Project

If Mouser saves you from installing Logitech Options+, consider supporting development:

<p align="center">
  <a href="https://github.com/sponsors/TomBadash">
    <img src="https://img.shields.io/badge/Sponsor-❤️-ea4aaa?style=for-the-badge&logo=githubsponsors" alt="Sponsor" />
  </a>
</p>

Every bit helps keep the project going — thank you!

## License

This project is licensed under the [MIT License](LICENSE).

---

## Acknowledgments

- **[@andrew-sz](https://github.com/andrew-sz)** — macOS port: CGEventTap mouse hooking, Quartz key simulation, NSWorkspace app detection, and NSEvent media key support
- **[@thisislvca](https://github.com/thisislvca)** — significant expansion of the project including macOS compatibility improvements, multi-device support, new UI features, and active involvement in triaging and resolving open issues

---

**Mouser** is not affiliated with or endorsed by Logitech. "Logitech", "MX Master", and "Options+" are trademarks of Logitech International S.A.
