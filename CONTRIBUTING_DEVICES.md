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
| `0x00C3` | Gesture button (physical) |
| `0x00C4` | Smart Shift / Mode Shift |
| `0x00D7` | Virtual gesture button |

Not all CIDs are divertable.  Check the `flags` field -- if bit `0x0020` is
set, the control can be intercepted by Mouser.

---

## 3. Add the device definition

### a) Add a device catalog entry

For exact device support, edit `core/logi_device_catalog.py` first. This file
holds Mouser's community-maintained per-device Logitech entries, including the
device image and hotspot coordinates used by the UI.

Add a new dict to `LOGI_DEVICE_SPECS`:

```python
{
    "key": "mx_ergo",                          # unique snake_case key
    "display_name": "MX Ergo",                 # human-readable name
    "product_ids": (0xB0XX,),                  # from your dump's product_id
    "aliases": ("Logitech MX Ergo",),          # alternative names the device may report
    "ui_layout": "mx_ergo",                    # exact layout key
    "image_asset": "logitech-mice/mx_ergo/mouse.png",
    "supported_buttons": GENERIC_BUTTONS,      # adjust to match your mouse
    "gesture_cids": (0x00C3,),                 # from gesture_candidates in your dump
    "dpi_min": 200,
    "dpi_max": 4000,                           # from discovered DPI range, or vendor specs
},
```

Pick the right button tuple for `supported_buttons`:

- `MX_MASTER_BUTTONS` -- middle, gesture (with swipes), back, forward, hscroll, mode_shift
- `MX_ANYWHERE_BUTTONS` -- middle, gesture (with swipes), back, forward
- `MX_VERTICAL_BUTTONS` -- middle, back, forward
- `GENERIC_BUTTONS` -- middle, back, forward (safe default)
- Or define a new tuple if your mouse has a unique button set.

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
"mx_ergo": {
    "key": "mx_ergo",
    "label": "MX Ergo",
    "image_asset": "logitech-mice/mx_ergo/mouse.png",
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
