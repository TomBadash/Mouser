"""Unit tests for scripts/build_app_icon.py.

Coverage targets:
* ``_validate_master`` -- exhaustive boundary validation of the master PNG.
* ``_require_tool``    -- explicit error when an OS-supplied binary is missing.
* ``_run_tool``        -- non-zero subprocess exit surfaces stderr.
* ``build_ico``        -- writes a valid multi-size .ico from the master.
* ``build_linux_icons`` -- writes hicolor app icons for Linux desktop entries.
* ``main``             -- platform gating refuses non-darwin runs.

We intentionally skip the live ``build_icns`` smoke test in CI: it shells out
to ``iconutil``/``sips`` which ship with macOS only, and exercising it would
mutate the repository's checked-in ``images/AppIcon.icns``. The build pipeline
already exercises the happy path on every macOS release.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is declared in requirements.txt
    Image = None  # type: ignore[assignment]

try:
    import build_app_icon  # noqa: E402  (sys.path mutation precedes import)
except ImportError:  # pragma: no cover - script absent in stripped builds
    build_app_icon = None  # type: ignore[assignment]


@unittest.skipUnless(Image is not None, "Pillow not installed in test environment")
@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class ValidateMasterTests(unittest.TestCase):
    """``_validate_master`` is the only input gate for the whole pipeline."""

    def setUp(self) -> None:
        self.tmp = Path(self._make_tempdir())
        self.master_path = self.tmp / "master.png"

    def _make_tempdir(self) -> str:
        import tempfile

        path = tempfile.mkdtemp(prefix="mouser-icon-test-")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def _write_master(self, *, mode: str, size: tuple[int, int]) -> Path:
        Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else 0).save(self.master_path)
        return self.master_path

    def test_missing_file_raises_with_path(self) -> None:
        with self.assertRaises(build_app_icon.BuildIconError) as ctx:
            build_app_icon._validate_master(self.tmp / "absent.png")
        self.assertIn("absent.png", str(ctx.exception))

    def test_rejects_non_rgba_mode(self) -> None:
        self._write_master(mode="RGB", size=(1024, 1024))
        with self.assertRaises(build_app_icon.BuildIconError) as ctx:
            build_app_icon._validate_master(self.master_path)
        self.assertIn("RGBA", str(ctx.exception))

    def test_rejects_wrong_canvas_size(self) -> None:
        self._write_master(mode="RGBA", size=(512, 512))
        with self.assertRaises(build_app_icon.BuildIconError) as ctx:
            build_app_icon._validate_master(self.master_path)
        self.assertIn("1024x1024", str(ctx.exception))
        self.assertIn("512x512", str(ctx.exception))

    def test_accepts_canonical_master(self) -> None:
        self._write_master(mode="RGBA", size=(1024, 1024))
        image = build_app_icon._validate_master(self.master_path)
        self.assertEqual(image.size, (1024, 1024))
        self.assertEqual(image.mode, "RGBA")


@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class RequireToolTests(unittest.TestCase):
    def test_returns_resolved_path_when_present(self) -> None:
        with mock.patch.object(build_app_icon.shutil, "which", return_value="/usr/bin/sips"):
            self.assertEqual(build_app_icon._require_tool("sips"), "/usr/bin/sips")

    def test_raises_with_actionable_message_when_missing(self) -> None:
        with mock.patch.object(build_app_icon.shutil, "which", return_value=None):
            with self.assertRaises(build_app_icon.BuildIconError) as ctx:
                build_app_icon._require_tool("iconutil")
        message = str(ctx.exception)
        self.assertIn("iconutil", message)
        self.assertIn("Run on macOS", message)


@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class RunToolTests(unittest.TestCase):
    """Subprocess error surfacing is the difference between a debuggable build
    failure and a stack trace pointing at ``subprocess.run``."""

    def test_succeeds_silently_on_zero_exit(self) -> None:
        completed = mock.Mock(returncode=0, stderr=b"")
        with mock.patch.object(build_app_icon.subprocess, "run", return_value=completed) as run:
            build_app_icon._run_tool(["fake", "--ok"])
        run.assert_called_once()

    def test_surfaces_stderr_in_error_message(self) -> None:
        error = subprocess.CalledProcessError(
            returncode=2,
            cmd=["sips", "--bad"],
            stderr=b"sips: cannot open input",
        )
        with mock.patch.object(build_app_icon.subprocess, "run", side_effect=error):
            with self.assertRaises(build_app_icon.BuildIconError) as ctx:
                build_app_icon._run_tool(["sips", "--bad"])
        message = str(ctx.exception)
        self.assertIn("status 2", message)
        self.assertIn("sips: cannot open input", message)

    def test_substitutes_placeholder_when_stderr_empty(self) -> None:
        error = subprocess.CalledProcessError(returncode=1, cmd=["x"], stderr=b"")
        with mock.patch.object(build_app_icon.subprocess, "run", side_effect=error):
            with self.assertRaises(build_app_icon.BuildIconError) as ctx:
                build_app_icon._run_tool(["x"])
        self.assertIn("(no stderr)", str(ctx.exception))


@unittest.skipUnless(Image is not None, "Pillow not installed in test environment")
@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class BuildIcoTests(unittest.TestCase):
    """``build_ico`` runs on every host -- it never shells out."""

    def setUp(self) -> None:
        import tempfile

        path = tempfile.mkdtemp(prefix="mouser-icon-test-")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        self.tmp = Path(path)

    def _opaque_master(self) -> Image.Image:
        # 824 px opaque squircle proxy centred on the 1024 canvas so the
        # alpha-bbox crop matches the canonical master's geometry.
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        body = Image.new("RGBA", (824, 824), (11, 18, 32, 255))
        canvas.paste(body, (100, 100))
        return canvas

    def test_rejects_fully_transparent_master(self) -> None:
        empty = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        with self.assertRaises(build_app_icon.BuildIconError) as ctx:
            build_app_icon.build_ico(empty, out_path=self.tmp / "logo.ico")
        self.assertIn("no visible pixels", str(ctx.exception))

    def test_writes_multisize_ico_to_target_path(self) -> None:
        master = self._opaque_master()
        out = self.tmp / "logo.ico"
        build_app_icon.build_ico(master, out_path=out)
        self.assertTrue(out.is_file())
        with Image.open(out) as ico:
            # Pillow ICO can report ``ico.ico.sizes()`` directly.
            sizes = set(ico.ico.sizes()) if hasattr(ico, "ico") else set()
            expected = set(build_app_icon.ICO_SIZES)
        self.assertTrue(
            sizes.issuperset(expected) or sizes == expected,
            f"expected {expected!r} sizes in .ico, got {sizes!r}",
        )

    def test_output_is_reproducible(self) -> None:
        """Two consecutive builds against the same master must yield byte-identical .ico."""
        master = self._opaque_master()
        first = self.tmp / "first.ico"
        second = self.tmp / "second.ico"
        build_app_icon.build_ico(master, out_path=first)
        build_app_icon.build_ico(master, out_path=second)
        self.assertEqual(first.read_bytes(), second.read_bytes())


@unittest.skipUnless(Image is not None, "Pillow not installed in test environment")
@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class BuildLinuxIconsTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        path = tempfile.mkdtemp(prefix="mouser-icon-test-")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        self.tmp = Path(path)

    def _opaque_master(self) -> Image.Image:
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        body = Image.new("RGBA", (824, 824), (11, 18, 32, 255))
        canvas.paste(body, (100, 100))
        return canvas

    def test_writes_hicolor_png_ladder(self) -> None:
        out_root = self.tmp / "hicolor"

        build_app_icon.build_linux_icons(self._opaque_master(), out_root=out_root)

        for size in build_app_icon.LINUX_ICON_SIZES:
            with self.subTest(size=size):
                path = (
                    out_root
                    / f"{size}x{size}"
                    / "apps"
                    / f"{build_app_icon.LINUX_ICON_NAME}.png"
                )
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, "RGBA")

    def test_output_is_reproducible(self) -> None:
        master = self._opaque_master()
        first = self.tmp / "first"
        second = self.tmp / "second"

        build_app_icon.build_linux_icons(master, out_root=first)
        build_app_icon.build_linux_icons(master, out_root=second)

        for size in build_app_icon.LINUX_ICON_SIZES:
            first_path = (
                first
                / f"{size}x{size}"
                / "apps"
                / f"{build_app_icon.LINUX_ICON_NAME}.png"
            )
            second_path = (
                second
                / f"{size}x{size}"
                / "apps"
                / f"{build_app_icon.LINUX_ICON_NAME}.png"
            )
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())


@unittest.skipUnless(build_app_icon is not None, "build_app_icon script unavailable")
class MainPlatformGateTests(unittest.TestCase):
    def test_refuses_to_run_off_darwin(self) -> None:
        with mock.patch.object(build_app_icon.sys, "platform", "linux"):
            with self.assertRaises(build_app_icon.BuildIconError) as ctx:
                build_app_icon.main()
        message = str(ctx.exception)
        self.assertIn("macOS", message)
        self.assertIn("iconutil", message)

    def test_runs_full_pipeline_on_darwin(self) -> None:
        with mock.patch.object(build_app_icon.sys, "platform", "darwin"), \
             mock.patch.object(build_app_icon, "_require_tool", return_value="/stub") as req, \
             mock.patch.object(build_app_icon, "_validate_master") as validate, \
             mock.patch.object(build_app_icon, "build_icns") as icns, \
             mock.patch.object(build_app_icon, "build_ico") as ico, \
             mock.patch.object(build_app_icon, "build_linux_icons") as linux_icons, \
             mock.patch("builtins.print"):
            validate.return_value = mock.Mock(spec=Image.Image)
            exit_code = build_app_icon.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(req.call_count, 2)
        icns.assert_called_once()
        ico.assert_called_once()
        linux_icons.assert_called_once()


if __name__ == "__main__":  # pragma: no cover - direct run convenience
    unittest.main()
