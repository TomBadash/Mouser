import copy
import ctypes
import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread as RealThread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.config import DEFAULT_CONFIG, load_config
from core import remote_session
from test_engine import _FakeMouseHook, _FakeAppDetector, _RecordedThread


class RemoteSessionDetectionTests(unittest.TestCase):
    def test_existing_config_gets_safe_default_and_preserves_opt_out(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        del cfg["settings"]["pause_in_remote_session"]
        with tempfile.TemporaryDirectory() as root:
            config_file = Path(root) / "config.json"
            for opt_out in (False, True):
                if opt_out:
                    cfg["settings"]["pause_in_remote_session"] = False
                config_file.write_text(json.dumps(cfg), encoding="utf-8")
                with (
                    patch("core.config.CONFIG_DIR", root),
                    patch("core.config.CONFIG_FILE", str(config_file)),
                ):
                    self.assertEqual(load_config()["settings"]["pause_in_remote_session"],
                                     not opt_out)

    def _probe(self, protocol=2, success=True, size=2):
        value = ctypes.c_ushort(protocol)

        def query(_server, session_id, info_class, buffer, length):
            self.assertEqual(session_id, 0xFFFFFFFF)
            self.assertEqual(info_class, 16)
            buffer._obj.value = ctypes.addressof(value)
            length._obj.value = size
            return success

        wts = SimpleNamespace(WTSQuerySessionInformationW=Mock(side_effect=query),
                              WTSFreeMemory=Mock())
        user32 = SimpleNamespace(GetSystemMetrics=Mock(return_value=0))
        with (
            patch.object(remote_session.sys, "platform", "win32"),
            patch.object(remote_session.ctypes, "WinDLL", return_value=wts, create=True),
            patch.object(remote_session.ctypes, "windll", SimpleNamespace(user32=user32), create=True),
        ):
            result = remote_session.is_remote_session()
        wts.WTSFreeMemory.assert_called_once()
        return result, user32.GetSystemMetrics

    def test_wts_distinguishes_current_console_and_rdp_sessions(self):
        for protocol, expected in ((0, False), (2, True)):
            with self.subTest(protocol=protocol):
                result, fallback = self._probe(protocol)
                self.assertIs(result, expected)
                fallback.assert_not_called()

    def test_unrecognized_failed_or_short_responses_remain_unknown(self):
        for args in ({"protocol": 1}, {"success": False}, {"size": 1}):
            with self.subTest(args=args):
                result, fallback = self._probe(**args)
                self.assertIsNone(result)
                fallback.assert_called_once_with(0x1000)

    def test_remote_metrics_fallback_and_unknown_local_metrics(self):
        for metric, expected in ((1, True), (0, None)):
            with (
                self.subTest(metric=metric),
                patch.object(remote_session.sys, "platform", "win32"),
                patch.object(remote_session.ctypes, "WinDLL", side_effect=OSError, create=True),
                patch.object(remote_session.ctypes, "windll", SimpleNamespace(
                    user32=SimpleNamespace(GetSystemMetrics=Mock(return_value=metric))), create=True),
            ):
                self.assertIs(remote_session.is_remote_session(), expected)

    def test_non_windows_does_not_call_windows_apis(self):
        with patch.object(remote_session.sys, "platform", "darwin"), \
             patch.object(remote_session.ctypes, "WinDLL", create=True) as dll:
            self.assertIs(remote_session.is_remote_session(), False)
            dll.assert_not_called()


class EngineRemoteSessionTests(unittest.TestCase):
    def setUp(self):
        from core.engine import Engine
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.cfg["profiles"]["default"]["mappings"]["xbutton1"] = "volume_down"
        self.cfg["profiles"]["default"]["mappings"]["xbutton2"] = "volume_up"
        self.state = False
        for target, value in (
            ("core.engine.MouseHook", _FakeMouseHook),
            ("core.engine.AppDetector", _FakeAppDetector),
            ("core.engine.load_config", Mock(return_value=self.cfg)),
            ("core.engine.is_remote_session", lambda: self.state),
            ("core.engine.threading.Thread", _RecordedThread),
            ("core.engine.sys.platform", "win32"),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.engine = Engine()
        self.engine.hook.start = Mock(return_value=True)
        self.engine.hook.stop = Mock()
        self.engine._app_detector.start = Mock()
        self.engine._app_detector.stop = Mock()

    def test_remote_start_never_installs_input_hook_or_app_detector(self):
        self.state = True
        self.engine.start()
        self.assertTrue(self.engine.remote_paused)
        self.engine.hook.start.assert_not_called()
        self.engine._app_detector.start.assert_not_called()
        self.assertFalse(self.engine.remapping_active)

    def test_local_remote_local_preserves_all_inversion_combinations_and_mappings(self):
        for vertical, horizontal in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(vertical=vertical, horizontal=horizontal):
                self.cfg["settings"]["invert_vscroll"] = vertical
                self.cfg["settings"]["invert_hscroll"] = horizontal
                saved = copy.deepcopy(self.cfg)
                self.state = False
                self.engine.start()
                self.engine.reload_mappings()
                self.assertEqual((self.engine.hook.invert_vscroll, self.engine.hook.invert_hscroll),
                                 (vertical, horizontal))
                self.state = True
                self.engine.refresh_remote_session()
                self.assertTrue(self.engine.remote_paused)
                self.assertEqual((self.engine.hook.invert_vscroll, self.engine.hook.invert_hscroll),
                                 (False, False))
                self.engine.refresh_remote_session()
                self.assertEqual(self.cfg, saved)
                self.state = False
                self.engine.refresh_remote_session()
                self.assertFalse(self.engine.remote_paused)
                self.assertEqual((self.engine.hook.invert_vscroll, self.engine.hook.invert_hscroll),
                                 (vertical, horizontal))
                self.engine.stop()

    def test_old_volume_and_mouse_handlers_cannot_execute_while_paused(self):
        volume = self.engine._make_handler("volume_down")
        mouse = self.engine._make_mouse_down_handler("mouse_left_click")
        self.state = True
        self.engine.start()
        with patch("core.engine.execute_action") as execute, patch("core.engine.inject_mouse_down") as down:
            volume(SimpleNamespace(event_type="xbutton1_down"))
            mouse(SimpleNamespace(event_type="xbutton2_down"))
            self.engine._dispatch_action("volume_up")
            execute.assert_not_called()
            down.assert_not_called()

    def test_entering_remote_releases_held_mouse_button_and_stops_runtime_once(self):
        self.engine.start()
        timer = Mock()
        self.engine._mouse_release_timers["mouse_left_click"] = timer
        self.state = True
        with patch("core.engine.inject_mouse_up") as up:
            self.engine.refresh_remote_session()
            self.engine.refresh_remote_session()
            up.assert_called_once_with("mouse_left_click")
        timer.cancel.assert_called_once()
        self.engine.hook.stop.assert_called_once()
        self.engine._app_detector.stop.assert_called_once()
        self.assertFalse(self.engine._mouse_release_timers)

    def test_cancelled_release_timer_cannot_inject_after_pause_or_release_new_press(self):
        self.engine.start()
        first, second = Mock(), Mock()
        handler = self.engine._make_mouse_down_handler("mouse_left_click")
        with (
            patch("core.engine.threading.Timer", side_effect=[first, second]) as timer,
            patch("core.engine.inject_mouse_down"),
            patch("core.engine.inject_mouse_up") as up,
        ):
            handler(SimpleNamespace(event_type="xbutton1_down"))
            old_release = timer.call_args.args[1]
            self.state = True
            self.engine.refresh_remote_session()
            up.assert_called_once_with("mouse_left_click")
            old_release()
            up.assert_called_once()
            self.state = False
            self.engine.refresh_remote_session()
            handler(SimpleNamespace(event_type="xbutton1_down"))
            old_release()
            up.assert_called_once()
            self.assertIs(self.engine._mouse_release_timers["mouse_left_click"], second)
            self.engine.stop()

    def test_pause_discards_partial_horizontal_mapping_accumulator(self):
        self.engine.start()
        for state in self.engine._hscroll_state.values():
            state.update(accum=0.75, last_fire_at=50.0)
        self.state = True
        self.engine.refresh_remote_session()
        for state in self.engine._hscroll_state.values():
            self.assertEqual(state, {"accum": 0.0, "last_fire_at": 0.0})

    def test_editing_while_paused_only_applies_when_back_at_console(self):
        self.state = True
        self.engine.start()
        self.cfg["settings"]["invert_vscroll"] = True
        self.engine.reload_mappings()
        self.engine.hook.start.assert_not_called()
        self.assertFalse(self.engine.hook.invert_vscroll)
        self.state = False
        self.engine.refresh_remote_session()
        self.assertTrue(self.engine.hook.invert_vscroll)

    def test_policy_opt_out_takes_effect_without_overwriting_manual_disable(self):
        self.state = True
        self.engine.start()
        self.engine.set_enabled(False)
        self.cfg["settings"]["pause_in_remote_session"] = False
        self.engine.refresh_remote_session()
        self.assertFalse(self.engine.remote_paused)
        self.assertFalse(self.engine.enabled)
        self.engine.hook.start.assert_called_once()
        self.cfg["settings"]["pause_in_remote_session"] = True
        self.engine.refresh_remote_session()
        self.assertTrue(self.engine.remote_paused)
        self.assertFalse(self.engine.enabled)

    def test_unknown_state_pauses_until_console_is_confirmed(self):
        self.state = None
        self.engine.start()
        self.assertEqual(self.engine.remote_session_state, "unknown")
        self.assertTrue(self.engine.remote_paused)
        self.engine.hook.start.assert_not_called()
        self.state = False
        self.engine.refresh_remote_session()
        self.engine.hook.start.assert_called_once()

    def test_stopped_engine_does_not_restart_from_a_late_session_notification(self):
        self.engine.start()
        self.engine.stop()
        self.engine.hook.start.reset_mock()
        self.engine.refresh_remote_session()
        self.engine.hook.start.assert_not_called()

    def test_repeated_start_does_not_install_duplicate_input_runtime(self):
        self.engine.start()
        self.engine.start()
        self.engine.refresh_remote_session()
        self.engine.hook.start.assert_called_once()
        self.engine._app_detector.start.assert_called_once()

    def test_concurrent_resume_waits_until_pause_cleanup_finishes(self):
        self.engine.start()
        self.engine.hook.start.reset_mock()
        cleanup_entered, release_cleanup = Event(), Event()
        resume_requested, resume_finished = Event(), Event()
        operations, errors = [], []

        def cleanup():
            operations.append("cleanup started")
            cleanup_entered.set()
            if not release_cleanup.wait(2):
                raise TimeoutError("test did not release pause cleanup")
            operations.append("cleanup finished")

        def refresh(requested=None, finished=None):
            if requested:
                requested.set()
            try:
                self.engine.refresh_remote_session()
            except Exception as error:
                errors.append(error)
            finally:
                if finished:
                    finished.set()

        self.engine.hook.stop.side_effect = cleanup
        self.engine.hook.start.side_effect = lambda: operations.append("runtime resumed")
        self.state = True
        # Use real caller threads; the engine's device workers remain mocked.
        pause_thread = RealThread(target=refresh, daemon=True)
        resume_thread = RealThread(
            target=refresh, args=(resume_requested, resume_finished), daemon=True,
        )
        pause_thread.start()
        try:
            self.assertTrue(cleanup_entered.wait(2))
            self.state = False
            resume_thread.start()
            self.assertTrue(resume_requested.wait(2))
            self.assertFalse(resume_finished.wait(0.1))
            self.assertEqual(operations, ["cleanup started"])
        finally:
            release_cleanup.set()
            pause_thread.join(2)
            if resume_thread.ident is not None:
                resume_thread.join(2)
        self.assertFalse(pause_thread.is_alive())
        self.assertFalse(resume_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(operations, [
            "cleanup started", "cleanup finished", "runtime resumed",
        ])
        self.assertFalse(self.engine.remote_paused)
        self.engine.hook.stop.assert_called_once()
        self.engine.hook.start.assert_called_once()

    def test_restart_applies_policy_even_when_session_type_is_unchanged(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                self.state = remote
                self.engine.start()
                self.engine.stop()
                self.engine.hook.start.reset_mock()
                self.engine._app_detector.start.reset_mock()
                self.engine.start()
                self.assertEqual(self.engine.remote_paused, remote)
                if remote:
                    self.engine.hook.start.assert_not_called()
                    self.engine._app_detector.start.assert_not_called()
                else:
                    self.engine.hook.start.assert_called_once()
                    self.engine._app_detector.start.assert_called_once()
                self.engine.stop()

    def test_paused_hid_callbacks_do_not_restart_device_workers(self):
        self.state = True
        self.engine.start()
        with patch("core.engine.threading.Thread") as thread:
            self.engine._on_connection_change(True)
            self.engine._request_saved_settings_replay()
            self.assertFalse(self.engine._run_saved_settings_replay())
            thread.assert_not_called()

    def test_device_settings_replay_cannot_write_old_settings_to_resumed_listener(self):
        self.engine.start()
        old = SimpleNamespace(connected_device=object(), smart_shift_supported=False,
                              set_dpi=Mock())
        new = SimpleNamespace(connected_device=object(), smart_shift_supported=False,
                              set_dpi=Mock())
        self.engine.hook._hid_gesture = old

        def switch_session(_delay):
            self.state = True
            self.engine.refresh_remote_session()
            self.engine.hook._hid_gesture = None
            self.state = False
            self.engine.refresh_remote_session()
            self.engine.hook._hid_gesture = new

        with patch("core.engine.time.sleep", side_effect=switch_session):
            self.assertFalse(self.engine._run_saved_settings_replay())
        old.set_dpi.assert_not_called()
        new.set_dpi.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows hook cleanup")
class WindowsHookPauseCleanupTests(unittest.TestCase):
    def test_stop_discards_pending_scroll_and_dispatch_events_before_restart(self):
        from core.mouse_hook_windows import MouseHook
        hook = MouseHook()
        hook._pending_vscroll = 120
        hook._pending_hscroll = -120
        hook._pending_shift_hscroll = 240
        hook._vscroll_posted = hook._hscroll_posted = hook._shift_hscroll_posted = True
        hook._dispatch_queue.put(SimpleNamespace(event_type="xbutton1_down"))
        hook.stop()
        self.assertTrue(hook._dispatch_queue.empty())
        self.assertEqual((hook._pending_vscroll, hook._pending_hscroll, hook._pending_shift_hscroll), (0, 0, 0))
        self.assertFalse(hook._vscroll_posted or hook._hscroll_posted or hook._shift_hscroll_posted)


if __name__ == "__main__":
    unittest.main()
