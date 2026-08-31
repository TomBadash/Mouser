# Mouser Focus Watcher — GNOME Shell Extension

Track the currently focused window on GNOME/Wayland and expose it via **D-Bus** — inspired by [flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus).

## Why?

Mouser's [AppDetector](../../../core/app_detector.py) currently **cannot detect the foreground application on GNOME/Wayland** (it returns an empty tuple). This extension solves that by:

1. Listening to Mutter's window focus events via `Shell.WindowTracker`
2. Exposing the focused window's details — **pid**, **id**, **title**, **wm_class**, **wm_class_instance**, and **executable** path — as a JSON string over D-Bus

## Architecture

```text
┌──────────────────────┐    D-Bus signal        ┌───────────────────┐
│  GNOME Shell         │ ◄───────────────────── │  Mouser/App       │
│  Focus Watcher Ext.  │   FocusChanged(payload)│  Detector         │
│                      │                        │  (Python)         │
│                      │                        │                   │
│  Shell.WindowTracker ┘                        │  D-Bus:           │
│    notify::focus-app  ───────► org.mouser.     │    GetFocusApp()  │
│                             FocusWatcher       │                   │
│                                                 └───────────────────┘
└──────────────────────┘                               │
                                                        ▼
                                                ┌───────────────────┐
                                                │  Mouser Engine    │
                                                │  per-app profiles │
                                                └───────────────────┘
```

## D-Bus Interface

```text
Service:   org.mouser.FocusWatcher
Object:    /github/mouser
Interface: org.mouser.FocusWatcher

Method: GetFocusApp() → (s)   // JSON string of the focused window
Signal: FocusChanged(s)       // JSON string whenever focus changes
```

Both `GetFocusApp()` and the `FocusChanged` signal carry a **JSON string** of the currently focused window:

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

Notes on the payload:

| Field | Description |
|-------|-------------|
| `id` | Mutter window id (`MetaWindow.get_id()`) |
| `pid` | Process id of the focused window (`MetaWindow.get_pid()`) |
| `title` | Window title (`MetaWindow.get_title()`) |
| `wm_class` | WM class (`MetaWindow.get_wm_class()`) |
| `wm_class_instance` | WM class instance (`MetaWindow.get_wm_class_instance()`) |
| `executable` | Resolved path of `/proc/<pid>/exe`; empty string (`""`) if unavailable |

## Files

| File | Description |
|------|-------------|
| `extension.js` | Main extension for GNOME 45+ (ESM module system) |
| `metadata.json` | Extension manifest for GNOME 45+ (shell-version 45–50) |

## Usage

The extension is meant to be consumed by Mouser's `app_detector.py` or any other D-Bus client.

### Query the focused window (one-shot)

```bash
gdbus call --session \
  --dest org.mouser.FocusWatcher \
  --object-path /github/mouser \
  --method org.mouser.FocusWatcher.GetFocusApp
```

### Listen for focus changes

```bash
gdbus monitor --session --dest org.mouser.FocusWatcher
# or watch the signal directly:
gdbus monitor --session org.mouser.FocusWatcher /github/mouser org.mouser.FocusWatcher.FocusChanged
```

## Installation

```bash
# 1. Install the extension
mkdir -p ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app
cp packaging/linux/gnome-focus-watcher/extension.js ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app/
cp packaging/linux/gnome-focus-watcher/metadata.json ~/.local/share/gnome-shell/extensions/focus-watcher@mouser.app/

# 2. Restart GNOME Shell (on X11: Alt+F2, type 'r', Enter; on Wayland: log out and back in)

# 3. Enable the extension
gnome-extensions enable focus-watcher@mouser.app

# 4. Verify
gnome-extensions show focus-watcher@mouser.app
gdbus call --session --dest org.mouser.FocusWatcher \
  --object-path /github/mouser \
  --method org.mouser.FocusWatcher.GetFocusApp
```

## Credits

- Inspired by [flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus)
