import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme

/*  Modal dialog for capturing a custom keyboard shortcut.
    Emits captured(comboString) with e.g. "ctrl+shift+f5".

    Two input modes, deliberately kept apart:
      * recording — every key press is recorded, the field is read-only.
        Windows keeps its Super key to itself (pressing it opens the Start
        menu), so the backend guard swallows it and reports its state instead.
      * typing    — a plain text field, so shifted characters such as "+"
        can be typed without the Shift press being recorded as the shortcut.  */

Rectangle {
    id: dialog
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    property string targetButton: ""
    property string targetProfile: ""
    property bool recording: false
    property bool showCustomLabel: false
    readonly property string customLabel: customLabelField.text.trim()
    property bool _valid: false
    property string _preview: ""
    property string _canonical: ""
    property string _warning: ""
    property string _pending: ""
    property int _lastModifiers: 0
    // False between a finished capture and the release of every held key, so
    // the "Ctrl + …" hint does not cover the shortcut just recorded.
    property bool _hintArmed: true

    readonly property bool hostActive: Qt.application.state === Qt.ApplicationActive

    signal captured(string comboString)
    signal cancelled()

    visible: false
    anchors.fill: parent
    color: "#80000000"
    z: 100

    function open(profile, button, initialLabel) {
        targetProfile = profile
        targetButton = button
        customLabelField.text = initialLabel || ""
        shortcutField.text = ""
        _valid = false
        _preview = ""
        _canonical = ""
        _warning = ""
        visible = true
        startRecording()
    }

    function close() {
        stopRecording()
        recording = false
        visible = false
    }

    // Arm the recorder: keys are captured instead of typed.
    function startRecording() {
        recording = true
        _pending = ""
        _lastModifiers = 0
        _hintArmed = true
        backend.beginShortcutCapture()
        shortcutField.forceActiveFocus()
    }

    // Release the keyboard guard. Kept separate from `recording` so the
    // dialog can drop the guard while the app is in the background without
    // losing the mode the user picked.
    function stopRecording() {
        _pending = ""
        _lastModifiers = 0
        backend.endShortcutCapture()
    }

    function switchToTyping() {
        stopRecording()
        recording = false
        shortcutField.forceActiveFocus()
    }

    onHostActiveChanged: {
        if (!visible || !recording)
            return
        if (hostActive)
            startRecording()
        else
            stopRecording()
    }

    function _validate(text) {
        if (!text || !text.trim()) {
            _valid = false
            _preview = ""
            _warning = ""
            return
        }
        var canonical = backend.canonicalizeCustomShortcut(text)
        if (!canonical) {
            var reason = dialog._validationErrorText(
                        backend.customShortcutValidationErrorInfo(text))
            _valid = false
            _canonical = ""
            _preview = "\u2718 " + (reason || "Invalid shortcut")
            _warning = ""
            return
        }
        var parts = canonical.split("+")
        var labels = []
        for (var j = 0; j < parts.length; j++)
            labels.push(dialog._displayKeyName(parts[j]))
        _valid = true
        _canonical = canonical
        _preview = "\u2714 " + labels.join(" + ")
        _warning = backend.isReservedCustomShortcut(canonical)
                   ? s["key_capture.reserved_warning"]
                   : ""
    }

    function _canonicalKeyName(name) {
        var lowered = (name || "").trim().toLowerCase()
        if (!lowered) return ""
        if (lowered === "control") return "ctrl"
        if (lowered === "option" || lowered === "opt") return "alt"
        if (lowered === "cmd" || lowered === "command" || lowered === "meta"
            || lowered === "win" || lowered === "windows") {
            return "super"
        }
        return lowered
    }

    function _displayKeyName(name) {
        var lowered = (name || "").trim().toLowerCase()
        if (!lowered) return ""
        if (lowered === "control") lowered = "ctrl"
        if (lowered === "option" || lowered === "opt") lowered = "alt"
        if (lowered === "cmd" || lowered === "command" || lowered === "meta"
            || lowered === "win" || lowered === "windows") {
            lowered = "super"
        }
        if (lowered.length === 1)
            return lowered.toUpperCase()
        return backend.displayShortcutKeyName(lowered)
    }

    function _validationErrorText(info) {
        var code = info && info.code ? info.code : "unsupported"
        var detail = info && info.detail ? info.detail : ""
        var template = s["key_capture.error." + code]
                       || s["key_capture.error.unsupported"]
                       || "Shortcut is not supported."
        return detail ? template.replace("%1", detail) : template.replace("%1", "")
    }

    function _comboFromEvent(event) {
        if (!event) return ""
        return backend.shortcutComboFromCaptureEvent(
                    event.key, event.modifiers, event.text)
    }

    function _isModifierKey(key) {
        return key === Qt.Key_Shift || key === Qt.Key_Control
                || key === Qt.Key_Alt || key === Qt.Key_AltGr
                || key === Qt.Key_Meta || key === Qt.Key_Super_L
                || key === Qt.Key_Super_R
    }

    // Live "Ctrl + Win + …" hint while only modifiers are held.
    function _refreshPending(modifiers) {
        _lastModifiers = modifiers
        var held = backend.shortcutComboFromCaptureEvent(0, modifiers, "")
        if (!held) {
            _hintArmed = true
            _pending = ""
            return
        }
        if (!_hintArmed) {
            _pending = ""
            return
        }
        var parts = held.split("+")
        var labels = []
        for (var i = 0; i < parts.length; i++)
            labels.push(dialog._displayKeyName(parts[i]))
        _pending = labels.join(" + ") + " + …"
    }

    function _acceptKey(event) {
        if (!event || event.isAutoRepeat)
            return
        // Typing mode leaves the field alone so shifted characters such as
        // "+" can be typed without Shift being recorded as the shortcut.
        if (!dialog.recording)
            return
        event.accepted = true
        if (dialog._isModifierKey(event.key)) {
            dialog._refreshPending(event.modifiers)
            return
        }
        var combo = dialog._comboFromEvent(event)
        if (!combo) {
            dialog._refreshPending(event.modifiers)
            return
        }
        dialog._hintArmed = false
        dialog._pending = ""
        shortcutField.text = combo
        dialog._validate(combo)
    }

    function _releaseKey(event) {
        if (!event || event.isAutoRepeat || !dialog.recording)
            return
        if (dialog._isModifierKey(event.key)) {
            event.accepted = true
            dialog._refreshPending(event.modifiers)
        }
    }

    Connections {
        target: backend
        function onSuperKeyHeldChanged() {
            if (dialog.visible && dialog.recording)
                dialog._refreshPending(dialog._lastModifiers)
        }
    }

    // Block clicks from reaching elements underneath
    MouseArea { anchors.fill: parent; onClicked: {} }

    Rectangle {
        width: 380
        height: col.implicitHeight + 48
        anchors.centerIn: parent
        radius: 16
        color: dialog.theme.bgCard
        border.width: 1
        border.color: dialog.theme.border

        Column {
            id: col
            anchors {
                left: parent.left; right: parent.right
                top: parent.top; margins: 24
            }
            spacing: 12

            Text {
                text: s["key_capture.title"]
                font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                color: dialog.theme.textPrimary
            }

            Text {
                text: s["key_capture.custom_label"] || "Ring label (optional)"
                font { family: uiState.fontFamily; pixelSize: 11 }
                color: dialog.theme.textSecondary
                visible: dialog.showCustomLabel
            }

            TextField {
                id: customLabelField
                width: parent.width
                visible: dialog.showCustomLabel
                placeholderText: s["key_capture.custom_label_placeholder"]
                                 || "e.g. ShareX screenshot"
                maximumLength: 40
                font { family: uiState.fontFamily; pixelSize: 13 }
                selectByMouse: true
                inputMethodHints: Qt.ImhNoPredictiveText
                Material.accent: dialog.theme.accent
            }

            TextField {
                id: shortcutField
                width: parent.width
                placeholderText: dialog.recording
                                 ? s["key_capture.placeholder_recording"]
                                 : s["key_capture.placeholder"]
                font { family: uiState.fontFamily; pixelSize: 13 }
                readOnly: dialog.recording
                selectByMouse: !dialog.recording
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                Material.accent: dialog.theme.accent
                Keys.priority: Keys.BeforeItem
                Keys.onPressed: function(event) { dialog._acceptKey(event) }
                Keys.onReleased: function(event) { dialog._releaseKey(event) }
                onTextChanged: dialog._validate(text)
            }

            Row {
                width: parent.width
                spacing: 8

                Text {
                    width: parent.width - modeButton.width - parent.spacing
                    text: dialog.recording ? s["key_capture.record_hint"]
                                           : s["key_capture.type_hint"]
                    wrapMode: Text.WordWrap
                    font { family: uiState.fontFamily; pixelSize: 11 }
                    color: dialog.theme.textDim
                }

                Rectangle {
                    id: modeButton
                    width: 104; height: 28; radius: 8
                    color: modeMa.containsMouse ? dialog.theme.bgSubtle
                                                : "transparent"
                    border.width: 1
                    border.color: dialog.theme.border

                    Text {
                        anchors.centerIn: parent
                        text: dialog.recording ? s["key_capture.mode_type"]
                                               : s["key_capture.mode_record"]
                        font { family: uiState.fontFamily; pixelSize: 11 }
                        color: dialog.theme.textSecondary
                    }

                    MouseArea {
                        id: modeMa; anchors.fill: parent
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (dialog.recording)
                                dialog.switchToTyping()
                            else
                                dialog.startRecording()
                        }
                    }
                }
            }

            Text {
                text: dialog._pending !== "" ? dialog._pending : dialog._preview
                width: parent.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                font { family: uiState.fontFamily; pixelSize: 12 }
                color: dialog._pending !== ""
                       ? dialog.theme.textSecondary
                       : (dialog._valid ? "#4caf50" : "#f44336")
                visible: dialog._pending !== "" || dialog._preview !== ""
            }

            Text {
                text: dialog._warning
                width: parent.width
                wrapMode: Text.WordWrap
                font { family: uiState.fontFamily; pixelSize: 11 }
                color: "#ffb74d"
                visible: dialog._warning !== ""
            }

            Text {
                text: s["key_capture.valid_keys"]
                font { family: uiState.fontFamily; pixelSize: 10 }
                color: dialog.theme.textDim
                lineHeight: 1.4
            }

            Row {
                anchors.right: parent.right
                spacing: 10

                Rectangle {
                    width: 80; height: 34; radius: 10
                    color: cancelMa.containsMouse ? dialog.theme.bgSubtle
                                                  : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: s["key_capture.cancel"]
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: dialog.theme.textSecondary
                    }
                    MouseArea {
                        id: cancelMa; anchors.fill: parent
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { dialog.cancelled(); dialog.close() }
                    }
                }

                Rectangle {
                    width: 90; height: 34; radius: 10
                    color: dialog._valid
                           ? (confirmMa.containsMouse ? dialog.theme.accent
                                                      : dialog.theme.accentDim)
                           : dialog.theme.bgSubtle
                    opacity: dialog._valid ? 1.0 : 0.5

                    Text {
                        anchors.centerIn: parent
                        text: s["key_capture.confirm"]
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                        color: dialog._valid ? dialog.theme.accent
                                             : dialog.theme.textDim
                    }

                    MouseArea {
                        id: confirmMa; anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: dialog._valid ? Qt.PointingHandCursor
                                                   : Qt.ArrowCursor
                        onClicked: {
                            if (!dialog._valid) return
                            dialog.captured(dialog._canonical)
                            dialog.close()
                        }
                    }
                }
            }
        }
    }
}
