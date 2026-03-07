import QtQuick
import "Theme.js" as Theme

/*  A single clickable hotspot dot placed over the mouse image.
    Position is given as normalised coordinates (0-1) within the
    source image, so it adapts when the image is scaled.

    An annotation label with a connecting line is drawn from the
    dot to an offset position.                                    */

Item {
    id: hotspot

    // ── Required properties ───────────────────────────────────
    required property Item imgItem        // the Image element
    required property real normX          // 0-1 x in source image
    required property real normY          // 0-1 y in source image
    required property string buttonKey    // config key (e.g. "middle")
    property bool isHScroll: false        // true for horizontal scroll dot

    property string label: ""
    property string sublabel: ""
    property string labelSide: "right"    // "left" or "right"
    property real labelOffX: 120          // x offset for annotation
    property real labelOffY: -30          // y offset for annotation

    // ── Computed centre ───────────────────────────────────────
    property real cx: imgItem.x + imgItem.offX + normX * imgItem.paintedWidth
    property real cy: imgItem.y + imgItem.offY + normY * imgItem.paintedHeight

    property bool isSelected: mousePage.selectedButton === buttonKey
    property bool isHovered: dotMa.containsMouse

    // ── Glow ring ─────────────────────────────────────────────
    Rectangle {
        id: glow
        x: cx - width / 2
        y: cy - height / 2
        width: 30; height: 30; radius: 15
        color: "transparent"
        border.width: isSelected ? 2 : 1
        border.color: isSelected ? Theme.accent : Qt.rgba(0, 0.83, 0.67, 0.3)
        opacity: isSelected || isHovered ? 1 : 0.6

        Behavior on opacity { NumberAnimation { duration: 200 } }
        Behavior on border.width { NumberAnimation { duration: 150 } }

        // Pulse animation when selected
        SequentialAnimation on scale {
            loops: Animation.Infinite
            running: isSelected
            NumberAnimation { from: 1.0; to: 1.25; duration: 800; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 1.25; to: 1.0; duration: 800; easing.type: Easing.InOutQuad }
        }
    }

    // ── Dot ───────────────────────────────────────────────────
    Rectangle {
        id: dot
        x: cx - width / 2
        y: cy - height / 2
        width: 16; height: 16; radius: 8
        color: isSelected ? Theme.accentHover : Theme.accent
        border.width: 2
        border.color: Qt.rgba(0, 0, 0, 0.3)

        scale: isHovered ? 1.2 : 1.0
        Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }
        Behavior on color { ColorAnimation { duration: 150 } }
    }

    // ── Click area (larger than the dot for easier targeting) ─
    MouseArea {
        id: dotMa
        x: cx - 18
        y: cy - 18
        width: 36; height: 36
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            if (isHScroll)
                mousePage.selectHScroll()
            else
                mousePage.selectButton(buttonKey)
        }
    }

    // ── Connecting line ───────────────────────────────────────
    Canvas {
        id: lineCanvas
        anchors.fill: parent
        z: -1
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = isSelected ? Theme.accent : Qt.rgba(0, 0.83, 0.67, 0.35)
            ctx.lineWidth = 1
            ctx.setLineDash([4, 3])
            ctx.beginPath()
            ctx.moveTo(cx, cy)
            ctx.lineTo(cx + labelOffX, cy + labelOffY)
            ctx.stroke()
        }

        // Repaint when position or selection changes
        Connections {
            target: hotspot
            function onCxChanged() { lineCanvas.requestPaint() }
            function onCyChanged() { lineCanvas.requestPaint() }
            function onIsSelectedChanged() { lineCanvas.requestPaint() }
        }
        Component.onCompleted: requestPaint()
    }

    // ── Annotation label ──────────────────────────────────────
    Rectangle {
        id: labelBg
        x: cx + labelOffX - (labelSide === "left" ? labelCol.width + 14 : -6)
        y: cy + labelOffY - 8
        width: labelCol.width + 20
        height: labelCol.height + 14
        radius: 8
        color: isSelected ? Qt.rgba(0, 0.83, 0.67, 0.12) : Qt.rgba(0, 0, 0, 0.35)
        border.width: isSelected ? 1 : 0
        border.color: Qt.rgba(0, 0.83, 0.67, 0.3)

        Behavior on color { ColorAnimation { duration: 200 } }

        Column {
            id: labelCol
            anchors {
                left: parent.left; leftMargin: 10
                verticalCenter: parent.verticalCenter
            }
            spacing: 1

            Text {
                text: hotspot.label
                font { family: Theme.fontFamily; pixelSize: 12; bold: true }
                color: isSelected ? Theme.accent : Theme.textPrimary
            }

            Text {
                text: hotspot.sublabel
                font { family: Theme.fontFamily; pixelSize: 10 }
                color: Theme.textSecondary
                visible: text !== ""
                width: Math.min(implicitWidth, 220)
                elide: Text.ElideRight
            }
        }

        // Make label clickable too
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (isHScroll)
                    mousePage.selectHScroll()
                else
                    mousePage.selectButton(buttonKey)
            }
        }
    }

    // ── Small dot at the end of the line ──────────────────────
    Rectangle {
        x: cx + labelOffX - 3
        y: cy + labelOffY - 3
        width: 6; height: 6; radius: 3
        color: isSelected ? Theme.accent : Qt.rgba(0, 0.83, 0.67, 0.5)
    }
}
