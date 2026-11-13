"""Exercise the actual macOS mode-shift callbacks without installing input hooks."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@unittest.skipUnless(sys.platform == "darwin", "macOS-only regression")
class MacOSModeShiftGestureTests(unittest.TestCase):
    def setUp(self):
        from core import mouse_hook_macos

        self.module = mouse_hook_macos
        self.quartz = MagicMock()
        for name in (
            "kCGEventSourceUserData", "kCGEventMouseMoved",
            "kCGEventOtherMouseDragged", "kCGMouseEventDeltaX",
            "kCGMouseEventDeltaY", "kCGEventOtherMouseDown",
            "kCGEventOtherMouseUp", "kCGEventScrollWheel",
        ):
            setattr(self.quartz, name, name)
        self.quartz.CGEventGetIntegerValueField.side_effect = (
            lambda event, field: event.get(field, 0)
        )
        self.addCleanup(patch.stopall)
        patch.object(mouse_hook_macos, "Quartz", self.quartz).start()
        self.clock = patch("time.monotonic", return_value=100.0).start()

    def make_hook(self, gesture=True):
        hook = self.module.MouseHook()
        hook._first_event_logged = True
        hook._connected_device = SimpleNamespace(key="mx_anywhere_3s")
        hook.configure_button_gestures(
            owners={"mode_shift"} if gesture else set(), threshold=25,
        )
        self.direct_events = []
        hook._dispatch = self.direct_events.append
        return hook

    def queued_events(self, hook):
        events = []
        while not hook._dispatch_queue.empty():
            events.append(hook._dispatch_queue.get_nowait())
        return events

    def move(self, hook, dx, dy):
        event = {"kCGMouseEventDeltaX": dx, "kCGMouseEventDeltaY": dy}
        return event, hook._event_tap_callback(
            None, self.quartz.kCGEventMouseMoved, event, None,
        )

    def test_mode_shift_tap_in_gesture_mode_emits_one_tap(self):
        hook = self.make_hook()
        hook._on_hid_mode_shift_down()
        self.assertEqual(hook._button_gesture_active_owner, "mode_shift")
        self.clock.return_value += 0.08
        hook._on_hid_mode_shift_up()
        events = self.queued_events(hook)
        self.assertEqual([e.event_type for e in events], ["button_tap"])
        self.assertEqual(events[0].raw_data["gesture_owner"], "mode_shift")
        self.assertEqual(self.direct_events, [])
        self.assertIsNone(hook._button_gesture_active_owner)

    def test_all_four_swipes_freeze_cursor_and_do_not_fire_tap(self):
        for direction, dx, dy in (
            ("up", 0, -20), ("down", 0, 20),
            ("left", -20, 0), ("right", 20, 0),
        ):
            with self.subTest(direction=direction):
                hook = self.make_hook()
                hook._on_hid_mode_shift_down()
                for _ in range(12):
                    self.clock.return_value += 0.01
                    _, result = self.move(hook, dx, dy)
                    self.assertIsNone(result, "gesture motion must not move the cursor")
                hook._on_hid_mode_shift_up()
                events = self.queued_events(hook)
                self.assertEqual(
                    [e.event_type for e in events], [f"button_swipe_{direction}"],
                )
                self.assertEqual(events[0].raw_data["gesture_owner"], "mode_shift")
                self.assertEqual(self.direct_events, [])
                self.assertIsNone(hook._button_gesture_active_owner)
                event, result = self.move(hook, 5, 0)
                self.assertIs(result, event, "normal cursor motion must resume after release")

    def test_ordinary_mode_shift_mapping_keeps_down_and_up(self):
        hook = self.make_hook(gesture=False)
        hook._on_hid_mode_shift_down()
        hook._on_hid_mode_shift_up()
        self.assertEqual(
            [e.event_type for e in self.direct_events],
            ["mode_shift_down", "mode_shift_up"],
        )
        self.assertEqual(self.queued_events(hook), [])


if __name__ == "__main__":
    unittest.main()
