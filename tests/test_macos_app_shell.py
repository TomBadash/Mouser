import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import main_qml
except Exception:  # pragma: no cover - env without PySide6 / project deps
    main_qml = None


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class MacOSLauncherPathTests(unittest.TestCase):
    def test_named_executable_uses_venv_shim_directory(self):
        executable = "/tmp/Mouser/.venv/bin/python"

        def fake_isfile(path):
            return path in {executable, "/tmp/Mouser/.venv/pyvenv.cfg"}

        with (
            patch.object(main_qml.sys, "executable", executable),
            patch.object(main_qml.os.path, "isfile", side_effect=fake_isfile),
        ):
            self.assertEqual(
                main_qml._macos_named_executable_path(),
                "/tmp/Mouser/.venv/bin/Mouser",
            )

    def test_named_executable_uses_project_fallback_outside_venv(self):
        with (
            patch.object(main_qml.sys, "executable", "/usr/bin/python3"),
            patch.object(main_qml.os.path, "isfile", return_value=False),
            patch.object(main_qml, "ROOT", "/tmp/Mouser"),
        ):
            self.assertEqual(
                main_qml._macos_named_executable_path(),
                "/tmp/Mouser/build/macos/bin/Mouser",
            )

    def test_relaunch_noops_off_macos(self):
        with (
            patch.object(main_qml.sys, "platform", "linux"),
            patch.object(main_qml.os, "execv") as execv,
        ):
            main_qml._maybe_relaunch_with_mouser_process_name()
        execv.assert_not_called()

    def test_relaunch_stages_symlink_and_execs_named_path(self):
        executable = "/tmp/Mouser/.venv/bin/python"
        target = "/tmp/Mouser/.venv/bin/Mouser"
        staging = f"{target}.staging.1234"

        def fake_isfile(path):
            return path in {executable, "/tmp/Mouser/.venv/pyvenv.cfg"}

        with (
            patch.object(main_qml.sys, "platform", "darwin"),
            patch.object(main_qml.sys, "executable", executable),
            patch.object(main_qml.sys, "argv", ["main_qml.py", "--show-window"]),
            patch.object(main_qml.os.path, "isfile", side_effect=fake_isfile),
            patch.object(main_qml.os, "makedirs") as makedirs,
            patch.object(main_qml.os, "symlink") as symlink,
            patch.object(main_qml.os, "replace") as replace,
            patch.object(main_qml.os, "getpid", return_value=1234),
            patch.object(main_qml.os, "execv") as execv,
            patch.dict(main_qml.os.environ, {}, clear=True),
        ):
            main_qml._maybe_relaunch_with_mouser_process_name()

        makedirs.assert_called_once_with("/tmp/Mouser/.venv/bin", exist_ok=True)
        symlink.assert_called_once_with(executable, staging)
        replace.assert_called_once_with(staging, target)
        execv.assert_called_once_with(target, [target, "main_qml.py", "--show-window"])


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class MacOSStatusItemEventTests(unittest.TestCase):
    def _appkit(self, event=None):
        return SimpleNamespace(
            NSLeftMouseDown=1,
            NSRightMouseDown=3,
            NSOtherMouseDown=25,
            NSControlKeyMask=1 << 18,
            NSAlternateKeyMask=1 << 19,
            NSApp=SimpleNamespace(currentEvent=lambda: event),
        )

    def _event(self, event_type, modifiers=0):
        return SimpleNamespace(type=lambda: event_type, modifierFlags=lambda: modifiers)

    def test_status_event_routes_plain_left_click_to_primary(self):
        appkit = self._appkit()
        event = self._event(appkit.NSLeftMouseDown)
        self.assertFalse(main_qml._macos_status_event_opens_menu(event, appkit))

    def test_status_event_routes_right_control_and_option_click_to_menu(self):
        appkit = self._appkit()
        self.assertTrue(
            main_qml._macos_status_event_opens_menu(
                self._event(appkit.NSRightMouseDown),
                appkit,
            )
        )
        self.assertTrue(
            main_qml._macos_status_event_opens_menu(
                self._event(appkit.NSLeftMouseDown, appkit.NSControlKeyMask),
                appkit,
            )
        )
        self.assertTrue(
            main_qml._macos_status_event_opens_menu(
                self._event(appkit.NSLeftMouseDown, appkit.NSAlternateKeyMask),
                appkit,
            )
        )

    def test_status_click_dispatches_to_selected_handler(self):
        calls = []
        menu_event = self._event(3)
        appkit = self._appkit(menu_event)

        main_qml._dispatch_macos_status_item_click({
            "appkit": appkit,
            "primary": lambda: calls.append("primary"),
            "menu": lambda: calls.append("menu"),
        })

        self.assertEqual(calls, ["menu"])


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class MacOSSystemQuitReasonTests(unittest.TestCase):
    def _descriptor(self, value):
        return SimpleNamespace(enumCodeValue=lambda: main_qml._four_char_code(value))

    def _appkit(self, *, descriptor):
        apple_event = SimpleNamespace(
            attributeDescriptorForKeyword_=lambda keyword: (
                descriptor if keyword == main_qml._four_char_code("why?") else None
            )
        )
        manager = SimpleNamespace(currentAppleEvent=lambda: apple_event)
        return SimpleNamespace(
            NSAppleEventManager=SimpleNamespace(
                sharedAppleEventManager=lambda: manager
            )
        )

    def test_system_quit_reason_codes_are_allowed_through(self):
        for reason in ("quia", "shut", "rest", "rlgo", "logo", "rrst", "rsdn"):
            with self.subTest(reason=reason):
                with (
                    patch.object(main_qml.sys, "platform", "darwin"),
                    patch.object(
                        main_qml,
                        "_macos_appkit",
                        return_value=self._appkit(descriptor=self._descriptor(reason)),
                    ),
                ):
                    self.assertTrue(
                        main_qml._macos_current_quit_is_system_session_event()
                    )

    def test_missing_or_unknown_quit_reason_stays_user_quit(self):
        for descriptor in (None, self._descriptor("quit")):
            with self.subTest(descriptor=descriptor):
                with (
                    patch.object(main_qml.sys, "platform", "darwin"),
                    patch.object(
                        main_qml,
                        "_macos_appkit",
                        return_value=self._appkit(descriptor=descriptor),
                    ),
                ):
                    self.assertFalse(
                        main_qml._macos_current_quit_is_system_session_event()
                    )


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class MacOSQuitAndAccessibilityTests(unittest.TestCase):
    def test_quit_filter_hides_window_and_blocks_app_quit(self):
        root_window = MagicMock()
        event = MagicMock()
        event.type.return_value = main_qml.QEvent.Type.Quit
        event_filter = main_qml._MacOSQuitToTrayFilter(root_window)

        self.assertTrue(event_filter.eventFilter(None, event))

        root_window.hide.assert_called_once()
        event.ignore.assert_called_once()

    def test_quit_filter_allows_explicit_tray_quit(self):
        root_window = MagicMock()
        event = MagicMock()
        event.type.return_value = main_qml.QEvent.Type.Quit
        event_filter = main_qml._MacOSQuitToTrayFilter(root_window)

        event_filter.allow_quit()

        self.assertFalse(event_filter.eventFilter(None, event))
        root_window.hide.assert_not_called()
        event.ignore.assert_not_called()

    def test_quit_filter_allows_system_session_quit(self):
        root_window = MagicMock()
        event = MagicMock()
        event.type.return_value = main_qml.QEvent.Type.Quit
        event_filter = main_qml._MacOSQuitToTrayFilter(root_window)

        with patch.object(
            main_qml,
            "_macos_current_quit_is_system_session_event",
            return_value=True,
        ):
            self.assertFalse(event_filter.eventFilter(None, event))

        root_window.hide.assert_not_called()
        event.ignore.assert_not_called()

    def test_session_quit_fallback_does_not_allow_ordinary_quit(self):
        event_filter = main_qml._MacOSQuitToTrayFilter(MagicMock())

        with patch.object(
            main_qml,
            "_macos_current_quit_is_system_session_event",
            return_value=False,
        ):
            self.assertFalse(
                main_qml._allow_macos_session_quit_if_requested(event_filter)
            )

        event = MagicMock()
        event.type.return_value = main_qml.QEvent.Type.Quit
        self.assertTrue(event_filter.eventFilter(None, event))

    def test_session_quit_fallback_allows_system_quit(self):
        event_filter = main_qml._MacOSQuitToTrayFilter(MagicMock())

        with patch.object(
            main_qml,
            "_macos_current_quit_is_system_session_event",
            return_value=True,
        ):
            self.assertTrue(
                main_qml._allow_macos_session_quit_if_requested(event_filter)
            )

        event = MagicMock()
        event.type.return_value = main_qml.QEvent.Type.Quit
        self.assertFalse(event_filter.eventFilter(None, event))

    def test_engine_start_not_scheduled_without_accessibility(self):
        engine = MagicMock()

        with patch("PySide6.QtCore.QTimer.singleShot") as single_shot:
            started = main_qml._schedule_engine_start(
                engine,
                accessibility_granted=False,
            )

        self.assertFalse(started)
        single_shot.assert_not_called()
        engine.start.assert_not_called()

    def test_engine_start_schedules_when_accessibility_is_granted(self):
        engine = MagicMock()

        with patch("PySide6.QtCore.QTimer.singleShot") as single_shot:
            started = main_qml._schedule_engine_start(
                engine,
                accessibility_granted=True,
            )

        self.assertTrue(started)
        delay, callback = single_shot.call_args.args
        self.assertEqual(delay, 0)

        callback()
        engine.start.assert_called_once()

    def test_accessibility_check_exception_fails_closed(self):
        with (
            patch.object(main_qml.sys, "platform", "darwin"),
            patch.object(main_qml, "is_process_trusted", side_effect=RuntimeError("boom")),
        ):
            self.assertFalse(main_qml._check_accessibility())

    def test_tray_minimized_notice_is_scheduled_with_module_qtimer(self):
        tray = MagicMock()
        locale_mgr = SimpleNamespace(tr=lambda key: f"translated:{key}")

        with patch.object(main_qml.QTimer, "singleShot") as single_shot:
            main_qml._schedule_tray_minimized_notice(tray, locale_mgr)

        delay, callback = single_shot.call_args.args
        self.assertEqual(delay, 400)

        callback()
        tray.showMessage.assert_called_once_with(
            "Mouser",
            "translated:tray.tray_message",
            main_qml.QSystemTrayIcon.MessageIcon.Information,
            5000,
        )


@unittest.skipIf(main_qml is None, "main_qml / PySide6 not available")
class AccessibilityGrantRecoveryTests(unittest.TestCase):
    """The watcher that revives Mouser once the user grants the
    Accessibility permission -- instead of leaving it idle until a
    manual quit-and-reopen."""

    def test_check_reports_grant_state_on_macos(self):
        with (
            patch.object(main_qml.sys, "platform", "darwin"),
            patch.object(main_qml, "is_process_trusted", return_value=True),
        ):
            self.assertTrue(main_qml._check_accessibility())

        with (
            patch.object(main_qml.sys, "platform", "darwin"),
            patch.object(main_qml, "is_process_trusted", return_value=False),
        ):
            self.assertFalse(main_qml._check_accessibility())

    def test_relaunch_releases_lock_and_execs_source_argv(self):
        single_server = MagicMock()

        with (
            patch.object(main_qml.sys, "executable", "/usr/bin/python3"),
            patch.object(main_qml.sys, "argv", ["main_qml.py", "--show-window"]),
            patch.object(main_qml.sys, "frozen", False, create=True),
            patch.object(main_qml.os, "execv") as execv,
        ):
            main_qml._relaunch_app(single_server)

        single_server.close.assert_called_once_with()
        execv.assert_called_once_with(
            "/usr/bin/python3",
            ["/usr/bin/python3", "main_qml.py", "--show-window"],
        )

    def test_relaunch_drops_argv0_for_frozen_build(self):
        binary = "/Applications/Mouser.app/Contents/MacOS/Mouser"

        with (
            patch.object(main_qml.sys, "executable", binary),
            patch.object(main_qml.sys, "argv", [binary, "--start-hidden"]),
            patch.object(main_qml.sys, "frozen", True, create=True),
            patch.object(main_qml.os, "execv") as execv,
        ):
            main_qml._relaunch_app(None)

        execv.assert_called_once_with(binary, [binary, "--start-hidden"])

    def test_relaunch_survives_failed_execv(self):
        with (
            patch.object(main_qml.sys, "executable", "/usr/bin/python3"),
            patch.object(main_qml.sys, "argv", ["main_qml.py"]),
            patch.object(main_qml.sys, "frozen", False, create=True),
            patch.object(main_qml.os, "execv", side_effect=OSError("denied")),
        ):
            main_qml._relaunch_app(None)  # must not raise

    def test_grant_poll_relaunches_once_permission_lands(self):
        timer = MagicMock()
        single_server = MagicMock()

        with (
            patch.object(main_qml, "is_process_trusted", return_value=True),
            patch.object(main_qml, "_relaunch_app") as relaunch,
        ):
            triggered = main_qml._accessibility_grant_poll(timer, single_server)

        self.assertTrue(triggered)
        timer.stop.assert_called_once_with()
        relaunch.assert_called_once_with(single_server)

    def test_grant_poll_keeps_waiting_without_permission(self):
        timer = MagicMock()

        with (
            patch.object(main_qml, "is_process_trusted", return_value=False),
            patch.object(main_qml, "_relaunch_app") as relaunch,
        ):
            triggered = main_qml._accessibility_grant_poll(timer, MagicMock())

        self.assertFalse(triggered)
        timer.stop.assert_not_called()
        relaunch.assert_not_called()

    def test_grant_poll_survives_check_exception(self):
        timer = MagicMock()

        with (
            patch.object(
                main_qml, "is_process_trusted", side_effect=RuntimeError("boom")
            ),
            patch.object(main_qml, "_relaunch_app") as relaunch,
        ):
            triggered = main_qml._accessibility_grant_poll(timer, MagicMock())

        self.assertFalse(triggered)
        timer.stop.assert_not_called()
        relaunch.assert_not_called()

    def test_watch_accessibility_grant_starts_polling_timer(self):
        fake_timer = MagicMock()

        with patch.object(main_qml, "QTimer", return_value=fake_timer):
            returned = main_qml._watch_accessibility_grant(MagicMock(), MagicMock())

        self.assertIs(returned, fake_timer)
        fake_timer.setInterval.assert_called_once_with(
            main_qml._ACCESSIBILITY_POLL_INTERVAL_MS
        )
        fake_timer.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
