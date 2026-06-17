import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication

from ui.macos_screenshot import (
    FALLBACK_STATUS,
    PERMISSION_FALLBACK_STATUS,
    MacDisplayInfo,
    MacScreenshotController,
    compose_display_images,
)
from ui.screenshot_common import (
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_FILE,
)


def _ensure_qapp():
    app = QCoreApplication.instance()
    if app is None:
        return QCoreApplication([])
    return app


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class MacScreenshotControllerTests(unittest.TestCase):
    def test_default_mode_delegates_file_action_to_shortcut(self):
        calls = []
        runner_calls = []
        controller = MacScreenshotController(
            has_custom_directory=lambda: False,
            fallback_action=lambda action_id: calls.append(action_id) or True,
            runner=lambda *args, **kwargs: runner_calls.append((args, kwargs)),
        )

        controller._handle_request(SCREENSHOT_FULL_FILE)

        self.assertEqual(calls, [SCREENSHOT_FULL_FILE])
        self.assertEqual(runner_calls, [])

    def test_clipboard_action_delegates_to_shortcut_even_with_custom_directory(self):
        calls = []
        controller = MacScreenshotController(
            has_custom_directory=lambda: True,
            fallback_action=lambda action_id: calls.append(action_id) or True,
        )

        controller._handle_request(SCREENSHOT_FULL_CLIP)

        self.assertEqual(calls, [SCREENSHOT_FULL_CLIP])

    def test_custom_full_file_action_runs_exact_screencapture_command(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shot.png"
            statuses = []
            commands = []

            def runner(cmd, **_kwargs):
                commands.append(cmd)
                Image.new("RGBA", (8, 6), (255, 0, 0, 255)).save(Path(cmd[-1]))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                runner=runner,
                thread_factory=ImmediateThread,
                display_info_provider=lambda: [MacDisplayInfo(1, 0, 0, 4, 3)],
                screen_capture_access_checker=lambda: True,
                temp_path_factory=lambda: Path(tmp) / "display-1.png",
            )

            controller._handle_request(SCREENSHOT_FULL_FILE)
            app.processEvents()

        self.assertEqual(
            commands,
            [["/usr/sbin/screencapture", "-x", "-D", "1", "-t", "png", str(Path(tmp) / "display-1.png")]],
        )
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_custom_region_file_action_runs_exact_screencapture_command(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "region.png"
            statuses = []
            commands = []

            def runner(cmd, **_kwargs):
                commands.append(cmd)
                target.write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                runner=runner,
                thread_factory=ImmediateThread,
                screen_capture_access_checker=lambda: True,
            )

            controller._handle_request(SCREENSHOT_REGION_FILE)
            app.processEvents()

        self.assertEqual(
            commands,
            [["/usr/sbin/screencapture", "-x", "-i", "-s", "-t", "png", str(target)]],
        )
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_custom_full_file_action_composes_one_target_for_multiple_displays(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "combined.png"
            temp_paths = [Path(tmp) / "display-1.png", Path(tmp) / "display-2.png"]
            statuses = []
            commands = []
            temp_iter = iter(temp_paths)

            def runner(cmd, **_kwargs):
                commands.append(cmd)
                path = Path(cmd[-1])
                if cmd[3] == "1":
                    Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(path)
                else:
                    Image.new("RGBA", (10, 10), (0, 0, 255, 255)).save(path)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                runner=runner,
                thread_factory=ImmediateThread,
                display_info_provider=lambda: [
                    MacDisplayInfo(1, 0, 0, 10, 10),
                    MacDisplayInfo(2, -5, -10, 10, 10),
                ],
                screen_capture_access_checker=lambda: True,
                temp_path_factory=lambda: next(temp_iter),
            )

            controller._handle_request(SCREENSHOT_FULL_FILE)
            app.processEvents()

            self.assertTrue(target.exists())
            image = Image.open(target).convert("RGBA")
            self.assertEqual(image.size, (30, 40))
            self.assertEqual(image.getpixel((1, 1)), (0, 0, 255, 255))
            self.assertEqual(image.getpixel((11, 21)), (255, 0, 0, 255))
            self.assertFalse(temp_paths[0].exists())
            self.assertFalse(temp_paths[1].exists())

        self.assertEqual(
            commands,
            [
                ["/usr/sbin/screencapture", "-x", "-D", "1", "-t", "png", str(temp_paths[0])],
                ["/usr/sbin/screencapture", "-x", "-D", "2", "-t", "png", str(temp_paths[1])],
            ],
        )
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_custom_region_file_action_is_not_scoped_to_cursor_display(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "region.png"
            statuses = []
            commands = []

            def runner(cmd, **_kwargs):
                commands.append(cmd)
                target.write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                runner=runner,
                thread_factory=ImmediateThread,
                screen_capture_access_checker=lambda: True,
            )

            controller._handle_request(SCREENSHOT_REGION_FILE)
            app.processEvents()

        self.assertEqual(
            commands,
            [["/usr/sbin/screencapture", "-x", "-i", "-s", "-t", "png", str(target)]],
        )
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_permission_denied_uses_shortcut_fallback_without_running_screencapture(self):
        app = _ensure_qapp()
        statuses = []
        fallback_calls = []
        runner_calls = []
        controller = MacScreenshotController(
            status_callback=statuses.append,
            path_factory=lambda: Path("/tmp/unused.png"),
            has_custom_directory=lambda: True,
            fallback_action=lambda action_id: fallback_calls.append(action_id) or True,
            runner=lambda *args, **kwargs: runner_calls.append((args, kwargs)),
            thread_factory=ImmediateThread,
            screen_capture_access_checker=lambda: False,
        )

        controller._handle_request(SCREENSHOT_FULL_FILE)
        app.processEvents()

        self.assertEqual(fallback_calls, [SCREENSHOT_FULL_FILE])
        self.assertEqual(runner_calls, [])
        self.assertEqual(statuses, [PERMISSION_FALLBACK_STATUS])

    def test_region_without_output_reports_cancelled_without_shortcut_fallback(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "region.png"
            statuses = []
            fallback_calls = []

            def runner(cmd, **_kwargs):
                return subprocess.CompletedProcess(cmd, 0, "", "")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                fallback_action=lambda action_id: fallback_calls.append(action_id) or True,
                runner=runner,
                thread_factory=ImmediateThread,
                screen_capture_access_checker=lambda: True,
            )

            controller._handle_request(SCREENSHOT_REGION_FILE)
            app.processEvents()

        self.assertEqual(statuses, ["Screenshot cancelled"])
        self.assertEqual(fallback_calls, [])

    def test_full_failure_falls_back_to_shortcut_and_deletes_partial_output(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shot.png"
            statuses = []
            fallback_calls = []

            def runner(cmd, **_kwargs):
                target.write_bytes(b"partial")
                return subprocess.CompletedProcess(cmd, 1, "", "denied")

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                fallback_action=lambda action_id: fallback_calls.append(action_id) or True,
                runner=runner,
                thread_factory=ImmediateThread,
                display_info_provider=lambda: [MacDisplayInfo(1, 0, 0, 4, 3)],
                screen_capture_access_checker=lambda: True,
                temp_path_factory=lambda: target,
            )

            controller._handle_request(SCREENSHOT_FULL_FILE)
            app.processEvents()

            self.assertFalse(target.exists())

        self.assertEqual(fallback_calls, [SCREENSHOT_FULL_FILE])
        self.assertEqual(statuses, [FALLBACK_STATUS])

    def test_timeout_falls_back_to_shortcut(self):
        app = _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shot.png"
            statuses = []
            fallback_calls = []

            def runner(cmd, **kwargs):
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

            controller = MacScreenshotController(
                status_callback=statuses.append,
                path_factory=lambda: target,
                has_custom_directory=lambda: True,
                fallback_action=lambda action_id: fallback_calls.append(action_id) or True,
                runner=runner,
                thread_factory=ImmediateThread,
                display_info_provider=lambda: [MacDisplayInfo(1, 0, 0, 4, 3)],
                screen_capture_access_checker=lambda: True,
                temp_path_factory=lambda: target,
            )

            controller._handle_request(SCREENSHOT_FULL_FILE)
            app.processEvents()

        self.assertEqual(fallback_calls, [SCREENSHOT_FULL_FILE])
        self.assertEqual(statuses, [FALLBACK_STATUS])


class MacScreenshotCompositionTests(unittest.TestCase):
    def test_compose_display_images_uses_white_max_dpi_canvas(self):
        captures = [
            (
                MacDisplayInfo(index=1, x=0, y=0, width=4, height=3),
                Image.new("RGBA", (8, 6), (255, 0, 0, 255)),
            ),
            (
                MacDisplayInfo(index=2, x=-2, y=-1, width=2, height=2),
                Image.new("RGBA", (2, 2), (0, 0, 255, 255)),
            ),
        ]

        image = compose_display_images(captures)

        self.assertEqual(image.size, (12, 8))
        self.assertEqual(image.getpixel((1, 1)), (0, 0, 255, 255))
        self.assertEqual(image.getpixel((5, 3)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((1, 7)), (255, 255, 255, 255))


if __name__ == "__main__":
    unittest.main()
