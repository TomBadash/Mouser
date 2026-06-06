import QtQuick
import "Theme.js" as Theme

/*  The Logitech Craft Crown dial, drawn as a clickable ring over the device
    photo. Clicking it opens a panel with the crown's sub-actions (rotate,
    click, touch, click+rotate) and the ratchet/smooth toggle.               */

Item {
    id: crownCtl
    readonly property var theme: Theme.palette(uiState.darkMode)

    required property var imgItem        // the Image element
    required property var crown          // {normX, normY, normR}
    property var crownButtons: []        // [{key,name,actionId,actionLabel}]

    // ── Geometry over the painted image ───────────────────────
    readonly property real ccx: imgItem.x + imgItem.offX + (crown.normX || 0) * imgItem.paintedWidth
    readonly property real ccy: imgItem.y + imgItem.offY + (crown.normY || 0) * imgItem.paintedHeight
    readonly property real cr: (crown.normR || 0.05) * imgItem.paintedWidth

    readonly property bool crownSelected: String(mousePage.selectedButton).indexOf("crown_") === 0
    property bool panelOpen: crownSelected

    // ── Crown ring ────────────────────────────────────────────
    Rectangle {
        id: ring
        x: ccx - cr; y: ccy - cr
        width: cr * 2; height: cr * 2
        radius: cr
        color: crownSelected ? Qt.rgba(0, 0.83, 0.67, 0.22) : Qt.rgba(0, 0.83, 0.67, 0.10)
        border.width: crownSelected ? 3 : 2
        border.color: crownSelected ? theme.accent : Qt.rgba(0, 0.83, 0.67, 0.7)
        Behavior on border.color { ColorAnimation { duration: 150 } }

        SequentialAnimation on scale {
            loops: Animation.Infinite
            running: crownSelected
            NumberAnimation { from: 1.0; to: 1.05; duration: 850; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 1.05; to: 1.0; duration: 850; easing.type: Easing.InOutQuad }
        }
    }

    MouseArea {
        x: ccx - cr; y: ccy - cr
        width: cr * 2; height: cr * 2
        cursorShape: Qt.PointingHandCursor
        onClicked: crownCtl.panelOpen = !crownCtl.panelOpen
    }

    // ── Crown actions panel ───────────────────────────────────
    Rectangle {
        id: panel
        visible: panelOpen
        z: 6
        width: 252
        height: panelCol.implicitHeight + 24
        radius: 14
        color: theme.bgCard
        border.width: 1
        border.color: theme.border
        // Open to the right of the dial, clamped inside the area.
        x: Math.max(8, Math.min(parent.width - width - 8, ccx + cr + 12))
        y: Math.max(8, Math.min(parent.height - height - 8, ccy - height / 2))

        Column {
            id: panelCol
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            spacing: 8

            Text {
                text: "Crown"
                font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                color: theme.textPrimary
            }

            // Ratchet / Smooth toggle
            Row {
                spacing: 8
                Text {
                    text: "Rotation"
                    anchors.verticalCenter: parent.verticalCenter
                    font { family: uiState.fontFamily; pixelSize: 11 }
                    color: theme.textSecondary
                }
                Repeater {
                    model: [{ lbl: "Ratchet", smooth: false }, { lbl: "Smooth", smooth: true }]
                    delegate: Rectangle {
                        required property var modelData
                        width: 72; height: 24; radius: 7
                        color: backend.crownSmooth === modelData.smooth ? theme.accent : "transparent"
                        border.width: 1
                        border.color: backend.crownSmooth === modelData.smooth ? theme.accent : theme.border
                        Text {
                            anchors.centerIn: parent
                            text: modelData.lbl
                            font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                            color: backend.crownSmooth === modelData.smooth ? theme.bgCard : theme.textSecondary
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.setCrownSmooth(modelData.smooth)
                        }
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: theme.border }

            // One row per crown sub-action.
            Repeater {
                model: crownButtons
                delegate: Rectangle {
                    required property var modelData
                    width: panelCol.width
                    height: 38
                    radius: 8
                    readonly property bool sel: mousePage.selectedButton === modelData.key
                    color: sel ? Qt.rgba(0, 0.83, 0.67, 0.14)
                                : (rowMa.containsMouse ? theme.bgHover : "transparent")
                    border.width: sel ? 1 : 0
                    border.color: Qt.rgba(0, 0.83, 0.67, 0.4)

                    Column {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 10 }
                        spacing: 1
                        Text {
                            text: { var _l = lm.strings; return lm.trButton(modelData.name) }
                            font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                            color: sel ? theme.accent : theme.textPrimary
                            elide: Text.ElideRight
                            width: parent.width
                        }
                        Text {
                            text: { var _l = lm.strings; return lm.trAction(modelData.actionLabel) }
                            font { family: uiState.fontFamily; pixelSize: 10 }
                            color: theme.textSecondary
                            elide: Text.ElideRight
                            width: parent.width
                        }
                    }

                    MouseArea {
                        id: rowMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: mousePage.selectButton(modelData.key)
                    }
                }
            }
        }
    }
}
