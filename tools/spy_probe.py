"""Live MouseButtonSpy probe for G502 on Windows.

Opens short+long HID++ collections (same as Mouser), finds 0x8110, and
prints every notification for ~20s. Press sniper / DPI while it runs.

Usage (stop Mouser first):
  py -3 tools/spy_probe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import hid_gesture as hg


def _open_path(path):
    return hg.HidGestureListener._open_hidapi_path(path)


def main():
    if not hg.HIDAPI_OK:
        print("hidapi unavailable:", hg.HIDAPI_IMPORT_ERROR)
        return 1

    infos = hg.HidGestureListener._vendor_hid_infos()
    print(f"candidates={len(infos)}")
    for info in infos:
        pid = int(info.get("product_id", 0) or 0)
        up = int(info.get("usage_page", 0) or 0)
        usage = int(info.get("usage", 0) or 0)
        print(
            f"  PID=0x{pid:04X} UP=0x{up:04X} usage=0x{usage:04X} "
            f"product={info.get('product_string')!r} "
            f"path={hg._device_path_display(info.get('path'))}"
        )

    # Prefer Lightspeed/Bolt receiver, then any vendor collection.
    receivers = [
        i for i in infos
        if int(i.get("product_id", 0) or 0) in (
            hg.LIGHTSPEED_RECEIVER_PID,
            hg.BOLT_RECEIVER_PID,
        )
    ]
    pool = receivers or [
        i for i in infos if int(i.get("usage_page", 0) or 0) >= 0xFF00
    ]
    if not pool:
        print("no HID++ candidates")
        return 1

    primary = sorted(
        pool,
        key=lambda i: (0 if int(i.get("usage", 0) or 0) >= 2 else 1),
    )[0]
    siblings = hg._win_hidpp_siblings(primary, infos) or [primary]
    print(f"primary usage={int(primary.get('usage', 0) or 0)} siblings={len(siblings)}")

    opened = []
    write_dev = None
    write_usage = -1
    for info in siblings:
        try:
            dev = _open_path(info.get("path"))
            try:
                dev.set_nonblocking(False)
            except Exception:
                pass
            usage = int(info.get("usage", 0) or 0)
            opened.append((dev, info))
            if usage >= write_usage:
                write_dev = dev
                write_usage = usage
            print(f"opened usage=0x{usage:04X}")
        except Exception as exc:
            print(f"open failed usage={info.get('usage')}: {exc}")

    if not opened or write_dev is None:
        print("no open handles")
        return 1

    bundle = hg._WinHidppBundle(
        write_dev=write_dev,
        read_devs=tuple(d for d, _ in opened),
    )

    listener = hg.HidGestureListener()
    listener._dev = bundle
    # Lightspeed slots first, then direct.
    idx_order = (1, 2, 3, 4, 5, 6, 0xFF)
    spy_idx = None
    for idx in idx_order:
        listener._dev_idx = idx
        fi = listener._find_feature(hg.FEAT_MOUSE_BUTTON_SPY, timeout_ms=400)
        if fi is not None:
            spy_idx = fi
            print(f"MOUSE_BUTTON_SPY @0x{fi:02X} devIdx=0x{idx:02X}")
            break
        print(f"no spy on devIdx=0x{idx:02X}")

    if spy_idx is None:
        print("feature 0x8110 not found")
        bundle.close()
        return 1

    listener._mouse_button_spy_idx = spy_idx
    count = listener._request(spy_idx, 0, [], timeout_ms=800, count_timeout=False)
    print(f"getButtonCount resp={count[4] if count else None}")
    listener._enable_mouse_button_spy(timeout_ms=800)

    print("Press sniper / DPI for 20s…")
    deadline = time.time() + 20
    while time.time() < deadline:
        raw = bundle.read(64, timeout_ms=200)
        if not raw:
            continue
        msg = hg._parse(raw)
        if msg is None:
            print(f"unparsed: {hg._hex_bytes(raw)}")
            continue
        dev, feat, func, sw, params = msg
        if feat != spy_idx:
            continue
        bitmap = 0
        if len(params) >= 2:
            bitmap = (int(params[0]) << 8) | int(params[1])
        bits = [b for b in range(16) if bitmap & (1 << b)]
        print(
            f"spy notify feat=0x{feat:02X} func={func} sw={sw} "
            f"bitmap=0x{bitmap:04X} bits={bits} params={hg._hex_bytes(params[:4])}"
        )

    bundle.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
