import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ui.linux_screenshot import (
    LinuxScreenshotController,
    ScreenshotCancelled,
    ScreenshotError,
    SpectacleScreenshotBackend,
)
from ui.screenshot_common import (
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
)


class SpectacleScreenshotBackendTests(unittest.TestCase):
    def test_detect_returns_backend_when_spectacle_exists(self):
        with patch("ui.linux_screenshot.shutil.which", return_value="/usr/bin/spectacle"):
            backend = SpectacleScreenshotBackend.detect()

        self.assertIsInstance(backend, SpectacleScreenshotBackend)
        self.assertEqual(backend.executable, "/usr/bin/spectacle")

    def test_detect_returns_none_when_spectacle_is_missing(self):
        with patch("ui.linux_screenshot.shutil.which", return_value=None):
            backend = SpectacleScreenshotBackend.detect()

        self.assertIsNone(backend)

    def test_command_for_action_uses_fullscreen_or_region_mode(self):
        backend = SpectacleScreenshotBackend(executable="/usr/bin/spectacle")

        self.assertEqual(
            backend.command_for_action(SCREENSHOT_FULL_FILE, Path("/tmp/full.png")),
            ["/usr/bin/spectacle", "-n", "-b", "-f", "-o", "/tmp/full.png"],
        )
        self.assertEqual(
            backend.command_for_action(SCREENSHOT_REGION_CLIP, Path("/tmp/region.png")),
            ["/usr/bin/spectacle", "-n", "-b", "-r", "-o", "/tmp/region.png"],
        )

    def test_successful_file_action_returns_target_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shot.png"
            calls = []

            def runner(cmd, **_kwargs):
                calls.append(cmd)
                Path(cmd[-1]).write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            backend = SpectacleScreenshotBackend(
                executable="spectacle",
                runner=runner,
                path_factory=lambda: target,
            )

            result = backend.perform_action(SCREENSHOT_FULL_FILE)

        self.assertEqual(result.path, target)
        self.assertEqual(calls, [["spectacle", "-n", "-b", "-f", "-o", str(target)]])

    def test_clipboard_action_captures_temp_file_and_returns_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)

            def runner(cmd, **_kwargs):
                Image.new("RGB", (7, 8), (1, 2, 3)).save(Path(cmd[-1]))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            backend = SpectacleScreenshotBackend(
                executable="spectacle",
                runner=runner,
                temp_dir=temp_dir,
            )

            result = backend.perform_action(SCREENSHOT_FULL_CLIP)

            self.assertEqual(result.image.size, (7, 8))
            self.assertEqual(list(temp_dir.iterdir()), [])

    def test_timeout_is_reported_as_error(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        backend = SpectacleScreenshotBackend(executable="spectacle", runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ScreenshotError, "timed out"):
                backend.capture_to_path(SCREENSHOT_FULL_FILE, Path(tmp) / "shot.png")

    def test_region_without_output_is_treated_as_cancelled(self):
        def runner(cmd, **_kwargs):
            return subprocess.CompletedProcess(cmd, 0, "", "")

        backend = SpectacleScreenshotBackend(executable="spectacle", runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ScreenshotCancelled):
                backend.capture_to_path(SCREENSHOT_REGION_FILE, Path(tmp) / "shot.png")

    def test_spectacle_authorization_error_has_nobara_guidance(self):
        def runner(cmd, **_kwargs):
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                'Screenshot request failed: "The process is not authorized to take a screenshot"',
            )

        backend = SpectacleScreenshotBackend(executable="spectacle", runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ScreenshotError, "Nobara/KDE"):
                backend.capture_to_path(SCREENSHOT_FULL_FILE, Path(tmp) / "shot.png")


class LinuxScreenshotControllerTests(unittest.TestCase):
    def test_missing_backend_emits_unavailable_status(self):
        statuses = []
        controller = LinuxScreenshotController(backend=None, status_callback=statuses.append)

        controller._handle_request(SCREENSHOT_FULL_FILE)

        self.assertEqual(statuses, ["Screenshot backend unavailable: install Spectacle"])

    def test_busy_controller_rejects_second_screenshot(self):
        class DeferredThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        statuses = []
        controller = LinuxScreenshotController(
            backend=object(),
            status_callback=statuses.append,
            thread_factory=DeferredThread,
        )

        controller._handle_request(SCREENSHOT_FULL_FILE)
        controller._handle_request(SCREENSHOT_REGION_FILE)

        self.assertEqual(statuses, ["Finish the current screenshot first"])


if __name__ == "__main__":
    unittest.main()
