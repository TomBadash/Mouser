"""Tests for the HID++ native wheel-invert path.

Native invert = Mouser writes the firmware invert bit on `0x2121` /
`0x2150` *without* diverting the wheel through HID++ notifications. The OS
receives native HID scroll with the direction already flipped at the
device, so KVM forwarders see inverted scroll and the native scroll
cadence / momentum is preserved end-to-end.
"""

from __future__ import annotations

import copy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from core import hid_gesture as hg_mod
from core.config import DEFAULT_CONFIG, _migrate
from core.hid_gesture import (
    FEAT_HIRES_WHEEL_ENHANCED,
    FEAT_THUMB_WHEEL,
    HidGestureListener,
)
from core.logi_devices import resolve_device
from core.mouse_hook_base import BaseMouseHook
from core.mouse_hook_contract import MouseHookLike


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_listener() -> HidGestureListener:
    return HidGestureListener()


def _resp(params):
    return (0xFF, 0x12, 0x0, 0x0, list(params))


# ──────────────────────────────────────────────────────────────────────────────
# Signed-int helper
# ──────────────────────────────────────────────────────────────────────────────


class DecodeS16BETests(unittest.TestCase):
    def test_decode_s16_be(self):
        decode = HidGestureListener._decode_s16
        self.assertEqual(decode(0x80, 0x00), -32768)
        self.assertEqual(decode(0x7F, 0xFF), 32767)
        self.assertEqual(decode(0x00, 0x01), 1)
        self.assertEqual(decode(0xFF, 0xFF), -1)
        self.assertEqual(decode(0x00, 0x00), 0)

    def test_decode_s16_be_full_range(self):
        decode = HidGestureListener._decode_s16
        for hi in range(256):
            for lo in range(256):
                v = decode(hi, lo)
                self.assertGreaterEqual(v, -32768)
                self.assertLessEqual(v, 32767)


# ──────────────────────────────────────────────────────────────────────────────
# Capability discovery
# ──────────────────────────────────────────────────────────────────────────────


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_capability_discovery(self):
        listener = _make_listener()
        feature_map = {FEAT_HIRES_WHEEL_ENHANCED: 0x07, FEAT_THUMB_WHEEL: 0x08}
        request_responses = {
            (0x07, 0): _resp([8, 0x00, 0x10, 0x00]),     # multiplier=8
            (0x08, 0): _resp([0x00, 0x10, 0x00, 0x78]),  # divertedRes=120
        }

        def fake_find(feat_id):
            return feature_map.get(feat_id)

        def fake_request(feat, func, params, timeout_ms=2000):
            return request_responses.get((feat, func))

        with (
            patch.object(listener, "_find_feature", side_effect=fake_find),
            patch.object(listener, "_request", side_effect=fake_request),
        ):
            hw_fi = listener._find_feature(FEAT_HIRES_WHEEL_ENHANCED)
            if hw_fi:
                listener._hires_wheel_idx = hw_fi
                cap = listener._request(hw_fi, 0, [])
                if cap:
                    _, _, _, _, p = cap
                    listener._hires_wheel_multiplier = p[0] or None
            tw_fi = listener._find_feature(FEAT_THUMB_WHEEL)
            if tw_fi:
                listener._thumbwheel_idx = tw_fi
                info = listener._request(tw_fi, 0, [])
                if info:
                    _, _, _, _, p = info
                    listener._thumbwheel_multiplier = ((p[2] << 8) | p[3]) or None

        self.assertEqual(listener._hires_wheel_idx, 0x07)
        self.assertEqual(listener._hires_wheel_multiplier, 8)
        self.assertEqual(listener._thumbwheel_idx, 0x08)
        self.assertEqual(listener._thumbwheel_multiplier, 120)
        self.assertTrue(listener.hires_wheel_supported)
        self.assertTrue(listener.thumbwheel_supported)

    def test_capability_discovery_negative(self):
        listener = _make_listener()
        with (
            patch.object(listener, "_find_feature", return_value=None),
            patch.object(listener, "_request", return_value=None),
        ):
            self.assertIsNone(listener._find_feature(FEAT_HIRES_WHEEL_ENHANCED))
        self.assertFalse(listener.hires_wheel_supported)
        self.assertFalse(listener.thumbwheel_supported)


# ──────────────────────────────────────────────────────────────────────────────
# Native-invert apply
# ──────────────────────────────────────────────────────────────────────────────


class _FakeDevice:
    def write(self, *args, **kwargs):
        return len(args[0]) if args else 0

    def read(self, *args, **kwargs):
        return None

    def close(self):
        pass


class NativeInvertApplyTests(unittest.TestCase):
    def _setup_capable_listener(self):
        listener = _make_listener()
        listener._dev = _FakeDevice()
        listener._hires_wheel_idx = 0x07
        listener._thumbwheel_idx = 0x08
        listener._hires_wheel_multiplier = 8
        listener._thumbwheel_multiplier = 120
        return listener

    @staticmethod
    def _request_router(get_mode_response, write_response=None):
        """Build a side_effect function for _request that returns a
        getWheelMode response on fn=1 and a generic ack on fn=2 (or
        whatever the test passes as write_response). Mirrors the
        read-modify-write protocol the helper now uses."""
        if write_response is None:
            write_response = _resp([0])

        def _route(feat, func, params, timeout_ms=2000):
            if feat == 0x07 and func == 1:
                return get_mode_response
            return write_response

        return _route

    def test_apply_invert_on_writes_low_res_invert(self):
        # Mouser drives wheel mode to native low-res with invert ON
        # regardless of the device's current state. Hi-res mode causes
        # jumpy scroll on apps without trackpad-class smoothing, so we
        # always clear bit 1.
        listener = self._setup_capable_listener()
        get_mode = _resp([0x00])
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, True)
            listener._apply_pending_native_wheel_invert()
            self.assertTrue(listener._wheel_divert_state)
            req.assert_any_call(0x07, 1, [])               # read current mode
            req.assert_any_call(0x07, 2, [0x04])           # native low-res + invert
            req.assert_any_call(0x08, 2, [0x00, 0x01])

    def test_apply_invert_on_clears_existing_hires_bit(self):
        # If the device is currently in hi-res mode (e.g. left over from
        # Logitech Options+ or a previous Mouser build), Mouser must
        # forcibly downgrade it to low-res to fix the jumpy feel.
        listener = self._setup_capable_listener()
        get_mode = _resp([0x02])  # hi-res, native, no invert
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, False)
            listener._apply_pending_native_wheel_invert()
            req.assert_any_call(0x07, 2, [0x04])           # hi-res CLEARED, invert set
            req.assert_any_call(0x08, 2, [0x00, 0x00])

    def test_apply_invert_off_writes_low_res_no_invert(self):
        listener = self._setup_capable_listener()
        listener._wheel_divert_state = True
        get_mode = _resp([0x06])  # hi-res + invert active
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (False, False)
            listener._apply_pending_native_wheel_invert()
            self.assertTrue(listener._wheel_divert_state)
            req.assert_any_call(0x07, 2, [0x00])           # firmware default
            req.assert_any_call(0x08, 2, [0x00, 0x00])

    def test_apply_invert_clears_divert_bit(self):
        # Pathological case: device left in divert state from a crashed
        # Mouser session. We must clear bit 0 (target) AND bit 1 (hi-res).
        listener = self._setup_capable_listener()
        get_mode = _resp([0x07])  # target + hi-res + invert
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, False)
            listener._apply_pending_native_wheel_invert()
            req.assert_any_call(0x07, 2, [0x04])           # only invert kept

    def test_apply_invert_skips_redundant_write(self):
        # Device already exactly in target state → no setWheelMode call.
        listener = self._setup_capable_listener()
        get_mode = _resp([0x04])  # native low-res + invert
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, True)
            listener._apply_pending_native_wheel_invert()
            self.assertEqual(
                [c for c in req.call_args_list
                 if c.args[:2] == (0x07, 2)],
                [],
                "Vertical setWheelMode must not write when current == target",
            )

    def test_apply_invert_fails_when_hscroll_requested_without_thumbwheel(self):
        # Device exposes 0x2121 but not 0x2150 (e.g. MX Anywhere). Claiming
        # success for invert_h would suppress the OS-layer fallback and the
        # user would get no horizontal inversion at all.
        listener = self._setup_capable_listener()
        listener._thumbwheel_idx = None
        get_mode = _resp([0x00])
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ):
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, True)
            listener._apply_pending_native_wheel_invert()
            self.assertFalse(listener._wheel_divert_state)

    def test_apply_invert_succeeds_vertical_only_without_thumbwheel(self):
        # Same device, but no horizontal inversion requested: the absent
        # thumbwheel feature must still count as a no-op success.
        listener = self._setup_capable_listener()
        listener._thumbwheel_idx = None
        get_mode = _resp([0x00])
        with patch.object(
            listener, "_request",
            side_effect=self._request_router(get_mode),
        ) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, False)
            listener._apply_pending_native_wheel_invert()
            self.assertTrue(listener._wheel_divert_state)
            req.assert_any_call(0x07, 2, [0x04])

    def test_apply_invert_rolls_back_vertical_when_horizontal_write_fails(self):
        # Vertical write acks, thumbwheel write fails: the vertical invert
        # must be reverted before reporting failure, otherwise the OS-layer
        # fallback double-inverts vertical scrolling.
        listener = self._setup_capable_listener()
        wheel_mode = [0x00]  # stateful: reads reflect the last write

        def _route(feat, func, params, timeout_ms=2000):
            if feat == 0x07 and func == 1:
                return _resp([wheel_mode[0]])
            if feat == 0x07 and func == 2:
                wheel_mode[0] = params[0]
                return _resp([0])
            if feat == 0x08:
                return None  # thumbwheel write fails
            return _resp([0])

        with patch.object(listener, "_request", side_effect=_route) as req:
            with listener._wheel_divert_lock:
                listener._pending_wheel_divert = (True, True)
            listener._apply_pending_native_wheel_invert()
            self.assertFalse(listener._wheel_divert_state)
            vertical_writes = [
                c.args[2] for c in req.call_args_list if c.args[:2] == (0x07, 2)
            ]
            self.assertIn([0x04], vertical_writes, "invert applied first")
            self.assertEqual(
                vertical_writes[-1], [0x00],
                "vertical invert must be rolled back after horizontal failure",
            )

    def test_request_native_invert_idempotent(self):
        """Two consecutive request_wheel_native_invert calls each issue
        fresh device reads/writes (firmware can forget after sleep)."""
        listener = self._setup_capable_listener()

        def drain_apply():
            listener._apply_pending_native_wheel_invert()

        with patch.object(
            listener, "_request",
            side_effect=self._request_router(_resp([0x00])),
        ) as req:
            def fake_wait(timeout=None):
                drain_apply()
                listener._wheel_divert_event.set()
                return True

            with patch.object(listener._wheel_divert_event, "wait", side_effect=fake_wait):
                ok1 = listener.request_wheel_native_invert(True, False)
                ok2 = listener.request_wheel_native_invert(True, False)

            self.assertTrue(ok1)
            self.assertTrue(ok2)
            # Each call: 1 read + 1 write (vertical) + 1 write (thumb) = 3 calls
            self.assertGreaterEqual(req.call_count, 6)

    def test_undivert_on_stop(self):
        """stop() restores the device to native non-inverted state when the
        listener was holding firmware invert active. The read-modify-write
        helper inspects the current mode first, so we simulate a device
        currently inverted (bit 2 set) to force the revert write to fire."""
        listener = self._setup_capable_listener()
        listener._wheel_divert_state = True
        listener._connected_device_info = SimpleNamespace(key="mx_master_3s")
        listener._thread = None

        with patch.object(
            listener, "_request",
            side_effect=self._request_router(_resp([0x04])),
        ) as req:
            listener.stop()

        targets = {(c.args[0], c.args[1]) for c in req.call_args_list}
        self.assertIn((0x07, 2), targets)   # write reverted mode
        self.assertIn((0x08, 2), targets)   # thumbwheel revert
        self.assertFalse(listener._wheel_divert_state)


# ──────────────────────────────────────────────────────────────────────────────
# Catalog flags
# ──────────────────────────────────────────────────────────────────────────────


class CatalogFlagsTests(unittest.TestCase):
    def test_catalog_flags(self):
        for name in ("MX Master 3S", "MX Master 3", "MX Master 4", "MX Master 2S", "MX Master"):
            spec = resolve_device(product_name=name)
            self.assertIsNotNone(spec, name)
            self.assertTrue(spec.has_hires_wheel, name)
            self.assertTrue(spec.has_thumbwheel, name)

        spec = resolve_device(product_name="MX Vertical")
        self.assertIsNotNone(spec)
        self.assertFalse(spec.has_hires_wheel)
        self.assertFalse(spec.has_thumbwheel)


# ──────────────────────────────────────────────────────────────────────────────
# Base hook native-invert flag
# ──────────────────────────────────────────────────────────────────────────────


class BaseHookFlagTests(unittest.TestCase):
    def test_default_state(self):
        hook = BaseMouseHook()
        self.assertFalse(hook.wheel_native_invert_active)

    def test_configure_wheel_multipliers_is_noop(self):
        # Native-invert mode does no scroll injection, so multipliers are
        # unused. The method is retained only for shape compatibility.
        hook = BaseMouseHook()
        hook.configure_wheel_multipliers(8, 120)
        # No exception, no state change beyond not having the old fields.
        self.assertFalse(hasattr(hook, "_wheel_residual_v"))


# ──────────────────────────────────────────────────────────────────────────────
# macOS event-tap suppression of OS-layer inversion
# ──────────────────────────────────────────────────────────────────────────────


class MacOSSuppressionTests(unittest.TestCase):
    """When `wheel_native_invert_active=True`, the macOS event-tap callback
    must skip the OS-layer inversion path (`_negate_scroll_axis`) so the
    firmware-level flip doesn't get double-applied. When inactive, in-place
    negation runs against the original event (no block-and-reinject)."""

    _kCGScrollWheelEventIsContinuous = 88
    _kCGEventScrollWheel = 22

    def setUp(self):
        try:
            from core import mouse_hook_macos
        except Exception:
            self.skipTest("macOS hook unavailable in this environment")
        self._mouse_hook_macos = mouse_hook_macos
        self._prev_quartz = getattr(mouse_hook_macos, "Quartz", None)
        self.mock_quartz = MagicMock(name="Quartz")
        self.mock_quartz.kCGEventScrollWheel = self._kCGEventScrollWheel
        mouse_hook_macos.Quartz = self.mock_quartz

    def tearDown(self):
        if self._prev_quartz is None:
            if hasattr(self._mouse_hook_macos, "Quartz"):
                delattr(self._mouse_hook_macos, "Quartz")
        else:
            self._mouse_hook_macos.Quartz = self._prev_quartz

    def _mock_get_field(self, *, is_continuous=0, source_user_data=0):
        def _get(_event, field):
            if field == self._kCGScrollWheelEventIsContinuous:
                return is_continuous
            if field == self.mock_quartz.kCGEventSourceUserData:
                return source_user_data
            return 0
        return _get

    def test_os_inversion_skipped_when_native_active(self):
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.wheel_native_invert_active = True
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )
        with patch.object(hook, "_negate_scroll_axis") as negate:
            result = hook._event_tap_callback(
                None, self._kCGEventScrollWheel, cg_event, None
            )
        negate.assert_not_called()
        # Original event flows through untouched -- no block, no reinject.
        self.assertIs(result, cg_event)

    def _logitech_stub(self):
        """Minimal stand-in for a connected Logitech ``ConnectedDeviceInfo``.

        The OS-fallback inversion path requires ``_connected_device is not
        None`` as proof that scroll events are coming from a Logitech the
        user's invert toggle is meant to apply to. Tests that exercise the
        fallback path must pin this state explicitly.
        """
        return SimpleNamespace(
            key="mx_master_3s",
            display_name="MX Master 3S",
            thumb_button_via_hid=False,
            gesture_via_sense_panel=False,
        )

    def test_os_inversion_runs_when_native_inactive(self):
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.wheel_native_invert_active = False
        hook._connected_device = self._logitech_stub()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )
        with patch.object(hook, "_negate_scroll_axis") as negate:
            result = hook._event_tap_callback(
                None, self._kCGEventScrollWheel, cg_event, None
            )
        # Vertical inversion negates axis 1 in place; the SAME event is
        # returned (not None), so the caller passes it through untouched
        # apart from the sign flip.
        negate.assert_called_once_with(cg_event, 1)
        self.assertIs(result, cg_event)

    def test_horizontal_inversion_negates_axis_2_in_place(self):
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_hscroll = True
        hook.wheel_native_invert_active = False
        hook._connected_device = self._logitech_stub()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )
        with patch.object(hook, "_negate_scroll_axis") as negate:
            result = hook._event_tap_callback(
                None, self._kCGEventScrollWheel, cg_event, None
            )
        negate.assert_called_once_with(cg_event, 2)
        self.assertIs(result, cg_event)

    def test_both_axes_inverted_in_single_pass(self):
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.invert_hscroll = True
        hook.wheel_native_invert_active = False
        hook._connected_device = self._logitech_stub()
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )
        with patch.object(hook, "_negate_scroll_axis") as negate:
            result = hook._event_tap_callback(
                None, self._kCGEventScrollWheel, cg_event, None
            )
        negate.assert_any_call(cg_event, 1)
        negate.assert_any_call(cg_event, 2)
        self.assertEqual(negate.call_count, 2)
        self.assertIs(result, cg_event)

    def test_os_inversion_skipped_when_no_logitech_connected(self):
        """The wheel-invert toggle is meant for Logitech scroll. When no
        Logitech is connected we have no source-of-truth that a scroll event
        came from a device the toggle applies to, so the OS-layer fallback
        must stand down rather than invert every trackpad / generic mouse
        scroll the OS forwards through us.
        """
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.invert_hscroll = True
        hook.wheel_native_invert_active = False
        hook._connected_device = None  # no Logitech detected
        cg_event = MagicMock(name="cg_event")
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )
        with patch.object(hook, "_negate_scroll_axis") as negate:
            result = hook._event_tap_callback(
                None, self._kCGEventScrollWheel, cg_event, None
            )
        negate.assert_not_called()
        self.assertIs(result, cg_event)

    def test_os_inversion_resumes_when_logitech_reconnects(self):
        """Disconnect/reconnect transitions must not require Mouser restart:
        the very next event after ``_connected_device`` flips back to a
        ``ConnectedDeviceInfo`` is the one we start inverting again.
        """
        hook = self._mouse_hook_macos.MouseHook()
        hook._running = True
        hook._tap = MagicMock(name="tap")
        hook.invert_vscroll = True
        hook.wheel_native_invert_active = False
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = (
            self._mock_get_field(is_continuous=0)
        )

        hook._connected_device = None
        with patch.object(hook, "_negate_scroll_axis") as negate_off:
            hook._event_tap_callback(
                None, self._kCGEventScrollWheel, MagicMock(name="evt-off"), None
            )
        negate_off.assert_not_called()

        hook._connected_device = self._logitech_stub()
        with patch.object(hook, "_negate_scroll_axis") as negate_on:
            hook._event_tap_callback(
                None, self._kCGEventScrollWheel, MagicMock(name="evt-on"), None
            )
        negate_on.assert_called_once()

    def test_negate_scroll_axis_flips_all_three_delta_fields_in_place(self):
        """Direct unit test: negate flips Delta, FixedPtDelta, and
        PointDelta for the requested axis. Apps read different fields,
        so all three must be consistent."""
        from unittest.mock import call
        hook = self._mouse_hook_macos.MouseHook()
        # Mock Quartz field-name attributes the negate loop reads.
        self.mock_quartz.kCGScrollWheelEventDeltaAxis1 = 0xA
        self.mock_quartz.kCGScrollWheelEventFixedPtDeltaAxis1 = 0xB
        self.mock_quartz.kCGScrollWheelEventPointDeltaAxis1 = 0xC
        cg_event = MagicMock(name="cg_event")
        # Field-id → mocked current value lookup.
        values = {0xA: 5, 0xB: 50_000, 0xC: 8}

        def _get_field(_event, field):
            return values.get(field, 0)
        self.mock_quartz.CGEventGetIntegerValueField.side_effect = _get_field
        sets = []

        def _set_field(_event, field, value):
            sets.append((field, value))
        self.mock_quartz.CGEventSetIntegerValueField.side_effect = _set_field

        hook._negate_scroll_axis(cg_event, 1)

        self.assertIn((0xA, -5), sets)
        self.assertIn((0xB, -50_000), sets)
        self.assertIn((0xC, -8), sets)


# ──────────────────────────────────────────────────────────────────────────────
# Protocol conformance
# ──────────────────────────────────────────────────────────────────────────────


class ProtocolConformanceTests(unittest.TestCase):
    def test_protocol_conformance(self):
        modules = []
        for name in ("mouse_hook_macos", "mouse_hook_windows", "mouse_hook_linux"):
            try:
                mod = __import__(f"core.{name}", fromlist=["MouseHook"])
                modules.append(mod.MouseHook)
            except Exception:
                continue
        if not modules:
            self.skipTest("No platform mouse hook importable")

        for cls in modules:
            try:
                inst = cls()
            except Exception:
                inst = cls.__new__(cls)
                BaseMouseHook.__init__(inst)
            for attr in (
                "wheel_native_invert_active",
                "invert_vscroll",
                "invert_hscroll",
            ):
                self.assertTrue(
                    hasattr(inst, attr),
                    f"{cls.__name__} missing {attr}",
                )


# ──────────────────────────────────────────────────────────────────────────────
# Engine driver
# ──────────────────────────────────────────────────────────────────────────────


class _FakeHook:
    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False
        self.divert_mode_shift = False
        self.divert_dpi_switch = False
        self.wheel_native_invert_active = False
        self.wheel_divert_active = False  # back-compat alias
        self._hid_gesture = None
        self._blocked_events = set()

    def set_debug_callback(self, cb): pass
    def set_gesture_callback(self, cb): pass
    def set_status_callback(self, cb): pass
    def set_connection_change_callback(self, cb): pass
    def set_battery_notify_callback(self, cb): pass
    def configure_gestures(self, **kwargs): pass
    def configure_wheel_multipliers(self, v, h): return None
    def block(self, event_type): pass
    def register(self, event_type, callback): pass
    def reset_bindings(self): pass
    def start(self): pass
    def stop(self): pass


class _FakeAppDetector:
    def __init__(self, callback):
        self.callback = callback
    def start(self): pass
    def stop(self): pass


class _FakeHidGesture:
    def __init__(self, *, ack=True, has_wheel=True, has_thumb=True):
        self.ack = ack
        self.requests = []
        self._hires_wheel_idx = 0x07 if has_wheel else None
        self._thumbwheel_idx = 0x08 if has_thumb else None
        self._hires_wheel_multiplier = 8 if has_wheel else None
        self._thumbwheel_multiplier = 120 if has_thumb else None
        self.connected_device = SimpleNamespace(
            has_hires_wheel=has_wheel, has_thumbwheel=has_thumb,
        )
        self.smart_shift_supported = False
        self.flags_set_to = None

    def request_wheel_native_invert(self, invert_v, invert_h, timeout_s=3.0):
        self.requests.append((bool(invert_v), bool(invert_h)))
        return bool(self.ack)

    def set_wheel_divert_active_flags(self, vertical, thumb):
        self.flags_set_to = (vertical, thumb)


class EngineNativeInvertTests(unittest.TestCase):
    def _make_engine(self, *, wheel_divert="auto", invert_v=False, invert_h=False,
                     ack=True, has_wheel=True, has_thumb=True, capable=True):
        from core.engine import Engine

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["wheel_divert"] = wheel_divert
        cfg["settings"]["invert_vscroll"] = invert_v
        cfg["settings"]["invert_hscroll"] = invert_h

        with (
            patch("core.engine.MouseHook", _FakeHook),
            patch("core.engine.AppDetector", _FakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            engine = Engine()
        if capable:
            engine.hook._hid_gesture = _FakeHidGesture(
                ack=ack, has_wheel=has_wheel, has_thumb=has_thumb,
            )
            engine.hook.connected_device = SimpleNamespace(
                has_hires_wheel=has_wheel,
                has_thumbwheel=has_thumb,
            )
        return engine

    def test_capable_device_drives_native_invert(self):
        engine = self._make_engine(invert_v=True, invert_h=False)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        self.assertEqual(hg.requests, [(True, False)])
        self.assertTrue(engine.wheel_native_invert_active)
        self.assertTrue(engine.hook.wheel_native_invert_active)

    def test_capable_device_resets_to_native_when_invert_off(self):
        # Even with both flags False, the engine still owns the wheel-mode
        # write so a stale invert lease from a prior crashed Mouser session
        # gets reset to non-inverted on connect.
        engine = self._make_engine(invert_v=False, invert_h=False)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        self.assertEqual(hg.requests, [(False, False)])
        self.assertTrue(engine.wheel_native_invert_active)

    def test_kill_switch_skips_firmware_invert(self):
        engine = self._make_engine(wheel_divert="off", invert_v=True)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        # No request issued when kill-switch is on.
        self.assertEqual(hg.requests, [])
        self.assertFalse(engine.wheel_native_invert_active)

    def test_incapable_device_skips_firmware_invert(self):
        engine = self._make_engine(invert_v=True, has_wheel=False, has_thumb=False)
        engine.hook.connected_device = SimpleNamespace(
            has_hires_wheel=False, has_thumbwheel=False,
        )
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        self.assertEqual(hg.requests, [])
        self.assertFalse(engine.wheel_native_invert_active)

    def test_failed_ack_falls_back_to_os_layer(self):
        engine = self._make_engine(invert_v=True, ack=False)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        self.assertEqual(hg.requests, [(True, False)])
        self.assertFalse(engine.wheel_native_invert_active)

    def test_fast_path_skips_redundant_apply(self):
        engine = self._make_engine(invert_v=True)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        hg.requests.clear()
        for _ in range(5):
            engine._apply_wheel_invert_setting()
        self.assertEqual(hg.requests, [])

    def test_force_replays_writes(self):
        engine = self._make_engine(invert_v=True)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        hg.requests.clear()
        engine._apply_wheel_invert_setting(force=True)
        self.assertEqual(hg.requests, [(True, False)])

    def test_toggle_invert_writes_new_state(self):
        engine = self._make_engine(invert_v=False)
        engine._apply_wheel_invert_setting()
        hg = engine.hook._hid_gesture
        hg.requests.clear()
        engine.cfg["settings"]["invert_vscroll"] = True
        engine._apply_wheel_invert_setting()
        self.assertEqual(hg.requests, [(True, False)])

    def test_change_callback_fires_on_transition(self):
        engine = self._make_engine(invert_v=True)
        seen = []
        engine.set_wheel_divert_change_callback(seen.append)
        self.assertEqual(seen, [False])
        engine._apply_wheel_invert_setting()
        self.assertEqual(seen, [False, True])
        engine.cfg["settings"]["wheel_divert"] = "off"
        engine._apply_wheel_invert_setting()
        self.assertEqual(seen, [False, True, False])


# ──────────────────────────────────────────────────────────────────────────────
# Config migration
# ──────────────────────────────────────────────────────────────────────────────


class ConfigMigrationTests(unittest.TestCase):
    def test_migration_adds_wheel_divert_default_auto(self):
        legacy = {
            "version": 1,
            "settings": {"invert_vscroll": False},
            "profiles": {
                "default": {"label": "Default", "apps": [], "mappings": {}},
            },
        }
        migrated = _migrate(legacy)
        self.assertEqual(migrated["settings"]["wheel_divert"], "auto")

    def test_migration_preserves_off_value(self):
        legacy = {
            "version": 9,
            "settings": {"wheel_divert": "off"},
            "profiles": {},
        }
        migrated = _migrate(legacy)
        self.assertEqual(migrated["settings"]["wheel_divert"], "off")

    def test_thumb_button_migration_preserves_user_mapping(self):
        # A pre-v10 config with a user-mapped thumb_button must NOT be
        # clobbered when the MX4 schema migration runs.
        pre_v10 = {
            "version": 9,
            "settings": {"wheel_divert": "auto"},
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {"thumb_button": "alt_tab"},
                },
            },
        }
        migrated = _migrate(pre_v10)
        self.assertEqual(
            migrated["profiles"]["default"]["mappings"]["thumb_button"],
            "alt_tab",
        )

    def test_thumb_button_migration_adds_default_when_missing(self):
        # Cold-start: a pre-v10 config should be populated with the
        # "none" default, not have an existing mapping overwritten.
        pre_v10 = {
            "version": 9,
            "settings": {"wheel_divert": "auto"},
            "profiles": {
                "gaming": {
                    "label": "Gaming",
                    "apps": [],
                    "mappings": {"xbutton1": "browser_back"},
                },
            },
        }
        migrated = _migrate(pre_v10)
        self.assertEqual(
            migrated["profiles"]["gaming"]["mappings"]["thumb_button"],
            "none",
        )
        self.assertEqual(
            migrated["profiles"]["gaming"]["mappings"]["xbutton1"],
            "browser_back",
        )


if __name__ == "__main__":
    unittest.main()
