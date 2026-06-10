"""Shared screenshot action helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QGuiApplication, QImage


SCREENSHOT_REGION_CLIP = "screenshot_region_clip"
SCREENSHOT_REGION_FILE = "screenshot_region_file"
SCREENSHOT_FULL_CLIP = "screenshot_full_clip"
SCREENSHOT_FULL_FILE = "screenshot_full_file"

SCREENSHOT_ACTIONS = frozenset({
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
})

SCREENSHOT_CLIPBOARD_ACTIONS = frozenset({
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_FULL_CLIP,
})

SCREENSHOT_FILE_ACTIONS = frozenset({
    SCREENSHOT_REGION_FILE,
    SCREENSHOT_FULL_FILE,
})

SCREENSHOT_REGION_ACTIONS = frozenset({
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
})

SCREENSHOT_FULL_ACTIONS = frozenset({
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
})


def pil_image_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    fmt = getattr(QImage.Format, "Format_RGBA8888", QImage.Format.Format_ARGB32)
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, fmt)
    return qimage.copy()


def copy_image_to_clipboard(image: Image.Image, clipboard=None) -> None:
    if clipboard is None:
        clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise RuntimeError("clipboard unavailable")
    clipboard.setImage(pil_image_to_qimage(image))


def screenshots_dir(home: Path | None = None) -> Path:
    root = home or Path.home()
    primary = root / "Pictures" / "Screenshots"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except OSError:
        fallback = root / "Pictures" / "Mouser Screenshots"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def screenshot_file_path(
    directory: Path | None = None,
    now: datetime | None = None,
) -> Path:
    directory = directory or screenshots_dir()
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H%M%S")
    base = directory / f"Screenshot {stamp}.png"
    if not base.exists():
        return base
    for idx in range(2, 1000):
        candidate = directory / f"Screenshot {stamp} ({idx}).png"
        if not candidate.exists():
            return candidate
    raise RuntimeError("could not allocate screenshot filename")


def save_image_to_file(image: Image.Image, path: Path | None = None) -> Path:
    target = path or screenshot_file_path()
    image.save(target, format="PNG")
    return target
