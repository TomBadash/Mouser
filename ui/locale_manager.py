"""
Locale Manager — provides i18n support for the QML UI.
Supports English (en), Simplified Chinese (zh_CN), and Traditional Chinese (zh_TW).
Exposed to QML as the context property `lm`.
"""

from PySide6.QtCore import QObject, Property, Signal, Slot

_TRANSLATIONS = {
    "en": {
        # Navigation sidebar
        "nav.mouse_profiles": "Mouse & Profiles",
        "nav.point_scroll": "Point & Scroll",

        # Mouse page — profile list
        "mouse.profiles": "Profiles",
        "mouse.all_applications": "All applications",
        "mouse.add_app_profile": "Add App Profile",
        "mouse.search_installed_apps": "Search installed apps or browse for one manually",
        "mouse.delete_profile": "Delete Profile",

        # Mouse page — connection / status
        "mouse.connected": "Connected",
        "mouse.not_connected": "Not Connected",
        "mouse.waiting_for_connection": "Waiting for connection",
        "mouse.connect_mouse": "Connect your Logitech mouse",
        "mouse.connect_mouse_desc": "Mouser will detect the active device, unlock button mapping, and enable the correct layout mode as soon as the mouse is available.",
        "mouse.layout_appears_auto": "Layout mode appears automatically",
        "mouse.per_device_settings": "Per-device settings stay separate",

        # Mouse page — header subtitles
        "mouse.turn_on_mouse": "Turn on your Logitech mouse to start customizing buttons",
        "mouse.click_dot": "Click a dot to configure its action",
        "mouse.choose_layout": "Choose a layout mode below while we build a dedicated overlay",

        # Mouse page — layout mode
        "mouse.layout_mode": "Layout mode",
        "mouse.experimental_override_prefix": "Experimental override active: ",
        "mouse.experimental_override_suffix": ". Switch back to Auto-detect if the hotspot map does not line up.",
        "mouse.interactive_layout_coming": "Interactive layout coming later",
        "mouse.auto_detect": "Auto-detect",

        # Mouse page — action / mapping helpers
        "mouse.do_nothing": "Do Nothing",
        "mouse.horizontal_scroll": "Horizontal Scroll",
        "mouse.tap": "Tap: ",
        "mouse.swipes_configured": "Swipes configured",
        "mouse.installed_app": "Installed app",
        "mouse.applications": "Applications",
        "mouse.system_applications": "System Applications",
        "mouse.macos_coreservices": "macOS CoreServices",

        # Mouse page — action picker
        "mouse.choose_action_suffix": " \u2014 Choose Action",
        "mouse.configure_scroll_actions": "Configure separate actions for scroll left and right",
        "mouse.configure_gesture": "Configure tap behavior plus swipe actions for the gesture button",
        "mouse.select_button_action": "Select what happens when you use this button",
        "mouse.scroll_left": "SCROLL LEFT",
        "mouse.scroll_right": "SCROLL RIGHT",
        "mouse.tap_action": "TAP ACTION",
        "mouse.swipe_actions": "SWIPE ACTIONS",
        "mouse.swipe_left": "Swipe left",
        "mouse.swipe_right": "Swipe right",
        "mouse.swipe_up": "Swipe up",
        "mouse.swipe_down": "Swipe down",
        "mouse.threshold": "Threshold",

        # Mouse page — debug panel
        "mouse.debug_events": "Debug Events",
        "mouse.debug_events_desc": "Collects detected buttons, gestures, and mapped actions",
        "mouse.clear": "Clear",
        "mouse.clear_rec": "Clear Rec",
        "mouse.on": "On",
        "mouse.off": "Off",
        "mouse.rec": "Rec",
        "mouse.record": "Record",
        "mouse.live_gesture_monitor": "Live Gesture Monitor",
        "mouse.held": "Held",
        "mouse.idle": "Idle",
        "mouse.move_seen": "Move Seen",
        "mouse.no_move": "No Move",
        "mouse.debug_placeholder": "Turn on debug mode, then press buttons or use the gesture button.",
        "mouse.gesture_placeholder": "Turn on Record and perform a few gesture attempts.",

        # Mouse page — add app dialog
        "mouse.add_app_dialog.title": "Add App Profile",
        "mouse.add_app_dialog.desc": "Choose an app. Mouser will switch to this profile when that app is focused.",
        "mouse.search_placeholder": "Search apps by name",
        "mouse.browse": "Browse",
        "mouse.search_results": "Search Results",
        "mouse.suggested_apps": "Suggested Apps",
        "mouse.no_matched": "No apps matched that search.",
        "mouse.no_suggested": "No suggested apps available.",
        "mouse.try_different": "Try a different name, or use Browse to choose the app directly.",
        "mouse.use_search": "Use the search box above, or browse to choose an app directly.",
        "mouse.create_profile": "Create Profile",
        "mouse.cancel": "Cancel",

        # Mouse page — delete dialog
        "mouse.delete_dialog.title": "Delete profile?",
        "mouse.delete_dialog.confirm_prefix": "Delete the profile for ",
        "mouse.delete_dialog.confirm_suffix": "?",
        "mouse.delete_dialog.desc": "This removes its custom button mappings. The default profile will remain.",

        # Scroll / Settings page
        "scroll.title": "Point & Scroll",
        "scroll.subtitle": "Adjust pointer speed, appearance, and scroll behaviour",
        "scroll.pointer_speed": "Pointer Speed (DPI)",
        "scroll.pointer_speed_desc": "Adjust the tracking speed of the sensor. Higher = faster pointer.",
        "scroll.pointer_speed_desc_range_prefix": "Adjust the tracking speed of the sensor. This device supports ",
        "scroll.pointer_speed_desc_range_to": " to ",
        "scroll.pointer_speed_desc_range_suffix": " DPI.",
        "scroll.presets": "Presets:",
        "scroll.wheel_mode": "Scroll Wheel Mode",
        "scroll.wheel_mode_desc": "Switch between tactile ratchet scrolling and smooth free-spin.",
        "scroll.ratchet": "Ratchet",
        "scroll.freespin": "Free Spin",
        "scroll.smart_shift": "SmartShift",
        "scroll.smart_shift_desc": "Automatically switches the scroll wheel from line-by-line scrolling to hyper-fast scrolling when you scroll faster.",
        "scroll.sensitivity_value": "SENSITIVITY VALUE",
        "scroll.scroll_mode_section": "SCROLL MODE",
        "scroll.appearance": "Appearance",
        "scroll.appearance_desc": "Choose whether Mouser follows the system, stays light, or stays dark.",
        "scroll.system": "System",
        "scroll.light": "Light",
        "scroll.dark": "Dark",
        "scroll.startup": "Startup",
        "scroll.startup_desc": "Start Mouser at login on Windows and macOS, and choose whether the settings window opens on launch or Mouser stays in the system tray.",
        "scroll.start_at_login": "Start at login",
        "scroll.start_minimized": "Start minimized",
        "scroll.scroll_speed": "Scroll Speed",
        "scroll.scroll_speed_desc": "Adjust how fast the page scrolls per wheel click. 1.0\u00d7 is the system default.",
        "scroll.scroll_speed_presets": "Presets:",
        "scroll.smooth_scroll": "Smooth Scrolling",
        "scroll.smooth_scroll_desc": "Add inertia so the page coasts to a stop after each wheel tick, similar to Logi Options.",
        "scroll.scroll_direction": "Scroll Direction",
        "scroll.scroll_direction_desc": "Invert the scroll direction (natural scrolling)",
        "scroll.invert_vertical": "Invert vertical scroll",
        "scroll.invert_horizontal": "Invert horizontal scroll",
        "scroll.dpi_note": "DPI changes require HID++ communication with the device and will take effect after a short delay.",
        "scroll.language": "Language",
        "scroll.language_desc": "Choose the display language for the application.",

        # Key-capture dialog
        "key_capture.title": "Custom Shortcut",
        "key_capture.placeholder": "e.g. ctrl+shift+f5",
        "key_capture.valid_keys": "Valid keys: ctrl, shift, alt, super, a\u2013z, f1\u2013f12,\nspace, tab, enter, esc, left, right, up, down, delete, ...",
        "key_capture.cancel": "Cancel",
        "key_capture.confirm": "Confirm",

        # System tray (used from Python)
        "tray.open_settings": "Open Settings",
        "tray.disable_remapping": "Disable Remapping",
        "tray.enable_remapping": "Enable Remapping",
        "tray.enable_debug": "Enable Debug Mode",
        "tray.disable_debug": "Disable Debug Mode",
        "tray.quit": "Quit Mouser",
        "tray.tray_message": "Mouser is running in the system tray. Click the icon to open settings.",

        # Accessibility dialog (macOS)
        "accessibility.title": "Accessibility Permission Required",
        "accessibility.text": (
            "Mouser needs Accessibility permission to intercept "
            "mouse button events.\n\n"
            "macOS should have opened the System Settings prompt.\n"
            "Please grant permission, then restart Mouser."
        ),
        "accessibility.info": "System Settings -> Privacy & Security -> Accessibility",

        # Language names
        "lang.en": "English",
        "lang.zh_CN": "\u7b80\u4f53\u4e2d\u6587",
        "lang.zh_TW": "\u7e41\u9ad4\u4e2d\u6587",
    },

    # ── Simplified Chinese ────────────────────────────────────────
    "zh_CN": {
        "nav.mouse_profiles": "\u9f20\u6807\u4e0e\u914d\u7f6e\u6587\u4ef6",
        "nav.point_scroll": "\u6307\u9488\u4e0e\u6eda\u8f6e",

        "mouse.profiles": "\u914d\u7f6e\u6587\u4ef6",
        "mouse.all_applications": "\u6240\u6709\u5e94\u7528\u7a0b\u5e8f",
        "mouse.add_app_profile": "\u6dfb\u52a0\u5e94\u7528\u914d\u7f6e",
        "mouse.search_installed_apps": "\u641c\u7d22\u5df2\u5b89\u88c5\u7684\u5e94\u7528\u6216\u624b\u52a8\u6d4f\u89c8",
        "mouse.delete_profile": "\u5220\u9664\u914d\u7f6e",

        "mouse.connected": "\u5df2\u8fde\u63a5",
        "mouse.not_connected": "\u672a\u8fde\u63a5",
        "mouse.waiting_for_connection": "\u7b49\u5f85\u8fde\u63a5",
        "mouse.connect_mouse": "\u8fde\u63a5\u60a8\u7684\u7f57\u6280\u9f20\u6807",
        "mouse.connect_mouse_desc": "Mouser \u5c06\u68c0\u6d4b\u6d3b\u52a8\u8bbe\u5907\uff0c\u89e3\u9501\u6309\u952e\u6620\u5c04\uff0c\u5e76\u5728\u9f20\u6807\u53ef\u7528\u540e\u542f\u7528\u6b63\u786e\u7684\u5e03\u5c40\u6a21\u5f0f\u3002",
        "mouse.layout_appears_auto": "\u5e03\u5c40\u6a21\u5f0f\u81ea\u52a8\u663e\u793a",
        "mouse.per_device_settings": "\u6bcf\u4e2a\u8bbe\u5907\u7684\u8bbe\u7f6e\u72ec\u7acb\u4fdd\u5b58",

        "mouse.turn_on_mouse": "\u6253\u5f00\u60a8\u7684\u7f57\u6280\u9f20\u6807\u4ee5\u5f00\u59cb\u81ea\u5b9a\u4e49\u6309\u952e",
        "mouse.click_dot": "\u70b9\u51fb\u5706\u70b9\u914d\u7f6e\u5176\u52a8\u4f5c",
        "mouse.choose_layout": "\u5728\u6211\u4eec\u6784\u5efa\u4e13\u5c5e\u8986\u76d6\u5c42\u7684\u540c\u65f6\uff0c\u8bf7\u5728\u4e0b\u65b9\u9009\u62e9\u5e03\u5c40\u6a21\u5f0f",

        "mouse.layout_mode": "\u5e03\u5c40\u6a21\u5f0f",
        "mouse.experimental_override_prefix": "\u5b9e\u9a8c\u6027\u8986\u76d6\u5df2\u6fc0\u6d3b\uff1a",
        "mouse.experimental_override_suffix": "\u3002\u5982\u679c\u70ed\u70b9\u56fe\u4e0d\u5bf9\u9f50\uff0c\u8bf7\u5207\u6362\u56de\u81ea\u52a8\u68c0\u6d4b\u3002",
        "mouse.interactive_layout_coming": "\u4ea4\u4e92\u5f0f\u5e03\u5c40\u5373\u5c06\u63a8\u51fa",
        "mouse.auto_detect": "\u81ea\u52a8\u68c0\u6d4b",

        "mouse.do_nothing": "\u65e0\u64cd\u4f5c",
        "mouse.horizontal_scroll": "\u6c34\u5e73\u6eda\u52a8",
        "mouse.tap": "\u70b9\u51fb\uff1a",
        "mouse.swipes_configured": "\u5df2\u914d\u7f6e\u6ed1\u52a8",
        "mouse.installed_app": "\u5df2\u5b89\u88c5\u7684\u5e94\u7528",
        "mouse.applications": "\u5e94\u7528\u7a0b\u5e8f",
        "mouse.system_applications": "\u7cfb\u7edf\u5e94\u7528\u7a0b\u5e8f",
        "mouse.macos_coreservices": "macOS \u6838\u5fc3\u670d\u52a1",

        "mouse.choose_action_suffix": " \u2014 \u9009\u62e9\u52a8\u4f5c",
        "mouse.configure_scroll_actions": "\u4e3a\u5411\u5de6\u548c\u5411\u53f3\u6eda\u52a8\u5206\u522b\u914d\u7f6e\u52a8\u4f5c",
        "mouse.configure_gesture": "\u914d\u7f6e\u624b\u52bf\u6309\u9215\u7684\u70b9\u51fb\u884c\u4e3a\u548c\u6ed1\u52a8\u52a8\u4f5c",
        "mouse.select_button_action": "\u9009\u62e9\u4f7f\u7528\u6b64\u6309\u952e\u65f6\u89e6\u53d1\u7684\u52a8\u4f5c",
        "mouse.scroll_left": "\u5411\u5de6\u6eda\u52a8",
        "mouse.scroll_right": "\u5411\u53f3\u6eda\u52a8",
        "mouse.tap_action": "\u70b9\u51fb\u52a8\u4f5c",
        "mouse.swipe_actions": "\u6ed1\u52a8\u52a8\u4f5c",
        "mouse.swipe_left": "\u5411\u5de6\u6ed1\u52a8",
        "mouse.swipe_right": "\u5411\u53f3\u6ed1\u52a8",
        "mouse.swipe_up": "\u5411\u4e0a\u6ed1\u52a8",
        "mouse.swipe_down": "\u5411\u4e0b\u6ed1\u52a8",
        "mouse.threshold": "\u9608\u5024",

        "mouse.debug_events": "\u8c03\u8bd5\u4e8b\u4ef6",
        "mouse.debug_events_desc": "\u6536\u96c6\u68c0\u6d4b\u5230\u7684\u6309\u952e\u3001\u624b\u52bf\u548c\u6620\u5c04\u52a8\u4f5c",
        "mouse.clear": "\u6e05\u9664",
        "mouse.clear_rec": "\u6e05\u9664\u5f55\u5236",
        "mouse.on": "\u5f00",
        "mouse.off": "\u5173",
        "mouse.rec": "\u5f55\u5236\u4e2d",
        "mouse.record": "\u5f55\u5236",
        "mouse.live_gesture_monitor": "\u5b9e\u65f6\u624b\u52bf\u76d1\u89c6\u5668",
        "mouse.held": "\u6309\u4f4f",
        "mouse.idle": "\u7a7a\u95f2",
        "mouse.move_seen": "\u68c0\u6d4b\u5230\u79fb\u52a8",
        "mouse.no_move": "\u65e0\u79fb\u52a8",
        "mouse.debug_placeholder": "\u5f00\u542f\u8c03\u8bd5\u6a21\u5f0f\uff0c\u7136\u540e\u6309\u4e0b\u6309\u952e\u6216\u4f7f\u7528\u624b\u52bf\u6309\u9215\u3002",
        "mouse.gesture_placeholder": "\u5f00\u542f\u5f55\u5236\u5e76\u8fdb\u884c\u51e0\u6b21\u624b\u52bf\u5c1d\u8bd5\u3002",

        "mouse.add_app_dialog.title": "\u6dfb\u52a0\u5e94\u7528\u914d\u7f6e",
        "mouse.add_app_dialog.desc": "\u9009\u62e9\u4e00\u4e2a\u5e94\u7528\u3002\u5f53\u8be5\u5e94\u7528\u5904\u4e8e\u7126\u70b9\u65f6\uff0cMouser \u5c06\u5207\u6362\u5230\u6b64\u914d\u7f6e\u3002",
        "mouse.search_placeholder": "\u6309\u540d\u79f0\u641c\u7d22\u5e94\u7528",
        "mouse.browse": "\u6d4f\u89c8",
        "mouse.search_results": "\u641c\u7d22\u7ed3\u679c",
        "mouse.suggested_apps": "\u63a8\u8350\u5e94\u7528",
        "mouse.no_matched": "\u672a\u627e\u5230\u5339\u914d\u7684\u5e94\u7528\u3002",
        "mouse.no_suggested": "\u6682\u65e0\u63a8\u8350\u5e94\u7528\u3002",
        "mouse.try_different": "\u8bf7\u5c1d\u8bd5\u5176\u4ed6\u540d\u79f0\uff0c\u6216\u4f7f\u7528\u201c\u6d4f\u89c8\u201d\u76f4\u63a5\u9009\u62e9\u5e94\u7528\u3002",
        "mouse.use_search": "\u8bf7\u4f7f\u7528\u4e0a\u65b9\u7684\u641c\u7d22\u6846\uff0c\u6216\u6d4f\u89c8\u4ee5\u76f4\u63a5\u9009\u62e9\u5e94\u7528\u3002",
        "mouse.create_profile": "\u521b\u5efa\u914d\u7f6e",
        "mouse.cancel": "\u53d6\u6d88",

        "mouse.delete_dialog.title": "\u5220\u9664\u914d\u7f6e\uff1f",
        "mouse.delete_dialog.confirm_prefix": "\u5220\u9664 ",
        "mouse.delete_dialog.confirm_suffix": " \u7684\u914d\u7f6e\uff1f",
        "mouse.delete_dialog.desc": "\u8fd9\u5c06\u5220\u9664\u5176\u81ea\u5b9a\u4e49\u6309\u952e\u6620\u5c04\u3002\u9ed8\u8ba4\u914d\u7f6e\u5c06\u4fdd\u7559\u3002",

        "scroll.title": "\u6307\u9488\u4e0e\u6eda\u8f6e",
        "scroll.subtitle": "\u8c03\u6574\u6307\u9488\u901f\u5ea6\u3001\u5916\u89c2\u548c\u6eda\u52a8\u884c\u4e3a",
        "scroll.pointer_speed": "\u6307\u9488\u901f\u5ea6 (DPI)",
        "scroll.pointer_speed_desc": "\u8c03\u6574\u4f20\u611f\u5668\u7684\u8ddf\u8e2a\u901f\u5ea6\u3002\u5024\u8d8a\u9ad8\uff0c\u6307\u9488\u79fb\u52a8\u8d8a\u5feb\u3002",
        "scroll.pointer_speed_desc_range_prefix": "\u8c03\u6574\u4f20\u611f\u5668\u7684\u8ddf\u8e2a\u901f\u5ea6\u3002\u6b64\u8bbe\u5907\u652f\u6301 ",
        "scroll.pointer_speed_desc_range_to": " \u81f3 ",
        "scroll.pointer_speed_desc_range_suffix": " DPI\u3002",
        "scroll.presets": "\u9884\u8bbe\uff1a",
        "scroll.wheel_mode": "\u6eda\u8f6e\u6a21\u5f0f",
        "scroll.wheel_mode_desc": "\u5728\u89e6\u89c9\u68d8\u8f6e\u6eda\u52a8\u548c\u987a\u6ed1\u98de\u8f6e\u6eda\u52a8\u4e4b\u95f4\u5207\u6362\u3002",
        "scroll.ratchet": "\u68d8\u8f6e",
        "scroll.freespin": "\u98de\u8f6e",
        "scroll.smart_shift": "SmartShift",
        "scroll.smart_shift_desc": "\u6eda\u8f6e\u6eda\u52a8\u8f83\u5feb\u65f6\uff0c\u81ea\u52a8\u4ece\u9010\u884c\u6eda\u52a8\u5207\u6362\u5230\u9ad8\u901f\u98de\u8f6e\u6a21\u5f0f\u3002",
        "scroll.sensitivity_value": "\u7075\u654f\u5ea6",
        "scroll.scroll_mode_section": "\u6eda\u8f6e\u6a21\u5f0f",
        "scroll.appearance": "\u5916\u89c2",
        "scroll.appearance_desc": "\u9009\u62e9 Mouser \u662f\u8ddf\u968f\u7cfb\u7edf\u3001\u4fdd\u6301\u6d45\u8272\u8fd8\u662f\u4fdd\u6301\u6df1\u8272\u3002",
        "scroll.system": "\u7cfb\u7edf",
        "scroll.light": "\u6d45\u8272",
        "scroll.dark": "\u6df1\u8272",
        "scroll.startup": "\u542f\u52a8",
        "scroll.startup_desc": "\u5728 Windows \u548c macOS \u4e0a\u968f\u767b\u5f55\u542f\u52a8 Mouser\uff0c\u5e76\u9009\u62e9\u542f\u52a8\u65f6\u662f\u5426\u6253\u5f00\u8bbe\u7f6e\u7a97\u53e3\u6216\u4ec5\u4fdd\u6301\u5728\u7cfb\u7edf\u6258\u76d8\u3002",
        "scroll.start_at_login": "\u5f00\u673a\u81ea\u542f\u52a8",
        "scroll.start_minimized": "\u542f\u52a8\u65f6\u6700\u5c0f\u5316",
        "scroll.scroll_speed": "\u6eda\u8f6e\u901f\u5ea6",
        "scroll.scroll_speed_desc": "\u8c03\u6574\u6bcf\u6b21\u6eda\u8f6e\u6eda\u52a8\u7684\u9875\u9762\u79fb\u52a8\u901f\u5ea6\u30021.0\u00d7 \u4e3a\u7cfb\u7edf\u9ed8\u8ba4\u3002",
        "scroll.scroll_speed_presets": "\u9884\u8bbe\uff1a",
        "scroll.smooth_scroll": "\u5e73\u6ed1\u6eda\u52a8",
        "scroll.smooth_scroll_desc": "\u6eda\u8f6e\u6eda\u52a8\u540e\u6dfb\u52a0\u60ef\u6027\u6ed1\u884c\u6548\u679c\uff0c\u7c7b\u4f3c Logi Options \u7684\u5e73\u6ed1\u6eda\u52a8\u4f53\u9a8c\u3002",
        "scroll.scroll_direction": "\u6eda\u52a8\u65b9\u5411",
        "scroll.scroll_direction_desc": "\u53cd\u8f6c\u6eda\u52a8\u65b9\u5411\uff08\u81ea\u7136\u6eda\u52a8\uff09",
        "scroll.invert_vertical": "\u53cd\u8f6c\u5782\u76f4\u6eda\u52a8",
        "scroll.invert_horizontal": "\u53cd\u8f6c\u6c34\u5e73\u6eda\u52a8",
        "scroll.dpi_note": "DPI \u66f4\u6539\u9700\u8981\u901a\u8fc7 HID++ \u4e0e\u8bbe\u5907\u901a\u4fe1\uff0c\u5c06\u5728\u77ed\u6682\u5ef6\u8fdf\u540e\u751f\u6548\u3002",
        "scroll.language": "\u8bed\u8a00",
        "scroll.language_desc": "\u9009\u62e9\u5e94\u7528\u7a0b\u5e8f\u7684\u663e\u793a\u8bed\u8a00\u3002",

        "key_capture.title": "\u81ea\u5b9a\u4e49\u5feb\u6377\u952e",
        "key_capture.placeholder": "\u4f8b\u5982\uff1actrl+shift+f5",
        "key_capture.valid_keys": "\u6709\u6548\u6309\u952e\uff1actrl\u3001shift\u3001alt\u3001super\u3001a\u2013z\u3001f1\u2013f12\u3001\nspace\u3001tab\u3001enter\u3001esc\u3001left\u3001right\u3001up\u3001down\u3001delete\u2026\u2026",
        "key_capture.cancel": "\u53d6\u6d88",
        "key_capture.confirm": "\u786e\u8ba4",

        "tray.open_settings": "\u6253\u5f00\u8bbe\u7f6e",
        "tray.disable_remapping": "\u7981\u7528\u6309\u952e\u91cd\u6620\u5c04",
        "tray.enable_remapping": "\u542f\u7528\u6309\u952e\u91cd\u6620\u5c04",
        "tray.enable_debug": "\u542f\u7528\u8c03\u8bd5\u6a21\u5f0f",
        "tray.disable_debug": "\u7981\u7528\u8c03\u8bd5\u6a21\u5f0f",
        "tray.quit": "\u9000\u51fa Mouser",
        "tray.tray_message": "Mouser \u6b63\u5728\u7cfb\u7edf\u6258\u76d8\u4e2d\u8fd0\u884c\u3002\u70b9\u51fb\u56fe\u6807\u6253\u5f00\u8bbe\u7f6e\u3002",

        "accessibility.title": "\u9700\u8981\u8f85\u52a9\u529f\u80fd\u6743\u9650",
        "accessibility.text": (
            "Mouser \u9700\u8981\u8f85\u52a9\u529f\u80fd\u6743\u9650\u4ee5\u62e6\u622a\u9f20\u6807\u6309\u952e\u4e8b\u4ef6\u3002\n\n"
            "macOS \u5e94\u5df2\u6253\u5f00\u7cfb\u7edf\u8bbe\u7f6e\u63d0\u793a\u3002\n"
            "\u8bf7\u6388\u4e88\u6743\u9650\uff0c\u7136\u540e\u91cd\u65b0\u542f\u52a8 Mouser\u3002"
        ),
        "accessibility.info": "\u7cfb\u7edf\u8bbe\u7f6e -> \u9690\u79c1\u4e0e\u5b89\u5168\u6027 -> \u8f85\u52a9\u529f\u80fd",

        "lang.en": "English",
        "lang.zh_CN": "\u7b80\u4f53\u4e2d\u6587",
        "lang.zh_TW": "\u7e41\u9ad4\u4e2d\u6587",
    },

    # ── Traditional Chinese ───────────────────────────────────────
    "zh_TW": {
        "nav.mouse_profiles": "\u6ed1\u9f20\u8207\u8a2d\u5b9a\u6a94",
        "nav.point_scroll": "\u6307\u6a19\u8207\u6372\u8ef8",

        "mouse.profiles": "\u8a2d\u5b9a\u6a94",
        "mouse.all_applications": "\u6240\u6709\u61c9\u7528\u7a0b\u5f0f",
        "mouse.add_app_profile": "\u65b0\u589e\u61c9\u7528\u7a0b\u5f0f\u8a2d\u5b9a\u6a94",
        "mouse.search_installed_apps": "\u641c\u5c0b\u5df2\u5b89\u88dd\u7684\u61c9\u7528\u7a0b\u5f0f\u6216\u624b\u52d5\u700f\u89bd",
        "mouse.delete_profile": "\u522a\u9664\u8a2d\u5b9a\u6a94",

        "mouse.connected": "\u5df2\u9023\u7dda",
        "mouse.not_connected": "\u672a\u9023\u7dda",
        "mouse.waiting_for_connection": "\u7b49\u5f85\u9023\u7dda",
        "mouse.connect_mouse": "\u9023\u63a5\u60a8\u7684\u7f85\u6280\u6ed1\u9f20",
        "mouse.connect_mouse_desc": "Mouser \u5c07\u5075\u6e2c\u6d3b\u52d5\u88dd\u7f6e\uff0c\u89e3\u9396\u6309\u9375\u5c0d\u6620\uff0c\u4e26\u5728\u6ed1\u9f20\u53ef\u7528\u5f8c\u555f\u7528\u6b63\u78ba\u7684\u7248\u9762\u914d\u7f6e\u6a21\u5f0f\u3002",
        "mouse.layout_appears_auto": "\u7248\u9762\u914d\u7f6e\u6a21\u5f0f\u81ea\u52d5\u986f\u793a",
        "mouse.per_device_settings": "\u6bcf\u500b\u88dd\u7f6e\u7684\u8a2d\u5b9a\u5206\u958b\u5132\u5b58",

        "mouse.turn_on_mouse": "\u958b\u555f\u60a8\u7684\u7f85\u6280\u6ed1\u9f20\u4ee5\u958b\u59cb\u81ea\u8a02\u6309\u9375",
        "mouse.click_dot": "\u9ede\u64ca\u5713\u9ede\u4ee5\u8a2d\u5b9a\u5176\u52d5\u4f5c",
        "mouse.choose_layout": "\u5728\u6211\u5011\u5efa\u7acb\u5c08\u5c6c\u8986\u84cb\u5c64\u7684\u540c\u6642\uff0c\u8acb\u5728\u4e0b\u65b9\u9078\u64c7\u7248\u9762\u914d\u7f6e\u6a21\u5f0f",

        "mouse.layout_mode": "\u7248\u9762\u914d\u7f6e\u6a21\u5f0f",
        "mouse.experimental_override_prefix": "\u5be6\u9a57\u6027\u8986\u84cb\u5df2\u555f\u7528\uff1a",
        "mouse.experimental_override_suffix": "\u3002\u5982\u679c\u71b1\u9ede\u5716\u4e0d\u5c0d\u9f4a\uff0c\u8acb\u5207\u63db\u56de\u81ea\u52d5\u5075\u6e2c\u3002",
        "mouse.interactive_layout_coming": "\u4e92\u52d5\u5f0f\u7248\u9762\u914d\u7f6e\u5373\u5c07\u63a8\u51fa",
        "mouse.auto_detect": "\u81ea\u52d5\u5075\u6e2c",

        "mouse.do_nothing": "\u7121\u52d5\u4f5c",
        "mouse.horizontal_scroll": "\u6c34\u5e73\u6372\u52d5",
        "mouse.tap": "\u9ede\u64ca\uff1a",
        "mouse.swipes_configured": "\u5df2\u8a2d\u5b9a\u6ed1\u52d5",
        "mouse.installed_app": "\u5df2\u5b89\u88dd\u7684\u61c9\u7528\u7a0b\u5f0f",
        "mouse.applications": "\u61c9\u7528\u7a0b\u5f0f",
        "mouse.system_applications": "\u7cfb\u7d71\u61c9\u7528\u7a0b\u5f0f",
        "mouse.macos_coreservices": "macOS \u6838\u5fc3\u670d\u52d9",

        "mouse.choose_action_suffix": " \u2014 \u9078\u64c7\u52d5\u4f5c",
        "mouse.configure_scroll_actions": "\u5206\u5225\u8a2d\u5b9a\u5411\u5de6\u548c\u5411\u53f3\u6372\u52d5\u7684\u52d5\u4f5c",
        "mouse.configure_gesture": "\u8a2d\u5b9a\u624b\u52e2\u6309\u9215\u7684\u9ede\u64ca\u884c\u70ba\u548c\u6ed1\u52d5\u52d5\u4f5c",
        "mouse.select_button_action": "\u9078\u64c7\u4f7f\u7528\u6b64\u6309\u9375\u6642\u89f8\u767c\u7684\u52d5\u4f5c",
        "mouse.scroll_left": "\u5411\u5de6\u6372\u52d5",
        "mouse.scroll_right": "\u5411\u53f3\u6372\u52d5",
        "mouse.tap_action": "\u9ede\u64ca\u52d5\u4f5c",
        "mouse.swipe_actions": "\u6ed1\u52d5\u52d5\u4f5c",
        "mouse.swipe_left": "\u5411\u5de6\u6ed1\u52d5",
        "mouse.swipe_right": "\u5411\u53f3\u6ed1\u52d5",
        "mouse.swipe_up": "\u5411\u4e0a\u6ed1\u52d5",
        "mouse.swipe_down": "\u5411\u4e0b\u6ed1\u52d5",
        "mouse.threshold": "\u95be\u5024",

        "mouse.debug_events": "\u9664\u932f\u4e8b\u4ef6",
        "mouse.debug_events_desc": "\u6536\u96c6\u5075\u6e2c\u5230\u7684\u6309\u9375\u3001\u624b\u52e2\u548c\u5c0d\u6620\u52d5\u4f5c",
        "mouse.clear": "\u6e05\u9664",
        "mouse.clear_rec": "\u6e05\u9664\u9304\u88fd",
        "mouse.on": "\u958b",
        "mouse.off": "\u95dc",
        "mouse.rec": "\u9304\u88fd\u4e2d",
        "mouse.record": "\u9304\u88fd",
        "mouse.live_gesture_monitor": "\u5373\u6642\u624b\u52e2\u76e3\u8996\u5668",
        "mouse.held": "\u6309\u4f4f",
        "mouse.idle": "\u9592\u7f6e",
        "mouse.move_seen": "\u5075\u6e2c\u5230\u79fb\u52d5",
        "mouse.no_move": "\u7121\u79fb\u52d5",
        "mouse.debug_placeholder": "\u958b\u555f\u9664\u932f\u6a21\u5f0f\uff0c\u7136\u5f8c\u6309\u4e0b\u6309\u9375\u6216\u4f7f\u7528\u624b\u52e2\u6309\u9215\u3002",
        "mouse.gesture_placeholder": "\u958b\u555f\u9304\u88fd\u4e26\u9032\u884c\u5e7e\u6b21\u624b\u52e2\u5617\u8a66\u3002",

        "mouse.add_app_dialog.title": "\u65b0\u589e\u61c9\u7528\u7a0b\u5f0f\u8a2d\u5b9a\u6a94",
        "mouse.add_app_dialog.desc": "\u9078\u64c7\u4e00\u500b\u61c9\u7528\u7a0b\u5f0f\u3002\u7576\u8a72\u61c9\u7528\u7a0b\u5f0f\u8655\u65bc\u7126\u9ede\u6642\uff0cMouser \u5c07\u5207\u63db\u5230\u6b64\u8a2d\u5b9a\u6a94\u3002",
        "mouse.search_placeholder": "\u6309\u540d\u7a31\u641c\u5c0b\u61c9\u7528\u7a0b\u5f0f",
        "mouse.browse": "\u700f\u89bd",
        "mouse.search_results": "\u641c\u5c0b\u7d50\u679c",
        "mouse.suggested_apps": "\u5efa\u8b70\u7684\u61c9\u7528\u7a0b\u5f0f",
        "mouse.no_matched": "\u672a\u627e\u5230\u7b26\u5408\u7684\u61c9\u7528\u7a0b\u5f0f\u3002",
        "mouse.no_suggested": "\u66ab\u7121\u5efa\u8b70\u7684\u61c9\u7528\u7a0b\u5f0f\u3002",
        "mouse.try_different": "\u8acb\u5617\u8a66\u5176\u4ed6\u540d\u7a31\uff0c\u6216\u4f7f\u7528\u300c\u700f\u89bd\u300d\u76f4\u63a5\u9078\u64c7\u61c9\u7528\u7a0b\u5f0f\u3002",
        "mouse.use_search": "\u8acb\u4f7f\u7528\u4e0a\u65b9\u7684\u641c\u5c0b\u6846\uff0c\u6216\u700f\u89bd\u4ee5\u76f4\u63a5\u9078\u64c7\u61c9\u7528\u7a0b\u5f0f\u3002",
        "mouse.create_profile": "\u5efa\u7acb\u8a2d\u5b9a\u6a94",
        "mouse.cancel": "\u53d6\u6d88",

        "mouse.delete_dialog.title": "\u522a\u9664\u8a2d\u5b9a\u6a94\uff1f",
        "mouse.delete_dialog.confirm_prefix": "\u522a\u9664 ",
        "mouse.delete_dialog.confirm_suffix": " \u7684\u8a2d\u5b9a\u6a94\uff1f",
        "mouse.delete_dialog.desc": "\u9019\u5c07\u522a\u9664\u5176\u81ea\u8a02\u6309\u9375\u5c0d\u6620\u3002\u9810\u8a2d\u8a2d\u5b9a\u6a94\u5c07\u4fdd\u7559\u3002",

        "scroll.title": "\u6307\u6a19\u8207\u6372\u8ef8",
        "scroll.subtitle": "\u8abf\u6574\u6307\u6a19\u901f\u5ea6\u3001\u5916\u89c0\u548c\u6372\u52d5\u884c\u70ba",
        "scroll.pointer_speed": "\u6307\u6a19\u901f\u5ea6 (DPI)",
        "scroll.pointer_speed_desc": "\u8abf\u6574\u611f\u6e2c\u5668\u7684\u8ffd\u8e64\u901f\u5ea6\u3002\u5024\u8d8a\u9ad8\uff0c\u6307\u6a19\u79fb\u52d5\u8d8a\u5feb\u3002",
        "scroll.pointer_speed_desc_range_prefix": "\u8abf\u6574\u611f\u6e2c\u5668\u7684\u8ffd\u8e64\u901f\u5ea6\u3002\u6b64\u88dd\u7f6e\u652f\u63f4 ",
        "scroll.pointer_speed_desc_range_to": " \u81f3 ",
        "scroll.pointer_speed_desc_range_suffix": " DPI\u3002",
        "scroll.presets": "\u9810\u8a2d\uff1a",
        "scroll.wheel_mode": "\u6372\u8ef8\u6a21\u5f0f",
        "scroll.wheel_mode_desc": "\u5728\u89f8\u89ba\u68d8\u8f2a\u6372\u52d5\u548c\u9806\u6ed1\u98db\u8f2a\u6372\u52d5\u4e4b\u9593\u5207\u63db\u3002",
        "scroll.ratchet": "\u68d8\u8f2a",
        "scroll.freespin": "\u98db\u8f2a",
        "scroll.smart_shift": "SmartShift",
        "scroll.smart_shift_desc": "\u6372\u8ef8\u6eda\u52d5\u8f03\u5feb\u6642\uff0c\u81ea\u52d5\u5f9e\u9010\u884c\u6372\u52d5\u5207\u63db\u5230\u9ad8\u901f\u98db\u8f2a\u6a21\u5f0f\u3002",
        "scroll.sensitivity_value": "\u9748\u654f\u5ea6",
        "scroll.scroll_mode_section": "\u6eda\u8f2a\u6a21\u5f0f",
        "scroll.appearance": "\u5916\u89c0",
        "scroll.appearance_desc": "\u9078\u64c7 Mouser \u662f\u8ddf\u96a8\u7cfb\u7d71\u3001\u4fdd\u6301\u6dfa\u8272\u9084\u662f\u4fdd\u6301\u6df1\u8272\u3002",
        "scroll.system": "\u7cfb\u7d71",
        "scroll.light": "\u6dfa\u8272",
        "scroll.dark": "\u6df1\u8272",
        "scroll.startup": "\u555f\u52d5",
        "scroll.startup_desc": "\u5728 Windows \u548c macOS \u4e0a\u96a8\u767b\u5165\u555f\u52d5 Mouser\uff0c\u4e26\u9078\u64c7\u555f\u52d5\u6642\u662f\u5426\u958b\u555f\u8a2d\u5b9a\u8996\u7a97\u6216\u50c5\u4fdd\u6301\u5728\u7cfb\u7d71\u5217\u3002",
        "scroll.start_at_login": "\u767b\u5165\u6642\u555f\u52d5",
        "scroll.start_minimized": "\u555f\u52d5\u6642\u6700\u5c0f\u5316",
        "scroll.scroll_speed": "\u6eda\u8f2a\u901f\u5ea6",
        "scroll.scroll_speed_desc": "\u8abf\u6574\u6bcf\u6b21\u6eda\u8f2a\u6eda\u52d5\u7684\u9801\u9762\u79fb\u52d5\u901f\u5ea6\u30021.0\u00d7 \u70ba\u7cfb\u7d71\u9810\u8a2d\u3002",
        "scroll.scroll_speed_presets": "\u9810\u8a2d\uff1a",
        "scroll.smooth_scroll": "\u5e73\u6ed1\u6372\u52d5",
        "scroll.smooth_scroll_desc": "\u6eda\u8f2a\u6eda\u52d5\u5f8c\u6dfb\u52a0\u6163\u6027\u6ed1\u884c\u6548\u679c\uff0c\u985e\u4f3c Logi Options \u7684\u5e73\u6ed1\u6372\u52d5\u9ad4\u9a57\u3002",
        "scroll.scroll_direction": "\u6372\u52d5\u65b9\u5411",
        "scroll.scroll_direction_desc": "\u53cd\u8f49\u6372\u52d5\u65b9\u5411\uff08\u81ea\u7136\u6372\u52d5\uff09",
        "scroll.invert_vertical": "\u53cd\u8f49\u5782\u76f4\u6372\u52d5",
        "scroll.invert_horizontal": "\u53cd\u8f49\u6c34\u5e73\u6372\u52d5",
        "scroll.dpi_note": "DPI \u66f4\u6539\u9700\u8981\u900f\u904e HID++ \u8207\u88dd\u7f6e\u901a\u8a0a\uff0c\u5c07\u5728\u77ed\u66ab\u5ef6\u9072\u5f8c\u751f\u6548\u3002",
        "scroll.language": "\u8a9e\u8a00",
        "scroll.language_desc": "\u9078\u64c7\u61c9\u7528\u7a0b\u5f0f\u7684\u986f\u793a\u8a9e\u8a00\u3002",

        "key_capture.title": "\u81ea\u8a02\u5feb\u901f\u9375",
        "key_capture.placeholder": "\u4f8b\u5982\uff1actrl+shift+f5",
        "key_capture.valid_keys": "\u6709\u6548\u6309\u9375\uff1actrl\u3001shift\u3001alt\u3001super\u3001a\u2013z\u3001f1\u2013f12\u3001\nspace\u3001tab\u3001enter\u3001esc\u3001left\u3001right\u3001up\u3001down\u3001delete\u2026\u2026",
        "key_capture.cancel": "\u53d6\u6d88",
        "key_capture.confirm": "\u78ba\u8a8d",

        "tray.open_settings": "\u958b\u555f\u8a2d\u5b9a",
        "tray.disable_remapping": "\u505c\u7528\u6309\u9375\u91cd\u65b0\u5c0d\u6620",
        "tray.enable_remapping": "\u555f\u7528\u6309\u9375\u91cd\u65b0\u5c0d\u6620",
        "tray.enable_debug": "\u555f\u7528\u9664\u932f\u6a21\u5f0f",
        "tray.disable_debug": "\u505c\u7528\u9664\u932f\u6a21\u5f0f",
        "tray.quit": "\u7d50\u675f Mouser",
        "tray.tray_message": "Mouser \u6b63\u5728\u7cfb\u7d71\u5217\u4e2d\u57f7\u884c\u3002\u9ede\u64ca\u5716\u793a\u958b\u555f\u8a2d\u5b9a\u3002",

        "accessibility.title": "\u9700\u8981\u8f14\u52a9\u4f7f\u7528\u6b0a\u9650",
        "accessibility.text": (
            "Mouser \u9700\u8981\u8f14\u52a9\u4f7f\u7528\u6b0a\u9650\u4ee5\u6514\u622a\u6ed1\u9f20\u6309\u9375\u4e8b\u4ef6\u3002\n\n"
            "macOS \u61c9\u5df2\u958b\u555f\u7cfb\u7d71\u8a2d\u5b9a\u63d0\u793a\u3002\n"
            "\u8acb\u6388\u4e88\u6b0a\u9650\uff0c\u7136\u5f8c\u91cd\u65b0\u555f\u52d5 Mouser\u3002"
        ),
        "accessibility.info": "\u7cfb\u7d71\u8a2d\u5b9a -> \u96b1\u79c1\u6b0a\u8207\u5b89\u5168\u6027 -> \u8f14\u52a9\u4f7f\u7528",

        "lang.en": "English",
        "lang.zh_CN": "\u7b80\u4f53\u4e2d\u6587",
        "lang.zh_TW": "\u7e41\u9ad4\u4e2d\u6587",
    },
}

AVAILABLE_LANGUAGES = [
    {"code": "en",    "name": "English"},
    {"code": "zh_CN", "name": "\u7b80\u4f53\u4e2d\u6587"},
    {"code": "zh_TW", "name": "\u7e41\u9ad4\u4e2d\u6587"},
]

# ── Button name translations ──────────────────────────────────────────────────
# Key = English name from config.py BUTTON_NAMES / PROFILE_BUTTON_NAMES
_BUTTON_TR: dict[str, dict[str, str]] = {
    "zh_CN": {
        "Middle button":          "\u4e2d\u952e",
        "Gesture button":         "\u624b\u52bf\u952e",
        "Back button":            "\u540e\u9000\u952e",
        "Forward button":         "\u524d\u8fdb\u952e",
        "Horizontal scroll left": "\u6c34\u5e73\u5de6\u6eda",
        "Horizontal scroll right":"\u6c34\u5e73\u53f3\u6eda",
        "Horizontal Scroll":      "\u6c34\u5e73\u6eda\u52a8",
        "Mode shift button":      "\u6a21\u5f0f\u5207\u6362\u952e",
        "Gesture swipe left":     "\u624b\u52bf\u5de6\u6ed1",
        "Gesture swipe right":    "\u624b\u52bf\u53f3\u6ed1",
        "Gesture swipe up":       "\u624b\u52bf\u4e0a\u6ed1",
        "Gesture swipe down":     "\u624b\u52bf\u4e0b\u6ed1",
    },
    "zh_TW": {
        "Middle button":          "\u4e2d\u9375",
        "Gesture button":         "\u624b\u52e2\u9375",
        "Back button":            "\u5f8c\u9000\u9375",
        "Forward button":         "\u524d\u9032\u9375",
        "Horizontal scroll left": "\u6c34\u5e73\u5de6\u6372",
        "Horizontal scroll right":"\u6c34\u5e73\u53f3\u6372",
        "Horizontal Scroll":      "\u6c34\u5e73\u6372\u52d5",
        "Mode shift button":      "\u6a21\u5f0f\u5207\u63db\u9375",
        "Gesture swipe left":     "\u624b\u52e2\u5de6\u6ed1",
        "Gesture swipe right":    "\u624b\u52e2\u53f3\u6ed1",
        "Gesture swipe up":       "\u624b\u52e2\u4e0a\u6ed1",
        "Gesture swipe down":     "\u624b\u52e2\u4e0b\u6ed1",
    },
}

# ── Action category translations ──────────────────────────────────────────────
_CATEGORY_TR: dict[str, dict[str, str]] = {
    "zh_CN": {
        "Other":      "\u5176\u4ed6",
        "Browser":    "\u6d4f\u89c8\u5668",
        "Editing":    "\u7f16\u8f91",
        "Media":      "\u5a92\u4f53",
        "Navigation": "\u5bfc\u822a",
        "Scroll":     "\u6eda\u8f6e",
        "Custom":     "\u81ea\u5b9a\u4e49",
    },
    "zh_TW": {
        "Other":      "\u5176\u4ed6",
        "Browser":    "\u700f\u89bd\u5668",
        "Editing":    "\u7de8\u8f2f",
        "Media":      "\u5a92\u9ad4",
        "Navigation": "\u5c0e\u822a",
        "Scroll":     "\u6eda\u8f2a",
        "Custom":     "\u81ea\u8a02",
    },
}

# ── Action label translations ─────────────────────────────────────────────────
# Key = exact English label returned by key_simulator.py / backend.
# Key combos in parentheses are preserved verbatim in the translated string.
_ACTION_TR: dict[str, dict[str, str]] = {
    "zh_CN": {
        # ── Other ─────────────────────────────────────────────────────
        "Do Nothing (Pass-through)":                "\u65e0\u64cd\u4f5c\uff08\u76f4\u901a\uff09",

        # ── Navigation (Windows) ──────────────────────────────────────
        "Alt + Tab (Switch Windows)":               "Alt + Tab\uff08\u5207\u6362\u7a97\u53e3\uff09",
        "Alt + Shift + Tab (Switch Windows Reverse)":"Alt + Shift + Tab\uff08\u53cd\u5411\u5207\u6362\uff09",
        "Show Desktop (Win+D)":                     "\u663e\u793a\u684c\u9762 (Win+D)",
        "Task View (Win+Tab)":                      "\u4efb\u52a1\u89c6\u56fe (Win+Tab)",
        "Previous Desktop":                         "\u4e0a\u4e00\u4e2a\u684c\u9762",
        "Next Desktop":                             "\u4e0b\u4e00\u4e2a\u684c\u9762",
        "Page Up":                                  "\u5411\u4e0a\u7ffb\u9875",
        "Page Down":                                "\u5411\u4e0b\u7ffb\u9875",
        "Home":                                     "\u884c\u9996 (Home)",
        "End":                                      "\u884c\u5c3e (End)",

        # ── Navigation (macOS) ────────────────────────────────────────
        "Cmd + Tab (Switch Windows)":               "Cmd + Tab\uff08\u5207\u6362\u7a97\u53e3\uff09",
        "Cmd + Shift + Tab (Switch Windows Reverse)":"Cmd + Shift + Tab\uff08\u53cd\u5411\u5207\u6362\uff09",
        "Mission Control (Ctrl+Up)":                "\u4efb\u52a1\u63a7\u5236 (Ctrl+\u2191)",
        "Mission Control":                          "\u4efb\u52a1\u63a7\u5236",
        "App Expose":                               "\u5e94\u7528 Expos\u00e9",
        "Show Desktop":                             "\u663e\u793a\u684c\u9762",
        "Launchpad":                                "\u542f\u52a8\u53f0",

        # ── Navigation (Linux) ────────────────────────────────────────
        "Show Desktop (Super+D)":                   "\u663e\u793a\u684c\u9762 (Super+D)",
        "Activities (Super)":                       "\u6d3b\u52a8\u8868 (Super)",

        # ── Browser ───────────────────────────────────────────────────
        "Browser Back":                             "\u6d4f\u89c8\u5668\u540e\u9000",
        "Browser Forward":                          "\u6d4f\u89c8\u5668\u524d\u8fdb",
        "Browser Back (Cmd+[)":                     "\u6d4f\u89c8\u5668\u540e\u9000 (Cmd+[)",
        "Browser Forward (Cmd+])":                  "\u6d4f\u89c8\u5668\u524d\u8fdb (Cmd+])",
        "Close Tab (Ctrl+W)":                       "\u5173\u95ed\u6807\u7b7e\u9875 (Ctrl+W)",
        "Close Tab (Cmd+W)":                        "\u5173\u95ed\u6807\u7b7e\u9875 (Cmd+W)",
        "New Tab (Ctrl+T)":                         "\u65b0\u5efa\u6807\u7b7e\u9875 (Ctrl+T)",
        "New Tab (Cmd+T)":                          "\u65b0\u5efa\u6807\u7b7e\u9875 (Cmd+T)",
        "Next Tab (Ctrl+Tab)":                      "\u4e0b\u4e00\u4e2a\u6807\u7b7e\u9875 (Ctrl+Tab)",
        "Next Tab (Cmd+Shift+])":                   "\u4e0b\u4e00\u4e2a\u6807\u7b7e\u9875 (Cmd+Shift+])",
        "Previous Tab (Ctrl+Shift+Tab)":            "\u4e0a\u4e00\u4e2a\u6807\u7b7e\u9875 (Ctrl+Shift+Tab)",
        "Previous Tab (Cmd+Shift+[)":               "\u4e0a\u4e00\u4e2a\u6807\u7b7e\u9875 (Cmd+Shift+[)",

        # ── Editing ───────────────────────────────────────────────────
        "Copy (Ctrl+C)":        "\u590d\u5236 (Ctrl+C)",
        "Copy (Cmd+C)":         "\u590d\u5236 (Cmd+C)",
        "Paste (Ctrl+V)":       "\u7c98\u8d34 (Ctrl+V)",
        "Paste (Cmd+V)":        "\u7c98\u8d34 (Cmd+V)",
        "Cut (Ctrl+X)":         "\u526a\u5207 (Ctrl+X)",
        "Cut (Cmd+X)":          "\u526a\u5207 (Cmd+X)",
        "Undo (Ctrl+Z)":        "\u64a4\u9500 (Ctrl+Z)",
        "Undo (Cmd+Z)":         "\u64a4\u9500 (Cmd+Z)",
        "Select All (Ctrl+A)":  "\u5168\u9009 (Ctrl+A)",
        "Select All (Cmd+A)":   "\u5168\u9009 (Cmd+A)",
        "Save (Ctrl+S)":        "\u4fdd\u5b58 (Ctrl+S)",
        "Save (Cmd+S)":         "\u4fdd\u5b58 (Cmd+S)",
        "Find (Ctrl+F)":        "\u67e5\u627e (Ctrl+F)",
        "Find (Cmd+F)":         "\u67e5\u627e (Cmd+F)",

        # ── Media ─────────────────────────────────────────────────────
        "Volume Up":            "\u97f3\u91cf\u589e\u5927",
        "Volume Down":          "\u97f3\u91cf\u51cf\u5c0f",
        "Volume Mute":          "\u9759\u97f3",
        "Play / Pause":         "\u64ad\u653e/\u6682\u505c",
        "Next Track":           "\u4e0b\u4e00\u9996",
        "Previous Track":       "\u4e0a\u4e00\u9996",

        # ── Scroll ────────────────────────────────────────────────────
        "Toggle SmartShift":                        "\u5207\u6362 SmartShift \u5f00\u5173",
        "Switch Scroll Mode (Ratchet / Free Spin)": "\u5207\u6362\u6eda\u8f6e\u6a21\u5f0f\uff08\u68d8\u8f6e / \u98de\u8f6e\uff09",

        # ── Custom ────────────────────────────────────────────────────
        "Custom Shortcut\u2026": "\u81ea\u5b9a\u4e49\u5feb\u6377\u952e\u2026",
    },
    "zh_TW": {
        # ── Other ─────────────────────────────────────────────────────
        "Do Nothing (Pass-through)":                "\u7121\u64cd\u4f5c\uff08\u76f4\u901a\uff09",

        # ── Navigation (Windows) ──────────────────────────────────────
        "Alt + Tab (Switch Windows)":               "Alt + Tab\uff08\u5207\u63db\u8996\u7a97\uff09",
        "Alt + Shift + Tab (Switch Windows Reverse)":"Alt + Shift + Tab\uff08\u53cd\u5411\u5207\u63db\uff09",
        "Show Desktop (Win+D)":                     "\u986f\u793a\u684c\u9762 (Win+D)",
        "Task View (Win+Tab)":                      "\u5de5\u4f5c\u8996\u5716 (Win+Tab)",
        "Previous Desktop":                         "\u4e0a\u4e00\u500b\u684c\u9762",
        "Next Desktop":                             "\u4e0b\u4e00\u500b\u684c\u9762",
        "Page Up":                                  "\u5411\u4e0a\u7ffb\u9801",
        "Page Down":                                "\u5411\u4e0b\u7ffb\u9801",
        "Home":                                     "\u884c\u9996 (Home)",
        "End":                                      "\u884c\u5c3e (End)",

        # ── Navigation (macOS) ────────────────────────────────────────
        "Cmd + Tab (Switch Windows)":               "Cmd + Tab\uff08\u5207\u63db\u8996\u7a97\uff09",
        "Cmd + Shift + Tab (Switch Windows Reverse)":"Cmd + Shift + Tab\uff08\u53cd\u5411\u5207\u63db\uff09",
        "Mission Control (Ctrl+Up)":                "\u4efb\u52d9\u63a7\u5236 (Ctrl+\u2191)",
        "Mission Control":                          "\u4efb\u52d9\u63a7\u5236",
        "App Expose":                               "\u61c9\u7528\u7a0b\u5f0f Expos\u00e9",
        "Show Desktop":                             "\u986f\u793a\u684c\u9762",
        "Launchpad":                                "\u555f\u52d5\u53f0",

        # ── Navigation (Linux) ────────────────────────────────────────
        "Show Desktop (Super+D)":                   "\u986f\u793a\u684c\u9762 (Super+D)",
        "Activities (Super)":                       "\u6d3b\u52d5\u8996\u5716 (Super)",

        # ── Browser ───────────────────────────────────────────────────
        "Browser Back":                             "\u700f\u89bd\u5668\u5f8c\u9000",
        "Browser Forward":                          "\u700f\u89bd\u5668\u524d\u9032",
        "Browser Back (Cmd+[)":                     "\u700f\u89bd\u5668\u5f8c\u9000 (Cmd+[)",
        "Browser Forward (Cmd+])":                  "\u700f\u89bd\u5668\u524d\u9032 (Cmd+])",
        "Close Tab (Ctrl+W)":                       "\u95dc\u9589\u6a19\u7c64\u9801 (Ctrl+W)",
        "Close Tab (Cmd+W)":                        "\u95dc\u9589\u6a19\u7c64\u9801 (Cmd+W)",
        "New Tab (Ctrl+T)":                         "\u65b0\u5efa\u6a19\u7c64\u9801 (Ctrl+T)",
        "New Tab (Cmd+T)":                          "\u65b0\u5efa\u6a19\u7c64\u9801 (Cmd+T)",
        "Next Tab (Ctrl+Tab)":                      "\u4e0b\u4e00\u500b\u6a19\u7c64\u9801 (Ctrl+Tab)",
        "Next Tab (Cmd+Shift+])":                   "\u4e0b\u4e00\u500b\u6a19\u7c64\u9801 (Cmd+Shift+])",
        "Previous Tab (Ctrl+Shift+Tab)":            "\u4e0a\u4e00\u500b\u6a19\u7c64\u9801 (Ctrl+Shift+Tab)",
        "Previous Tab (Cmd+Shift+[)":               "\u4e0a\u4e00\u500b\u6a19\u7c64\u9801 (Cmd+Shift+[)",

        # ── Editing ───────────────────────────────────────────────────
        "Copy (Ctrl+C)":        "\u8907\u88fd (Ctrl+C)",
        "Copy (Cmd+C)":         "\u8907\u88fd (Cmd+C)",
        "Paste (Ctrl+V)":       "\u8cbc\u4e0a (Ctrl+V)",
        "Paste (Cmd+V)":        "\u8cbc\u4e0a (Cmd+V)",
        "Cut (Ctrl+X)":         "\u526a\u5207 (Ctrl+X)",
        "Cut (Cmd+X)":          "\u526a\u5207 (Cmd+X)",
        "Undo (Ctrl+Z)":        "\u5fa9\u539f (Ctrl+Z)",
        "Undo (Cmd+Z)":         "\u5fa9\u539f (Cmd+Z)",
        "Select All (Ctrl+A)":  "\u5168\u9078 (Ctrl+A)",
        "Select All (Cmd+A)":   "\u5168\u9078 (Cmd+A)",
        "Save (Ctrl+S)":        "\u5132\u5b58 (Ctrl+S)",
        "Save (Cmd+S)":         "\u5132\u5b58 (Cmd+S)",
        "Find (Ctrl+F)":        "\u5c0b\u627e (Ctrl+F)",
        "Find (Cmd+F)":         "\u5c0b\u627e (Cmd+F)",

        # ── Media ─────────────────────────────────────────────────────
        "Volume Up":            "\u97f3\u91cf\u589e\u5927",
        "Volume Down":          "\u97f3\u91cf\u6e1b\u5c0f",
        "Volume Mute":          "\u975c\u97f3",
        "Play / Pause":         "\u64ad\u653e/\u66ab\u505c",
        "Next Track":           "\u4e0b\u4e00\u9996",
        "Previous Track":       "\u4e0a\u4e00\u9996",

        # ── Scroll ────────────────────────────────────────────────────
        "Toggle SmartShift":                        "\u5207\u63db SmartShift \u958b\u95dc",
        "Switch Scroll Mode (Ratchet / Free Spin)": "\u5207\u63db\u6eda\u8f2a\u6a21\u5f0f\uff08\u68d8\u8f2a / \u98db\u8f2a\uff09",

        # ── Custom ────────────────────────────────────────────────────
        "Custom Shortcut\u2026": "\u81ea\u8a02\u5feb\u901f\u9375\u2026",
    },
}


class LocaleManager(QObject):
    """Manages the active UI language and exposes translations to QML."""

    languageChanged = Signal()

    def __init__(self, language: str = "en", parent=None):
        super().__init__(parent)
        lang = language if language in _TRANSLATIONS else "en"
        self._language = lang
        self._strings: dict = dict(_TRANSLATIONS[lang])

    # ── language property ─────────────────────────────────────────
    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Slot(str)
    def setLanguage(self, lang: str) -> None:
        if lang == self._language:
            return
        if lang not in _TRANSLATIONS:
            return
        self._language = lang
        self._strings = dict(_TRANSLATIONS[lang])
        self.languageChanged.emit()

    # ── strings map (QVariantMap) ─────────────────────────────────
    @Property("QVariantMap", notify=languageChanged)
    def strings(self) -> dict:
        """Return the full translation dictionary for the active language."""
        return self._strings

    # ── helper slot usable from Python ───────────────────────────
    @Slot(str, result=str)
    def tr(self, key: str) -> str:
        return self._strings.get(key, key)

    # ── button / action / category translation slots for QML ─────
    @Slot(str, result=str)
    def trButton(self, english_name: str) -> str:
        """Translate a button name (e.g. 'Middle button' → '中键')."""
        return _BUTTON_TR.get(self._language, {}).get(english_name, english_name)

    @Slot(str, result=str)
    def trAction(self, english_label: str) -> str:
        """Translate an action label (e.g. 'Copy (Cmd+C)' → '复制 (Cmd+C)')."""
        return _ACTION_TR.get(self._language, {}).get(english_label, english_label)

    @Slot(str, result=str)
    def trCategory(self, english_cat: str) -> str:
        """Translate an action category (e.g. 'Browser' → '浏览器')."""
        return _CATEGORY_TR.get(self._language, {}).get(english_cat, english_cat)

    # ── available languages list ──────────────────────────────────
    @Property(list, constant=True)
    def availableLanguages(self) -> list:
        return AVAILABLE_LANGUAGES
