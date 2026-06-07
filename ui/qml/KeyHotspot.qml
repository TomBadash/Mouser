import QtQuick
import "Theme.js" as Theme

/*  A clickable keyboard key region placed over the device photo.
    Position and size are normalized (0-1) within the source image, so the
    overlay tracks the image as it scales. The assigned action is shown on the
    key; the function name appears on hover/selection.                       */

Item {
    id: keyspot
    readonly property var theme: Theme.palette(uiState.darkMode)

    // ── Required properties ───────────────────────────────────
    required property var imgItem         // the Image element
    required property real normX          // 0-1 center x in source image
    required property real normY          // 0-1 center y in source image
    property real normW: 0.030            // 0-1 width
    property real normH: 0.075            // 0-1 height
    required property string buttonKey    // config key (e.g. "kbd_volume_up")
    property string label: ""             // function name ("Volume Up")

    // ── Derived state ─────────────────────────────────────────
    readonly property string actionId: devicePage.actionFor_id(buttonKey)
    readonly property bool mapped: actionId !== "none"
    readonly property string actionLabel: devicePage.actionFor(buttonKey)
    readonly property bool isSelected: devicePage.selectedButton === buttonKey
    readonly property bool isHovered: keyMa.containsMouse

    // ── Geometry over the painted image ───────────────────────
    readonly property real rx: imgItem.x + imgItem.offX + (normX - normW / 2) * imgItem.paintedWidth
    readonly property real ry: imgItem.y + imgItem.offY + (normY - normH / 2) * imgItem.paintedHeight
    readonly property real rw: normW * imgItem.paintedWidth
    readonly property real rh: normH * imgItem.paintedHeight

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: label

    function triggerSelection() { devicePage.selectButton(buttonKey) }
    Keys.onReturnPressed: triggerSelection()
    Keys.onEnterPressed: triggerSelection()
    Keys.onSpacePressed: triggerSelection()

    // ── Key highlight rectangle ───────────────────────────────
    Rectangle {
        id: keyRect
        x: rx; y: ry; width: rw; height: rh
        radius: Math.min(rw, rh) * 0.28
        color: isSelected ? Qt.rgba(0, 0.83, 0.67, 0.30)
                          : mapped ? Qt.rgba(0, 0.83, 0.67, 0.16)
                                   : (isHovered ? Qt.rgba(1, 1, 1, 0.10) : "transparent")
        border.width: isSelected || keyspot.activeFocus ? 2 : (mapped || isHovered ? 1.5 : 1)
        border.color: isSelected || keyspot.activeFocus
                      ? theme.accent
                      : mapped ? Qt.rgba(0, 0.83, 0.67, 0.85)
                               : Qt.rgba(0, 0.83, 0.67, 0.35)
        Behavior on color { ColorAnimation { duration: 150 } }
        Behavior on border.color { ColorAnimation { duration: 150 } }

        SequentialAnimation on scale {
            loops: Animation.Infinite
            running: isSelected
            NumberAnimation { from: 1.0; to: 1.06; duration: 800; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 1.06; to: 1.0; duration: 800; easing.type: Easing.InOutQuad }
        }
    }

    // ── Mapped indicator: small accent dot (no permanent text) ─
    Rectangle {
        visible: mapped && !isSelected && !isHovered
        z: 3
        width: Math.max(6, rw * 0.16); height: width; radius: width / 2
        x: rx + rw - width - 2
        y: ry + 2
        color: theme.accent
    }

    // ── Detail label on hover/selection only (function + action) ─
    Rectangle {
        id: badge
        visible: isSelected || isHovered
        z: 20
        width: badgeCol.implicitWidth + 16
        height: badgeCol.implicitHeight + 8
        radius: 7
        x: Math.max(2, Math.min((parent ? parent.width : rx + rw) - width - 2,
                                rx + rw / 2 - width / 2))
        y: ry + rh + 6
        color: uiState.darkMode ? Qt.rgba(0.10, 0.12, 0.12, 0.97)
                                : Qt.rgba(1, 1, 1, 0.98)
        border.width: 1
        border.color: isSelected ? theme.accent : theme.border

        Column {
            id: badgeCol
            anchors.centerIn: parent
            spacing: 1
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: { var _l = lm.strings; return lm.trButton(label) }
                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                color: isSelected ? theme.accent : theme.textPrimary
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                // actionLabel already resolves to "Do Nothing" when unmapped.
                text: { var _l = lm.strings; return actionLabel }
                font { family: uiState.fontFamily; pixelSize: 10 }
                color: theme.textSecondary
            }
        }
    }

    MouseArea {
        id: keyMa
        x: rx; y: ry; width: rw; height: rh
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: keyspot.triggerSelection()
    }
}
