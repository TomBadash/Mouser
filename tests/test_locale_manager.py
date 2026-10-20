import unittest

from ui.locale_manager import AVAILABLE_LANGUAGES, LocaleManager, _TRANSLATIONS

from core.locales import language_for_system_locale, resolve_language_preference
from ui.font_manager import preferred_ui_font_family


class LocaleResolutionTests(unittest.TestCase):
    def test_system_locale_resolves_supported_chinese_variants(self):
        cases = {
            "en-US": "en",
            "zh-Hans-CN": "zh_CN",
            "zh-SG": "zh_CN",
            "zh-Hant-TW": "zh_TW",
            "zh-HK": "zh_TW",
        }
        for locale_name, expected in cases.items():
            with self.subTest(locale_name=locale_name):
                self.assertEqual(language_for_system_locale(locale_name), expected)

    def test_explicit_language_overrides_an_english_system(self):
        self.assertEqual(resolve_language_preference("zh_CN", "en-US"), "zh_CN")
        manager = LocaleManager(language="zh_CN", system_locale_name="en-US")
        self.assertEqual(manager.languagePreference, "zh_CN")
        self.assertEqual(manager.language, "zh_CN")

    def test_system_preference_is_distinct_when_resolved_language_is_same(self):
        manager = LocaleManager(language="en", system_locale_name="en-US")
        changes = []
        manager.languageChanged.connect(lambda: changes.append(manager.languagePreference))

        manager.setLanguage("system")

        self.assertEqual(manager.language, "en")
        self.assertEqual(manager.languagePreference, "system")
        self.assertEqual(changes, ["system"])

    def test_available_languages_include_system_default(self):
        self.assertEqual(AVAILABLE_LANGUAGES[0]["code"], "system")
        self.assertTrue(all("nameKey" in option for option in AVAILABLE_LANGUAGES))


class LocaleFontTests(unittest.TestCase):
    def test_simplified_chinese_uses_windows_ui_font_on_english_windows(self):
        family = preferred_ui_font_family(
            "win32",
            "zh_CN",
            ["Segoe UI", "Microsoft YaHei UI", "Microsoft JhengHei UI"],
            "Segoe UI",
        )
        self.assertEqual(family, "Microsoft YaHei UI")

    def test_traditional_chinese_uses_its_own_windows_glyph_family(self):
        family = preferred_ui_font_family(
            "win32",
            "zh_TW",
            ["Segoe UI", "Microsoft YaHei UI", "Microsoft JhengHei UI"],
            "Segoe UI",
        )
        self.assertEqual(family, "Microsoft JhengHei UI")

    def test_missing_cjk_fonts_fall_back_to_system_font(self):
        family = preferred_ui_font_family(
            "win32", "zh_CN", ["Segoe UI"], "Segoe UI"
        )
        self.assertEqual(family, "Segoe UI")


class LocaleManagerTranslationTests(unittest.TestCase):
    def test_key_capture_error_messages_exist_in_all_locales(self):
        required = {
            "key_capture.error.unsupported_key",
            "key_capture.error.unknown_key",
            "key_capture.error.duplicate_key",
            "key_capture.error.multiple_main_keys",
            "key_capture.error.missing_main_key",
            "key_capture.error.empty_segment",
            "key_capture.error.unsupported",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_key_capture_recorder_strings_exist_in_all_locales(self):
        required = {
            "key_capture.placeholder_recording",
            "key_capture.record_hint",
            "key_capture.type_hint",
            "key_capture.mode_type",
            "key_capture.mode_record",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_key_capture_help_text_covers_the_supported_function_keys(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertIn("f24", strings["key_capture.valid_keys"])

    def test_update_install_messages_exist_in_all_locales(self):
        required = {
            "scroll.update_idle",
            "scroll.update_available",
            "scroll.update_checking",
            "scroll.update_downloading",
            "scroll.update_verifying",
            "scroll.update_ready",
            "scroll.update_installing",
            "scroll.update_installed",
            "scroll.update_installed_version",
            "scroll.update_cancelled",
            "scroll.update_manual",
            "scroll.update_manual_windows",
            "scroll.update_manual_macos",
            "scroll.update_manual_linux",
            "scroll.update_no_asset",
            "scroll.update_error",
            "scroll.update_error_check_first",
            "scroll.update_error_network_error",
            "scroll.update_error_metadata_missing",
            "scroll.update_error_metadata_invalid",
            "scroll.update_error_permission_denied",
            "scroll.update_error_file_error",
            "scroll.update_error_install_failed",
            "scroll.update_error_sha256_mismatch",
            "scroll.update_error_size_mismatch",
            "scroll.update_error_expired_metadata",
            "scroll.update_error_older_build",
            "scroll.update_check",
            "scroll.update_download",
            "scroll.update_cancel",
            "scroll.update_verify",
            "scroll.update_install",
            "scroll.update_open_release",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())


class AccessibilityLocaleTests(unittest.TestCase):
    """The QML accessibility labels added in this batch reference these
    keys. Missing them in a non-English locale silently regresses to a
    KeyError-as-empty-string in the QML lookup ``s[...]``, which leaves
    screen readers reading nothing for an interactive control.
    """

    REQUIRED_KEYS = frozenset({
        "dialog.close",
        "scroll.ignore_trackpad",
        "scroll.ignore_trackpad_desc",
        "scroll.smart_shift",
    })
    ENGLISH_VALUES = frozenset({
        "Close",
        "Ignore trackpad",
        "Only respond to mouse events, not trackpad or Magic Mouse",
    })

    def test_required_accessibility_keys_present_in_all_locales(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                missing = self.REQUIRED_KEYS - strings.keys()
                self.assertFalse(missing, f"{locale} missing keys: {missing}")
                for key in self.REQUIRED_KEYS:
                    self.assertTrue(
                        strings[key].strip(),
                        f"{locale}.{key} is blank",
                    )

    def test_chinese_locales_do_not_passthrough_english(self):
        """Trackpad strings used to ship English text in the zh_CN and
        zh_TW maps. Pin that they are now actually localized."""
        for locale in ("zh_CN", "zh_TW"):
            with self.subTest(locale=locale):
                for key in (
                    "scroll.ignore_trackpad",
                    "scroll.ignore_trackpad_desc",
                ):
                    self.assertNotIn(
                        _TRANSLATIONS[locale][key],
                        self.ENGLISH_VALUES,
                        f"{locale}.{key} still ships English",
                    )
                self.assertNotEqual(
                    _TRANSLATIONS[locale]["scroll.smart_shift"],
                    "SmartShift",
                    f"{locale}.scroll.smart_shift still ships English",
                )


if __name__ == "__main__":
    unittest.main()
