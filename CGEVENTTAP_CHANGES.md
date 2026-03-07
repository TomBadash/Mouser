# CGEventTap Implementation — Active Event Blocking

## Summary

The macOS mouse hook has been upgraded from **passive NSEvent monitors** to **active CGEventTap filtering**. This change allows LogiControl to completely block the original button actions when remapped, preventing double-firing.

---

## What Changed

### Before (NSEvent Monitors)
- **Passive observation only** — could see events but not suppress them
- Original button action would fire alongside the remapped action
- Simple to implement but limited functionality

### After (CGEventTap)
- **Active event filtering** — can intercept and suppress events
- When a button is remapped, the original action is blocked completely
- Only the remapped action fires
- Returns `None` from the callback to suppress, or passes the event through

---

## Technical Details

### Key Changes in `mouse_hook.py`

1. **Import Quartz framework** (in addition to AppKit)
   ```python
   import Quartz
   ```

2. **Replaced NSEvent monitors with CGEventTap**
   - Uses `CGEventTapCreate()` to create an active filter
   - Event mask includes: `kCGEventOtherMouseDown`, `kCGEventOtherMouseUp`, `kCGEventScrollWheel`
   - Tap location: `kCGSessionEventTap` (current user session)
   - Tap placement: `kCGHeadInsertEventTap` (beginning of event queue)
   - Tap option: `kCGEventTapOptionDefault` (can modify/suppress events)

3. **New callback interface**
   ```python
   def _event_tap_callback(self, proxy, event_type, cg_event, refcon):
       # Process event, call registered callbacks
       # Return None to suppress, or return cg_event to pass through
       if should_block:
           return None  # Suppress
       else:
           return cg_event  # Pass through
   ```

4. **Integrated with Qt run loop**
   - Created `CFMachPortCreateRunLoopSource` from the tap
   - Added to current run loop with `CFRunLoopAddSource`
   - No separate thread needed — runs on Qt/Cocoa event loop

5. **Proper cleanup**
   - `CGEventTapEnable(tap, False)` to disable
   - `CFRunLoopRemoveSource()` to detach from run loop
   - Release resources properly on stop

---

## Event Blocking Logic

The tap callback checks the `_blocked_events` set:

```python
# Example: Back button (xbutton1)
if btn == _BTN_BACK:
    mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
    should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events

# ... dispatch the event to callbacks ...

if should_block:
    return None  # Original action is suppressed
else:
    return cg_event  # Original action passes through
```

When the Engine configures a remapping, it calls:
```python
mouse_hook.block(MouseEvent.XBUTTON1_DOWN)
mouse_hook.block(MouseEvent.XBUTTON1_UP)
```

This adds those event types to the blocked set, causing the tap to suppress them.

---

## Requirements

### Accessibility Permission

**Critical:** CGEventTap requires Accessibility permission to intercept events.

Grant access in:
```
System Settings → Privacy & Security → Accessibility
```

Add your terminal app (Terminal.app, iTerm2, etc.) or the Python executable to the list.

**Without this permission, the tap creation will fail with:**
```
[MouseHook] ERROR: Failed to create CGEventTap!
```

---

## Testing

1. **Verify the tap is created:**
   ```bash
   python main_qml.py
   ```
   
   Look for these log messages:
   ```
   [MouseHook] start: creating CGEventTap...
   [MouseHook] CGEventTap created successfully
   [MouseHook] CGEventTap enabled and integrated with run loop
   [MouseHook] FIRST EVENT: CGEventTap callback received
   ```

2. **Test event blocking:**
   - Configure a button remapping (e.g., Back button → Cmd+Left Arrow)
   - Press the back button
   - **Expected:** Only the remapped action (Cmd+Left) fires
   - **Before fix:** Both the browser back action AND Cmd+Left would fire

3. **Test pass-through:**
   - Disable remapping for a button
   - Press the button
   - **Expected:** Original action fires normally (browser back, etc.)

4. **Check for permission issues:**
   - If you see "Failed to create CGEventTap", check Accessibility settings
   - The app may need to be restarted after granting permission

---

## Diagnostic Flags

The existing flags still work:

```bash
# Skip CGEventTap (no button remapping)
python main_qml.py --no-monitors

# Skip HID gesture button
python main_qml.py --no-hid

# Both
python main_qml.py --no-monitors --no-hid
```

---

## Compatibility

- **Tested on:** macOS Sequoia (15.x)
- **Python:** 3.10+
- **Dependencies:** `pyobjc-framework-Quartz` (already in requirements.txt)
- **Device:** MX Master 3S via Bluetooth

---

## Comparison with Windows

Both platforms now have **equivalent active filtering** capabilities:

| Platform | Hook API | Can Block? |
|---|---|---|
| Windows | `SetWindowsHookExW` (WH_MOUSE_LL) | ✅ Yes (return 1) |
| macOS (old) | NSEvent global monitors | ❌ No (passive) |
| macOS (new) | CGEventTap | ✅ Yes (return None) |

---

## Troubleshooting

### "Failed to create CGEventTap"
- **Cause:** Missing Accessibility permission
- **Fix:** System Settings → Privacy & Security → Accessibility → Add your terminal app

### Events not being blocked
- **Check:** Is the event type in `_blocked_events`?
- **Check:** Is the callback returning `None` for that event?
- **Debug:** Enable `debug_mode` to see callback logs

### Cursor freezes on button press
- **Cause:** HID exclusive access issue (separate from CGEventTap)
- **Fix:** Already handled by `hid_darwin_set_open_exclusive(0)`

---

## Files Modified

1. **core/mouse_hook.py**
   - Added `import Quartz`
   - Replaced `_monitors` list with `_tap` and `_tap_source`
   - Replaced NSEvent handler methods with `_event_tap_callback()`
   - Updated `start()` to create CGEventTap
   - Updated `stop()` to disable and remove tap
   - Updated docstring to reflect active filtering

2. **readme_mac_osx.md**
   - Updated "Mouse Hook" section to describe CGEventTap
   - Updated architecture comparison table
   - Removed "NSEvent monitors are passive" from Known Limitations
   - Emphasized Accessibility permission requirement

---

**Result:** LogiControl now has feature parity with the Windows version — remapped buttons are properly blocked and do not trigger their original actions.
