import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtGui import QColor, QImage

from ui.linux_screenshot import (
    BackendUnavailable,
    KWIN_REQUIRED_METHODS,
    KWinScreenshotBackend,
    KWinScreenshotClient,
    KWIN_INTERFACE,
    KWIN_PATH,
    LinuxScreenshotController,
    PORTAL_TARGET_AREA,
    PORTAL_TARGET_SCREEN,
    PortalScreenshotBackend,
    ScreenshotError,
    SpectacleScreenshotBackend,
    KWIN_SERVICE,
    kwin_capture_options,
    kwin_methods_from_introspection,
    kwin_raw_image_to_pil,
    portal_options_for_action,
    portal_request_path,
    select_linux_screenshot_backend,
    select_linux_screenshot_backends,
)
from ui.screenshot_common import (
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
)
from ui.screenshot_overlay import IntRect


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


class FakeKWinClient:
    def __init__(self, methods=None, error=None):
        self._methods = set(methods or KWIN_REQUIRED_METHODS)
        self._error = error
        self.calls = []

    def available_methods(self):
        return self._methods

    def capture_workspace(self, options, timeout_seconds):
        self.calls.append(("workspace", dict(options), timeout_seconds))
        if self._error is not None:
            raise self._error
        return Image.new("RGBA", (4, 3), (1, 2, 3, 255))

    def capture_area(self, rect, options, timeout_seconds):
        self.calls.append(("area", rect, dict(options), timeout_seconds))
        if self._error is not None:
            raise self._error
        return Image.new("RGBA", (max(1, rect.width), max(1, rect.height)), (4, 5, 6, 255))


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class KWinScreenshotBackendTests(unittest.TestCase):
    def test_kde_selects_kwin_before_portal_and_spectacle(self):
        kwin = object()
        spectacle = object()

        backends = select_linux_screenshot_backends(
            environ={"XDG_CURRENT_DESKTOP": "KDE"},
            kwin_detector=lambda: kwin,
            portal_factory=lambda: FakePortalClient(),
            spectacle_detector=lambda: spectacle,
        )

        self.assertIs(backends[0], kwin)
        self.assertIsInstance(backends[1], PortalScreenshotBackend)
        self.assertIs(backends[2], spectacle)

    def test_non_kde_does_not_select_kwin(self):
        backends = select_linux_screenshot_backends(
            environ={"XDG_CURRENT_DESKTOP": "GNOME"},
            kwin_detector=lambda: self.fail("KWin detector should not run outside KDE"),
            portal_factory=lambda: FakePortalClient(),
            spectacle_detector=lambda: None,
        )

        self.assertEqual(len(backends), 1)
        self.assertIsInstance(backends[0], PortalScreenshotBackend)

    def test_legacy_single_backend_selector_returns_first_backend(self):
        spectacle = object()

        backend = select_linux_screenshot_backend(
            environ={"XDG_CURRENT_DESKTOP": "KDE"},
            portal_factory=lambda: FakePortalClient(targets=0),
            spectacle_detector=lambda: spectacle,
        )

        self.assertIs(backend, spectacle)

    def test_detect_requires_kde_and_capture_methods(self):
        client = FakeKWinClient(methods={"CaptureWorkspace"})

        missing_method = KWinScreenshotBackend.detect(
            environ={"XDG_CURRENT_DESKTOP": "KDE"},
            client_factory=lambda: client,
        )
        non_kde = KWinScreenshotBackend.detect(
            environ={"XDG_CURRENT_DESKTOP": "GNOME"},
            client_factory=lambda: FakeKWinClient(),
        )

        self.assertIsNone(missing_method)
        self.assertIsNone(non_kde)

    def test_detect_returns_backend_when_methods_are_available(self):
        backend = KWinScreenshotBackend.detect(
            environ={"XDG_CURRENT_DESKTOP": "KDE"},
            client_factory=lambda: FakeKWinClient(),
        )

        self.assertIsInstance(backend, KWinScreenshotBackend)

    def test_capture_workspace_and_area_use_exact_options(self):
        client = FakeKWinClient()
        backend = KWinScreenshotBackend(
            client_factory=lambda: client,
            probe_rect_factory=lambda: IntRect(0, 0, 1, 1),
        )

        backend.probe()
        full = backend.capture_full()
        region = backend.capture_region(IntRect(10, 20, 30, 45))

        self.assertEqual(full.size, (4, 3))
        self.assertEqual(region.size, (20, 25))
        self.assertEqual(client.calls[0], ("area", IntRect(0, 0, 1, 1), kwin_capture_options(), 15))
        self.assertEqual(client.calls[1], ("workspace", kwin_capture_options(), 15))
        self.assertEqual(client.calls[2], ("area", IntRect(10, 20, 30, 45), kwin_capture_options(), 15))

    def test_probe_is_cached(self):
        client = FakeKWinClient()
        backend = KWinScreenshotBackend(
            client_factory=lambda: client,
            probe_rect_factory=lambda: IntRect(0, 0, 1, 1),
        )

        backend.probe()
        backend.probe()

        self.assertEqual(len(client.calls), 1)

    def test_probe_denial_marks_backend_unavailable(self):
        backend = KWinScreenshotBackend(
            client_factory=lambda: FakeKWinClient(error=ScreenshotError("not authorized")),
            probe_rect_factory=lambda: IntRect(0, 0, 1, 1),
        )

        with self.assertRaises(BackendUnavailable):
            backend.probe()
        with self.assertRaises(BackendUnavailable):
            backend.probe()

    def test_introspection_parser_extracts_kwin_methods(self):
        xml = """
        <node>
          <interface name="org.kde.KWin.ScreenShot2">
            <method name="CaptureWorkspace"/>
            <method name="CaptureArea"/>
          </interface>
        </node>
        """

        self.assertEqual(kwin_methods_from_introspection(xml), KWIN_REQUIRED_METHODS)

    def test_raw_image_metadata_reconstructs_pil_image(self):
        qimage = QImage(2, 1, QImage.Format.Format_RGBA8888)
        qimage.fill(QColor(11, 22, 33, 255))
        metadata = {
            "type": "raw",
            "format": QImage.Format.Format_RGBA8888.value,
            "width": qimage.width(),
            "height": qimage.height(),
            "stride": qimage.bytesPerLine(),
            "scale": 1.0,
        }

        image = kwin_raw_image_to_pil(metadata, bytes(qimage.bits()[: qimage.sizeInBytes()]))

        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (2, 1))
        self.assertEqual(image.getpixel((0, 0)), (11, 22, 33, 255))

    def test_kwin_client_capture_area_passes_options_and_unix_fd(self):
        qimage = QImage(3, 2, QImage.Format.Format_RGBA8888)
        qimage.fill(QColor(8, 9, 10, 255))
        metadata = {
            "type": "raw",
            "format": QImage.Format.Format_RGBA8888.value,
            "width": qimage.width(),
            "height": qimage.height(),
            "stride": qimage.bytesPerLine(),
            "scale": 1.0,
        }
        data = bytes(qimage.bits()[: qimage.sizeInBytes()])
        calls = []

        class FakeReply:
            def arguments(self):
                return [metadata]

        class FakeInterface:
            def __init__(self, service, path, interface, bus):
                self.service = service
                self.path = path
                self.interface = interface
                self.bus = bus

            def setTimeout(self, timeout):
                calls.append(("timeout", timeout))

            def call(self, method, *args):
                calls.append(("call", self.service, self.path, self.interface, method, args))
                return FakeReply()

        class FakeBus:
            def isConnected(self):
                return True

        class FakeUnixFD:
            def __init__(self, fd):
                self.fd = fd

        client = KWinScreenshotClient(
            bus=FakeBus(),
            interface_factory=FakeInterface,
            unix_fd_factory=FakeUnixFD,
            fd_reader=lambda _fd, _count, _timeout: data,
        )

        image = client.capture_area(
            IntRect(5, 6, 12, 16),
            options=kwin_capture_options(),
            timeout_seconds=7,
        )

        self.assertEqual(image.size, (3, 2))
        self.assertEqual(calls[0], ("timeout", 7000))
        call = calls[1]
        self.assertEqual(call[:5], ("call", KWIN_SERVICE, KWIN_PATH, KWIN_INTERFACE, "CaptureArea"))
        self.assertEqual(call[5][:5], (5, 6, 7, 10, kwin_capture_options()))
        self.assertIsInstance(call[5][5], FakeUnixFD)


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

    def test_full_capture_uses_temp_file_and_returns_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            calls = []

            def runner(cmd, **_kwargs):
                calls.append(cmd)
                Image.new("RGB", (7, 8), (1, 2, 3)).save(Path(cmd[-1]))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            backend = SpectacleScreenshotBackend(
                executable="spectacle",
                runner=runner,
                temp_dir=temp_dir,
            )

            image = backend.capture_full()

            self.assertEqual(image.size, (7, 8))
            self.assertEqual(calls[0][:4], ["spectacle", "-n", "-b", "-f"])
            self.assertEqual(list(temp_dir.iterdir()), [])

    def test_region_capture_uses_region_flag_and_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            calls = []

            def runner(cmd, **_kwargs):
                calls.append(cmd)
                Image.new("RGB", (4, 5), (1, 2, 3)).save(Path(cmd[-1]))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            backend = SpectacleScreenshotBackend(
                executable="spectacle",
                runner=runner,
                temp_dir=temp_dir,
            )

            image = backend.capture_region()

            self.assertEqual(image.size, (4, 5))
            self.assertEqual(calls[0][:4], ["spectacle", "-n", "-b", "-r"])
            self.assertEqual(list(temp_dir.iterdir()), [])

    def test_timeout_is_reported_as_error(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        backend = SpectacleScreenshotBackend(executable="spectacle", runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ScreenshotError, "timed out"):
                backend.capture_to_path(SCREENSHOT_FULL_FILE, Path(tmp) / "shot.png")

    def test_region_without_output_reports_finish_guidance(self):
        def runner(cmd, **_kwargs):
            return subprocess.CompletedProcess(cmd, 0, "", "")

        backend = SpectacleScreenshotBackend(executable="spectacle", runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ScreenshotError, "Press Enter/Accept"):
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

    def test_successful_portal_full_capture_loads_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portal.png"
            Image.new("RGB", (9, 10), (1, 2, 3)).save(source)
            client = FakePortalClient(uri=source.as_uri())
            backend = PortalScreenshotBackend(client_factory=lambda: client)

            image = backend.capture_full()

            self.assertEqual(image.size, (9, 10))
            self.assertTrue(source.exists())
            self.assertEqual(client.requests[0][0], SCREENSHOT_FULL_FILE)

    def test_successful_portal_region_capture_loads_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portal.png"
            Image.new("RGB", (5, 6), (1, 2, 3)).save(source)
            client = FakePortalClient(uri=source.as_uri())
            backend = PortalScreenshotBackend(client_factory=lambda: client)

            image = backend.capture_region()

            self.assertEqual(image.size, (5, 6))
            self.assertTrue(source.exists())
            self.assertEqual(client.requests[0][0], SCREENSHOT_REGION_FILE)

    def test_portal_denial_error_is_preserved(self):
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(
                error=ScreenshotError("Screenshot failed: portal response 2")
            )
        )

        with self.assertRaisesRegex(ScreenshotError, "portal response 2"):
            backend.capture_full()

    def test_portal_timeout_error_mentions_desktop_portal(self):
        message = (
            "Screenshot failed: desktop portal did not respond. "
            "Open the Mouser window once and retry."
        )
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(error=ScreenshotError(message))
        )

        with self.assertRaisesRegex(ScreenshotError, "desktop portal did not respond"):
            backend.capture_full()

    def test_portal_missing_uri_is_rejected(self):
        backend = PortalScreenshotBackend(client_factory=lambda: FakePortalClient(uri=""))

        with self.assertRaisesRegex(ScreenshotError, "did not include an image URI"):
            backend.capture_full()

    def test_portal_non_file_uri_is_rejected(self):
        backend = PortalScreenshotBackend(
            client_factory=lambda: FakePortalClient(uri="https://example.invalid/shot.png")
        )

        with self.assertRaisesRegex(ScreenshotError, "non-file"):
            backend.capture_full()

    def test_portal_missing_image_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.png"
            backend = PortalScreenshotBackend(
                client_factory=lambda: FakePortalClient(uri=missing.as_uri())
            )

            with self.assertRaisesRegex(ScreenshotError, "not available"):
                backend.capture_full()


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

    def test_file_delivery_is_mouser_owned(self):
        statuses = []
        target = Path("/tmp/mouser-owned.png")
        controller = LinuxScreenshotController(backend=None, status_callback=statuses.append)

        with patch("ui.linux_screenshot.save_image_to_file", return_value=target) as save_image:
            controller._finish_worker(SCREENSHOT_FULL_FILE, Image.new("RGBA", (2, 2)), "")

        save_image.assert_called_once()
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_clipboard_delivery_is_mouser_owned(self):
        statuses = []
        controller = LinuxScreenshotController(backend=None, status_callback=statuses.append)
        image = Image.new("RGBA", (2, 2))

        with patch("ui.linux_screenshot.copy_image_to_clipboard") as copy_image:
            controller._finish_worker(SCREENSHOT_FULL_CLIP, image, "")

        copy_image.assert_called_once_with(image)
        self.assertEqual(statuses, ["Screenshot copied to clipboard"])

    def test_kwin_region_backend_uses_mouser_overlay(self):
        client = FakeKWinClient()
        backend = KWinScreenshotBackend(
            client_factory=lambda: client,
            probe_rect_factory=lambda: IntRect(0, 0, 1, 1),
        )
        controller = LinuxScreenshotController(
            backend=backend,
            thread_factory=ImmediateThread,
            logical_bounds_factory=lambda: IntRect(0, 0, 100, 100),
        )
        ready = []
        controller._regionSelectionReady.connect(lambda action, be, err: ready.append((action, be, err)))

        controller._run_action(SCREENSHOT_REGION_FILE)

        self.assertEqual(ready, [(SCREENSHOT_REGION_FILE, backend, "")])
        self.assertEqual(client.calls, [("area", IntRect(0, 0, 1, 1), kwin_capture_options(), 15)])

    def test_kwin_probe_failure_falls_through_to_next_backend(self):
        bad_backend = KWinScreenshotBackend(
            client_factory=lambda: FakeKWinClient(error=ScreenshotError("not authorized")),
            probe_rect_factory=lambda: IntRect(0, 0, 1, 1),
        )

        class GoodBackend:
            needs_mouser_region_selection = False

            def probe(self):
                pass

            def capture_full(self):
                return Image.new("RGBA", (3, 3))

            def capture_region(self, _rect):
                return Image.new("RGBA", (3, 3))

        controller = LinuxScreenshotController(backend=[bad_backend, GoodBackend()])
        finished = []
        controller._workerFinished.connect(lambda action, image, error: finished.append((action, image.size if image else None, error)))

        controller._run_action(SCREENSHOT_FULL_FILE)

        self.assertEqual(finished, [(SCREENSHOT_FULL_FILE, (3, 3), "")])


if __name__ == "__main__":
    unittest.main()
