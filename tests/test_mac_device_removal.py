"""Regression coverage for native HID removal and reconnection detection."""

import unittest
from unittest.mock import Mock, patch

from core import hid_gesture as hid


@unittest.skipUnless(hid._MAC_NATIVE_OK, "requires native macOS HID bindings")
class MacDeviceRemovalTests(unittest.TestCase):
    def setUp(self):
        self.device = hid._MacNativeHidDevice(0xB037)

    def test_removed_device_drains_queued_input_before_failing(self):
        self.device._report_queue.put(b"held button release")
        callback = hid._IOHID_REMOVAL_CALLBACK(self.device._on_removal)
        callback(None, 0, None)
        self.assertEqual(self.device.read(64, 10), b"held button release")
        with self.assertRaisesRegex(OSError, "IOHIDDevice removed"):
            self.device.read(64, 10)

    def test_removal_during_run_loop_interrupts_read(self):
        callback = hid._IOHID_REMOVAL_CALLBACK(self.device._on_removal)

        def pump(*_args):
            callback(None, 0, None)
            return 0

        with patch.object(hid._cf, "CFRunLoopRunInMode", side_effect=pump):
            with self.assertRaisesRegex(OSError, "IOHIDDevice removed"):
                self.device.read(64, 1000)

    def test_close_unregisters_callback_before_unschedule_and_is_idempotent(self):
        events = []
        self.device._device = 1
        self.device._run_loop = 2
        self.device._removal_callback = hid._IOHID_REMOVAL_CALLBACK(self.device._on_removal)
        with (
            patch.object(hid._iokit, "IOHIDDeviceRegisterRemovalCallback", side_effect=lambda *args: events.append(("unregister", args))),
            patch.object(hid._iokit, "IOHIDDeviceUnscheduleFromRunLoop", side_effect=lambda *args: events.append(("unschedule", args))),
            patch.object(hid._iokit, "IOHIDDeviceClose", side_effect=lambda *args: events.append(("close", args))),
            patch.object(hid._cf, "CFRelease", side_effect=lambda *args: events.append(("release", args))),
        ):
            self.device.close()
            self.device.close()
        self.assertEqual([event[0] for event in events], ["unregister", "unschedule", "close", "release"])
        self.assertEqual(events[0][1], (1, None, None))
        self.assertIsNone(self.device._removal_callback)

    def test_removal_enters_listener_reconnect_flow(self):
        events = []
        listener = hid.HidGestureListener(
            on_connect=lambda: events.append("connected"),
            on_disconnect=lambda: events.append("disconnected"),
            on_up=lambda: events.append("released"),
        )
        listener._running = True
        listener._held = True
        self.device._on_removal(None, 0, None)
        replacement = Mock()

        def try_connect():
            if not events:
                listener._dev = self.device
                return True
            listener._dev = replacement
            return True

        def on_connect():
            events.append("connected")
            if events.count("connected") == 2:
                listener._running = False

        listener._on_connect = on_connect
        original_read = self.device.read
        reads = []

        def read_with_guard(*args, **kwargs):
            reads.append(1)
            if len(reads) > 1:
                listener._running = False
                raise AssertionError("removed device was not detected on first read")
            return original_read(*args, **kwargs)

        with (
            patch.object(listener, "_try_connect", side_effect=try_connect),
            patch.object(listener, "_interruptible_sleep"),
            patch.object(listener, "_undivert"),
            patch.object(self.device, "close") as close_removed,
            patch.object(self.device, "read", side_effect=read_with_guard),
        ):
            listener._main_loop()
        self.assertEqual(events, ["connected", "released", "disconnected", "connected", "disconnected"])
        close_removed.assert_called_once()
        replacement.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
