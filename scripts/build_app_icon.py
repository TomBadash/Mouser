"""Build the platform icon assets from the canonical master PNG.

Inputs
------
``images/logo_icon.png``
    Canonical 1024 x 1024 RGBA master of the app icon. Conforms to the
    Apple Big Sur / Tahoe icon grid: an ~824 px squircle centred on a
    1024 px canvas with ~100 px transparent gutter on every side so
    macOS can composite the standard drop shadow without clipping.

Outputs (regenerated in place)
------------------------------
``images/AppIcon.icns``
    Multi-resolution Apple Icon Image (.icns) for the macOS bundle:
    16, 32, 128, 256, 512 + their ``@2x`` Retina variants, all derived
    by Lanczos-down-sampling the master. Consumed by ``Mouser-mac.spec``
    via ``CFBundleIconFile``.

``images/logo.ico``
    Multi-resolution Windows icon (.ico) at 16, 24, 32, 48, 64, 128, 256.
    The squircle is re-fit to ~96% of the canvas so the 16 px
    representation stays legible -- Windows taskbars do not allocate
    macOS-style gutter for drop shadows. Consumed by ``Mouser.spec`` on
    the Windows build path.

``packaging/linux/icons/hicolor/<size>x<size>/apps/io.github.tombadash.mouser.png``
    Linux icon-theme PNG ladder for portable zip desktop integration.
    Uses the same fitted icon body as the Windows asset so small KDE
    taskbar entries stay legible.

Tooling
-------
* ``iconutil`` (macOS-only, built into the OS) for ``.icns`` assembly.
* ``sips`` (macOS-only, built into the OS) for the per-size resample.
* ``Pillow`` (Python, declared in ``requirements.txt``) for the
  Windows variant resize, ``.ico`` write, and Linux PNG ladder.

Run
---
``python scripts/build_app_icon.py`` from the repository root. Exits
non-zero with an explicit error if a required tool is missing, the
master is missing or wrong-shaped, or any sub-process fails -- so CI
can wire it into a verification stage without ambiguity.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "images" / "logo_icon.png"
OUT_ICNS = ROOT / "images" / "AppIcon.icns"
OUT_ICO = ROOT / "images" / "logo.ico"
OUT_LINUX_HICOLOR = ROOT / "packaging" / "linux" / "icons" / "hicolor"

MAC_CANVAS = 1024
WIN_CANVAS = 1024
LINUX_ICON_NAME = "io.github.tombadash.mouser"
# Apple icon grid: 824 squircle on 1024 canvas (10% gutter each side).
# Microsoft Learn / Linux taskbars: no fixed gutter; 96% fill keeps the
# 16 px tile readable.
SMALL_SURFACE_FILL_RATIO = 980 / 1024

ICNS_SIZES = (16, 32, 128, 256, 512)
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256))
LINUX_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


class BuildIconError(SystemExit):
    """Raised for every recoverable build-time failure.

    Subclass of :class:`SystemExit` so an unhandled raise still exits
    the process with a non-zero status, but the type can be caught by
    tests without also catching unrelated SystemExits (e.g. argparse).
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"build_app_icon.py: {message}")


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise BuildIconError(
            f"required tool not found: {name!r}. "
            "Run on macOS; iconutil and sips ship with the OS."
        )
    return path


def _validate_master(master_path: Path = MASTER) -> Image.Image:
    if not master_path.is_file():
        raise BuildIconError(f"master missing at {master_path}")
    try:
        with Image.open(master_path) as source:
            image = source.copy()
    except Exception as exc:  # pragma: no cover - Pillow wraps many error types
        raise BuildIconError(f"master at {master_path} is not a valid image: {exc}") from exc
    if image.mode != "RGBA":
        raise BuildIconError(f"master must be RGBA, got {image.mode!r}")
    if image.size != (MAC_CANVAS, MAC_CANVAS):
        raise BuildIconError(
            f"master must be {MAC_CANVAS}x{MAC_CANVAS}, "
            f"got {image.size[0]}x{image.size[1]}"
        )
    return image


def _run_tool(argv: list[str]) -> None:
    """Run an external CLI tool and surface stderr on failure.

    ``subprocess.run(check=True)`` raises :class:`CalledProcessError`
    on non-zero exit but the user only sees a Python traceback. We
    capture stderr explicitly so the failure message is actionable.
    """
    try:
        subprocess.run(
            argv,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise BuildIconError(
            f"{argv[0]} exited with status {exc.returncode}: {stderr or '(no stderr)'}"
        ) from exc


def build_icns(
    iconutil: str,
    sips: str,
    *,
    master_path: Path = MASTER,
    out_path: Path = OUT_ICNS,
) -> None:
    with tempfile.TemporaryDirectory(prefix="mouser-iconset-") as tmp:
        iconset = Path(tmp) / "Mouser.iconset"
        iconset.mkdir()
        # Sorted iteration so that every CI run produces the same iconset
        # directory walk order regardless of filesystem enumeration. The
        # iconutil binary indexes by filename so this is belt-and-braces.
        for size in sorted(ICNS_SIZES):
            for retina in (False, True):
                pixel = size * 2 if retina else size
                suffix = "@2x" if retina else ""
                out = iconset / f"icon_{size}x{size}{suffix}.png"
                _run_tool(
                    [sips, "-z", str(pixel), str(pixel),
                     str(master_path), "--out", str(out)],
                )
        _run_tool([iconutil, "-c", "icns", str(iconset), "-o", str(out_path)])


def _fitted_small_surface_master(master: Image.Image) -> Image.Image:
    # Lift the squircle out of the master, then re-fit it to ~96% of the
    # canvas. We use the alpha channel as the squircle mask: pixels with
    # alpha > 0 belong to the squircle.
    alpha = master.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        raise BuildIconError("master has no visible pixels")
    squircle = master.crop(bbox)
    target_side = int(round(WIN_CANVAS * SMALL_SURFACE_FILL_RATIO))
    w, h = squircle.size
    scale = target_side / float(max(w, h))
    fitted = squircle.resize(
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (WIN_CANVAS, WIN_CANVAS), (0, 0, 0, 0))
    fx = (WIN_CANVAS - fitted.size[0]) // 2
    fy = (WIN_CANVAS - fitted.size[1]) // 2
    canvas.paste(fitted, (fx, fy), fitted)
    return canvas


def build_ico(master: Image.Image, *, out_path: Path = OUT_ICO) -> None:
    canvas = _fitted_small_surface_master(master)
    canvas.save(out_path, format="ICO", sizes=list(ICO_SIZES))


def build_linux_icons(
    master: Image.Image,
    *,
    out_root: Path = OUT_LINUX_HICOLOR,
) -> None:
    canvas = _fitted_small_surface_master(master)
    for size in LINUX_ICON_SIZES:
        target = (
            out_root
            / f"{size}x{size}"
            / "apps"
            / f"{LINUX_ICON_NAME}.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        image = canvas.resize((size, size), Image.LANCZOS)
        image.save(target, format="PNG")


def main() -> int:
    if sys.platform != "darwin":
        raise BuildIconError(
            "must run on macOS (needs iconutil + sips). "
            "The Windows and Linux variants cannot be regenerated alone here; "
            "rebuild from macOS so all committed icon assets stay in lockstep."
        )
    iconutil = _require_tool("iconutil")
    sips = _require_tool("sips")
    master = _validate_master()
    build_icns(iconutil, sips)
    build_ico(master)
    build_linux_icons(master)
    print(f"wrote {OUT_ICNS}")
    print(f"wrote {OUT_ICO}")
    print(f"wrote {OUT_LINUX_HICOLOR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
