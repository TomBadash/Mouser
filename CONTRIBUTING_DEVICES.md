# Contributing a New Device to Mouser

Mouser is built around the MX Master 3S because that is the only mouse the
maintainer owns.  If you have a different Logitech HID++ mouse and want Mouser
to support it, this guide walks you through the process.

---

## 1. Get a discovery dump from your mouse

1. Connect your Logitech mouse via Bluetooth or the Bolt receiver.
2. Open Mouser and go to the **Mouse** page.
3. Enable **Debug mode** in the Settings page.
4. In the debug panel that appears, click **Copy device info**.
5. The JSON blob on your clipboard describes every HID++ feature and
   reprogrammable control Mouser discovered on your device.

Paste this JSON into your GitHub issue  it is the single most useful piece of information for adding support.

### What the dump contains

| Field | What it tells us |
|---|---|
| `product_id` | USB Product ID (e.g. `0xB034`) |
| `display_name` | Name reported by the device or matched from our catalog |
| `reprog_controls` | Every button/control the device exposes via REPROG_V4 |
| `discovered_features` | Which HID++ features the device supports (DPI, SmartShift, battery, etc.) |
| `gesture_candidates` | CIDs that look like they can be diverted as gesture buttons |
| `supported_buttons` | The button set Mouser currently uses for this device |

---

## 2. Identify which buttons your mouse has

Look at the `reprog_controls` array.  Each entry has a `cid` (Control ID) and
`flags`.  Common CIDs across Logitech mice:

| CID | Typical button |
|---|---|
| `0x0050` | Left click |
| `0x0051` | Right click |
| `0x0052` | Middle click |
| `0x0053` | Back (side button) |
| `0x0056` | Forward (side button) |
| `0x00C3` | Gesture button (physical, "Thumb button" on MX Master 4) |
| `0x00C4` | Smart Shift / Mode Shift |
| `0x00D7` | Virtual gesture button |
| `0x01A0` | MX Master 4 Sense Panel (see role-swap notes below) |

MX Master 4 has two thumb-area buttons that both surface as divertable
HID++ controls and need an explicit role swap. The Sense Panel
(`0x01A0`, Solaar's `Haptic` feature -- the touch surface Logitech
markets as "Haptic Sense" and Logi Options+ exposes under the "Action
Ring" overlay) drives directional gestures because it's far more
comfortable for swipes than the small side button. The small Thumb
button (`0x00C3`, the legacy gesture CID on older MX Master variants;
Solaar's `Mouse_Gesture_Button` with the `Thumb_Button` alias on MX
Master 4) is the single-press trigger. Wire it like this:

```python
"gesture_cids": (0x01A0, 0x00C3, 0x00D7),  # Sense Panel CID first
"thumb_button_cid": 0x00C3,                # small button as button-only extra
"gesture_via_sense_panel": True,           # enables OS-level fallback swap
```

`0x01A0` lives in `gesture_cids` so the listener prefers diverting it
with rawXY. `thumb_button_cid` is diverted as button-only (no rawXY),
so the firmware doesn't suppress normal OS mouse motion while the
small button is held -- that was the root cause of the cursor-freeze
on stock MX Master 4. `gesture_via_sense_panel` enables an OS-level
`btn=6` / `BTN_TASK` swap fallback for cases where firmware rejects
the `0x01A0` divert; the platform mouse hooks consult
`active_gesture_cid` (set to `0x01A0` on success, anything else on
fallback) and `thumb_button_via_hid` (true when the extra divert is
installed) on `ConnectedDeviceInfo` to pick the right path.

Older MX Master mice (3S, 3, 2S, classic) keep `gesture_via_sense_panel
= False` (the default) so their HID++ gesture button continues to
drive swipes and the global `Gesture button` label is shown.

Not all CIDs are divertable.  Check the `flags` field -- if bit `0x0020` is
set, the control can be intercepted by Mouser.
Directional gesture mappings also require RawXY support (`0x0100` or
`0x0200`) and a successful RawXY divert during connection.

---

## 3. Add the device definition

### a) Add a device catalog entry

For exact device support, edit `core/logi_device_catalog.py` first. This file
holds Mouser's community-maintained per-device Logitech entries, including the
device image and hotspot coordinates used by the UI.

Add a new dict to `LOGI_DEVICE_SPECS`:

```python
{
    "key": "example_mouse",                    # unique snake_case key
    "display_name": "Example Mouse",           # human-readable name
    "product_ids": (0xB0XX,),                  # from your dump's product_id
    "aliases": ("Logitech Example Mouse",),    # alternative names the device may report
    "ui_layout": "example_mouse",              # exact layout key
    "image_asset": "logitech-mice/example_mouse/mouse.png",
    "supported_buttons": GENERIC_BUTTONS,      # adjust to match your mouse
    "gesture_cids": (0x00C3,),                 # from gesture_candidates in your dump
    "dpi_min": 200,
    "dpi_max": 4000,                           # from discovered DPI range, or vendor specs
    "has_hires_wheel": False,                  # set True if device exposes 0x2121
    "has_thumbwheel": False,                   # set True if device exposes 0x2150
},
```

#### `has_hires_wheel` and `has_thumbwheel`

These flags tell Mouser the device exposes the corresponding HID++ feature so it
can divert the wheel and apply scroll inversion at the source (matching Logitech
Options+ behavior). They're catalog hints only — runtime feature discovery in
`HidGestureListener` always overrides them, so a wrong catalog flag won't cause
a divert attempt against a non-existent feature.

Set them on every device you can confirm exposes the feature. Quick way to find
out: connect the device, run Mouser with debug logs enabled, and look for
`[HidGesture] Found wheel feature 0x2121` (HiResWheel) or `Found wheel feature
0x2150` (Thumbwheel) in the output.

| Flag | True when device has |
|---|---|
| `has_hires_wheel` | A vertical scroll wheel that supports HID++ feature `0x2121` (HiResWheel). Most modern Logitech mice. |
| `has_thumbwheel` | A horizontal thumbwheel that supports HID++ feature `0x2150` (Thumbwheel). MX Master family only. |

Pick the right button tuple for `supported_buttons`:

- `MX_MASTER_BUTTONS` -- middle, gesture (with swipes), back, forward, hscroll, mode_shift
- `MX_MASTER_4_BUTTONS` -- everything in `MX_MASTER_BUTTONS` plus
  `thumb_button`, the slot fed by the small Thumb button (CID `0x00C3`
  via HID++) and -- on fallback paths where the Sense Panel divert was
  rejected -- by the Sense Panel itself (button 6 / `BTN_TASK` at the
  OS layer)
- `MX_ANYWHERE_BUTTONS` -- middle, gesture (with swipes), back, forward
- `MX_VERTICAL_BUTTONS` -- middle, back, forward
- `GENERIC_BUTTONS` -- middle, back, forward (safe default)
- Or define a new tuple if your mouse has a unique button set.

`supported_buttons` is a static fallback.  When Mouser connects through HID++
and discovers `REPROG_V4` controls, it may narrow HID++-gated buttons such as
gesture, Smart Shift / mode shift, and DPI switch based on the runtime control
table.  Unknown CIDs are intentionally not exposed until Mouser has code that
knows how to handle them.  Horizontal scroll remains catalog-driven because
some devices implement it as OS events or side-button + wheel behavior instead
of a standalone reprogrammable control.

Use `core/logi_devices.py` only when you are adding a broader family fallback
without exact art yet.

### b) Add an exact interactive layout

If you want the mouse page to show an interactive diagram with clickable
hotspot dots, add a layout dict in `core/logi_device_catalog.py` instead of
growing `core/device_layouts.py`:

1. Create a small image set for your mouse and place it in
   `images/logitech-mice/<device-key>/`.
2. Add a layout dict to `LOGI_DEVICE_LAYOUTS`:

```python
"example_mouse": {
    "key": "example_mouse",
    "label": "Example Mouse",
    "image_asset": "logitech-mice/example_mouse/mouse.png",
    "image_width": 260,
    "image_height": 400,
    "interactive": True,
    "manual_selectable": False,
    "note": "",
    "hotspots": [
        {
            "buttonKey": "middle",      # must match a supported_buttons entry
            "label": "Middle button",
            "summaryType": "mapping",   # "mapping", "gesture", or "hscroll"
            "normX": 0.50,              # 0-1, fraction of image width
            "normY": 0.30,              # 0-1, fraction of image height
            "labelSide": "right",       # "left" or "right"
            "labelOffX": 150,           # pixel offset for the annotation line
            "labelOffY": -60,
        },
    ],
},
```

`core/device_layouts.py` still owns shared manual family layouts such as
`mx_master`, `mx_anywhere`, and `mx_vertical`.  Keep those family entries
manual-selectable; keep exact per-device layouts auto-detected only.

### Estimating hotspot coordinates

Open your image in any editor that shows cursor coordinates.  Divide the
cursor X by image width and cursor Y by image height to get `normX`/`normY`.
The label offset values control where the annotation text appears relative to
the dot -- experiment with positive/negative values until it looks right.

### Keep it small

- Prefer focused, reviewable device entries over large multi-device changes.
- Keep image assets and hotspot data close to what the UI actually uses.
- Prefer exact per-device entries for hardware that has been checked in-app.
- If the device is only partially understood, add a family fallback first and
  leave the exact layout for a follow-up contribution.

---

## 4. Test your changes

```bash
python main_qml.py
```

- Connect your mouse and verify it is detected with the correct name.
- Check that only the buttons your mouse actually has appear in the UI.
- Test assigning actions to each button.
- If you added an interactive layout, verify the hotspot dots line up with the
  mouse image.

---

## 5. Submit a pull request

Include:
- The device discovery dump (JSON) in the PR description.
- Which buttons you tested and confirmed working.
- A photo or screenshot of the interactive layout (if applicable).
- The Logitech model name and any alternative names your OS reports.

Even a partial contribution helps -- if you can provide just the discovery dump,
someone else can wire up the layout later.

---

## FAQ

**Q: My mouse connects but Mouser says "Logitech PID 0xXXXX".**
A: Your PID is not in the catalog yet.  Follow step 3a to add it.

**Q: My mouse has a button Mouser does not know about.**
A: Check the CID in your dump against the REPROG_V4 flags.  If it is
divertable, it can potentially be supported.  Open an issue describing the
button and its CID.

**Q: I do not have a nice image for the interactive layout.**
A: That is fine!  Skip step 3b entirely -- the fallback button list still lets
users configure every button.  Someone else can contribute the image later.

**Q: Mouser works on my mouse but a button does not respond.**
A: Some CIDs require specific divert flags.  Share your discovery dump in an
issue so we can investigate.
