import QtQuick

Item {
    id: root

    property real from: 0
    property real to: 1
    property real stepSize: 0
    property real value: from
    property color accentColor: "#00d4aa"
    property color accentDimColor: "#0d2e26"
    property color trackColor: "#263246"
    readonly property bool pressed: dragArea.pressed
    readonly property real normalizedPosition: {
        var span = to - from
        if (span <= 0)
            return 0
        return Math.max(0, Math.min(1, (value - from) / span))
    }

    signal moved()

    implicitHeight: 28
    implicitWidth: 240

    function clamp(v) {
        return Math.max(from, Math.min(to, v))
    }

    function snap(v) {
        if (stepSize <= 0)
            return clamp(v)
        return clamp(from + Math.round((v - from) / stepSize) * stepSize)
    }

    function setFromPointer(xPos) {
        var widthSpan = Math.max(1, groove.width)
        var ratio = Math.max(0, Math.min(1, xPos / widthSpan))
        var nextValue = snap(from + ratio * (to - from))
        if (nextValue === value)
            return
        value = nextValue
        moved()
    }

    Rectangle {
        id: groove
        anchors {
            left: parent.left
            right: parent.right
            verticalCenter: parent.verticalCenter
        }
        height: 6
        radius: 3
        color: root.trackColor
    }

    Rectangle {
        anchors {
            left: groove.left
            verticalCenter: groove.verticalCenter
        }
        width: handle.x + handle.width / 2
        height: groove.height
        radius: groove.radius
        color: root.accentColor
    }

    Rectangle {
        id: handle
        width: 18
        height: 18
        radius: 9
        color: dragArea.pressed ? root.accentColor : root.accentDimColor
        border.width: 2
        border.color: root.accentColor
        x: Math.max(0, Math.min(groove.width - width, root.normalizedPosition * groove.width - width / 2))
        anchors.verticalCenter: groove.verticalCenter
    }

    MouseArea {
        id: dragArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        preventStealing: true
        scrollGestureEnabled: false
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.PointingHandCursor

        onWheel: function(wheel) {
            wheel.accepted = false
        }

        onPressed: function(mouse) {
            root.setFromPointer(mouse.x)
        }

        onPositionChanged: function(mouse) {
            if (pressed)
                root.setFromPointer(mouse.x)
        }
    }
}
