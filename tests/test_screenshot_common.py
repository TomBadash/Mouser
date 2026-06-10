import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

from ui.screenshot_common import (
    copy_image_to_clipboard,
    pil_image_to_qimage,
    screenshot_file_path,
    screenshots_dir,
)


class ScreenshotOutputTests(unittest.TestCase):
    def test_screenshot_file_path_uses_numeric_suffix_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            now = datetime(2026, 6, 10, 14, 9, 23)
            (directory / "Screenshot 2026-06-10 140923.png").touch()
            (directory / "Screenshot 2026-06-10 140923 (2).png").touch()

            path = screenshot_file_path(directory=directory, now=now)

            self.assertEqual(path.name, "Screenshot 2026-06-10 140923 (3).png")

    def test_screenshots_dir_falls_back_when_primary_path_is_not_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            pictures = home / "Pictures"
            pictures.mkdir()
            (pictures / "Screenshots").write_text("not a directory")

            directory = screenshots_dir(home=home)

            self.assertEqual(directory, pictures / "Mouser Screenshots")
            self.assertTrue(directory.is_dir())

    def test_pil_image_to_qimage_preserves_dimensions(self):
        qimage = pil_image_to_qimage(Image.new("RGB", (3, 4), (1, 2, 3)))

        self.assertEqual(qimage.width(), 3)
        self.assertEqual(qimage.height(), 4)

    def test_copy_image_to_clipboard_sets_qimage(self):
        class FakeClipboard:
            def __init__(self):
                self.image = None

            def setImage(self, image):
                self.image = image

        clipboard = FakeClipboard()

        copy_image_to_clipboard(Image.new("RGB", (5, 6), (1, 2, 3)), clipboard=clipboard)

        self.assertIsNotNone(clipboard.image)
        self.assertEqual(clipboard.image.width(), 5)
        self.assertEqual(clipboard.image.height(), 6)


if __name__ == "__main__":
    unittest.main()
