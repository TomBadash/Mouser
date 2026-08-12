"""
Shared mouse hook behavior used by platform implementations.
"""

import queue
import threading
import time

try:
    from core.hid_gesture import HidGestureListener
except Exception:
    HidGestureListener = None

from core.gesture_recognizer import GestureRecognizer
from core.mouse_hook_types import HidRuntimeState, MouseEvent, format_debug_details
from core.pan_scroller import PanScroller

# Swipe direction -> event, per event family. The Gesture button (thumb)
# always uses the gesture_* family; the Sense Panel (MX Master 4 primary
# gesture control) uses the sense_* family.
_GESTURE_SWIPE_EVENTS = {
    "left": MouseEvent.GESTURE_SWIPE_LEFT,
    "right": MouseEvent.GESTURE_SWIPE_RIGHT,
    "up": MouseEvent.GESTURE_SWIPE_UP,
    "down": MouseEvent.GESTURE_SWIPE_DOWN,
}
_SENSE_SWIPE_EVENTS = {
    "left": MouseEvent.SENSE_SWIPE_LEFT,
    "right": MouseEvent.SENSE_SWIPE_RIGHT,
    "up": MouseEvent.SENSE_SWIPE_UP,
    "down": MouseEvent.SENSE_SWIPE_DOWN,
}
# Backwards-compatible alias (primary control default family).
_SWIPE_EVENTS = _GESTURE_SWIPE_EVENTS
# Per-button slide-gesture direction -> event (owner carried in raw_data).
_BUTTON_SWIPE_EVENTS = {
    "left": MouseEvent.BUTTON_SWIPE_LEFT,
    "right": MouseEvent.BUTTON_SWIPE_RIGHT,
    "up": MouseEvent.BUTTON_SWIPE_UP,
    "down": MouseEvent.BUTTON_SWIPE_DOWN,
}


class BaseMouseHook:
    def __init__(self):
        self._callbacks = {}
        self._blocked_events = set()
        self._debug_callback = None
        self._gesture_callback = None
        self._status_callback = None
        self.debug_mode = False
        self.invert_vscroll = False
        self.invert_hscroll = False
        self._gesture_active = False
        self._hid_gesture = None
        self._device_connected = False
        self._connection_change_cb = None
        self._battery_notify_cb = None
        self.divert_mode_shift = False
        self.divert_dpi_switch = False
        # Side buttons, HID++ diverted only when a hold mode (Pan / Gesture
        # Swipe) needs them. Some devices never report a sustained side-button
        # hold through the OS (MX Anywhere 3S over Bluetooth emits a ~20ms
        # click on tap and nothing at all while held), so hold modes on these
        # buttons arm from the HID press instead -- the mode-shift hybrid.
        self.divert_xbutton1 = False
        self.divert_xbutton2 = False
        self.wheel_native_invert_active = False
        self._gesture_direction_enabled = False
        self._gesture_os_passthrough = False
        self._gesture_move_callback = None
        # Primary gesture control recognizer (thumb on MX3/3S/classic,
        # Sense Panel on the MX Master 4).
        self._gesture_recognizer = GestureRecognizer(
            on_swipe=self._on_recognized_swipe,
            on_debug=self._emit_gesture_event,
        )
        # True when the device's primary gesture control is a Sense Panel
        # (MX Master 4). Set on connect. Governs which event family the
        # primary control emits (sense_* vs gesture_*).
        self._gesture_via_sense_panel = False
        # Secondary Gesture button (thumb) on the MX Master 4 — its own
        # movement-swipe recognizer, independent of the Sense Panel's.
        self._thumb_active = False
        self._thumb_direction_enabled = False
        self._thumb_os_passthrough = False
        self._thumb_move_callback = None
        self._thumb_recognizer = GestureRecognizer(
            on_swipe=self._on_thumb_recognized_swipe,
            on_debug=self._emit_gesture_event,
        )
        # ── Per-button slide gestures (back/forward/middle, all platforms) ──
        # A separate recognizer from the HID ones above: the shared recognizer
        # locks to its first motion source, so button gestures (OS pointer
        # motion) get their own instance. Only one owner button gestures at a
        # time; _button_gesture_active_owner names it while held.
        self._button_gesture_owners = set()
        self._button_gesture_enabled = False
        self._button_gesture_active_owner = None
        self._button_gesture_armed_at = 0.0
        self._button_gesture_timeout_ms = 3000
        self._button_gesture_origin_needed = False
        self._button_gesture_recognizer = GestureRecognizer(
            on_swipe=self._on_button_recognized_swipe,
            on_debug=self._emit_gesture_event,
        )
        # ── Pan ───────────────────────────────────────────────────────────
        # Pan is a second *mode* of the arm/sample/release machinery above
        # rather than a parallel system: a pan owner is a button-gesture owner
        # whose held motion streams out as scroll instead of resolving into a
        # discrete swipe. Modelling it this way means every platform hook's
        # existing button dispatch arms and feeds pan with no changes.
        self._pan_owners = set()
        # A pan legitimately lasts as long as the user holds the button, so the
        # swipe timeout (3s) would cut it off mid-drag. This is only the
        # wedge guard for a missed button-up freezing the pointer forever.
        self._pan_timeout_ms = 30000
        self._pan_scroller = PanScroller(emit=self._emit_pan_scroll)
        # Post-release momentum glide. The generation counter is the
        # cancellation token: bumping it makes any running coast thread exit
        # on its next tick, with no locks (single writer + GIL).
        self._pan_coast_gen = 0
        self._pan_coast_thread = None
        # True (default): the glide follows the pointer wherever it goes,
        # scrolling whatever is under it. False: the glide is pinned to the
        # window the throw happened over and stops at its boundary.
        self._pan_glide_across_windows = True
        self._connected_device = None
        self._dispatch_queue = None

    def _init_dispatch_queue(self, maxsize=0):
        """Initialize dispatch queue storage for subclasses with event threads."""
        self._dispatch_queue = queue.Queue(maxsize=max(0, int(maxsize)))

    def _enqueue_dispatch_event(self, event):
        """Best-effort enqueue that bounds memory when queue has a max size."""
        q = self._dispatch_queue
        if q is None:
            return
        if q.maxsize <= 0:
            q.put(event)
            return
        try:
            q.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(event)
        except queue.Full:
            self._emit_debug(f"Dropped event due to full dispatch queue: {event.event_type}")

    def register(self, event_type, callback):
        self._callbacks.setdefault(event_type, []).append(callback)

    def block(self, event_type):
        self._blocked_events.add(event_type)

    def unblock(self, event_type):
        self._blocked_events.discard(event_type)

    def reset_bindings(self):
        self._callbacks.clear()
        self._blocked_events.clear()

    def configure_wheel_multipliers(self, v, h):
        """No-op kept for interface-shape compatibility.

        Native-invert mode does no scroll injection, so wheel multipliers are
        unused here; subclasses that inject scroll may override this."""
        return None

    def configure_gestures(
        self,
        enabled=False,
        threshold=50,
        commit_window_ms=400,
        settle_ms=90,
        cross_ratio=0.5,
    ):
        self._gesture_direction_enabled = bool(enabled)
        self._gesture_recognizer.configure(
            enabled=bool(enabled),
            threshold=threshold,
            commit_window_ms=commit_window_ms,
            settle_ms=settle_ms,
            cross_ratio=cross_ratio,
        )

    def configure_thumb_gestures(
        self,
        enabled=False,
        threshold=50,
        commit_window_ms=400,
        settle_ms=90,
        cross_ratio=0.5,
    ):
        """Configure the MX Master 4 thumb Gesture button's swipe recognizer.
        Also tells the HID listener whether to hand rawXY to the thumb on
        press (so holding the thumb + moving the mouse recognizes a swipe)."""
        self._thumb_direction_enabled = bool(enabled)
        self._thumb_recognizer.configure(
            enabled=bool(enabled),
            threshold=threshold,
            commit_window_ms=commit_window_ms,
            settle_ms=settle_ms,
            cross_ratio=cross_ratio,
        )
        hg = self._hid_gesture
        if hg is not None and hasattr(hg, "set_thumb_rawxy_enabled"):
            hg.set_thumb_rawxy_enabled(bool(enabled))

    # ── Per-button slide gestures (back/forward/middle) ───────────────
    # Shared, platform-agnostic arm/sample/release for ordinary buttons that
    # have been set to the "gesture_swipe" action. Each platform hook calls
    # these from its own event path (Windows WH_MOUSE_LL, macOS CGEventTap,
    # Linux evdev): arm on owner-button-down, feed motion while held, release
    # on owner-button-up. All direction math lives in the shared recognizer,
    # so there is one source of truth across platforms.
    def configure_button_gestures(
        self,
        owners=None,
        threshold=50,
        commit_window_ms=400,
        settle_ms=90,
        cross_ratio=0.5,
        timeout_ms=3000,
        pan_owners=None,
        pan_speed=None,
        pan_natural=None,
        pan_momentum=None,
        pan_glide=None,
        pan_glide_across_windows=None,
        pan_timeout_ms=30000,
    ):
        """Set which buttons (owner names "middle"/"xbutton1"/"xbutton2") are
        armed as slide pads and configure their shared recognizer.

        ``owners`` are Gesture Swipe pads (slide resolves to a direction);
        ``pan_owners`` are Pan pads (slide streams out as scroll). Both are fed
        by the same platform arm/sample/release calls, so both sets are held in
        ``_button_gesture_owners`` and the mode is decided per owner.
        """
        swipe_owners = set(owners) if owners else set()
        pan = set(pan_owners) if pan_owners else set()
        # A button's mapping is single-valued, so it cannot really be in both
        # modes; if a hand-edited config says otherwise, swipe wins and pan is
        # dropped rather than both arming on the same press.
        pan -= swipe_owners

        self._pan_owners = pan
        self._button_gesture_owners = swipe_owners | pan
        self._button_gesture_enabled = bool(self._button_gesture_owners)
        self._button_gesture_timeout_ms = max(250, int(timeout_ms))
        self._pan_timeout_ms = max(1000, int(pan_timeout_ms))
        self._pan_scroller.configure(speed=pan_speed, natural=pan_natural,
                                     momentum=pan_momentum, glide_tau=pan_glide)
        if pan_glide_across_windows is not None:
            self._pan_glide_across_windows = bool(pan_glide_across_windows)
        if pan_momentum is False:
            self.cancel_pan_coast()
        self._button_gesture_recognizer.configure(
            enabled=bool(swipe_owners),
            threshold=threshold,
            commit_window_ms=commit_window_ms,
            settle_ms=settle_ms,
            cross_ratio=cross_ratio,
        )
        if not self._button_gesture_enabled:
            self._button_gesture_active_owner = None
            self._pan_scroller.end()
            self.cancel_pan_coast()

    def is_button_gesture_owner(self, owner):
        """True if ``owner`` is currently armed as a slide pad (swipe or pan)."""
        return owner in self._button_gesture_owners

    def is_pan_owner(self, owner):
        """True if ``owner`` is armed as a Pan pad specifically."""
        return owner in self._pan_owners

    def _emit_pan_scroll(self, dv, dh):
        """Emit one scroll step during a pan hold.

        Base is inert: a platform hook only pans once it overrides this to
        inject a real scroll event. Config keeps the Pan action out of the UI on
        platforms that have not implemented it, so this no-op should be
        unreachable in practice -- it exists so that a mapping carried over from
        another machine degrades to "button does nothing" rather than crashing
        inside the event tap.
        """
        return False

    def arm_button_gesture(self, owner, now=None):
        """Begin a gesture hold for ``owner`` (called on owner-button-down).
        Returns True if the press was consumed (do not emit the normal down).
        First-wins: ignored if another owner is already mid-gesture."""
        if owner not in self._button_gesture_owners:
            return False
        if self._button_gesture_active_owner is not None:
            return False
        self._button_gesture_active_owner = owner
        self._button_gesture_armed_at = (
            time.monotonic() if now is None else now
        )
        # Platforms that derive deltas from an absolute cursor position (Windows)
        # must re-establish their origin on the first move of this hold, since a
        # button may arm without a known start point (e.g. mode shift over HID).
        self._button_gesture_origin_needed = True
        if owner in self._pan_owners:
            # Grabbing the button catches a glide in flight, like planting a
            # finger on a coasting trackpad.
            self.cancel_pan_coast()
            self._pan_scroller.begin()
            self._emit_debug(f"Pan armed owner={owner}")
            return True
        self._button_gesture_recognizer.begin()
        self._emit_debug(f"Button gesture armed owner={owner}")
        return True

    def sample_button_gesture(self, dx, dy, source="os_motion", now=None):
        """Feed one movement delta while an owner button is held. Returns True
        if consumed (the platform hook should swallow the motion to freeze the
        cursor). Auto-aborts a stuck hold once it outlives the timeout so a
        missed button-up can never wedge the pointer."""
        owner = self._button_gesture_active_owner
        if owner is None:
            return False
        is_pan = owner in self._pan_owners
        t = time.monotonic() if now is None else now
        timeout_ms = self._pan_timeout_ms if is_pan else self._button_gesture_timeout_ms
        if (t - self._button_gesture_armed_at) * 1000.0 > timeout_ms:
            self.abort_button_gesture("timeout")
            return False
        if is_pan:
            self._pan_scroller.sample(dx, dy, now=now)
        else:
            self._button_gesture_recognizer.sample(dx, dy, source, now=now)
        return True

    def release_button_gesture(self, owner, now=None):
        """End a gesture hold on owner-button-up. Returns "gesture" if a swipe
        fired during the hold, "click" if it was a plain tap, or None if this
        owner was not the armed one. On a plain tap, emits a BUTTON_TAP event
        tagged with the owner so the engine can fire the in-gesture tap action."""
        if self._button_gesture_active_owner != owner:
            return None
        if owner in self._pan_owners:
            # A pan owns its button outright: the press was swallowed on the way
            # in, and a tap that panned nowhere stays swallowed rather than
            # replaying as a click. Assigning Pan to a button gives up that
            # button's click, which is what picking a hold-mode means.
            coast = self._pan_scroller.end(now=now)
            self._button_gesture_active_owner = None
            self._emit_debug(f"Pan released owner={owner} "
                             f"coast={'yes' if coast else 'no'}")
            if coast is not None:
                self._start_pan_coast(coast)
            return "pan"
        was_click = self._button_gesture_recognizer.end()
        self._button_gesture_active_owner = None
        result = "click" if was_click else "gesture"
        self._emit_debug(f"Button gesture released owner={owner} -> {result}")
        if was_click:
            self._emit_gesture_swipe(
                MouseEvent(MouseEvent.BUTTON_TAP, {"gesture_owner": owner})
            )
        return result

    def _start_pan_coast(self, coast):
        """Run a post-release glide on its own small thread at ~240 Hz.

        The tick rate is the glide's frame rate: each tick posts at most one
        whole-pixel scroll event, so a slow tick reads as visible chop. 240 Hz
        with a drift-corrected deadline (rather than a naive sleep, whose
        error accumulates under scheduler jitter) keeps steps small and their
        cadence even; the dt-based decay math is rate-independent, so only
        smoothness changes with the tick, never the distance travelled.

        Cancellation is the generation counter: any cancel_pan_coast() bump
        (new grab, momentum turned off, hook stop, real wheel input on
        platforms that report it) makes the loop exit on its next tick. The
        coast itself finishes when it decays below the stop speed, with a
        hard wall-clock cap as the runaway guard.
        """
        self.cancel_pan_coast()
        self._pan_coast_gen += 1
        generation = self._pan_coast_gen
        # Window-boundary policy: with glide-across-windows off, remember the
        # window the throw happened over and stop the glide once the pointer
        # is over a different one. Checked every few ticks (the lookup is a
        # platform call), and platforms without a lookup always return None,
        # which compares equal forever -- i.e. they glide across everything.
        across_windows = self._pan_glide_across_windows
        start_window = (
            None if across_windows else self._current_window_under_pointer()
        )

        def _run():
            tick = 1.0 / 240.0
            deadline = time.monotonic() + 8.0
            last = time.monotonic()
            next_tick = last + tick
            ticks = 0
            while (self._pan_coast_gen == generation
                   and time.monotonic() < deadline):
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                next_tick += tick
                ticks += 1
                # The window lookup is a platform call, far too heavy for every
                # tick -- ~16 checks/s is plenty to notice a window change.
                if (not across_windows and ticks % 15 == 0
                        and self._current_window_under_pointer()
                        != start_window):
                    break
                now_t = time.monotonic()
                step = coast.step(now_t - last)
                last = now_t
                if step is None:
                    break
                dv, dh = step
                if dv or dh:
                    self._emit_pan_scroll(dv, dh)

        self._pan_coast_thread = threading.Thread(
            target=_run, name="pan-coast", daemon=True
        )
        self._pan_coast_thread.start()

    def _current_window_under_pointer(self):
        """Identify the window currently under the pointer, for the pinned
        (non-across-windows) glide policy. Base returns None -- None always
        equals None, so platforms without a lookup glide across everything.
        """
        return None

    def cancel_pan_coast(self):
        """Stop any running post-release glide (idempotent, lock-free)."""
        self._pan_coast_gen += 1

    def abort_button_gesture(self, reason=""):
        """Give up an armed gesture without firing or replaying anything."""
        self.cancel_pan_coast()
        owner = self._button_gesture_active_owner
        if owner is None:
            return
        if owner in self._pan_owners:
            self._pan_scroller.end()
        else:
            self._button_gesture_recognizer.end()
        self._button_gesture_active_owner = None
        self._emit_debug(f"Button gesture aborted owner={owner} reason={reason}")

    def _on_button_recognized_swipe(self, direction):
        """Recognizer callback: emit a BUTTON_SWIPE event tagged with the
        currently-held owner so the engine routes it to <owner>_<direction>."""
        owner = self._button_gesture_active_owner
        if owner is None:
            return
        event_type = _BUTTON_SWIPE_EVENTS.get(direction)
        if event_type is None:
            return
        self._emit_gesture_swipe(
            MouseEvent(event_type, {"gesture_owner": owner, "direction": direction})
        )

    def set_gesture_os_passthrough(self, enabled, move_callback=None):
        """When True, rawXY deltas during a gesture hold are forwarded to
        move_callback instead of being fed to the gesture recognizer.
        Setting both atomically avoids a window where passthrough is
        active but the callback is not yet installed."""
        self._gesture_move_callback = move_callback
        self._gesture_os_passthrough = bool(enabled)

    def set_thumb_os_passthrough(self, enabled, move_callback=None):
        """Thumb-button counterpart of set_gesture_os_passthrough, used when
        the thumb's tap action is the Actions Ring."""
        self._thumb_move_callback = move_callback
        self._thumb_os_passthrough = bool(enabled)

    # ── Primary-control event family ──────────────────────────────────
    # The primary gesture control emits sense_* on a Sense Panel device
    # (MX Master 4) and gesture_* everywhere else.
    def _primary_swipe_events(self):
        return (_SENSE_SWIPE_EVENTS if self._gesture_via_sense_panel
                else _GESTURE_SWIPE_EVENTS)

    def _primary_click_event(self):
        return (MouseEvent.SENSE_CLICK if self._gesture_via_sense_panel
                else MouseEvent.GESTURE_CLICK)

    def _primary_button_down_event(self):
        return (MouseEvent.SENSE_BUTTON_DOWN if self._gesture_via_sense_panel
                else MouseEvent.GESTURE_BUTTON_DOWN)

    def _primary_button_up_event(self):
        return (MouseEvent.SENSE_BUTTON_UP if self._gesture_via_sense_panel
                else MouseEvent.GESTURE_BUTTON_UP)

    def set_connection_change_callback(self, cb):
        self._connection_change_cb = cb

    def set_battery_notify_callback(self, cb):
        """Register ``cb(level, charging)`` for unsolicited battery events."""
        self._battery_notify_cb = cb

    @property
    def device_connected(self):
        return self._device_connected

    @property
    def connected_device(self):
        return self._connected_device

    @property
    def hid_runtime_state(self):
        hg = getattr(self, "_hid_gesture", None)
        hid_device = getattr(hg, "connected_device", None) if hg else None
        return HidRuntimeState(
            input_ready=bool(self._device_connected),
            hid_ready=hid_device is not None,
            connected_device=self._connected_device,
        )

    def _should_intercept_events(self) -> bool:
        """True only when the platform hook should block, remap, or dispatch
        OS-level mouse events to the engine.

        Mouser exists to remap a Logitech mouse's buttons. The global event
        taps on macOS (CGEventTap) and Windows (WH_MOUSE_LL) see events
        from every input device the OS knows about -- when no Logitech is
        currently bound to this host (KVM switched to another machine,
        the device is mid-reconnect after sleep, or the user simply has
        not plugged one in) those hooks must stay completely out of the
        way, otherwise xbutton clicks and scroll events from a trackpad
        or generic USB mouse get swallowed and routed through Mouser's
        remap pipeline.

        Linux's evdev hook only attaches once a Logitech source device
        has been resolved, so it is naturally gated -- but consult this
        property defensively before dispatching there as well so the
        contract stays platform-uniform.
        """
        return self._connected_device is not None

    def dump_device_info(self):
        hg = getattr(self, "_hid_gesture", None)
        if hg and hasattr(hg, "dump_device_info"):
            return hg.dump_device_info()
        return None

    def _set_device_connected(self, connected):
        if connected == self._device_connected:
            return
        self._device_connected = connected
        state = "Connected" if connected else "Disconnected"
        print(f"[MouseHook] Device {state}")
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass

    def set_debug_callback(self, callback):
        self._debug_callback = callback

    def set_gesture_callback(self, callback):
        self._gesture_callback = callback

    def set_status_callback(self, callback):
        self._status_callback = callback

    def _emit_debug(self, message):
        if self.debug_mode and self._debug_callback:
            try:
                self._debug_callback(message)
            except Exception:
                pass

    def _emit_status(self, message):
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass

    def _emit_gesture_event(self, event):
        if self.debug_mode and self._gesture_callback:
            try:
                self._gesture_callback(event)
            except Exception:
                pass

    def _dispatch(self, event):
        callbacks = self._callbacks.get(event.event_type, [])
        self._emit_debug(
            f"Dispatch {event.event_type}"
            f"{format_debug_details(event.raw_data)} callbacks={len(callbacks)}"
        )
        if event.event_type.startswith(("gesture_", "sense_")):
            self._emit_gesture_event(
                {
                    "type": "dispatch",
                    "event_name": event.event_type,
                    "callbacks": len(callbacks),
                }
            )
        if not callbacks:
            self._emit_debug(f"No mapped action for {event.event_type}")
            if event.event_type.startswith(("gesture_", "sense_")):
                self._emit_gesture_event(
                    {
                        "type": "unmapped",
                        "event_name": event.event_type,
                    }
                )
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                print(f"[MouseHook] callback error: {exc}")

    def _hid_gesture_available(self):
        return self._hid_gesture is not None and self._device_connected

    def _build_extra_diverts(self):
        extra = {}
        if self.divert_mode_shift:
            extra[0x00C4] = {
                "on_down": self._on_hid_mode_shift_down,
                "on_up": self._on_hid_mode_shift_up,
            }
        if self.divert_dpi_switch:
            extra[0x00FD] = {
                "on_down": self._on_hid_dpi_switch_down,
                "on_up": self._on_hid_dpi_switch_up,
            }
        if self.divert_xbutton1:
            extra[0x0053] = {
                "on_down": self._on_hid_xbutton1_down,
                "on_up": self._on_hid_xbutton1_up,
            }
        if self.divert_xbutton2:
            extra[0x0056] = {
                "on_down": self._on_hid_xbutton2_down,
                "on_up": self._on_hid_xbutton2_up,
            }
        return extra

    def refresh_extra_diverts(self):
        """Push the current divert flag set to a live HID listener.

        Without this, a flag flipped at runtime (user maps a side button to
        Pan) would not take effect until the next reconnect, because the
        listener captures its divert set at construction. No-op when no
        listener is running -- the next start picks the flags up anyway.
        """
        hg = self._hid_gesture
        if hg is not None and hasattr(hg, "update_extra_diverts"):
            hg.update_extra_diverts(self._build_extra_diverts())

    def _start_hid_listener(self):
        platform_module = getattr(self.__class__, "_platform_module", None)
        listener_cls = getattr(platform_module, "HidGestureListener", HidGestureListener)
        if listener_cls is None:
            return None
        listener = listener_cls(
            on_down=self._on_hid_gesture_down,
            on_up=self._on_hid_gesture_up,
            on_move=self._on_hid_gesture_move,
            on_connect=self._on_hid_connect,
            on_disconnect=self._on_hid_disconnect,
            extra_diverts=self._build_extra_diverts(),
            on_thumb_button_down=self._on_hid_thumb_button_down,
            on_thumb_button_up=self._on_hid_thumb_button_up,
            on_thumb_button_move=self._on_hid_thumb_button_move,
            on_battery=self._on_hid_battery,
        )
        self._hid_gesture = listener
        if not listener.start():
            self._hid_gesture = None
        elif hasattr(listener, "set_thumb_rawxy_enabled"):
            # Re-apply the last thumb-swipe config to the fresh listener.
            listener.set_thumb_rawxy_enabled(self._thumb_direction_enabled)
        return self._hid_gesture

    def _stop_hid_listener(self):
        if self._hid_gesture:
            self._hid_gesture.stop()
            self._hid_gesture = None

    def _on_hid_connect(self):
        self._connected_device = (
            self._hid_gesture.connected_device if self._hid_gesture else None
        )
        self._gesture_via_sense_panel = bool(
            getattr(self._connected_device, "gesture_via_sense_panel", False)
        )
        self._set_device_connected(True)

    def _on_hid_disconnect(self):
        self._connected_device = None
        self._set_device_connected(False)

    def _on_hid_battery(self, level, charging):
        cb = self._battery_notify_cb
        if cb:
            try:
                cb(level, charging)
            except Exception:
                pass

    def _on_hid_gesture_down(self):
        if getattr(self, "_ui_passthrough", False):
            return
        if self._gesture_active:
            return
        self._gesture_recognizer.begin()
        self._gesture_active = True
        self._emit_debug("HID gesture button down")
        self._emit_gesture_event({"type": "button_down"})
        self._dispatch(MouseEvent(self._primary_button_down_event()))

    def _on_hid_gesture_up(self):
        if getattr(self, "_ui_passthrough", False):
            return
        if not self._gesture_active:
            return
        self._gesture_active = False
        was_click = self._gesture_recognizer.end()
        hg = self._hid_gesture
        if was_click and hg and getattr(hg, "extra_held_during_gesture", False):
            was_click = False
        self._log_gesture_summary()
        self._emit_debug(
            f"HID gesture button up click_candidate={str(was_click).lower()}"
        )
        self._emit_gesture_event(
            {"type": "button_up", "click_candidate": was_click}
        )
        self._dispatch(MouseEvent(self._primary_button_up_event()))
        if was_click:
            self._dispatch(MouseEvent(self._primary_click_event()))

    def _on_hid_gesture_move(self, dx, dy):
        if getattr(self, "_ui_passthrough", False):
            return
        self._emit_gesture_event(
            {"type": "move", "source": "hid_rawxy", "dx": dx, "dy": dy}
        )
        if self._gesture_os_passthrough and self._gesture_active:
            cb = self._gesture_move_callback
            if cb:
                try:
                    cb(dx, dy)
                except Exception:
                    pass
            return
        self._gesture_recognizer.sample(dx, dy, "hid_rawxy")

    def _on_recognized_swipe(self, direction):
        event_type = self._primary_swipe_events().get(direction)
        if event_type is not None:
            self._emit_gesture_swipe(MouseEvent(event_type))

    def _on_thumb_recognized_swipe(self, direction):
        # The thumb Gesture button always emits the gesture_* family.
        event_type = _GESTURE_SWIPE_EVENTS.get(direction)
        if event_type is not None:
            self._emit_gesture_swipe(MouseEvent(event_type))

    def _emit_gesture_swipe(self, mouse_event):
        self._dispatch(mouse_event)

    def _log_gesture_summary(self):
        s = self._gesture_recognizer.summary()
        outcome = "+".join(s["fired"]) if s["fired"] else "click"
        print(
            f"[Gesture] hold={s['duration_ms']:.0f}ms samples={s['samples']} "
            f"net=({s['net_x']:+.0f},{s['net_y']:+.0f}) "
            f"peak={s['peak_speed']:.0f}u/s src={s['source'] or '-'} "
            f"-> {outcome}"
        )

    def _on_hid_mode_shift_down(self):
        # Mode shift is HID++ diverted (no OS button event), so when it's armed
        # as a gesture pad we start the hold here on the HID press and let the
        # platform hook feed OS pointer motion -- the same hybrid the macOS
        # gesture button uses. Otherwise it's a normal button press.
        if self.is_button_gesture_owner("mode_shift") and self.arm_button_gesture(
            "mode_shift"
        ):
            return
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        if self._button_gesture_active_owner == "mode_shift":
            self.release_button_gesture("mode_shift")
            return
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_xbutton_down(self, owner, event_type):
        # A diverted side button is the mode-shift hybrid: armed here on the
        # HID press (the OS never sees the button while diverted), fed OS
        # pointer motion by the platform hook. When it is not a hold-mode
        # owner (e.g. another profile is active), it dispatches the normal
        # button event so plain mappings keep firing through the divert.
        if self.is_button_gesture_owner(owner) and self.arm_button_gesture(owner):
            return
        self._dispatch(MouseEvent(event_type))

    def _on_hid_xbutton_up(self, owner, event_type):
        if self._button_gesture_active_owner == owner:
            self.release_button_gesture(owner)
            return
        self._dispatch(MouseEvent(event_type))

    def _on_hid_xbutton1_down(self):
        self._on_hid_xbutton_down("xbutton1", MouseEvent.XBUTTON1_DOWN)

    def _on_hid_xbutton1_up(self):
        self._on_hid_xbutton_up("xbutton1", MouseEvent.XBUTTON1_UP)

    def _on_hid_xbutton2_down(self):
        self._on_hid_xbutton_down("xbutton2", MouseEvent.XBUTTON2_DOWN)

    def _on_hid_xbutton2_up(self):
        self._on_hid_xbutton_up("xbutton2", MouseEvent.XBUTTON2_UP)

    def _on_hid_dpi_switch_down(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))

    def _on_hid_thumb_button_down(self):
        # The MX Master 4's small thumb-area button (CID 0x00C3) is the
        # physical "Gesture button" — config key "gesture" — so it emits the
        # gesture_* family (matching how the primary thumb behaves on the
        # MX3/3S/classic). When thumb-swipe is enabled, the HID layer has
        # handed rawXY to this CID so hold+move recognizes a direction.
        if getattr(self, "_ui_passthrough", False):
            return
        if self._thumb_active:
            return
        self._thumb_recognizer.begin()
        self._thumb_active = True
        self._emit_debug("HID thumb button down")
        self._dispatch(MouseEvent(MouseEvent.GESTURE_BUTTON_DOWN))

    def _on_hid_thumb_button_up(self):
        if getattr(self, "_ui_passthrough", False):
            return
        if not self._thumb_active:
            return
        self._thumb_active = False
        was_click = self._thumb_recognizer.end()
        self._emit_debug(
            f"HID thumb button up click_candidate={str(was_click).lower()}"
        )
        self._dispatch(MouseEvent(MouseEvent.GESTURE_BUTTON_UP))
        if was_click:
            self._dispatch(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _on_hid_thumb_button_move(self, dx, dy):
        if getattr(self, "_ui_passthrough", False):
            return
        self._emit_gesture_event(
            {"type": "move", "source": "hid_rawxy_thumb", "dx": dx, "dy": dy}
        )
        if self._thumb_os_passthrough and self._thumb_active:
            cb = self._thumb_move_callback
            if cb:
                try:
                    cb(dx, dy)
                except Exception:
                    pass
            return
        self._thumb_recognizer.sample(dx, dy, "hid_rawxy")
