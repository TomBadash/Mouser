import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ui.linux_screenshot import (
    LinuxScreenshotController,
    PORTAL_TARGET_AREA,
    PORTAL_TARGET_SCREEN,
    PortalScreenshotBackend,
    ScreenshotCancelled,
    ScreenshotError,
    SpectacleScreenshotBackend,
    portal_options_for_action,
    portal_request_path,
    select_linux_screenshot_backend,
)
from ui.screenshot_common import (
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
)


class FakePortalClient:
    def __init__(
        self,
        targets=PORTAL_TARGET_SCREEN | PORTAL_TARGET_AREA,
        uri="",
        error=None,
    ):
        self._targets = targets
        self._uri = uri
        self._error = error
        self.requests = []

    def available_targets(self):
        return self._targets

    def request_screenshot(self, action_id, timeout_ms):
        self.requests.append((action_id, timeout_ms))
        if self._error is not None:
            raise self._error
        return self._uri


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


class PortalScreenshotBackendTests(unittest.TestCase):
    def test_gnome_selects_portal_before_spectacle_when_targets_are_available(self):
        portal_client = FakePortalClient()
        spectacle = object()

        backend = select_linux_screenshot_backend(
            environ={"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
            portal_factory=lambda: portal_client,
            spectacle_detector=lambda: spectacle,
        )

        self.assertIsInstance(backend, PortalScreenshotBackend)

    def test_kde_still_prefers_spectacle(self):
        spectacle = object()

        backend = select_linux_screenshot_backend(
            environ={"XDG_CURRENT_DESKTOP": "KDE"},
            portal_factory=lambda: FakePortalClient(),
            spectacle_detector=lambda: spectacle,
        )

        self.assertIs(backend, spectacle)

    def test_portal_detection_requires_screen_and_area_targets(self):
        backend = PortalScreenshotBackend.detect(
            client_factory=lambda: FakePortalClient(targets=PORTAL_TARGET_SCREEN)
        )

        self.assertIsNone(backend)

    def test_portal_detection_ignores_unavailable_session_bus(self):
        def factory():
            raise ScreenshotError(
                "Screenshot backend unavailable: D-Bus session bus is not connected"
            )

        backend = PortalScreenshotBackend.detect(client_factory=factory)

        self.assertIsNone(backend)

    def test_portal_request_options_use_interactive_target_and_token(self):
        options = portal_options_for_action(SCREENSHOT_REGION_CLIP, "mouser_token")

        self.assertEqual(options["handle_token"], "mouser_token")
        self.assertIs(options["interactive"], True)
        self.assertIs(options["modal"], True)
        self.assertEqual(options["target"], PORTAL_TARGET_AREA)
        self.assertEqual(
            portal_options_for_action(SCREENSHOT_FULL_FILE, "mouser_token")["target"],
            PORTAL_TARGET_SCREEN,
        )

    def test_portal_request_path_uses_base_service_and_token(self):
        self.assertEqual(
            portal_request_path(":1.234", "mouser_token"),
            "/org/freedesktop/portal/desktop/request/1_234/mouser_token",
        )

    def test_successful_portal_file_action_copies_to_mouser_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portal.png"
            target = Path(tmp) / "mouser.png"
            source.write_bytes(b"portal image")
            client = FakePortalClient(uri=source.as_uri())
            backend = PortalScreenshotBackend(
                client_factory=lambda: client,
                path_factory=lambda: target,
            )

            result = backend.perform_action(SCREENSHOT_FULL_FILE)

            self.assertEqual(result.path, target)
            self.assertEqual(target.read_bytes(), b"portal image")
            self.assertTrue(source.exists())
            self.assertEqual(client.requests[0][0], SCREENSHOT_FULL_FILE)

    def test_successful_portal_clipboard_action_loads_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portal.png"
            Image.new("RGB", (9, 10), (1, 2, 3)).save(source)
            client = FakePortalClient(uri=source.as_uri())
            backend = PortalScreenshotBackend(client_factory=lambda: client)

            result = backend.perform_action(SCREENSHOT_REGION_CLIP)

            self.assertEqual(result.image.size, (9, 10))
            self.assertTrue(source.exists())
            self.assertEqual(client.requests[0][0], SCREENSHOT_REGION_CLIP)

    def test_portal_cancel_is_preserved(self):
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(error=ScreenshotCancelled())
        )

        with self.assertRaises(ScreenshotCancelled):
            backend.perform_action(SCREENSHOT_REGION_FILE)

    def test_portal_denial_error_is_preserved(self):
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(
                error=ScreenshotError("Screenshot failed: portal response 2")
            )
        )

        with self.assertRaisesRegex(ScreenshotError, "portal response 2"):
            backend.perform_action(SCREENSHOT_FULL_FILE)

    def test_portal_timeout_error_mentions_gnome_permission(self):
        message = (
            "Screenshot failed: GNOME portal did not respond. "
            "Open the Mouser window once and retry."
        )
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(error=ScreenshotError(message))
        )

        with self.assertRaisesRegex(ScreenshotError, "GNOME portal did not respond"):
            backend.perform_action(SCREENSHOT_FULL_FILE)

    def test_portal_missing_uri_is_rejected(self):
        backend = PortalScreenshotBackend(client_factory=lambda: FakePortalClient(uri=""))

        with self.assertRaisesRegex(ScreenshotError, "did not include an image URI"):
            backend.perform_action(SCREENSHOT_FULL_FILE)

    def test_portal_non_file_uri_is_rejected(self):
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(uri="https://example.invalid/shot.png")
        )

        with self.assertRaisesRegex(ScreenshotError, "non-file"):
            backend.perform_action(SCREENSHOT_FULL_FILE)

    def test_portal_missing_image_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.png"
            backend = PortalScreenshotBackend(
                client_factory=lambda: FakePortalClient(uri=missing.as_uri())
            )

            with self.assertRaisesRegex(ScreenshotError, "not available"):
                backend.perform_action(SCREENSHOT_FULL_CLIP)


class LinuxScreenshotControllerTests(unittest.TestCase):
    def test_missing_backend_emits_unavailable_status(self):
        statuses = []
        controller = LinuxScreenshotController(backend=None, status_callback=statuses.append)

        controller._handle_request(SCREENSHOT_FULL_FILE)

        self.assertEqual(statuses, ["Screenshot backend unavailable"])

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
