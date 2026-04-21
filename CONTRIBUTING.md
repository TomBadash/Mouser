# Contributing

## Structure

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

<hr />

<p align="center">
<img src=".github/assets/project-structure_banner_en.png" alt="Project Structure Banner" />
</p>

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

<hr />

<p align="center">
<img src=".github/assets/ui-overview_banner_en.png" alt="UI Overview Banner" />
</p>

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

<hr />

<p align="center">
<img src=".github/assets/known-limitations_banner_en.png" alt="Known Limitations Banner" />
</p>

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

<hr />

<p align="center">
<img src=".github/assets/future-work_banner_en.png" alt="Future Work Banner" />
</p>

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
