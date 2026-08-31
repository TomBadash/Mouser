# Mouser 焦点监视器 — GNOME Shell 扩展

在 GNOME/Wayland 下跟踪当前聚焦的窗口，并通过 **D-Bus** 暴露其信息 — 灵感来自 [flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus)。

## 为什么需要它？

Mouser 的 [AppDetector](../../../core/app_detector.py) 目前**无法在 GNOME/Wayland 下检测到前台应用**（它返回空元组）。本扩展通过以下方式解决该问题：

1. 通过 `Shell.WindowTracker` 监听 Mutter 的窗口焦点事件
2. 将当前聚焦窗口的详细信息 — **pid**、**id**、**title**、**wm_class**、**wm_class_instance** 和 **executable**（可执行文件路径）— 以 JSON 字符串的形式通过 D-Bus 暴露

## 架构

```text
┌──────────────────────┐    D-Bus 信号         ┌───────────────────┐
│  GNOME Shell         │ ◄───────────────────── │  Mouser/App       │
│  焦点监视器扩展       │   FocusChanged(payload) │  检测器           │
│                      │                        │  (Python)         │
│                      │                        │                   │
│  Shell.WindowTracker ┘                        │  D-Bus:           │
│    notify::focus-app  ───────► org.mouser.     │    GetFocusApp()  │
│                             FocusWatcher       │                   │
│                                                 └───────────────────┘
└──────────────────────┘                               │
                                                        ▼
                                                ┌───────────────────┐
                                                │  Mouser 引擎      │
                                                │  按应用配置文件   │
                                                └───────────────────┘
```

## D-Bus 接口

```text
Service:   org.mouser.FocusWatcher
Object:    /github/mouser
Interface: org.mouser.FocusWatcher

Method: GetFocusApp() → (s)   // 当前聚焦窗口的 JSON 字符串
Signal: FocusChanged(s)       // 焦点变化时发送 JSON 字符串
```

`GetFocusApp()` 和 `FocusChanged` 信号都会携带当前聚焦窗口的 **JSON 字符串**：

```json
{
  "id": 12345,
  "pid": 6789,
  "title": "Terminal — Mozilla Firefox",
  "wm_class": "firefox",
  "wm_class_instance": "Navigator",
  "executable": "/usr/lib/firefox/firefox"
}
```

字段说明：

| 字段 | 说明 |
|-------|-------------|
| `id` | Mutter 窗口 id（`MetaWindow.get_id()`） |
| `pid` | 聚焦窗口对应的进程 id（`MetaWindow.get_pid()`） |
| `title` | 窗口标题（`MetaWindow.get_title()`） |
| `wm_class` | WM class（`MetaWindow.get_wm_class()`） |
| `wm_class_instance` | WM class 实例（`MetaWindow.get_wm_class_instance()`） |
| `executable` | 通过 `/proc/<pid>/exe` 解析出的可执行文件路径；无法获取时为空字符串（`""`） |

## 文件

| 文件 | 说明 |
|------|-------------|
| `extension.js` | 适用于 GNOME 45+ 的主扩展（ESM 模块系统） |
| `metadata.json` | GNOME 45+ 的扩展清单（shell-version 45–50.1） |

## 使用方法

本扩展供 Mouser 的 `app_detector.py` 或其他任何 D-Bus 客户端使用。

### 一次性查询聚焦窗口

```bash
gdbus call --session \
  --dest org.mouser.FocusWatcher \
  --object-path /github/mouser \
  --method org.mouser.FocusWatcher.GetFocusApp
```

### 监听焦点变化

```bash
gdbus monitor --session --dest org.mouser.FocusWatcher
# 或直接监听该信号：
gdbus monitor --session org.mouser.FocusWatcher /github/mouser org.mouser.FocusWatcher.FocusChanged
```

## 安装

```bash
# 1. 安装扩展
mkdir -p ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app
cp packaging/linux/gnome-focus-watcher/extension.js ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app/
cp packaging/linux/gnome-focus-watcher/metadata.json ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app/

# 2. 重启 GNOME Shell（X11：Alt+F2，输入 'r'，回车；Wayland：注销后重新登录）

# 3. 启用扩展
gnome-extensions enable focus-watcher@mouser.app

# 4. 验证
gnome-extensions show focus-watcher@mouser.app
gdbus call --session --dest org.mouser.FocusWatcher \
  --object-path /github/mouser \
  --method org.mouser.FocusWatcher.GetFocusApp
```

## 致谢

- 灵感来自 [flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus)
