"""Source-level guards for the custom-shortcut recorder dialog.

The recorder has two failure modes that are easy to reintroduce and painful on
Windows: recording every keystroke while the user types a combo by hand (Shift
for "+" replaced the whole shortcut), and leaving the Windows-key guard armed
once the dialog is gone (the Start menu stays swallowed app-wide).
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DIALOG_QML = (ROOT / "ui" / "qml" / "KeyCaptureDialog.qml").read_text(
    encoding="utf-8"
)


class KeyCaptureDialogQmlTests(unittest.TestCase):
    def test_typing_mode_does_not_record_keystrokes(self):
        self.assertIn("if (!dialog.recording)", DIALOG_QML)
        self.assertIn("readOnly: dialog.recording", DIALOG_QML)

    def test_recording_uses_the_guard_aware_capture_slot(self):
        self.assertIn("backend.shortcutComboFromCaptureEvent", DIALOG_QML)
        self.assertNotIn("backend.shortcutComboFromQtEvent", DIALOG_QML)

    def test_dialog_arms_and_releases_the_keyboard_guard(self):
        self.assertIn("backend.beginShortcutCapture()", DIALOG_QML)
        self.assertIn("backend.endShortcutCapture()", DIALOG_QML)
        # close() must release the guard, not just hide the dialog.
        close_body = DIALOG_QML.split("function close()", 1)[1].split("}", 1)[0]
        self.assertIn("stopRecording()", close_body)

    def test_guard_is_released_while_the_app_is_in_the_background(self):
        self.assertIn("Qt.application.state === Qt.ApplicationActive", DIALOG_QML)
        self.assertIn("onHostActiveChanged", DIALOG_QML)

    def test_held_modifiers_are_previewed_instead_of_being_recorded(self):
        self.assertIn("function _isModifierKey(", DIALOG_QML)
        self.assertIn("function _refreshPending(", DIALOG_QML)
        self.assertIn("onSuperKeyHeldChanged", DIALOG_QML)

    def test_mode_toggle_is_offered_in_both_directions(self):
        self.assertIn('s["key_capture.mode_type"]', DIALOG_QML)
        self.assertIn('s["key_capture.mode_record"]', DIALOG_QML)
        self.assertIn("dialog.switchToTyping()", DIALOG_QML)
        self.assertIn("dialog.startRecording()", DIALOG_QML)

    def test_optional_ring_label_field_is_exposed(self):
        self.assertIn("property bool showCustomLabel", DIALOG_QML)
        self.assertIn("readonly property string customLabel", DIALOG_QML)
        self.assertIn('s["key_capture.custom_label"]', DIALOG_QML)


if __name__ == "__main__":
    unittest.main()
