# Mouser — 罗技鼠标按键映射工具

<p align="center">
  <img src="images/logo_icon.png" width="128" alt="Mouser logo" />
</p>

中文文档｜[English README](README.md)

一个轻量、开源、**完全本地运行** 的 **Logitech Options+** 替代品，用于对罗技 HID++ 鼠标进行按键/手势重映射。当前对 **MX Master** 系列体验最佳，同时也对更多罗技型号提供早期识别与通用回退 UI。

无需云端、无需罗技账号、纯本地运行。

注: 在<a href="https://github.com/TomBadash/Mouser/r">原项目</a>的基础上添加平滑滚动,添加了中文.

---

## 功能特性

### 🖱️ 按键重映射
- **重映射任意可编程按键**：中键、手势键、前进/后退、模式切换（滚轮按压）、水平滚轮等
- **按应用配置 Profile**：切换前台应用时自动切换映射（例如 Chrome vs. VS Code）
- **自定义快捷键**：可将任意组合键（如 Ctrl+Shift+P）设为按键动作
- **30+ 内置动作**：导航/浏览器/编辑/媒体/桌面等，动作标签会随平台自适配

### ⚙️ 设备控制
- **DPI / 指针速度**：200–8000 DPI 滑块与预设档位，HID++ 实时同步
- **Smart Shift 开关**：启用/关闭罗技“棘轮 ↔ 自由滚动”的自动切换
- **滚动方向反转**：垂直/水平滚动可分别反转
- **手势键 + 方向滑动**：轻点一个动作，上/下/左/右滑动可绑定不同动作

### 🖥️ 跨平台
- **Windows / macOS / Linux**：各平台使用原生 hook（WH_MOUSE_LL、CGEventTap、evdev/uinput）
- **开机自启**：Windows 注册表 + macOS LaunchAgent，并支持“启动后最小化到托盘/菜单栏”
- **单实例**：重复启动会将已运行窗口置前

### 🔌 智能连接
- **蓝牙和 Logi Bolt**：同时支持蓝牙和 Logi Bolt USB 接收器；连接方式显示在 UI 中
- **自动重连**：检测鼠标断电/重连，无需重启即可恢复完整功能
- **实时连接状态**：UI 中显示”Connected / Not Connected”
- **设备感知 UI**：MX Master 提供可点击热区的交互示意图；其他型号使用通用回退卡片

### 🌐 多语言 UI
- **English / 简体中文 / 繁體中文**：应用内即时切换，无需重启
- 语言偏好会自动保存到 `config.json` 并在下次启动恢复
- 已覆盖主要 UI：导航、鼠标页、设置页、对话框、托盘/菜单栏、权限提示等

### 🛡️ 隐私优先
- **完全本地**：配置为 JSON 文件，所有处理都在本机完成
- **托盘 / 菜单栏**：后台安静运行，随时从托盘快速访问
- **零遥测 / 零云端 / 零账号**

## 截图

<p align="center">
  <img src="images/Screenshot_mouse.png" alt="Mouser — Mouse & Profiles page" />
</p>

<p align="center">
  <img src="images/Screenshot_settings.png" alt="Mouser — Point & Scroll settings" />
</p>

## 当前支持的设备范围

| Family / model | Detection + HID++ probing | UI support |
|---|---|---|
| MX Master 4 / 3S / 3 / 2S / MX Master | Yes | Dedicated interactive `mx_master` layout |
| MX Anywhere 3S / 3 / 2S | Yes | Generic fallback card, experimental manual override |
| MX Vertical | Yes | Generic fallback card |
| Unknown Logitech HID++ mice | Best effort by PID/name | Generic fallback card |

> **说明：** 目前只有 MX Master 系列有专用的可视化热区覆盖层。其他设备仍可被识别并在 UI 中显示型号，并可尝试实验性的布局覆盖选择器；但在加入专用覆盖层前，按键热区位置可能不够精确。

## 默认映射

| Button | Default Action |
|---|---|
| Back button | Alt + Tab (Switch Windows) |
| Forward button | Alt + Tab (Switch Windows) |
| Middle click | Pass-through |
| Gesture button | Pass-through |
| Mode shift (scroll click) | Pass-through |
| Horizontal scroll left | Browser Back |
| Horizontal scroll right | Browser Forward |

## 可用动作

动作标签会随平台变化。例如 Windows 提供 `Win+D` 与 `Task View`，而 macOS 提供 `Mission Control`、`Show Desktop`、`App Expose`、`Launchpad` 等。

| Category | Actions |
|---|---|
| **Navigation** | Alt+Tab, Alt+Shift+Tab, Show Desktop, Previous Desktop, Next Desktop, Task View (Windows), Mission Control (macOS), App Expose (macOS), Launchpad (macOS) |
| **Browser** | Back, Forward, Close Tab (Ctrl+W), New Tab (Ctrl+T), Next Tab (Ctrl+Tab), Previous Tab (Ctrl+Shift+Tab) |
| **Editing** | Copy, Paste, Cut, Undo, Select All, Save, Find |
| **Media** | Volume Up, Volume Down, Volume Mute, Play/Pause, Next Track, Previous Track |
| **Custom** | User-defined keyboard shortcuts (any key combination) |
| **Other** | Do Nothing (pass-through) |

---

<a id="download-run"></a>

## 下载与运行

> **无需安装。** 下载 → 解压 → 双击运行即可。

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

### 步骤

1. 进入 [**最新 Release 页面**](https://github.com/TomBadash/Mouser/releases/latest)
2. 下载对应平台的 zip：**Mouser-Windows.zip**、**Mouser-macOS.zip**、**Mouser-Linux.zip**
3. **解压**到任意目录（桌面/文档等均可）
4. **运行**：`Mouser.exe`（Windows）、`Mouser.app`（macOS）、`./Mouser`（Linux）

完成。程序启动后会立即开始接管并重映射鼠标按键。

macOS 的辅助功能权限与登录项注意事项，请参见 [macOS 安装/权限指南](readme_mac_osx.md)。

### 你会看到什么

- 打开 **设置窗口**，显示当前设备对应的鼠标页面
- 系统托盘（右下角）出现 **托盘图标**
- 按键重映射 **立即生效**
- 关闭窗口并不会退出程序：它会继续在托盘运行
- 完全退出：右键托盘图标 → **Quit Mouser**

### 首次运行提示

- **Windows SmartScreen** 首次可能弹警告：点击 **More info** → **Run anyway**
- **Logitech Options+** 必须退出（会与 HID++ 访问冲突，导致 Mouser 异常或崩溃）
- 配置文件默认保存于：`%APPDATA%\Mouser`（Windows）、`~/Library/Application Support/Mouser`（macOS）、`~/.config/Mouser`（Linux）

---

<a id="installation"></a>

## 从源码安装

### 前置条件

- **Windows 10/11**、**macOS 12+（Monterey）**、或 **Linux（实验性；X11 + KDE Wayland 应用检测）**
- **Python 3.10+**（已在 3.14 上测试）
- 一只支持的罗技 HID++ 鼠标（蓝牙或 USB 接收器均可）；当前 MX Master 系列 UI 支持最完整
- **必须退出 Logitech Options+**（会与 HID++ 访问冲突）
- **仅 macOS：** 需要两个隐私权限：
  - **Accessibility / 辅助功能**（系统设置 → 隐私与安全性 → 辅助功能）：用于 CGEventTap 拦截鼠标按键
  - **Input Monitoring / 输入监控**（系统设置 → 隐私与安全性 → 输入监控）：用于 HID++（手势键、DPI、Smart Shift、设备名）
- **仅 Linux：** `xdotool` 用于 X11 的按应用 Profile 切换；`kdotool` 额外用于 KDE Wayland 检测
- **仅 Linux：** 需要读取 `/dev/input/event*` 和写入 `/dev/uinput` 权限（可能需要把用户加入 `input` 组）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/TomBadash/Mouser.git
cd Mouser

# 2. 创建虚拟环境
python -m venv .venv

# 3. 激活虚拟环境
.venv\Scripts\activate        # Windows (PowerShell / CMD)
source .venv/bin/activate      # macOS / Linux

# 4. 安装依赖
pip install -r requirements.txt
```

### 依赖说明

| Package | Purpose |
|---|---|
| `PySide6` | Qt Quick / QML UI framework |
| `hidapi` | HID++ communication with the mouse (gesture button, DPI) |
| `Pillow` | Image processing for icon generation |
| `pyobjc-framework-Quartz` | macOS CGEventTap / Quartz event support |
| `pyobjc-framework-Cocoa` | macOS app detection and media-key support |
| `evdev` | Linux mouse grab and virtual device forwarding (uinput) |

### 运行方式

```bash
# 方式 A：直接运行
python main_qml.py

# 方式 B：直接后台启动（托盘/菜单栏）
python main_qml.py --start-hidden

# 方式 C：使用批处理（会显示控制台窗口）
Mouser.bat

# 方式 D：使用桌面快捷方式（不显示控制台）
# 双击 Mouser.lnk
```

> **提示：** 如需不显示控制台窗口，请使用 `pythonw.exe main_qml.py` 或 `.lnk` 快捷方式。
> macOS 上 `--start-hidden` 等价于“托盘优先”的后台启动路径；登录项会使用你保存的启动设置。

macOS 传输后端临时切换（仅用于排障）：

```bash
python main_qml.py --hid-backend=iokit
python main_qml.py --hid-backend=hidapi
python main_qml.py --hid-backend=auto
```

仅用于故障排查。macOS 默认使用 `iokit`；`hidapi` 与 `auto` 仍可作为手动覆盖选项。其他平台仍默认 `auto`。

### 创建桌面快捷方式

仓库自带 `Mouser.lnk`。也可手动创建：

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Mouser.lnk")
$s.TargetPath = "C:\path\to\mouser\.venv\Scripts\pythonw.exe"
$s.Arguments = "main_qml.py"
$s.WorkingDirectory = "C:\path\to\mouser"
$s.IconLocation = "C:\path\to\mouser\images\logo.ico, 0"
$s.Save()
```

### 构建发布包（Distribution Artifacts）

#### 快速总览

| Platform | Command | Output |
|---|---|---|
| Windows | `build.bat` or `pyinstaller Mouser.spec --noconfirm` | `dist\Mouser\` |
| macOS | `./build_macos_app.sh` | `dist/Mouser.app` |
| Linux | `pyinstaller Mouser-linux.spec --noconfirm` | `dist/Mouser/` |

#### Windows 便携版构建

```bash
# 1. 安装 PyInstaller（在 venv 内）
pip install pyinstaller

# 2. 使用 spec 文件构建
pyinstaller Mouser.spec --noconfirm

# 或直接运行脚本：
build.bat
```

输出目录为 `dist\Mouser\`，将整个目录打包 zip 即可分发。

#### macOS 原生 App Bundle 构建

```bash
# 1. 安装 PyInstaller（在 venv 内）
pip install pyinstaller

# 2. 构建菜单栏 App Bundle
./build_macos_app.sh
```

输出为 `dist/Mouser.app`。脚本优先使用 `images/AppIcon.icns`；若不存在，则从 `images/logo_icon.png` 生成 `.icns`，并使用 `codesign --sign -` 对 bundle 进行 ad-hoc 签名。

#### Linux 便携版构建

```bash
# 1. 安装系统依赖
sudo apt-get install libhidapi-dev

# 2. 安装 PyInstaller（在 venv 内）
pip install pyinstaller

# 3. 使用 Linux spec 构建
pyinstaller Mouser-linux.spec --noconfirm
```

输出目录为 `dist/Mouser/`，将整个目录打包 zip 即可分发。

> **自动化发布：** 推送 `v*` 标签会触发 [release 工作流](.github/workflows/release.yml)，在 CI 中构建三平台产物并发布到 GitHub Releases。

#### 多语言支持（无需额外构建步骤）

翻译内容直接以 Python 字典形式内置在 `ui/locale_manager.py`。没有 `.ts`/`.qm` 文件，也不需要 `lupdate`/`lrelease` —— Windows/macOS/Linux 的打包流程都会自动包含该模块。新增语言步骤：

1. Add a new entry to `_TRANSLATIONS` in `ui/locale_manager.py`
2. Append the language to `AVAILABLE_LANGUAGES`
3. Rebuild as usual

---

## 工作原理

### 架构

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

### Mouse Hook（`mouse_hook.py`）

Mouser 在统一的 `MouseHook` 抽象后面，为不同平台提供原生实现：

- **Windows** — `SetWindowsHookExW` with `WH_MOUSE_LL` on a dedicated background thread, plus Raw Input for extra mouse data
- **macOS** — `CGEventTap` for mouse interception and Quartz events for key simulation
- **Linux** — `evdev` to grab the physical mouse and `uinput` to forward pass-through events via a virtual device

三平台都会进入同一套内部事件模型，并可拦截：

- `WM_XBUTTONDOWN/UP` — side buttons (back/forward)
- `WM_MBUTTONDOWN/UP` — middle click
- `WM_MOUSEHWHEEL` — horizontal scroll
- `WM_MOUSEWHEEL` — vertical scroll (for inversion)

被拦截的事件要么被 **block**（hook 返回 1）并替换成动作，要么原样 **pass-through** 交给应用处理。

### 设备目录与布局注册

- `core/logi_devices.py` resolves known product IDs and model aliases into a `ConnectedDeviceInfo` record with display name, DPI range, preferred gesture CIDs, and default UI layout key
- `core/device_layouts.py` stores image assets, hotspot coordinates, layout notes, and whether a layout is interactive or only a generic fallback
- `ui/backend.py` combines auto-detected device info with any persisted per-device layout override and exposes the effective layout to QML

### 手势键检测

罗技的手势/拇指键并不总是以标准鼠标事件出现。Mouser 采用分层检测：

1. **HID++ 2.0** (primary) — Opens the Logitech HID collection, discovers `REPROG_CONTROLS_V4` (feature `0x1B04`), ranks gesture CID candidates from the device registry plus control-capability heuristics, and diverts the best candidate. When supported, Mouser also enables RawXY movement data.
2. **Raw Input** (Windows fallback) — Registers for raw mouse input and detects extra button bits beyond the standard 5.
3. **Gesture tap/swipe dispatch** — A clean press/release emits `gesture_click`; once movement crosses the configured threshold, Mouser emits directional swipe actions instead.

### 前台应用检测（`app_detector.py`）

Polls the foreground window every 300ms using `GetForegroundWindow` → `GetWindowThreadProcessId` → process name. Handles UWP apps by resolving `ApplicationFrameHost.exe` to the actual child process.

### 引擎（`engine.py`）

核心编排器。前台应用变化时会做 **轻量化的 Profile 切换**：只清理并重新绑定回调，不会销毁 hook 线程或 HID++ 连接，从而避免完整重启带来的延迟与不稳定。引擎也会将已连接设备信息传递给 backend，让 QML 渲染正确的型号与布局状态。

### 设备重连

Mouser handles mouse power-off/on cycles automatically:

- **HID++ layer** — `HidGestureListener` detects device disconnection (read errors) and enters a reconnect loop, retrying every 2–5 seconds until the device is back
- **Hook layer** — `MouseHook` listens for `WM_DEVICECHANGE` notifications and reinstalls the low-level mouse hook when devices are added or removed
- **UI layer** — connection state and device identity flow from HID++ → MouseHook → Engine → Backend (cross-thread safe via Qt signals) → QML, updating the status badge, device name, and active layout in real time

### 配置

All settings are stored in `%APPDATA%\Mouser\config.json` (Windows) or `~/Library/Application Support/Mouser/config.json` (macOS). The config supports:
- Multiple named profiles with per-profile button mappings, including gesture tap + swipe actions
- Per-profile app associations (list of `.exe` names)
- Global settings: DPI, scroll inversion, gesture tuning, appearance, debug flags, Smart Shift, startup preferences (`start_at_login`, `start_minimized`), and display language (`language`: `"en"` / `"zh_CN"` / `"zh_TW"`)
- Per-device layout override selections for unsupported devices
- Automatic migration from older config versions

---

## 项目结构

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
│   ├── locale_manager.py    # i18n: English / Simplified Chinese / Traditional Chinese
│   └── qml/
│       ├── Main.qml         # App shell (sidebar + page stack + tray toast)
│       ├── MousePage.qml    # Merged mouse diagram + profile manager
│       ├── ScrollPage.qml   # DPI slider + scroll inversion toggles + language picker
│       ├── KeyCaptureDialog.qml  # Custom keyboard shortcut input dialog
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

## UI 概览

应用通过左侧侧边栏切换两页：

### 鼠标与配置（Mouse & Profiles，页面 1）

- **Left panel:** List of profiles. The "Default (All Apps)" profile is always present. Per-app profiles show the app icon and name. Select a profile to edit its mappings.
- **Right panel:** Device-aware mouse view. MX Master-family devices get clickable hotspot dots on the image; unsupported layouts fall back to a generic device card with an experimental "try another supported map" picker.
- **Add profile:** ComboBox at the bottom lists known apps (Chrome, Edge, VS Code, VLC, etc.). Click "+" to create a per-app profile.

### 指针与滚动（Point & Scroll，页面 2）

- **DPI slider:** 200–8000 with quick presets (400, 800, 1000, 1600, 2400, 4000, 6000, 8000). Reads the current DPI from the device on startup.
- **Scroll inversion:** Independent toggles for vertical and horizontal scroll direction.
- **Smart Shift:** Toggle Logitech Smart Shift (ratchet-to-free-spin scroll mode switching) on or off.
- **Startup controls:** **Start at login** (Windows and macOS) and **Start minimized** (all platforms) to launch directly into the system tray.

---

## 已知限制

- **Early multi-device support** — only the MX Master family currently has a dedicated interactive overlay; MX Anywhere, MX Vertical, and unknown Logitech mice still use the generic fallback card
- **Per-device mappings are not fully separated yet** — layout overrides are stored per detected device, but profile mappings are still global rather than truly device-specific
- **Bluetooth and Logi Bolt supported** — HID++ gesture button divert works over both Bluetooth and Logi Bolt USB receivers
- **Conflicts with Logitech Options+** — both apps fight over HID++ access; quit Options+ before running Mouser
- **Scroll inversion is experimental** — uses coalesced `PostMessage` injection to avoid LL hook deadlocks; may not work perfectly in all apps
- **Admin not required** — but some games or elevated windows may not receive injected keystrokes
- **Linux app detection is still limited** — X11 works via `xdotool`, KDE Wayland works via `kdotool`, and GNOME / other Wayland compositors still fall back to the default profile
- **Linux remapping needs device permissions** — Mouser must be able to read `/dev/input/event*` and write `/dev/uinput`

## 未来计划

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

## 贡献指南

欢迎贡献！快速开始：

1. Fork the repo and create a feature branch
2. 搭建开发环境（参见 [从源码安装](#installation)）
3. Make your changes and test with a supported Logitech HID++ mouse (MX Master family preferred for now)
4. Submit a pull request with a clear description

### 需要帮助的方向

- Testing with other Logitech HID++ devices
- Scroll inversion improvements
- Broader Linux/Wayland validation
- UI/UX polish and accessibility

## 支持项目

If Mouser saves you from installing Logitech Options+, consider supporting development:

<p align="center">
  <a href="https://github.com/sponsors/TomBadash">
    <img src="https://img.shields.io/badge/Sponsor-❤️-ea4aaa?style=for-the-badge&logo=githubsponsors" alt="Sponsor" />
  </a>
</p>

Every bit helps keep the project going — thank you!

## 许可证

This project is licensed under the [MIT License](LICENSE).

---

## 致谢

- **[@andrew-sz](https://github.com/andrew-sz)** — macOS port: CGEventTap mouse hooking, Quartz key simulation, NSWorkspace app detection, and NSEvent media key support
- **[@thisislvca](https://github.com/thisislvca)** — significant expansion of the project including macOS compatibility improvements, multi-device support, new UI features, and active involvement in triaging and resolving open issues
- **[@awkure](https://github.com/awkure)** — cross-platform login startup (Windows registry + macOS LaunchAgent), single-instance guard, start minimized option, and MX Master 4 detection
- **[@hieshima](https://github.com/hieshima)** — Linux support (evdev + HID++ + uinput), mode shift button mapping, Smart Shift toggle, and custom keyboard shortcut support
- **[@pavelzaichyk](https://github.com/pavelzaichyk)** — Next Tab and Previous Tab browser actions, persistent rotating log file storage, Smart Shift enhanced support (HID++ 0x2111) with sensitivity control and scroll mode sync
- **[@nellwhoami](https://github.com/nellwhoami)** - Multi-language UI system (English, Simplified Chinese, Traditional Chinese) and Page Up/Down/Home/End navigation actions

---

**Mouser** 与罗技（Logitech）无隶属关系亦未获其背书。“Logitech”“MX Master”“Options+” 为 Logitech International S.A. 的商标。
