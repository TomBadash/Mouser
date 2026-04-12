# Mouser — Logitech Mouse Remapper

<p align="center">
  <img src="images/logo_icon.png" width="128" alt="Mouser logo" />
</p>

English | [中文文档](README_CN.md)

A lightweight, open-source, fully local alternative to **Logitech Options+** for
remapping Logitech HID++ mice. The current best experience is on the **MX Master**
family, with early detection and fallback UI support for additional Logitech models.

No telemetry. No cloud. No Logitech account required.

---

## Features

### 🖱️ Button Remapping
- **Remap any programmable button** — middle click, gesture button, back, forward, mode shift, and horizontal scroll
- **Per-application profiles** — automatically switch mappings when you switch apps (e.g., Chrome vs. VS Code)
- **Custom keyboard shortcuts** — define arbitrary key combinations (e.g., Ctrl+Shift+P) as button actions
- **30+ built-in actions** — navigation, browser, editing, media, and desktop shortcuts that adapt per platform

### ⚙️ Device Control
- **DPI / pointer speed** — slider from 200–8000 DPI with quick presets, synced live via HID++
- **Smart Shift toggle** — enable or disable Logitech's ratchet-to-free-spin scroll mode switching
- **Scroll direction inversion** — independent toggles for vertical and horizontal scroll
- **Gesture button + swipe actions** — tap for one action, swipe up/down/left/right for others

### 🖥️ Cross-Platform
- **Windows, macOS, and Linux** — native hooks on each platform (WH_MOUSE_LL, CGEventTap, evdev/uinput)
- **Start at login** — Windows registry and macOS LaunchAgent, with an independent "Start minimized" tray-only option
- **Single instance guard** — launching a second copy brings the existing window to the front

### 🔌 Smart Connectivity
- **Bluetooth and Logi Bolt** — works with both Bluetooth and Logi Bolt USB receivers; connection type shown in the UI
- **Auto-reconnection** — detects power-off/on and restores full functionality without restarting
- **Live connection status** — real-time "Connected" / "Not Connected" badge in the UI
- **Device-aware UI** — interactive MX Master diagram with clickable hotspots; generic fallback for other models

### 🌐 Multi-Language UI
- **English / Simplified Chinese / Traditional Chinese** - switch instantly in-app, no restart required
- Language preference is automatically saved to `config.json` and restored on next launch
- Covers all major UI surfaces: navigation, mouse page, settings page, dialogs, system tray/menu bar, and permission prompts

### 🛡️ Privacy First
- **Fully local** — config is a JSON file, all processing happens on your machine
- **System tray / menu bar** — runs quietly in the background with quick access from the tray
- **Zero telemetry, zero cloud, zero account required**

## Screenshots

<p align="center">
  <img src="images/Screenshot_mouse.png" alt="Mouser — Mouse & Profiles page" />
</p>

<p align="center">
  <img src="images/Screenshot_settings.png" alt="Mouser — Point & Scroll settings" />
</p>

## Current Device Coverage

| Family / model | Detection + HID++ probing | UI support |
|---|---|---|
| MX Master 4 / 3S / 3 / 2S / MX Master | Yes | Dedicated interactive `mx_master` layout |
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
| Mode shift (scroll click) | Pass-through |
| Horizontal scroll left | Browser Back |
| Horizontal scroll right | Browser Forward |

## Available Actions

Action labels adapt by platform. For example, Windows exposes `Win+D` and `Task View`, while macOS exposes `Mission Control`, `Show Desktop`, `App Expose`, and `Launchpad`.

| Category | Actions |
|---|---|
| **Navigation** | Alt+Tab, Alt+Shift+Tab, Show Desktop, Previous Desktop, Next Desktop, Task View (Windows), Mission Control (macOS), App Expose (macOS), Launchpad (macOS) |
| **Browser** | Back, Forward, Close Tab (Ctrl+W), New Tab (Ctrl+T), Next Tab (Ctrl+Tab), Previous Tab (Ctrl+Shift+Tab) |
| **Editing** | Copy, Paste, Cut, Undo, Select All, Save, Find |
| **Media** | Volume Up, Volume Down, Volume Mute, Play/Pause, Next Track, Previous Track |
| **Custom** | User-defined keyboard shortcuts (any key combination) |
| **Other** | Do Nothing (pass-through) |

---

## Download & Run

> **No install required.** Just download, extract, and double-click.

<p align="center">
  <a href="https://github.com/TomBadash/Mouser/releases/latest">
    <img src="https://img.shields.io/github/downloads/TomBadash/Mouser/latest/Mouser-Windows.zip?style=for-the-badge&color=00d4aa&logo=windows&label=Windows&displayAssetName=false" alt="Windows Downloads" />
  </a>
  <a href="https://github.com/TomBadash/Mouser/releases/latest">
    <img src="https://img.shields.io/github/downloads/TomBadash/Mouser/latest/Mouser-macOS.zip?style=for-the-badge&color=00d4aa&logo=apple&label=macOS&displayAssetName=false" alt="macOS Downloads" />
  </a>
  <a href="https://github.com/TomBadash/Mouser/releases/latest">
    <img src="https://img.shields.io/github/downloads/TomBadash/Mouser/latest/Mouser-Linux.zip?style=for-the-badge&color=00d4aa&logo=linux&label=Linux&displayAssetName=false" alt="Linux Downloads" />
  </a>
  <br />
  <img src="https://img.shields.io/github/downloads/TomBadash/Mouser/total?style=for-the-badge&color=00d4aa&label=Total%20Downloads%20(all%20versions)" alt="Downloads" />
</p>

### Steps

1. Go to the [**latest release page**](https://github.com/TomBadash/Mouser/releases/latest)
2. Download the zip for your platform: **Mouser-Windows.zip**, **Mouser-macOS.zip**, or **Mouser-Linux.zip**
3. **Extract** the zip to any folder (Desktop, Documents, wherever you like)
4. **Run** the executable: `Mouser.exe` (Windows), `Mouser.app` (macOS), or `./Mouser` (Linux)

That's it. The app will open and start remapping your mouse buttons immediately.

For macOS Accessibility permissions and login-item notes, see the [macOS Setup Guide](readme_mac_osx.md).

### What to expect

- The **settings window** opens showing the current device-aware mouse page
- A **system tray icon** appears near the clock (bottom-right)
- Button remapping is **active immediately**
- Closing the window does not quit the app — it keeps running in the tray
- To fully quit: right-click the tray icon and select **Quit Mouser**

### First-time notes

- **Windows SmartScreen** may show a warning the first time — click **More info** then **Run anyway**
- **Logitech Options+** must not be running (it conflicts with HID++ access and will cause Mouser to malfunction or crash)
- Config is saved automatically to `%APPDATA%\Mouser` (Windows), `~/Library/Application Support/Mouser` (macOS), or `~/.config/Mouser` (Linux)

---

## Installation (from source)

### Prerequisites

- **Windows 10/11**, **macOS 12+ (Monterey)**, or **Linux (experimental; X11 plus KDE Wayland app detection)**
- **Python 3.10+** (tested with 3.14)
- **A supported Logitech HID++ mouse** paired via Bluetooth or USB receiver. MX Master-family devices currently have the most complete UI support.
- **Logitech Options+ must NOT be running** (it conflicts with HID++ access)
- **macOS only:** Accessibility permission required (System Settings → Privacy & Security → Accessibility)
- **Linux only:** `xdotool` enables per-app profile switching on X11; `kdotool` additionally enables KDE Wayland detection
- **Linux only:** read access to `/dev/input/event*` and write access to `/dev/uinput` are required for remapping (you may need to add your user to the `input` group)

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
| `Pillow` | Image processing for icon generation |
| `pyobjc-framework-Quartz` | macOS CGEventTap / Quartz event support |
| `pyobjc-framework-Cocoa` | macOS app detection and media-key support |
| `evdev` | Linux mouse grab and virtual device forwarding (uinput) |

### Running

```bash
# Option A: Run directly
python main_qml.py

# Option B: Start directly in the tray / menu bar
python main_qml.py --start-hidden

# Option C: Use the batch file (shows a console window)
Mouser.bat

# Option D: Use the desktop shortcut (no console window)
# Double-click Mouser.lnk
```

> **Tip:** To run without a console window, use `pythonw.exe main_qml.py` or the `.lnk` shortcut.
> On macOS, `--start-hidden` is the same tray-first startup path used when you launch Mouser directly in the background. The login item uses your saved startup settings.

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

### Building Distribution Artifacts

Windows portable build:

```bash
# 1. Install PyInstaller (inside your venv)
pip install pyinstaller

# 2. Build using the included spec file
pyinstaller Mouser.spec --noconfirm

# — or simply run the build script —
build.bat
```

The output is in `dist\Mouser\`. Zip that entire folder and distribute it.

macOS native bundle:

```bash
# 1. Install PyInstaller (inside your venv)
pip install pyinstaller

# 2. Build the native menu-bar app bundle
./build_macos_app.sh
```

The output is `dist/Mouser.app`. The script prefers `images/AppIcon.icns` when present, otherwise it generates an `.icns` icon from `images/logo_icon.png`, then ad-hoc signs the bundle with `codesign --sign -`.

Linux portable build:

```bash
# 1. Install system dependencies
sudo apt-get install libhidapi-dev

# 2. Install PyInstaller (inside your venv)
pip install pyinstaller

# 3. Build using the Linux-specific spec file
pyinstaller Mouser-linux.spec --noconfirm
```

The output is in `dist/Mouser/`. Zip that entire folder and distribute it.

> **Automated releases:** Pushing a `v*` tag triggers the [release workflow](.github/workflows/release.yml), which builds all three platforms in CI and publishes them as GitHub Release assets.

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
- **Linux** — `evdev` to grab the physical mouse and `uinput` to forward pass-through events via a virtual device

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
- Global settings: DPI, scroll inversion, gesture tuning, appearance, debug flags, Smart Shift, and startup preferences (`start_at_login`, `start_minimized`)
- Per-device layout override selections for unsupported devices
- Automatic migration from older config versions

---

## Project Structure

```
mouser/
├── main_qml.py              # Application entry point (PySide6 + QML)
├── Mouser.bat               # Quick-launch batch file
├── Mouser-mac.spec          # Native macOS app-bundle spec
├── Mouser-linux.spec        # Linux PyInstaller spec
├── build_macos_app.sh       # macOS bundle build + icon/signing flow
├── .github/workflows/
│   ├── ci.yml               # CI checks (compile, tests, QML lint)
│   └── release.yml          # Automated release builds (Win/macOS/Linux)
├── README.md
├── readme_mac_osx.md
├── requirements.txt
├── .gitignore
│
├── core/                    # Backend logic
│   ├── accessibility.py     # macOS Accessibility trust checks
│   ├── engine.py            # Core engine — wires hook ↔ simulator ↔ config
│   ├── mouse_hook.py        # Low-level mouse hook + HID++ gesture listener
│   ├── hid_gesture.py       # HID++ 2.0 gesture button divert (Bluetooth + Logi Bolt)
│   ├── logi_devices.py      # Known Logitech device catalog + connected-device metadata
│   ├── device_layouts.py    # Device-family layout registry for QML overlays
│   ├── key_simulator.py     # Platform-specific action simulator
│   ├── startup.py           # Cross-platform login startup (Windows registry + macOS LaunchAgent)
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
    ├── AppIcon.icns        # Committed macOS app-bundle icon
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
- **Smart Shift:** Toggle Logitech Smart Shift (ratchet-to-free-spin scroll mode switching) on or off.
- **Startup controls:** **Start at login** (Windows and macOS) and **Start minimized** (all platforms) to launch directly into the system tray.

---

## Known Limitations

- **Early multi-device support** — only the MX Master family currently has a dedicated interactive overlay; MX Anywhere, MX Vertical, and unknown Logitech mice still use the generic fallback card
- **Per-device mappings are not fully separated yet** — layout overrides are stored per detected device, but profile mappings are still global rather than truly device-specific
- **Bluetooth and Logi Bolt supported** — HID++ gesture button divert works over both Bluetooth and Logi Bolt USB receivers
- **Conflicts with Logitech Options+** — both apps fight over HID++ access; quit Options+ before running Mouser
- **Scroll inversion is experimental** — uses coalesced `PostMessage` injection to avoid LL hook deadlocks; may not work perfectly in all apps
- **Admin not required** — but some games or elevated windows may not receive injected keystrokes
- **Linux app detection is still limited** — X11 works via `xdotool`, KDE Wayland works via `kdotool`, and GNOME / other Wayland compositors still fall back to the default profile
- **Linux remapping needs device permissions** — Mouser must be able to read `/dev/input/event*` and write `/dev/uinput`. HID++ features (DPI, battery, Smart Shift) additionally require access to `/dev/hidraw*`, which most distros restrict to root by default. Create a udev rule file at `/etc/udev/rules.d/69-logitech-mouser.rules` with the following content:
  ```
  # Logitech HID++ access for Mouser (USB + Bluetooth)
  ACTION=="add", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", TAG+="uaccess"
  ACTION=="add", SUBSYSTEM=="hidraw", KERNELS=="0005:046D:*", TAG+="uaccess"
  ```
  Then reload:
  ```bash
  sudo udevadm control --reload && sudo udevadm trigger
  ```

## Future Work

- [ ] **Dedicated overlays for more devices** — add real hotspot maps and artwork for MX Anywhere, MX Vertical, and other Logitech families
- [ ] **True per-device config** — separate mappings and layout state cleanly when multiple Logitech mice are used on the same machine
- [ ] **Dynamic button inventory** — build button lists from discovered `REPROG_CONTROLS_V4` controls instead of relying on the current fixed mapping set
- [x] **Custom key combos** — user-defined arbitrary key sequences (e.g., Ctrl+Shift+P)
- [x] **Windows login item support** — cross-platform login startup via Windows registry and macOS LaunchAgent
- [ ] **Improved scroll inversion** — explore driver-level or interception-driver approaches
- [ ] **Gesture swipe tuning** — improve swipe reliability and defaults across more Logitech devices
- [ ] **Per-app profile auto-creation** — detect new apps and prompt to create a profile
- [ ] **Export/import config** — share configurations between machines
- [ ] **Tray icon badge** — show active profile name in tray tooltip
- [x] **macOS support** — added via CGEventTap, Quartz CGEvent, and NSWorkspace
- [ ] **Broader Wayland support and Linux validation** — extend app detection beyond KDE Wayland / X11 and validate across more distros and desktop environments
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
- Broader Linux/Wayland validation
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
- **[@awkure](https://github.com/awkure)** — cross-platform login startup (Windows registry + macOS LaunchAgent), single-instance guard, start minimized option, and MX Master 4 detection
- **[@hieshima](https://github.com/hieshima)** — Linux support (evdev + HID++ + uinput), mode shift button mapping, Smart Shift toggle, and custom keyboard shortcut support; Linux connection state stabilization (evdev/HID++ split readiness, HID settings replay on reconnect); macOS CGEventTap reliability (auto re-enable on timeout, trackpad scroll filtering)
- **[@pavelzaichyk](https://github.com/pavelzaichyk)** — Next Tab and Previous Tab browser actions, persistent rotating log file storage, Smart Shift enhanced support (HID++ 0x2111) with sensitivity control and scroll mode sync
- **[@nellwhoami](https://github.com/nellwhoami)** — Multi-language UI system (English, Simplified Chinese, Traditional Chinese) and Page Up/Down/Home/End navigation actions
- **[@guilamu](https://github.com/guilamu)** — Mouse-to-mouse button remapping (left, right, middle, back, forward click), HID++ stability fixes (stuck button auto-release, auto-reconnect after consecutive timeouts, async dispatch queue for Windows hook)

---

**Mouser** is not affiliated with or endorsed by Logitech. "Logitech", "MX Master", and "Options+" are trademarks of Logitech International S.A.
