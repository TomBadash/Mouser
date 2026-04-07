import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme

/*  Modal dialog for entering a custom keyboard shortcut as text.
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
            labels.push(name.charAt(0).toUpperCase() + name.slice(1))
        }
        if (!hasNonModifier) {
            _valid = false
            _preview = "\u2718 Need at least one non-modifier key"
            return
        }
        _valid = true
        _preview = "\u2714 " + labels.join(" + ")
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
                Material.accent: dialog.theme.accent
                onTextChanged: dialog._validate(text)
                Keys.onEscapePressed: { dialog.cancelled(); dialog.close() }
                Keys.onReturnPressed: {
                    if (dialog._valid) {
                        var normalized = text.split("+").map(
                            function(p) { return p.trim().toLowerCase() }
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
