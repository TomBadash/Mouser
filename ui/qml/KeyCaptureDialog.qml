import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme

/*  Modal dialog for capturing a custom keyboard shortcut.
    Emits captured(comboString) with e.g. "ctrl+shift+f5".  */

Rectangle {
    id: dialog
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    property string targetButton: ""
    property string targetProfile: ""
    property bool _valid: false
    property string _preview: ""

    signal captured(string comboString)
    signal cancelled()

    visible: false
    anchors.fill: parent
    color: "#80000000"
    z: 100

    function open(profile, button) {
        targetProfile = profile
        targetButton = button
        shortcutField.text = ""
        _valid = false
        _preview = ""
        visible = true
        shortcutField.forceActiveFocus()
    }

    function close() {
        visible = false
    }

    function _validate(text) {
        if (!text || !text.trim()) {
            _valid = false
            _preview = ""
            return
        }
        var modifiers = ["ctrl", "shift", "alt", "super"]
        var parts = text.split("+")
        var validNames = backend.validKeyNames
        var validSet = {}
        for (var i = 0; i < validNames.length; i++)
            validSet[validNames[i]] = true
        var labels = []
        var seen = {}
        var hasNonModifier = false
        for (var j = 0; j < parts.length; j++) {
            var name = parts[j].trim().toLowerCase()
            if (!name) {
                _valid = false
                _preview = "\u2718 Empty key segment"
                return
            }
            if (!validSet[name]) {
                _valid = false
                _preview = "\u2718 Unknown key: " + parts[j].trim()
                return
            }
            if (seen[name]) {
                _valid = false
                _preview = "\u2718 Duplicate key: " + name
                return
            }
            seen[name] = true
            if (modifiers.indexOf(name) < 0) hasNonModifier = true
            labels.push(dialog._displayKeyName(name))
        }
        if (!hasNonModifier) {
            _valid = false
            _preview = "\u2718 Need at least one non-modifier key"
            return
        }
        _valid = true
        _preview = "\u2714 " + labels.join(" + ")
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
        if (lowered === "super")
            return "Super"
        if (lowered === "alt")
            return Qt.platform.os === "osx" ? "Opt" : "Alt"
        if (lowered === "ctrl")
            return "Ctrl"
        if (lowered === "shift")
            return "Shift"
        if (lowered.length === 1)
            return lowered.toUpperCase()
        return lowered.charAt(0).toUpperCase() + lowered.slice(1)
    }

    function _comboFromEvent(event) {
        if (!event) return ""
        return backend.shortcutComboFromQtEvent(event.key, event.modifiers, event.text)
    }

    function _acceptKey(event) {
        if (!event || event.isAutoRepeat)
            return
        var combo = _comboFromEvent(event)
        if (!combo)
            return
        if (combo === "enter")
            return
        shortcutField.text = combo
        _validate(combo)
        event.accepted = true
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

            TextField {
                id: shortcutField
                width: parent.width
                placeholderText: s["key_capture.placeholder"]
                font { family: uiState.fontFamily; pixelSize: 13 }
                readOnly: true
                selectByMouse: false
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                Material.accent: dialog.theme.accent
                Keys.priority: Keys.BeforeItem
                Keys.onPressed: function(event) { dialog._acceptKey(event) }
                Keys.onEscapePressed: { dialog.cancelled(); dialog.close() }
                Keys.onReturnPressed: {
                    if (dialog._valid) {
                        var normalized = shortcutField.text.split("+").map(
                            function(p) { return dialog._canonicalKeyName(p) }
                        ).join("+")
                        dialog.captured(normalized)
                        dialog.close()
                    }
                }
            }

            Text {
                text: dialog._preview
                font { family: uiState.fontFamily; pixelSize: 12 }
                color: dialog._valid ? "#4caf50" : "#f44336"
                visible: dialog._preview !== ""
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
                            var normalized = shortcutField.text.split("+").map(
                                function(p) { return p.trim().toLowerCase() }
                            ).join("+")
                            dialog.captured(normalized)
                            dialog.close()
                        }
                    }
                }
            }
        }
    }
}
