import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import accessibility


class AccessibilityTests(unittest.TestCase):
    def test_returns_true_on_non_macos(self):
        with patch.object(accessibility.sys, "platform", "linux"):
            self.assertTrue(accessibility.is_process_trusted())

    def test_uses_basic_trust_check_without_prompt(self):
        fake_app_services = SimpleNamespace(
            AXIsProcessTrusted=lambda: False,
        )
        fake_core_foundation = SimpleNamespace(
            CFRelease=lambda _: None,
        )

        with patch("core.accessibility._load_frameworks", return_value=(
            fake_app_services,
            fake_core_foundation,
        )):
            self.assertFalse(accessibility.is_process_trusted())

    def test_uses_prompt_api_when_requested(self):
        calls = []
        fake_app_services = SimpleNamespace(
            AXIsProcessTrusted=lambda: False,
            AXIsProcessTrustedWithOptions=lambda options: calls.append(options) or False,
        )
        fake_core_foundation = SimpleNamespace(
            CFRelease=lambda options: calls.append(("release", options)),
        )

        with (
            patch("core.accessibility._load_frameworks", return_value=(
                fake_app_services,
                fake_core_foundation,
            )),
            patch("core.accessibility._create_prompt_options", return_value="options"),
        ):
            self.assertFalse(accessibility.is_process_trusted(prompt=True))

        self.assertEqual(calls, ["options", ("release", "options")])


if __name__ == "__main__":
    unittest.main()
