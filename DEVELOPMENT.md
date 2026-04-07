# Development Guide

This document contains technical details designed to help new developers understand the core components of the Mouser project.

## Entry Point: `main_qml.py`

`main_qml.py` is the primary launch script for Mouser, bringing together the core processing logic (Engine) and the graphical user interface (QML Backend). It replaces an older `tkinter`-based interface.

### What the Code is Responsible For

- **Environment Setup:** Defines absolute paths to handle both dev environments and frozen PyInstaller executables (`.app` bundles on macOS, `_internal` on Windows).
- **App Initialization:** Creates the `QApplication` and configures the Qt Material theme.
- **Engine Bootstrapping:** Initializes the core HID (Human Interface Device) engine and the UI backend.
- **QML Loading:** Registers context properties and image providers, then loads `Main.qml`.
- **System Integration:** Sets up the OS system tray / menu-bar icon, checks macOS accessibility permissions, syncs login-item state, and binds system-wide dark/light mode states.

### Key Classes and Functions

- `main()`: The main entry point. Orchestrates the startup sequence, initializes the `Engine` and `Backend`, loads the QML files, exposes Python objects to QML, creates the system tray, and starts the Qt event loop (`app.exec()`).
- `UiState(QObject)`: A bridge class that tracks the OS's system appearance (Dark vs. Light mode) and exposes it to the QML frontend via Qt Properties and Signals.
- `_check_accessibility()`: A macOS-specific function that checks (and prompts) the user for Accessibility Permissions. This is crucial for intercepting or simulating mouse/keyboard events on Mac.
- `core/accessibility.py`: Centralizes the native macOS trust check used by both startup and backend-exposed state.
- `core/startup.py`: Owns login startup integration on both Windows and macOS, including the per-user macOS LaunchAgent used by the **Start at login** UI toggle.
- `AppIconProvider` & `SystemIconProvider`: Subclasses of `QQuickImageProvider`. QML uses these to request images dynamically (e.g., rendering SVGs cleanly at various DPIs or reading native file icons via `QFileIconProvider`).
- `_app_icon()`, `_tray_icon()`, & `_render_svg_pixmap()`: Utility functions that construct high-resolution (`QIcon` / `QPixmap`) icons for the taskbar and the system tray, handling platform differences.

### How Data Flows Through the Code

1. **Configuration Flow:** Command-line args are parsed (`_parse_cli_args`) to configure hardware specifics like `--hid-backend` and startup behavior such as `--start-hidden`.
2. **Setup Flow:** The `Engine()` (core logic) and `Backend()` (QML interface) are instantiated.
3. **QML Binding:** Instances of the `Backend` and `UiState` are injected directly into the QML engine's root context. This allows the QML JavaScript/UI layer to read application state and invoke methods on the Python objects.
4. **Execution Flow:**
   - `qml_engine.load(...)` parses and renders `Main.qml`.
   - A deferral (`QTimer.singleShot(0, ...)`) is queued to start the `Engine` asynchronously.
   - If `--start-hidden` is present, the window is kept hidden and Mouser starts as a tray / menu-bar app first.
   - Execution hands over to `app.exec()`, blocking the main thread to run the Qt UI event loop.
   - `engine.stop()` gracefully shuts down background threads when the Qt event loop terminates.

### Non-Obvious Decisions and Tradeoffs

- **PyInstaller Pathing (`getattr(sys, "frozen", ...)`)**: Handles the different execution environments. Running via `python main_qml.py` uses local paths, but running a compiled PyInstaller build uses paths nested in the macOS `.app/Contents/Resources` or Windows `_internal` folders.
- **Deferred Engine Start:** The core `engine.start()` is wrapped in `QTimer.singleShot(0, ...)`. This ensures the graphical window renders and appears BEFORE the potentially blocking process of binding to HID devices occurs.
- **Hardcoded PySide6 Plugin Paths:** `QML2_IMPORT_PATH` and `QT_PLUGIN_PATH` are manually set via `os.environ` to work around PyInstaller/PySide6 edge cases where the QML engine fails to locate basic QML modules when bundled.
- **LaunchAgent Wiring:** macOS autostart is implemented as a per-user LaunchAgent that launches either the frozen app executable or the current interpreter plus `main_qml.py`, so the same UI toggle works in packaged and source-based workflows.
- **Centralized Accessibility Check:** The backend and startup path share the same native trust check from `core/accessibility.py`, avoiding drift between the permission banner and the live settings state.
- **macOS System Tray Contrast:** The system tray icon provides two different SVGs (black and white) marked as `Normal` and `Selected`. This macOS-specific trick ensures the menu bar icon automatically inverts color appropriately when the user selects it or toggles dark/light mode.
- **macOS Debugging (`SIGUSR1`):** A custom signal handler `signal.signal(signal.SIGUSR1, _dump_threads)` is registered, providing developers a hidden way to dump all thread stack traces directly to the terminal via `kill -SIGUSR1 <pid>`. This is highly useful for debugging cross-thread freezing bugs without a debugger attached.
- **Startup Benchmarks:** Explicit timing logic (`_t0`, `_t1`, ..., `_t8`) is used to profile startup times. Because importing heavy UI frameworks like Qt in Python can be slow, this enforces performance budgets.
