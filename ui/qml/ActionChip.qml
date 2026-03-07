import QtQuick
import "Theme.js" as Theme

/*  A single action chip for the action picker.  */

Rectangle {
    id: chip

    property string actionId: ""
    property string actionLabel: ""
    property bool isCurrent: false

    signal picked(string aid)

    width: chipText.implicitWidth + 24
    height: 34
    radius: 8

    color: isCurrent
           ? Theme.accent
           : chipMa.containsMouse
             ? Theme.bgCardHover
             : Theme.bgCard
    border.width: 1
    border.color: isCurrent ? Theme.accent : Theme.border

    Behavior on color { ColorAnimation { duration: 120 } }

    Text {
        id: chipText
        anchors.centerIn: parent
        text: actionLabel
        font { family: Theme.fontFamily; pixelSize: 12 }
        color: isCurrent ? Theme.bgSidebar : Theme.textPrimary
    }

    MouseArea {
        id: chipMa
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.picked(actionId)
    }
}
