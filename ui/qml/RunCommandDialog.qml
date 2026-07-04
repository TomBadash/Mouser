import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme

/*  Modal dialog for configuring a "Run Command" action.
    Emits captured(commandText) with the raw command line, e.g.
    "notepad.exe" or "/usr/bin/firefox --new-window https://example.com".
    The command is later stored as "run:<commandText>" and launched with
    shell=False (argv split via shlex), never through a shell.            */

Rectangle {
    id: dialog
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    property string targetButton: ""
    property string targetProfile: ""
    property bool _valid: false
    property string _warning: ""

    signal captured(string commandText)
    signal cancelled()

    visible: false
    anchors.fill: parent
    color: "#80000000"
    z: 100

    function open(profile, button, currentActionId) {
        targetProfile = profile
        targetButton = button
        commandField.text = (currentActionId && currentActionId.indexOf("run:") === 0)
                             ? backend.runCommandTextFor(currentActionId)
                             : ""
        _validate(commandField.text)
        visible = true
        commandField.forceActiveFocus()
        commandField.selectAll()
    }

    function close() {
        visible = false
    }

    function _validate(text) {
        var info = backend.runCommandValidationErrorInfo(text)
        _valid = Object.keys(info).length === 0
        _warning = _valid ? "" : dialog._validationErrorText(info)
    }

    function _validationErrorText(info) {
        var code = info && info.code ? info.code : "empty"
        var detail = info && info.detail ? info.detail : ""
        var template = s["run_command.error." + code]
                       || s["run_command.error.empty"]
                       || "Enter a command to run."
        return detail ? template.replace("%1", detail) : template.replace("%1", "")
    }

    function _confirm() {
        if (!_valid) return
        dialog.captured(commandField.text.trim())
        dialog.close()
    }

    // Block clicks from reaching elements underneath
    MouseArea { anchors.fill: parent; onClicked: {} }

    Rectangle {
        width: 420
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
                text: s["run_command.title"] || "Run Command"
                font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                color: dialog.theme.textPrimary
            }

            Text {
                width: parent.width
                text: s["run_command.desc"]
                      || "Enter a command line to launch. It runs directly (no shell), so pipes and redirects are treated as plain text."
                wrapMode: Text.WordWrap
                font { family: uiState.fontFamily; pixelSize: 11 }
                color: dialog.theme.textSecondary
            }

            TextField {
                id: commandField
                width: parent.width
                placeholderText: s["run_command.placeholder"] || "e.g. notepad.exe"
                font { family: uiState.fontFamily; pixelSize: 13 }
                selectByMouse: true
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                Material.accent: dialog.theme.accent
                onTextChanged: dialog._validate(text)
                Keys.onReturnPressed: dialog._confirm()
                Keys.onEnterPressed: dialog._confirm()
            }

            Text {
                text: dialog._warning
                width: parent.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                font { family: uiState.fontFamily; pixelSize: 12 }
                color: "#f44336"
                visible: dialog._warning !== ""
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
                        text: s["run_command.cancel"] || "Cancel"
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
                        text: s["run_command.confirm"] || "Save"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                        color: dialog._valid ? dialog.theme.accent
                                             : dialog.theme.textDim
                    }

                    MouseArea {
                        id: confirmMa; anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: dialog._valid ? Qt.PointingHandCursor
                                                   : Qt.ArrowCursor
                        onClicked: dialog._confirm()
                    }
                }
            }
        }
    }
}
