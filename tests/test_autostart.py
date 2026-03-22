import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import autostart


class AutostartTests(unittest.TestCase):
    def test_build_launch_agent_payload_for_source_mode(self):
        fake_python = Path("/opt/homebrew/bin/python3")
        fake_module = Path("/tmp/Mouser/core/autostart.py")

        with (
            patch.object(autostart.sys, "platform", "darwin"),
            patch.object(autostart.sys, "frozen", False, create=True),
            patch.object(autostart.sys, "executable", str(fake_python)),
            patch.object(autostart, "__file__", str(fake_module)),
        ):
            payload = autostart.build_launch_agent_payload(start_hidden=True)

        self.assertEqual(payload["Label"], autostart.LAUNCH_AGENT_LABEL)
        self.assertEqual(payload["ProgramArguments"][0], str(fake_python))
        self.assertEqual(
            payload["ProgramArguments"][1],
            str((fake_module.parent.parent / "main_qml.py").resolve()),
        )
        self.assertEqual(payload["ProgramArguments"][-1], "--start-hidden")
        self.assertEqual(
            payload["WorkingDirectory"],
            str(fake_module.parent.parent.resolve()),
        )
        self.assertEqual(payload["LimitLoadToSessionType"], ["Aqua"])

    def test_enable_launch_at_login_writes_plist(self):
        fake_executable = "/Applications/Mouser.app/Contents/MacOS/Mouser"

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(autostart.sys, "platform", "darwin"),
                patch.object(autostart.sys, "frozen", True, create=True),
                patch.object(autostart.sys, "executable", fake_executable),
            ):
                plist_path = autostart.enable_launch_at_login(
                    start_hidden=True,
                    home=temp_dir,
                )

            self.assertTrue(plist_path.exists())
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)

        self.assertEqual(
            payload["ProgramArguments"][0], str(Path(fake_executable))
        )
        self.assertEqual(payload["ProgramArguments"][-1], "--start-hidden")
        self.assertTrue(payload["RunAtLoad"])

    def test_disable_launch_at_login_removes_plist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plist_path = autostart.launch_agent_path(temp_dir)
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text("placeholder", encoding="utf-8")

            with patch.object(autostart.sys, "platform", "darwin"):
                autostart.disable_launch_at_login(home=temp_dir)

            self.assertFalse(plist_path.exists())


if __name__ == "__main__":
    unittest.main()
