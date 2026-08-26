"""Guided G502 HID++ capture: mash current button, SPACE = next.

Uses GetAsyncKeyState so SPACE works without focusing this window.
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import hid_gesture as hg

VK_SPACE = 0x20
USER32 = ctypes.windll.user32

BUTTONS = (
    "LEFT click",
    "RIGHT click",
    "MIDDLE click",
    "SNIPER (thumb DPI-shift)",
    "DPI button (behind wheel)",
    "BACK (thumb)",
    "FORWARD (thumb)",
    "SCROLL TILT LEFT",
    "SCROLL TILT RIGHT",
    "DPI UP (if present)",
    "DPI DOWN (if present)",
)


def space_edge(prev: bool) -> tuple[bool, bool]:
    down = bool(USER32.GetAsyncKeyState(VK_SPACE) & 0x8000)
    return down, (down and not prev)


def main() -> int:
    if not hg.HIDAPI_OK:
        print("hidapi unavailable")
        return 1

    infos = [
        i
        for i in hg.HidGestureListener._vendor_hid_infos()
        if int(i.get("product_id", 0) or 0) == hg.LIGHTSPEED_RECEIVER_PID
    ]
    if not infos:
        print("no Lightspeed receiver")
        return 1

    primary = sorted(
        infos,
        key=lambda i: (0 if int(i.get("usage", 0) or 0) >= 2 else 1),
    )[0]
    siblings = hg._win_hidpp_siblings(primary, infos) or [primary]
    opened = []
    write = None
    write_usage = -1
    for info in siblings:
        dev = hg.HidGestureListener._open_hidapi_path(info.get("path"))
        dev.set_nonblocking(False)
        usage = int(info.get("usage", 0) or 0)
        opened.append(dev)
        if usage >= write_usage:
            write = dev
            write_usage = usage

    bundle = hg._WinHidppBundle(write_dev=write, read_devs=tuple(opened))
    listener = hg.HidGestureListener()
    listener._dev = bundle
    listener._dev_idx = 1

    spy = listener._find_feature(hg.FEAT_MOUSE_BUTTON_SPY, timeout_ms=800)
    onboard = listener._find_feature(hg.FEAT_ONBOARD_PROFILES, timeout_ms=500)
    print(f"spy_idx={spy} onboard_idx={onboard}", flush=True)
    if spy is not None:
        listener._mouse_button_spy_idx = spy
        listener._enable_mouse_button_spy(timeout_ms=400)

    print(
        "\nMash the named mouse button. Press SPACE to advance.\n"
        "SPACE again on the last button finishes.\n",
        flush=True,
    )
    time.sleep(0.5)

    # Drain stuck SPACE from launching.
    space_down = True
    while space_down:
        space_down, _ = space_edge(False)
        time.sleep(0.05)
    time.sleep(0.2)

    results = []
    for index, label in enumerate(BUTTONS):
        print(f"\n>>> [{index + 1}/{len(BUTTONS)}] {label}", flush=True)
        print("    mash it, then SPACE = next", flush=True)
        try:
            ctypes.windll.kernel32.Beep(880, 100)
        except Exception:
            pass

        hits = []
        prev_space = False
        # Wait until SPACE advances (no fixed timeout).
        while True:
            space_down, edged = space_edge(prev_space)
            prev_space = space_down
            if edged:
                break

            raw = bundle.read(64, timeout_ms=40)
            if not raw:
                continue
            msg = hg._parse(raw)
            if msg is None:
                line = f"raw {hg._hex_bytes(raw[:14])}"
                print(f"    {line}", flush=True)
                hits.append(line)
                continue
            _dev, feat, func, sw, params = msg
            line = (
                f"feat=0x{feat:02X} fn={func} sw={sw} "
                f"params={hg._hex_bytes(params[:8])}"
            )
            print(f"    HIT {line}", flush=True)
            hits.append(line)

        print(f"<<< {label}: {len(hits)} hits", flush=True)
        results.append((label, hits))
        # Debounce SPACE.
        time.sleep(0.25)
        while True:
            space_down, _ = space_edge(False)
            if not space_down:
                break
            time.sleep(0.05)

    print("\n======== SUMMARY ========", flush=True)
    for label, hits in results:
        print(f"{label}: {len(hits)} hits", flush=True)
        for hit in hits[:12]:
            print(f"  {hit}", flush=True)
        if len(hits) > 12:
            print(f"  ... +{len(hits) - 12} more", flush=True)

    bundle.close()
    print("\nALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
