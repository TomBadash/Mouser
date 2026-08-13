import unittest

from core import key_registry


class KeyRegistryParsingTests(unittest.TestCase):
    def test_manual_entry_is_case_insensitive_and_orders_modifiers(self):
        self.assertEqual(
            key_registry.canonical_shortcut_text("Shift + Ctrl + A"),
            "ctrl+shift+a",
        )

    def test_aliases_resolve_to_canonical_names(self):
        self.assertEqual(
            key_registry.canonical_shortcut_text("command+page down"),
            "super+pagedown",
        )
        self.assertEqual(
            key_registry.canonical_shortcut_text("win+pgup"),
            "super+pageup",
        )

    def test_shifted_symbols_normalize_to_physical_us_keys(self):
        self.assertEqual(
            key_registry.canonical_shortcut_text("ctrl+<"),
            "ctrl+shift+comma",
        )
        self.assertEqual(
            key_registry.canonical_shortcut_text("win+plus"),
            "shift+super+equal",
        )

    def test_duplicate_keys_are_rejected(self):
        with self.assertRaises(key_registry.ShortcutParseError):
            key_registry.canonical_shortcut_text("ctrl+control+a")

    def test_multiple_non_modifier_keys_are_rejected(self):
        with self.assertRaises(key_registry.ShortcutParseError):
            key_registry.canonical_shortcut_text("ctrl+a+b")

    def test_modifier_only_shortcuts_are_rejected_by_default(self):
        with self.assertRaises(key_registry.ShortcutParseError):
            key_registry.canonical_shortcut_text("ctrl+shift")

    def test_platform_maps_include_navigation_function_and_punctuation_keys(self):
        windows = key_registry.build_key_name_to_code_map(platform_name="win32")
        macos = key_registry.build_key_name_to_code_map(platform_name="darwin")
        linux = key_registry.build_key_name_to_code_map(platform_name="linux")

        self.assertEqual(windows["insert"], 0x2D)
        self.assertEqual(macos["insert"], 0x72)
        self.assertEqual(linux["insert"], 110)

        self.assertEqual(windows["printscreen"], 0x2C)
        self.assertEqual(macos["printscreen"], 0x69)
        self.assertEqual(linux["printscreen"], 99)

        self.assertEqual(windows["semicolon"], 0xBA)
        self.assertEqual(macos["semicolon"], 0x29)
        self.assertEqual(linux["semicolon"], 39)

        self.assertEqual(windows["f24"], 0x87)
        self.assertIn("f20", macos)
        self.assertIn("f24", linux)

    def test_valid_names_include_aliases_and_shifted_symbol_words(self):
        names = set(key_registry.valid_key_names("win32"))

        self.assertIn("pgup", names)
        self.assertIn("plus", names)
        self.assertIn(";", names)
        self.assertIn("insert", names)
        self.assertIn("printscreen", names)
        self.assertIn("prtsc", names)

    def test_print_screen_aliases_normalize_to_one_cross_platform_key(self):
        for alias in ("print", "Print Screen", "PrtSc", "PrtScn", "SysRq"):
            with self.subTest(alias=alias):
                self.assertEqual(
                    key_registry.canonical_shortcut_text(alias),
                    "printscreen",
                )

    def test_platform_support_validation_rejects_unsupported_keys(self):
        self.assertEqual(
            key_registry.canonical_shortcut_text("F20", platform_name="darwin"),
            "f20",
        )
        with self.assertRaisesRegex(
            key_registry.ShortcutParseError,
            "Key is not supported on this platform: F24",
        ) as ctx:
            key_registry.canonical_shortcut_text("F24", platform_name="darwin")
        self.assertEqual(ctx.exception.code, "unsupported_key")
        self.assertEqual(ctx.exception.detail, "F24")

        self.assertEqual(
            key_registry.canonical_shortcut_text("F24", platform_name="win32"),
            "f24",
        )

    def test_valid_names_omit_platform_unsupported_keys(self):
        macos = set(key_registry.valid_key_names("darwin"))
        windows = set(key_registry.valid_key_names("win32"))

        self.assertIn("f20", macos)
        self.assertNotIn("f24", macos)
        self.assertIn("f24", windows)

    def test_reserved_shortcuts_warn_but_still_parse(self):
        self.assertEqual(
            key_registry.canonical_shortcut_text("Win+Shift+S"),
            "shift+super+s",
        )
        self.assertTrue(key_registry.is_reserved_risky_shortcut("Win+Shift+S"))
        self.assertTrue(key_registry.is_reserved_risky_shortcut("Ctrl+Alt+Delete"))
        self.assertTrue(key_registry.is_reserved_risky_shortcut("Cmd+Space"))

    def test_regular_shortcuts_do_not_warn(self):
        self.assertFalse(key_registry.is_reserved_risky_shortcut("Ctrl+Shift+P"))

    def test_pretty_modifier_names_are_platform_aware(self):
        self.assertEqual(key_registry.pretty_key_name("super", platform_name="darwin"), "Cmd")
        self.assertEqual(key_registry.pretty_key_name("super", platform_name="win32"), "Win")
        self.assertEqual(key_registry.pretty_key_name("super", platform_name="linux"), "Super")
        self.assertEqual(key_registry.pretty_key_name("alt", platform_name="darwin"), "Opt")
        self.assertEqual(key_registry.pretty_key_name("alt", platform_name="linux"), "Alt")


if __name__ == "__main__":
    unittest.main()
