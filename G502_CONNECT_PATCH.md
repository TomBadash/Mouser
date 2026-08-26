# G502 connect + DPI

Upstream Mouser refused to mark G502 / G502 X connected because `_try_connect`
required HID++ feature `REPROG_CONTROLS_V4` (`0x1B04`). Gaming mice do not
expose that feature.

## Connect

- Catalog flag `connect_without_reprog` on G502 family entries
- OS-level connect only when **ADJUSTABLE_DPI (0x2201)** is actually found
- Prefer Lightspeed receiver `0xC547` / vendor usage pages over WPID stubs
- Reject Windows **HID VHF Driver** interfaces (WPID e.g. `0x4099`, UP `0x59`)
  — they match the catalog but expose zero HID++ features

## DPI

Once connected on a real HID++ interface, DPI is `setSensorDpi` only.
Do not switch onboard Host mode on write (that resets the mouse).

If dump shows `adjustable_dpi: false` / empty `discovered_features`, you are
on the wrong interface — DPI cannot work until connect finds 0x2201.

## Rebuild Windows exe

```bat
setup-windows.bat
```
