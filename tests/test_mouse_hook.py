import importlib
import queue
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, call, patch

import core
from core import mouse_hook
from core.mouse_hook_base import BaseMouseHook
from core.mouse_hook_types import HidRuntimeState


class _FakeEvdevDevice:
    def __init__(self, *, name, path, vendor, capabilities, product=0, fd=11,
                 active_keys=()):
        self.name = name
        self.path = path
        self.fd = fd
        self.info = SimpleNamespace(
            vendor=vendor,
            product=product,
            version=1,
            bustype=0x03,
        )
        self._capabilities = capabilities
        self._active_keys = list(active_keys)
        self.grab = Mock()
        self.ungrab = Mock()
        self.close = Mock()
        self.read = Mock(return_value=[])

    def capabilities(self, absinfo=False):
        return self._capabilities

    def active_keys(self, verbose=False):
        return list(self._active_keys)

    def set_active_keys(self, keys):
        self._active_keys = list(keys)


class _CapturingListener:
    def __init__(self, on_down=None, on_up=None, on_move=None,
                 on_connect=None, on_disconnect=None, extra_diverts=None,
                 on_thumb_button_down=None, on_thumb_button_up=None,
                 on_thumb_button_move=None, **_kwargs):
        self.on_down = on_down
        self.on_up = on_up
        self.on_move = on_move
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.extra_diverts = extra_diverts or {}
        self.on_thumb_button_down = on_thumb_button_down
        self.on_thumb_button_up = on_thumb_button_up
        self.on_thumb_button_move = on_thumb_button_move
        self.connected_device = None
        self.started = False
        self.stopped = False
        self.thumb_rawxy_enabled = False

    def set_thumb_rawxy_enabled(self, enabled):
        self.thumb_rawxy_enabled = bool(enabled)

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class _FakeLinuxEcodes:
    EV_SYN = 0x00
    EV_REL = 0x02
    EV_KEY = 0x01
    REL_X = 0x00
    REL_Y = 0x01
    REL_WHEEL = 0x08
    REL_HWHEEL = 0x06
    REL_WHEEL_HI_RES = 0x0B
    REL_HWHEEL_HI_RES = 0x0C
    BTN_LEFT = 0x110
    BTN_RIGHT = 0x111
    BTN_MIDDLE = 0x112
    BTN_SIDE = 0x113
    BTN_EXTRA = 0x114
    KEY_LEFTSHIFT = 42
    KEY_RIGHTSHIFT = 54


class _FakeLinuxUInput:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.write_event = Mock()
        self.write = Mock()
        self.close = Mock()


class BaseMouseHookRuntimeStateTests(unittest.TestCase):
    def test_default_runtime_state_is_disconnected(self):
        hook = BaseMouseHook()

        self.assertEqual(hook.hid_runtime_state, HidRuntimeState())

    def test_runtime_state_projects_hid_identity(self):
        hook = BaseMouseHook()
        device = SimpleNamespace(name="MX Master 3S")
        hook._hid_gesture = SimpleNamespace(connected_device=device)

        hook._on_hid_connect()

        state = hook.hid_runtime_state
        self.assertTrue(state.input_ready)
        self.assertTrue(state.hid_ready)
        self.assertIs(state.connected_device, device)

    def test_status_callback_is_optional(self):
        hook = BaseMouseHook()
        hook._emit_status("ignored")
        messages = []

        hook.set_status_callback(messages.append)
        hook._emit_status("Linux evdev remapping restored.")

        self.assertEqual(messages, ["Linux evdev remapping restored."])

    def test_should_intercept_events_defaults_to_false(self):
        """Fresh hook, no Logitech bound -- platform taps must stand
        down so non-Logitech mice are not silently remapped."""
        hook = BaseMouseHook()

        self.assertFalse(hook._should_intercept_events())

    def test_should_intercept_events_flips_on_hid_connect(self):
        hook = BaseMouseHook()
        device = SimpleNamespace(name="MX Master 3S")
        hook._hid_gesture = SimpleNamespace(connected_device=device)

        hook._on_hid_connect()

        self.assertTrue(hook._should_intercept_events())

    def test_should_intercept_events_flips_off_on_hid_disconnect(self):
        """KVM switch / sleep wake: the moment HID++ drops the device,
        the next OS event must pass through untouched."""
        hook = BaseMouseHook()
        device = SimpleNamespace(name="MX Master 3S")
        hook._hid_gesture = SimpleNamespace(connected_device=device)
        hook._on_hid_connect()
        self.assertTrue(hook._should_intercept_events())

        hook._on_hid_disconnect()

        self.assertFalse(hook._should_intercept_events())


class BaseMouseHookDispatchQueueTests(unittest.TestCase):
    def test_enqueue_keeps_queue_bounded_and_drops_oldest(self):
        hook = BaseMouseHook()
        hook._init_dispatch_queue(maxsize=2)

        hook._enqueue_dispatch_event(SimpleNamespace(event_type="e1", raw_data=None))
        hook._enqueue_dispatch_event(SimpleNamespace(event_type="e2", raw_data=None))
        hook._enqueue_dispatch_event(SimpleNamespace(event_type="e3", raw_data=None))

        self.assertEqual(hook._dispatch_queue.qsize(), 2)
        first = hook._dispatch_queue.get_nowait()
        second = hook._dispatch_queue.get_nowait()
        self.assertEqual(first.event_type, "e2")
        self.assertEqual(second.event_type, "e3")

    def test_enqueue_drops_and_emits_debug_when_still_full(self):
        hook = BaseMouseHook()
        hook._init_dispatch_queue(maxsize=1)
        hook.debug_mode = True
        hook.set_debug_callback(Mock())

        hook._dispatch_queue.put_nowait(SimpleNamespace(event_type="old", raw_data=None))
        with patch.object(hook._dispatch_queue, "get_nowait", side_effect=queue.Empty):
            with patch.object(hook._dispatch_queue, "put_nowait", side_effect=[queue.Full, queue.Full]):
                hook._enqueue_dispatch_event(SimpleNamespace(event_type="new", raw_data=None))

        hook._debug_callback.assert_called_once()
        self.assertIn("Dropped event due to full dispatch queue", hook._debug_callback.call_args[0][0])


class LinuxMouseHookReconnectTests(unittest.TestCase):
    def _reload_for_linux(self):
        fake_evdev = SimpleNamespace(
            ecodes=_FakeLinuxEcodes,
            UInput=_FakeLinuxUInput,
            InputDevice=Mock(name="InputDevice"),
        )
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"evdev": fake_evdev}),
        ):
            sys.modules.pop("core.mouse_hook_linux", None)
            if hasattr(core, "mouse_hook_linux"):
                delattr(core, "mouse_hook_linux")
            mouse_hook_linux = importlib.import_module("core.mouse_hook_linux")
            importlib.reload(mouse_hook)

        def cleanup():
            sys.modules.pop("core.mouse_hook_linux", None)
            if hasattr(core, "mouse_hook_linux"):
                delattr(core, "mouse_hook_linux")
            importlib.reload(mouse_hook)

        self.addCleanup(cleanup)
        return mouse_hook

    def _fake_caps(self, module, *, include_side=True):
        ecodes = module._ecodes
        key_codes = [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]
        if include_side:
            key_codes.extend([ecodes.BTN_SIDE, ecodes.BTN_EXTRA])
        return {
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
            ecodes.EV_KEY: key_codes,
        }

    def _patch_evdev_lookup(self, module, devices_by_path):
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: list(devices_by_path))

        def fake_input_device(path):
            return devices_by_path[path]

        return (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module, "_InputDevice", side_effect=fake_input_device),
        )

    def test_find_mouse_device_prefers_logitech_candidates(self):
        module = self._reload_for_linux()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        generic = _FakeEvdevDevice(
            name="Generic Mouse",
            path="/dev/input/event0",
            vendor=0x1234,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                generic.path: generic,
                logi.path: logi,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, logi)
        self.assertTrue(generic.close.called)
        self.assertFalse(logi.close.called)

    def test_find_mouse_device_prefers_known_supported_logitech_model(self):
        module = self._reload_for_linux()
        legacy = _FakeEvdevDevice(
            name="Logitech Performance MX",
            path="/dev/input/event11",
            vendor=module._LOGI_VENDOR,
            product=0x101A,
            capabilities=self._fake_caps(module),
        )
        modern = _FakeEvdevDevice(
            name="Logitech MX Master 3S",
            path="/dev/input/event22",
            vendor=module._LOGI_VENDOR,
            product=0xB034,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                legacy.path: legacy,
                modern.path: modern,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, modern)
        self.assertTrue(legacy.close.called)
        self.assertFalse(modern.close.called)

    def test_find_mouse_device_returns_none_when_only_non_logitech_candidates_exist(self):
        module = self._reload_for_linux()
        generic_one = _FakeEvdevDevice(
            name="Generic Mouse A",
            path="/dev/input/event0",
            vendor=0x1234,
            capabilities=self._fake_caps(module),
        )
        generic_two = _FakeEvdevDevice(
            name="Generic Mouse B",
            path="/dev/input/event1",
            vendor=0x4321,
            capabilities=self._fake_caps(module),
        )

        patches = self._patch_evdev_lookup(
            module,
            {
                generic_one.path: generic_one,
                generic_two.path: generic_two,
            },
        )
        with patches[0], patches[1]:
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIsNone(chosen)

    def test_find_mouse_device_logs_permission_errors_opening_evdev(self):
        module = self._reload_for_linux()
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: ["/dev/input/event0"])

        with (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module, "_InputDevice", side_effect=PermissionError("denied")),
            patch("builtins.print") as print_mock,
        ):
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIsNone(chosen)
        messages = [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]
        self.assertTrue(
            any("Permission denied opening /dev/input/event0" in msg for msg in messages)
        )

    def test_find_mouse_device_falls_back_to_glob_when_evdev_list_is_empty(self):
        module = self._reload_for_linux()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event4",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        fake_evdev_mod = SimpleNamespace(list_devices=lambda: [])

        with (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module.glob, "glob", return_value=[logi.path]),
            patch.object(module, "_InputDevice", return_value=logi),
            patch("builtins.print") as print_mock,
        ):
            module._LOG_ONCE_KEYS.clear()
            chosen = module.MouseHook()._find_mouse_device()

        self.assertIs(chosen, logi)
        messages = [
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        ]
        self.assertTrue(
            any("falling back to visible /dev/input/event* nodes" in msg for msg in messages)
        )

    def test_hid_reconnect_requests_rescan_for_fallback_evdev_device(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=0x1234))

        hook._on_hid_connect()

        self.assertFalse(hook.device_connected)
        self.assertTrue(hook.hid_ready)
        self.assertEqual(hook.connected_device, {"name": "MX Master 3S"})
        self.assertEqual(
            hook.hid_runtime_state,
            HidRuntimeState(
                input_ready=False,
                hid_ready=True,
                connected_device={"name": "MX Master 3S"},
            ),
        )
        self.assertTrue(hook._rescan_requested.is_set())
        self.assertTrue(hook._evdev_wakeup.is_set())

    def test_hid_connect_wakes_evdev_scan_when_no_evdev_device_is_grabbed(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})

        hook._on_hid_connect()

        self.assertTrue(hook.hid_ready)
        self.assertTrue(hook._rescan_requested.is_set())
        self.assertTrue(hook._evdev_wakeup.is_set())

    def test_hid_reconnect_does_not_rescan_when_evdev_already_grabs_logitech(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(
            info=SimpleNamespace(vendor=module._LOGI_VENDOR)
        )
        hook._evdev_connected_device = {"name": "MX Master 3S"}
        hook._set_evdev_ready(True)

        hook._on_hid_connect()

        self.assertTrue(hook.device_connected)
        self.assertFalse(hook._rescan_requested.is_set())
        self.assertEqual(
            hook.hid_runtime_state,
            HidRuntimeState(
                input_ready=True,
                hid_ready=True,
                connected_device={"name": "MX Master 3S"},
            ),
        )

    def test_hid_connect_does_not_mark_device_connected_when_evdev_is_missing(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=0x1234))

        hook._on_hid_connect()

        self.assertFalse(hook.device_connected)

    def test_hid_disconnect_keeps_evdev_driven_connected_state(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._hid_gesture = SimpleNamespace(connected_device={"name": "MX Master 3S"})
        hook._evdev_device = SimpleNamespace(info=SimpleNamespace(vendor=module._LOGI_VENDOR))
        hook._evdev_connected_device = {"name": "MX Master 3S"}
        hook._set_evdev_ready(True)
        hook._hid_ready = True
        hook._connected_device = {"name": "MX Master 3S"}

        hook._on_hid_disconnect()

        self.assertTrue(hook.device_connected)
        self.assertEqual(hook.connected_device, {"name": "MX Master 3S"})
        self.assertEqual(
            hook.hid_runtime_state,
            HidRuntimeState(
                input_ready=True,
                hid_ready=False,
                connected_device={"name": "MX Master 3S"},
            ),
        )

    def test_setup_evdev_marks_connected_and_populates_fallback_device_info(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )

        with (
            patch.object(hook, "_find_mouse_device", return_value=logi),
        ):
            self.assertTrue(hook._setup_evdev())

        self.assertTrue(hook.device_connected)
        self.assertEqual(getattr(hook.connected_device, "display_name", None), "MX Master 3S")
        self.assertEqual(getattr(hook.connected_device, "source", None), "evdev")
        self.assertEqual(hook.hid_runtime_state.input_ready, True)
        self.assertEqual(hook.hid_runtime_state.hid_ready, False)
        self.assertEqual(
            getattr(hook.hid_runtime_state.connected_device, "source", None),
            "evdev",
        )
        self.assertTrue(hook.evdev_remap_ready)

    def test_setup_evdev_in_passthrough_detects_without_uinput_or_grab(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook.set_ui_passthrough(True)
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )

        with (
            patch.object(hook, "_find_mouse_device", return_value=logi),
            patch.object(module, "_UInput", side_effect=AssertionError("no uinput")),
        ):
            self.assertTrue(hook._setup_evdev())

        self.assertTrue(hook.device_connected)
        self.assertTrue(hook.evdev_ready)
        self.assertFalse(hook.evdev_remap_ready)
        logi.grab.assert_not_called()
        self.assertIsNone(hook._uinput)

    def test_setup_evdev_uinput_failure_keeps_detection_without_remap(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        messages = []
        hook.set_status_callback(messages.append)
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )

        with (
            patch.object(hook, "_find_mouse_device", return_value=logi),
            patch.object(module, "_UInput", side_effect=PermissionError("denied")),
        ):
            self.assertTrue(hook._setup_evdev())

        self.assertTrue(hook.device_connected)
        self.assertTrue(hook.evdev_ready)
        self.assertFalse(hook.evdev_remap_ready)
        logi.grab.assert_not_called()
        self.assertEqual(len(messages), 1)
        self.assertIn("virtual input device could not be created", messages[0])

    def test_setup_evdev_grab_failure_keeps_detection_without_remap(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        messages = []
        hook.set_status_callback(messages.append)
        hook._dispatch = Mock()
        logi = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        logi.grab.side_effect = OSError("busy")

        with patch.object(hook, "_find_mouse_device", return_value=logi):
            self.assertTrue(hook._setup_evdev())

        self.assertTrue(hook.device_connected)
        self.assertFalse(hook.evdev_remap_ready)
        self.assertIsNone(hook._uinput)
        self.assertEqual(len(messages), 1)
        self.assertIn("mouse could not be grabbed", messages[0])

        hook._handle_button(
            SimpleNamespace(
                type=module._ecodes.EV_KEY,
                code=module._ecodes.BTN_MIDDLE,
                value=1,
            )
        )
        hook._handle_rel(
            SimpleNamespace(
                type=module._ecodes.EV_REL,
                code=module._ecodes.REL_HWHEEL,
                value=1,
            )
        )

        hook._dispatch.assert_not_called()

    def test_filtered_uinput_events_drop_hi_res_wheel_codes(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        module._ecodes.EV_FF = 0x15
        module._ecodes.REL_WHEEL_HI_RES = 0x0B
        module._ecodes.REL_HWHEEL_HI_RES = 0x0C
        dev = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities={
                module._ecodes.EV_SYN: [0, 1, 2],
                module._ecodes.EV_REL: [
                    module._ecodes.REL_X,
                    module._ecodes.REL_Y,
                    module._ecodes.REL_WHEEL,
                    module._ecodes.REL_HWHEEL,
                    module._ecodes.REL_WHEEL_HI_RES,
                    module._ecodes.REL_HWHEEL_HI_RES,
                ],
                module._ecodes.EV_KEY: [
                    module._ecodes.BTN_LEFT,
                    module._ecodes.BTN_RIGHT,
                    module._ecodes.BTN_MIDDLE,
                ],
                module._ecodes.EV_FF: [80],
            },
        )

        events = hook._filtered_uinput_events(dev)

        self.assertNotIn(module._ecodes.EV_SYN, events)
        self.assertNotIn(module._ecodes.EV_FF, events)
        self.assertEqual(
            events[module._ecodes.EV_REL],
            [
                module._ecodes.REL_X,
                module._ecodes.REL_Y,
                module._ecodes.REL_WHEEL,
                module._ecodes.REL_HWHEEL,
            ],
        )

    def test_listen_loop_exits_when_rescan_is_requested(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._set_evdev_remap_ready(True)
        hook._evdev_device = SimpleNamespace(fd=11, read=Mock(return_value=[]))
        select_calls = []

        def fake_select(readable, writable, exceptional, timeout):
            select_calls.append(timeout)
            hook._rescan_requested.set()
            return ([11], [], [])

        with patch.object(module, "_select_mod", SimpleNamespace(select=fake_select)):
            hook._listen_loop()

        self.assertEqual(select_calls, [0.5])
        self.assertEqual(hook._evdev_device.read.call_count, 1)

    def test_listen_loop_waits_without_polling_when_remap_is_not_ready(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        hook._evdev_device = SimpleNamespace(fd=11, read=Mock(return_value=[]))
        select_mock = Mock()

        def stop_wait(timeout):
            hook._running = False

        with (
            patch.object(module, "_select_mod", SimpleNamespace(select=select_mock)),
            patch.object(hook, "_wait_for_evdev_wakeup", side_effect=stop_wait) as wait_mock,
        ):
            hook._listen_loop()

        wait_mock.assert_called_once_with(None)
        select_mock.assert_not_called()
        hook._evdev_device.read.assert_not_called()

    def test_evdev_loop_clears_rescan_and_retries_after_listen_returns(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        setup_calls = []
        seen_rescan_state = []
        cleanup_calls = []

        def fake_setup():
            setup_calls.append(len(setup_calls))
            if len(setup_calls) == 1:
                hook._set_evdev_remap_ready(True)
                return True
            seen_rescan_state.append(hook._rescan_requested.is_set())
            hook._running = False
            return False

        def fake_listen():
            hook._rescan_requested.set()

        def fake_cleanup():
            cleanup_calls.append(True)

        with (
            patch.object(hook, "_setup_evdev", side_effect=fake_setup),
            patch.object(hook, "_listen_loop", side_effect=fake_listen),
            patch.object(hook, "_cleanup_evdev", side_effect=fake_cleanup),
        ):
            hook._evdev_loop()

        self.assertEqual(len(setup_calls), 2)
        self.assertEqual(seen_rescan_state, [False])
        self.assertEqual(len(cleanup_calls), 1)

    def test_evdev_loop_detection_only_waits_without_reopening(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._running = True
        setup_calls = []
        cleanup_calls = []
        wait_timeouts = []

        def fake_setup():
            setup_calls.append(True)
            hook._evdev_device = SimpleNamespace(close=Mock())
            hook._set_evdev_ready(True)
            hook._set_evdev_remap_ready(False)
            return True

        def fake_wait(timeout):
            wait_timeouts.append(timeout)
            self.assertIsNotNone(hook._evdev_device)
            hook._running = False

        def fake_cleanup():
            cleanup_calls.append(True)
            hook._evdev_device = None

        with (
            patch.object(hook, "_setup_evdev", side_effect=fake_setup),
            patch.object(hook, "_wait_for_evdev_wakeup", side_effect=fake_wait),
            patch.object(hook, "_cleanup_evdev", side_effect=fake_cleanup),
        ):
            hook._evdev_loop()

        self.assertEqual(len(setup_calls), 1)
        self.assertEqual(wait_timeouts, [None])
        self.assertEqual(len(cleanup_calls), 1)

    def test_evdev_remap_status_dedupes_by_ready_reason_tuple(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        messages = []
        hook.set_status_callback(messages.append)

        hook._set_evdev_remap_ready(False, "uinput_failed")
        hook._set_evdev_remap_ready(False, "uinput_failed")
        hook._set_evdev_remap_ready(False, "grab_failed")
        hook._set_evdev_remap_ready(True)
        hook._disable_evdev_remapping()
        hook._set_evdev_remap_ready(True)

        self.assertEqual(len(messages), 3)
        self.assertIn("virtual input device could not be created", messages[0])
        self.assertIn("mouse could not be grabbed", messages[1])
        self.assertEqual(messages[2], "Linux evdev remapping restored.")

    def test_evdev_remap_helpers_are_idempotent(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()

        self.assertFalse(hook._acquire_evdev_grab())
        hook._disable_evdev_remapping()

        dev = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        hook._evdev_device = dev

        self.assertTrue(hook._enable_evdev_remapping())
        self.assertTrue(hook._enable_evdev_remapping())

        dev.grab.assert_called_once()
        self.assertTrue(hook.evdev_remap_ready)

    def test_hid_mode_shift_dispatches_when_evdev_remap_is_unavailable(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        hook._ui_passthrough = False
        hook._set_evdev_remap_ready(False, "grab_failed")
        hook._dispatch = Mock()

        hook._on_hid_mode_shift_down()

        hook._dispatch.assert_called_once()

    def test_gesture_click_callback_fires_again_after_reconnect(self):
        module = self._reload_for_linux()
        seen = []

        with (
            patch.object(module, "HidGestureListener", _CapturingListener),
            patch.object(module, "_EVDEV_OK", False),
        ):
            hook = module.MouseHook()
            hook.register(module.MouseEvent.GESTURE_CLICK, lambda event: seen.append(event.event_type))
            hook.start()
            listener = hook._hid_gesture

            listener.on_down()
            listener.on_up()
            hook._on_hid_disconnect()
            hook._on_hid_connect()
            listener.on_down()
            listener.on_up()

        self.assertEqual(
            seen,
            [module.MouseEvent.GESTURE_CLICK, module.MouseEvent.GESTURE_CLICK],
        )

    def test_ui_passthrough_does_not_mirror_ungrabbed_events(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        forwarded = Mock()
        uinput = SimpleNamespace(write_event=forwarded, write=Mock())
        hook._uinput = uinput
        hook._dispatch = Mock()
        hook.invert_vscroll = True
        hook.set_ui_passthrough(True)

        event = SimpleNamespace(
            type=module._ecodes.EV_REL,
            code=module._ecodes.REL_WHEEL,
            value=1,
        )

        hook._handle_rel(event)

        forwarded.assert_not_called()
        uinput.write.assert_not_called()
        hook._dispatch.assert_not_called()

    def test_ui_passthrough_releases_grab_and_wakes_evdev_loop(self):
        module = self._reload_for_linux()
        hook = module.MouseHook()
        messages = []
        hook.set_status_callback(messages.append)
        dev = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities=self._fake_caps(module),
        )
        hook._evdev_device = dev
        hook._evdev_grabbed = True

        hook.set_ui_passthrough(True)
        hook.set_ui_passthrough(False)

        dev.ungrab.assert_called_once()
        dev.grab.assert_called_once()
        self.assertFalse(hook._rescan_requested.is_set())
        self.assertTrue(hook.evdev_remap_ready)
        self.assertEqual(
            messages,
            [
                "Linux input passthrough enabled; evdev remapping paused",
                "Linux input passthrough disabled; evdev remapping restored",
            ],
        )

    def test_mode_shift_callbacks_fire_again_after_reconnect(self):
        module = self._reload_for_linux()
        seen = []

        with (
            patch.object(module, "HidGestureListener", _CapturingListener),
            patch.object(module, "_EVDEV_OK", False),
        ):
            hook = module.MouseHook()
            hook.divert_mode_shift = True
            hook.register(module.MouseEvent.MODE_SHIFT_DOWN, lambda event: seen.append(event.event_type))
            hook.register(module.MouseEvent.MODE_SHIFT_UP, lambda event: seen.append(event.event_type))
            hook.start()
            listener = hook._hid_gesture

            listener.extra_diverts[0x00C4]["on_down"]()
            listener.extra_diverts[0x00C4]["on_up"]()
            hook._on_hid_disconnect()
            hook._on_hid_connect()
            listener.extra_diverts[0x00C4]["on_down"]()
            listener.extra_diverts[0x00C4]["on_up"]()

        self.assertEqual(
            seen,
            [
                module.MouseEvent.MODE_SHIFT_DOWN,
                module.MouseEvent.MODE_SHIFT_UP,
                module.MouseEvent.MODE_SHIFT_DOWN,
                module.MouseEvent.MODE_SHIFT_UP,
            ],
        )


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSEventTapDisabledTests(unittest.TestCase):
    """Verify CGEventTap is re-enabled when macOS disables it."""

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _make_hook(self):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        return hook

    def test_reenable_on_timeout(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")

        hook._event_tap_callback(
            None, mouse_hook._kCGEventTapDisabledByTimeout, dummy, None)

        self.mock_quartz.CGEventTapEnable.assert_called_once_with(
            hook._tap, True)

    def test_reenable_on_user_input(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")

        hook._event_tap_callback(
            None, mouse_hook._kCGEventTapDisabledByUserInput, dummy, None)

        self.mock_quartz.CGEventTapEnable.assert_called_once_with(
            hook._tap, True)

    def test_normal_event_does_not_reenable(self):
        hook = self._make_hook()
        dummy = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.return_value = 0

        hook._event_tap_callback(None, 1, dummy, None)  # kCGEventLeftMouseDown

        self.mock_quartz.CGEventTapEnable.assert_not_called()


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSTrackpadScrollFilterTests(unittest.TestCase):
    """Verify CGEventTap callback passes through trackpad events untouched."""

    _kCGEventScrollWheel = 22  # Quartz.kCGEventScrollWheel

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        self.mock_quartz.kCGEventScrollWheel = self._kCGEventScrollWheel
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _make_hook(self):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.block(mouse_hook.MouseEvent.HSCROLL_LEFT)
        hook.block(mouse_hook.MouseEvent.HSCROLL_RIGHT)
        hook._connected_device = SimpleNamespace(
            key="mx_master_3s",
            thumb_button_via_hid=False,
            gesture_via_sense_panel=False,
        )
        return hook

    def _mock_get_field(self, scroll_phase, source_user_data=0):
        """side_effect: returns scroll_phase for kCGScrollWheelEventScrollPhase,
        source_user_data for kCGEventSourceUserData, and 0 for everything else."""
        def _get(event, field):
            if field == self.mock_quartz.kCGScrollWheelEventScrollPhase:
                return scroll_phase
            if field == self.mock_quartz.kCGEventSourceUserData:
                return source_user_data
            return 0
        return _get

    def test_trackpad_scroll_passes_through_callback(self):
        """Trackpad continuous scroll should be returned as-is, not blocked."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._mock_get_field(scroll_phase=1)

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)
        # Verify no HSCROLL events were dispatched
        self.assertTrue(hook._dispatch_queue.empty())

    def test_trackpad_hscroll_not_blocked(self):
        """Trackpad horizontal scroll must NOT trigger hscroll action."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self.mock_quartz.kCGScrollWheelEventScrollPhase:
                return 1  # trackpad
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 5 * 65536  # non-zero horizontal delta
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)  # passed through, not blocked
        self.assertTrue(hook._dispatch_queue.empty())

    def test_trackpad_filter_can_be_disabled(self):
        """Continuous scroll should be handled when ignore_trackpad is off."""
        hook = self._make_hook()
        hook.ignore_trackpad = False
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self.mock_quartz.kCGScrollWheelEventScrollPhase:
                return 1  # trackpad / Magic Mouse
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 3 * 65536  # positive = HSCROLL_RIGHT
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result)
        self.assertFalse(hook._dispatch_queue.empty())
        event = hook._dispatch_queue.get_nowait()
        self.assertEqual(event.event_type, mouse_hook.MouseEvent.HSCROLL_RIGHT)

    def test_mouse_wheel_hscroll_dispatched_and_blocked(self):
        """Discrete mouse wheel horizontal scroll SHOULD dispatch and block."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")

        def _get(event, field):
            if field == self.mock_quartz.kCGScrollWheelEventScrollPhase:
                return 0  # mouse wheel (no phase)
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return 3 * 65536  # positive = HSCROLL_RIGHT
            if field == self.mock_quartz.kCGEventSourceUserData:
                return 0
            return 0
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result)  # blocked
        self.assertFalse(hook._dispatch_queue.empty())
        event = hook._dispatch_queue.get_nowait()
        self.assertEqual(event.event_type, mouse_hook.MouseEvent.HSCROLL_RIGHT)


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSPassthroughWhenNoDeviceTests(unittest.TestCase):
    """End-to-end pin of the KVM pass-through contract on the macOS event
    tap. The CGEventTap is global -- it sees events from every input
    device the OS knows about -- so any failure here is a user-visible
    regression: trackpad swipes get inverted, generic-mouse xbuttons
    get swallowed, and so on."""

    _kCGEventScrollWheel = 22
    _kCGEventOtherMouseDown = 25

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        self.mock_quartz.kCGEventScrollWheel = self._kCGEventScrollWheel
        self.mock_quartz.kCGEventOtherMouseDown = self._kCGEventOtherMouseDown
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _bare_hook(self):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.invert_hscroll = True
        hook.block(mouse_hook.MouseEvent.XBUTTON1_DOWN)
        hook.block(mouse_hook.MouseEvent.HSCROLL_RIGHT)
        return hook

    def test_scroll_passes_through_when_no_logitech_connected(self):
        hook = self._bare_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.return_value = 0

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)
        self.assertTrue(hook._dispatch_queue.empty())

    def test_xbutton_passes_through_when_no_logitech_connected(self):
        hook = self._bare_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.return_value = 0

        result = hook._event_tap_callback(
            None, self._kCGEventOtherMouseDown, cg_event, None)

        self.assertIs(result, cg_event)
        self.assertTrue(hook._dispatch_queue.empty())


class LinuxShiftWheelHScrollTests(unittest.TestCase):
    """Verify Linux REL_WHEEL is translated to REL_HWHEEL when Shift is held."""

    def _reload_for_linux(self):
        fake_evdev = SimpleNamespace(
            ecodes=_FakeLinuxEcodes,
            UInput=_FakeLinuxUInput,
            InputDevice=Mock(name="InputDevice"),
        )
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(sys.modules, {"evdev": fake_evdev}),
        ):
            sys.modules.pop("core.mouse_hook_linux", None)
            if hasattr(core, "mouse_hook_linux"):
                delattr(core, "mouse_hook_linux")
            importlib.import_module("core.mouse_hook_linux")
            importlib.reload(mouse_hook)

        def cleanup():
            sys.modules.pop("core.mouse_hook_linux", None)
            if hasattr(core, "mouse_hook_linux"):
                delattr(core, "mouse_hook_linux")
            importlib.reload(mouse_hook)

        self.addCleanup(cleanup)
        return mouse_hook

    def _make_keyboard(self, *, path="/dev/input/event5", active_keys=()):
        ecodes = _FakeLinuxEcodes
        return _FakeEvdevDevice(
            name="Fake Keyboard",
            path=path,
            vendor=0x1234,
            capabilities={
                ecodes.EV_KEY: [
                    ecodes.KEY_LEFTSHIFT,
                    ecodes.KEY_RIGHTSHIFT,
                ],
            },
            active_keys=active_keys,
        )

    def _install_hook(self, module, *, keyboards, mouse_hi_res=False):
        ecodes = module._ecodes
        rel_caps = [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL]
        if mouse_hi_res:
            rel_caps.extend([ecodes.REL_WHEEL_HI_RES, ecodes.REL_HWHEEL_HI_RES])
        mouse = _FakeEvdevDevice(
            name="MX Master 3S",
            path="/dev/input/event1",
            vendor=module._LOGI_VENDOR,
            capabilities={
                ecodes.EV_REL: rel_caps,
                ecodes.EV_KEY: [
                    ecodes.BTN_LEFT,
                    ecodes.BTN_RIGHT,
                    ecodes.BTN_MIDDLE,
                ],
            },
        )
        devices_by_path = {kb.path: kb for kb in keyboards}
        devices_by_path[mouse.path] = mouse
        fake_evdev_mod = SimpleNamespace(
            list_devices=lambda: list(devices_by_path)
        )

        def fake_input_device(path):
            return devices_by_path[path]

        hook = module.MouseHook()
        hook._evdev_device = mouse
        hook._uinput = _FakeLinuxUInput()
        hook._set_evdev_remap_ready(True)
        patches = (
            patch.object(module, "_evdev_mod", fake_evdev_mod),
            patch.object(module, "_InputDevice", side_effect=fake_input_device),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return hook, mouse

    def _make_rel_event(self, code, value):
        return SimpleNamespace(type=_FakeLinuxEcodes.EV_REL, code=code, value=value)

    def test_keyboard_devices_with_shift_are_opened(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard()
        non_keyboard = _FakeEvdevDevice(
            name="Random Sensor",
            path="/dev/input/event9",
            vendor=0x0000,
            capabilities={ecodes.EV_KEY: [ecodes.BTN_LEFT]},
        )
        hook, _ = self._install_hook(module, keyboards=[keyboard])
        # Add the non-keyboard candidate alongside the keyboard.
        fake_paths = {
            "/dev/input/event5": keyboard,
            "/dev/input/event9": non_keyboard,
            "/dev/input/event1": hook._evdev_device,
        }
        with (
            patch.object(
                module, "_evdev_mod",
                SimpleNamespace(list_devices=lambda: list(fake_paths)),
            ),
            patch.object(
                module, "_InputDevice", side_effect=lambda p: fake_paths[p],
            ),
        ):
            hook._ensure_keyboard_devices()

        self.assertIn(keyboard, hook._keyboard_devices)
        self.assertNotIn(non_keyboard, hook._keyboard_devices)
        self.assertTrue(non_keyboard.close.called)

    def test_shift_held_reflects_active_keys(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard(active_keys=[ecodes.KEY_LEFTSHIFT])
        hook, _ = self._install_hook(module, keyboards=[keyboard])
        hook._ensure_keyboard_devices()

        self.assertTrue(hook._shift_held())

        keyboard.set_active_keys([])
        self.assertFalse(hook._shift_held())

        keyboard.set_active_keys([ecodes.KEY_RIGHTSHIFT])
        self.assertTrue(hook._shift_held())

    def test_rel_wheel_with_shift_translates_to_hwheel(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard(active_keys=[ecodes.KEY_LEFTSHIFT])
        hook, _ = self._install_hook(module, keyboards=[keyboard])
        hook._ensure_keyboard_devices()

        event = self._make_rel_event(ecodes.REL_WHEEL, 1)
        hook._handle_rel(event)

        hook._uinput.write.assert_called_once_with(
            ecodes.EV_REL, ecodes.REL_HWHEEL, 1
        )
        hook._uinput.write_event.assert_not_called()

    def test_rel_wheel_without_shift_passes_through(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard(active_keys=[])
        hook, _ = self._install_hook(module, keyboards=[keyboard])
        hook._ensure_keyboard_devices()

        event = self._make_rel_event(ecodes.REL_WHEEL, 1)
        hook._handle_rel(event)

        hook._uinput.write_event.assert_called_once_with(event)
        hook._uinput.write.assert_not_called()

    def test_invert_hscroll_flips_translated_direction(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard(active_keys=[ecodes.KEY_LEFTSHIFT])
        hook, _ = self._install_hook(module, keyboards=[keyboard])
        hook.invert_hscroll = True
        hook._ensure_keyboard_devices()

        event = self._make_rel_event(ecodes.REL_WHEEL, 2)
        hook._handle_rel(event)

        hook._uinput.write.assert_called_once_with(
            ecodes.EV_REL, ecodes.REL_HWHEEL, -2
        )

    def test_rel_wheel_hi_res_with_shift_is_suppressed(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        keyboard = self._make_keyboard(active_keys=[ecodes.KEY_LEFTSHIFT])
        hook, _ = self._install_hook(module, keyboards=[keyboard], mouse_hi_res=True)
        hook._ensure_keyboard_devices()

        event = self._make_rel_event(ecodes.REL_WHEEL_HI_RES, 60)
        hook._handle_rel(event)

        hook._uinput.write.assert_not_called()
        hook._uinput.write_event.assert_not_called()

    def test_filtered_uinput_events_always_adds_rel_hwheel(self):
        module = self._reload_for_linux()
        ecodes = module._ecodes
        hook = module.MouseHook()
        dev_no_tilt = _FakeEvdevDevice(
            name="Basic Mouse",
            path="/dev/input/event2",
            vendor=module._LOGI_VENDOR,
            capabilities={
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL],
                ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
            },
        )

        events = hook._filtered_uinput_events(dev_no_tilt)

        self.assertIn(ecodes.REL_HWHEEL, events[ecodes.EV_REL])


@unittest.skipUnless(sys.platform == "darwin", "macOS-only tests")
class MacOSShiftWheelHScrollTests(unittest.TestCase):
    """Verify Shift+wheel translates into a horizontal scroll event."""

    _kCGScrollWheelEventIsContinuous = 88
    _kCGEventScrollWheel = 22
    _kCGEventFlagMaskShift = 0x00020000
    _kCGScrollEventUnitLine = 0
    _kCGScrollEventUnitPixel = 1
    _AXIS1_DELTA = "kCGScrollWheelEventDeltaAxis1"
    _AXIS1_FIXED = "kCGScrollWheelEventFixedPtDeltaAxis1"
    _AXIS1_POINT = "kCGScrollWheelEventPointDeltaAxis1"
    _AXIS2_DELTA = "kCGScrollWheelEventDeltaAxis2"
    _AXIS2_FIXED = "kCGScrollWheelEventFixedPtDeltaAxis2"
    _AXIS2_POINT = "kCGScrollWheelEventPointDeltaAxis2"

    def setUp(self):
        self.mock_quartz = MagicMock(name="Quartz")
        self.mock_quartz.kCGEventScrollWheel = self._kCGEventScrollWheel
        self.mock_quartz.kCGEventFlagMaskShift = self._kCGEventFlagMaskShift
        self.mock_quartz.kCGScrollEventUnitLine = self._kCGScrollEventUnitLine
        self.mock_quartz.kCGScrollEventUnitPixel = self._kCGScrollEventUnitPixel
        for axis_attr in (
            self._AXIS1_DELTA, self._AXIS1_FIXED, self._AXIS1_POINT,
            self._AXIS2_DELTA, self._AXIS2_FIXED, self._AXIS2_POINT,
        ):
            setattr(self.mock_quartz, axis_attr, axis_attr)
        mouse_hook.Quartz = self.mock_quartz

    def tearDown(self):
        if hasattr(mouse_hook, "Quartz") and isinstance(
                mouse_hook.Quartz, MagicMock):
            del mouse_hook.Quartz

    def _make_hook(self, *, block_hscroll=True):
        hook = mouse_hook.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook._connected_device = SimpleNamespace(
            key="mx_master_3s",
            thumb_button_via_hid=False,
            gesture_via_sense_panel=False,
        )
        if block_hscroll:
            hook.block(mouse_hook.MouseEvent.HSCROLL_LEFT)
            hook.block(mouse_hook.MouseEvent.HSCROLL_RIGHT)
        return hook

    def _field_getter(self, *, shift=False, h_fixed=0, v_line=0, v_fixed=0,
                      v_point=0, is_continuous=0, source_user_data=0):
        def _get(event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return is_continuous
            if field == self.mock_quartz.kCGEventSourceUserData:
                return source_user_data
            if field == self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis2:
                return h_fixed
            if field == self._AXIS1_DELTA:
                return v_line
            if field == self._AXIS1_FIXED:
                return v_fixed
            if field == self._AXIS1_POINT:
                return v_point
            return 0
        return _get

    def test_shift_wheel_up_translates_to_horizontal_scroll(self):
        """Shift held + vertical wheel scroll posts a horizontal-scroll event."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(v_line=1, v_fixed=65536, v_point=10)
        self.mock_quartz.CGEventGetFlags.return_value = (
            self._kCGEventFlagMaskShift)
        new_event = MagicMock(name="translated_event")
        self.mock_quartz.CGEventCreateScrollWheelEvent.return_value = new_event

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result, "original vertical scroll must be blocked")
        self.mock_quartz.CGEventCreateScrollWheelEvent.assert_called_once()
        create_args = self.mock_quartz.CGEventCreateScrollWheelEvent.call_args
        # (source, unit, wheelCount, delta1, delta2)
        self.assertEqual(create_args.args[2], 2,
                         "must create a two-axis scroll event")
        self.assertEqual(create_args.args[3], 0,
                         "vertical delta on translated event must be 0")
        self.assertNotEqual(create_args.args[4], 0,
                            "horizontal delta on translated event must be set")
        self.mock_quartz.CGEventPost.assert_called_once()

    def test_shift_wheel_strips_shift_modifier_from_translated_event(self):
        """Translated event must clear Shift so apps don't double-translate."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(v_line=1, v_fixed=65536, v_point=10)
        self.mock_quartz.CGEventGetFlags.return_value = (
            self._kCGEventFlagMaskShift | 0x00010000)  # Shift + something else
        new_event = MagicMock(name="translated_event")
        self.mock_quartz.CGEventCreateScrollWheelEvent.return_value = new_event

        hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        # Find the CGEventSetFlags call on the translated event
        set_flags_calls = [
            c for c in self.mock_quartz.CGEventSetFlags.call_args_list
            if c.args[0] is new_event
        ]
        self.assertEqual(len(set_flags_calls), 1)
        applied_flags = set_flags_calls[0].args[1]
        self.assertEqual(applied_flags & self._kCGEventFlagMaskShift, 0,
                         "Shift mask must be stripped from translated event")
        self.assertEqual(applied_flags & 0x00010000, 0x00010000,
                         "other modifier flags must be preserved")

    def test_translated_event_passes_through_tap_on_reentry(self):
        """The marker on the translated event makes the tap pass it through."""
        hook = self._make_hook()
        cg_event = MagicMock(name="re_entered_event")
        # Source user data set to the shift-wheel marker
        marker = mouse_hook._SHIFT_WHEEL_HSCROLL_MARKER
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(source_user_data=marker)

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event)
        # No new event should be created for a re-entered marker event
        self.mock_quartz.CGEventCreateScrollWheelEvent.assert_not_called()

    def test_no_shift_means_no_translation(self):
        """A plain vertical scroll without Shift must not be translated."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(v_line=1, v_fixed=65536, v_point=10)
        self.mock_quartz.CGEventGetFlags.return_value = 0  # no modifiers

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIs(result, cg_event, "event must pass through unchanged")
        self.mock_quartz.CGEventCreateScrollWheelEvent.assert_not_called()

    def test_shift_with_zero_vertical_delta_is_noop(self):
        """Shift held but no vertical delta (e.g. axis-2 only) does not translate."""
        hook = self._make_hook()
        cg_event = MagicMock(name="cg_event")
        # h_fixed != 0 means the existing hscroll path takes over, not our shift path.
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(h_fixed=3 * 65536)
        self.mock_quartz.CGEventGetFlags.return_value = (
            self._kCGEventFlagMaskShift)

        hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        # Existing hscroll path: blocked + dispatched, but NOT translated.
        self.mock_quartz.CGEventCreateScrollWheelEvent.assert_not_called()

    def test_invert_hscroll_flips_translated_direction(self):
        """`invert_hscroll` must flip the sign of the translated horizontal delta."""
        hook = self._make_hook()
        hook.invert_hscroll = True
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(v_line=1, v_fixed=65536, v_point=10)
        self.mock_quartz.CGEventGetFlags.return_value = (
            self._kCGEventFlagMaskShift)
        new_event = MagicMock(name="translated_event")
        self.mock_quartz.CGEventCreateScrollWheelEvent.return_value = new_event

        result = hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        self.assertIsNone(result)
        create_args = self.mock_quartz.CGEventCreateScrollWheelEvent.call_args
        # delta2 passed to CGEventCreateScrollWheelEvent should be negated (-1 line)
        self.assertEqual(create_args.args[4], -1)
        # And the explicit axis-2 set calls should also use negated values.
        axis2_fixed_calls = [
            c for c in self.mock_quartz.CGEventSetIntegerValueField.call_args_list
            if c.args[0] is new_event
            and c.args[1] == self._AXIS2_FIXED
        ]
        self.assertEqual(len(axis2_fixed_calls), 1)
        self.assertEqual(axis2_fixed_calls[0].args[2], -65536)

    def test_invert_hscroll_off_preserves_translated_direction(self):
        """Default (invert_hscroll=False) keeps the original sign on translation."""
        hook = self._make_hook()
        hook.invert_hscroll = False
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = \
            self._field_getter(v_line=1, v_fixed=65536, v_point=10)
        self.mock_quartz.CGEventGetFlags.return_value = (
            self._kCGEventFlagMaskShift)
        new_event = MagicMock(name="translated_event")
        self.mock_quartz.CGEventCreateScrollWheelEvent.return_value = new_event

        hook._event_tap_callback(
            None, self._kCGEventScrollWheel, cg_event, None)

        create_args = self.mock_quartz.CGEventCreateScrollWheelEvent.call_args
        self.assertEqual(create_args.args[4], 1)


class GestureEventFamilyTests(unittest.TestCase):
    def test_gesture_button_event_constants_exist(self):
        # The Gesture button (thumb) uses the gesture_* family on every device.
        self.assertEqual(mouse_hook.MouseEvent.GESTURE_CLICK, "gesture_click")
        self.assertEqual(mouse_hook.MouseEvent.GESTURE_BUTTON_DOWN, "gesture_button_down")
        self.assertEqual(mouse_hook.MouseEvent.GESTURE_BUTTON_UP, "gesture_button_up")

    def test_sense_panel_event_constants_exist(self):
        # The MX Master 4 Sense Panel ("Actions Ring") uses the sense_* family.
        self.assertEqual(mouse_hook.MouseEvent.SENSE_CLICK, "sense_click")
        self.assertEqual(mouse_hook.MouseEvent.SENSE_BUTTON_DOWN, "sense_button_down")
        self.assertEqual(mouse_hook.MouseEvent.SENSE_BUTTON_UP, "sense_button_up")
        self.assertEqual(mouse_hook.MouseEvent.SENSE_SWIPE_LEFT, "sense_swipe_left")


if __name__ == "__main__":
    unittest.main()
