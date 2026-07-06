import json
import unittest

from core import config


def _cfg_with_mappings(mappings):
    """A DEFAULT_CONFIG deep copy with extra mappings applied to the default profile."""
    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["profiles"]["default"]["mappings"].update(mappings)
    return cfg


class PerButtonGestureSchemaTests(unittest.TestCase):
    def test_twelve_namespaced_keys_exist_and_validate(self):
        self.assertEqual(len(config.PER_BUTTON_GESTURE_KEYS), 12)
        for owner in ("back", "forward", "middle"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, config.PER_BUTTON_GESTURE_KEYS)
                    self.assertIn(key, config.PROFILE_BUTTON_NAMES)
                    # Deliberately NOT in BUTTON_TO_EVENTS: the kernel emits the
                    # generic gesture_swipe_<dir> tagged with gesture_owner, so
                    # a namespaced event string is never dispatched. These keys
                    # resolve via gesture_bindings_for() instead.
                    self.assertNotIn(key, config.BUTTON_TO_EVENTS)
                    self.assertEqual(
                        config.DEFAULT_CONFIG["profiles"]["default"]["mappings"][key],
                        "none",
                    )


class GestureOwnersTests(unittest.TestCase):
    def test_default_config_has_zero_gesture_owners(self):
        cfg = _cfg_with_mappings({})
        self.assertEqual(config.gesture_owners(cfg), set())

    def test_one_bound_direction_marks_its_owner(self):
        cfg = _cfg_with_mappings({"gesture_forward_up": "mission_control"})
        self.assertEqual(config.gesture_owners(cfg), {"forward"})

    def test_multiple_owners_bound_independently(self):
        cfg = _cfg_with_mappings({
            "gesture_back_left": "browser_back",
            "gesture_middle_right": "browser_forward",
        })
        self.assertEqual(config.gesture_owners(cfg), {"back", "middle"})

    def test_gesture_bindings_for_returns_swipe_keyed_dict(self):
        cfg = _cfg_with_mappings({
            "gesture_forward_up": "mission_control",
            "gesture_forward_down": "app_expose",
        })
        self.assertEqual(
            config.gesture_bindings_for(cfg, "forward"),
            {
                "swipe_left": "none",
                "swipe_right": "none",
                "swipe_up": "mission_control",
                "swipe_down": "app_expose",
            },
        )

    def test_gesture_bindings_for_unbound_owner_is_all_none(self):
        cfg = _cfg_with_mappings({"gesture_forward_up": "mission_control"})
        self.assertEqual(
            config.gesture_bindings_for(cfg, "back"),
            {"swipe_left": "none", "swipe_right": "none", "swipe_up": "none", "swipe_down": "none"},
        )


class TiltGestureSchemaTests(unittest.TestCase):
    def test_owner_split_button_vs_tilt(self):
        self.assertEqual(config.BUTTON_GESTURE_OWNERS, ("back", "forward", "middle"))
        self.assertEqual(config.TILT_GESTURE_OWNERS, ("tilt_left", "tilt_right"))
        # GESTURE_OWNERS is the union the helpers iterate; the two subsets are disjoint.
        self.assertEqual(
            set(config.GESTURE_OWNERS),
            set(config.BUTTON_GESTURE_OWNERS) | set(config.TILT_GESTURE_OWNERS),
        )
        self.assertEqual(
            set(config.BUTTON_GESTURE_OWNERS) & set(config.TILT_GESTURE_OWNERS), set()
        )

    def test_eight_tilt_keys_exist_and_validate(self):
        self.assertEqual(len(config.TILT_GESTURE_KEYS), 8)
        for owner in ("tilt_left", "tilt_right"):
            for direction in ("left", "right", "up", "down"):
                key = f"gesture_{owner}_{direction}"
                with self.subTest(key=key):
                    self.assertIn(key, config.TILT_GESTURE_KEYS)
                    self.assertIn(key, config.PROFILE_BUTTON_NAMES)
                    # Same as the button gesture keys: a tilt TAP reuses the
                    # existing hscroll mapping and a tilt SLIDE routes via the
                    # gesture_owner tag, so no namespaced event is dispatched.
                    self.assertNotIn(key, config.BUTTON_TO_EVENTS)
                    self.assertEqual(
                        config.DEFAULT_CONFIG["profiles"]["default"]["mappings"][key],
                        "none",
                    )

    def test_tilt_keys_do_not_leak_into_per_button_keys(self):
        self.assertEqual(len(config.PER_BUTTON_GESTURE_KEYS), 12)
        self.assertEqual(
            set(config.PER_BUTTON_GESTURE_KEYS) & set(config.TILT_GESTURE_KEYS), set()
        )

    def test_default_config_has_zero_tilt_owners(self):
        cfg = _cfg_with_mappings({})
        self.assertEqual(
            config.gesture_owners(cfg) & set(config.TILT_GESTURE_OWNERS), set()
        )

    def test_bound_tilt_direction_marks_its_owner(self):
        cfg = _cfg_with_mappings({"gesture_tilt_left_up": "mission_control"})
        self.assertIn("tilt_left", config.gesture_owners(cfg))

    def test_gesture_bindings_for_tilt_owner(self):
        cfg = _cfg_with_mappings({
            "gesture_tilt_right_left": "browser_back",
            "gesture_tilt_right_right": "browser_forward",
        })
        self.assertEqual(
            config.gesture_bindings_for(cfg, "tilt_right"),
            {
                "swipe_left": "browser_back",
                "swipe_right": "browser_forward",
                "swipe_up": "none",
                "swipe_down": "none",
            },
        )


class TiltReleaseMsTests(unittest.TestCase):
    def test_default_release_ms_is_150(self):
        # 150ms sits safely above the ~110ms tilt inter-pulse gap so a held
        # tilt's pulse stream keeps the gesture armed instead of fragmenting
        # into spurious taps / dropped slow slides.
        migrated = config._migrate({"version": 1, "profiles": {}, "settings": {}})
        self.assertEqual(migrated["settings"]["tilt_gesture_release_ms"], 150)

    def test_release_ms_preserves_valid_custom_value(self):
        migrated = config._migrate(
            {"version": 9, "profiles": {}, "settings": {"tilt_gesture_release_ms": 220}}
        )
        self.assertEqual(migrated["settings"]["tilt_gesture_release_ms"], 220)

    def test_release_ms_clamped_to_50_minimum(self):
        migrated = config._migrate(
            {"version": 9, "profiles": {}, "settings": {"tilt_gesture_release_ms": 10}}
        )
        self.assertEqual(migrated["settings"]["tilt_gesture_release_ms"], 50)

    def test_legacy_config_backfills_tilt_keys(self):
        legacy = {
            "version": 9,
            "active_profile": "default",
            "profiles": {"default": {"label": "Default", "apps": [], "mappings": {}}},
            "settings": {},
        }
        migrated = config._migrate(legacy)
        for key in config.TILT_GESTURE_KEYS:
            self.assertEqual(migrated["profiles"]["default"]["mappings"][key], "none")


class GestureHoldFloorTests(unittest.TestCase):
    def test_default_hold_floor_is_80ms(self):
        migrated = config._migrate({"version": 1, "profiles": {}, "settings": {}})
        self.assertEqual(migrated["settings"]["gesture_hold_floor_ms"], 80)

    def test_hold_floor_preserves_a_valid_custom_value(self):
        migrated = config._migrate(
            {"version": 9, "profiles": {}, "settings": {"gesture_hold_floor_ms": 120}}
        )
        self.assertEqual(migrated["settings"]["gesture_hold_floor_ms"], 120)

    def test_hold_floor_clamped_to_zero_minimum(self):
        migrated = config._migrate(
            {"version": 9, "profiles": {}, "settings": {"gesture_hold_floor_ms": -50}}
        )
        self.assertEqual(migrated["settings"]["gesture_hold_floor_ms"], 0)


class GestureBackCompatTests(unittest.TestCase):
    def test_preexisting_config_with_no_owner_keys_loads_with_zero_owners(self):
        # Simulates a config saved by pre-#001 Mouser: no per-button gesture
        # keys anywhere in the mappings dict.
        legacy = {
            "version": 9,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "middle": "none",
                        "xbutton1": "alt_tab",
                        "xbutton2": "alt_tab",
                    },
                }
            },
            "settings": {},
        }

        migrated = config._migrate(legacy)

        self.assertEqual(config.gesture_owners(migrated), set())
        for key in config.PER_BUTTON_GESTURE_KEYS:
            self.assertEqual(migrated["profiles"]["default"]["mappings"][key], "none")

    def test_legacy_global_gesture_keys_still_resolve_and_are_not_owners(self):
        # A config with the OLD global gesture_left/right/up/down keys bound
        # (the MX Master HID-thumb-button path) must keep working exactly as
        # before, and must NOT be mistaken for a per-button owner.
        legacy = {
            "version": 3,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "apps": [],
                    "mappings": {
                        "gesture": "gesture_click_action",
                        "gesture_left": "mission_control",
                        "gesture_right": "app_expose",
                        "gesture_up": "desktop_left",
                        "gesture_down": "desktop_right",
                    },
                }
            },
            "settings": {},
        }

        migrated = config._migrate(legacy)

        mappings = migrated["profiles"]["default"]["mappings"]
        self.assertEqual(mappings["gesture"], "gesture_click_action")
        self.assertEqual(mappings["gesture_left"], "mission_control")
        self.assertEqual(mappings["gesture_right"], "app_expose")
        self.assertEqual(mappings["gesture_up"], "desktop_left")
        self.assertEqual(mappings["gesture_down"], "desktop_right")
        self.assertEqual(config.gesture_owners(migrated), set())


if __name__ == "__main__":
    unittest.main()
