import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

ApplicationWindow {
    id: root
    visible: true
    width: 1060
    height: 700
    minimumWidth: 900
    minimumHeight: 600
    title: "LogiControl — MX Master 3S"
    color: Theme.bg

    Material.theme: Material.Dark
    Material.accent: Theme.accent

    // ── Navigation state ──────────────────────────────────────
    property int currentPage: 0

    Row {
        anchors.fill: parent

        // ── Sidebar ───────────────────────────────────────────
        Rectangle {
            id: sidebar
            width: 64
            height: parent.height
            color: Theme.bgSidebar

            Column {
                anchors.fill: parent
                anchors.topMargin: 20
                spacing: 4

                // Brand logo
                Rectangle {
                    width: 42; height: 42
                    radius: 12
                    color: Theme.accent
                    anchors.horizontalCenter: parent.horizontalCenter

                    Text {
                        anchors.centerIn: parent
                        text: "M"
                        font { family: Theme.fontFamily; pixelSize: 20; bold: true }
                        color: Theme.bgSidebar
                    }
                }

                Item { width: 1; height: 20 }

                // Nav items
                Repeater {
                    model: [
                        { label: "🖱", tip: "Mouse & Profiles", page: 0 },
                        { label: "⚙",  tip: "Point & Scroll",  page: 1 }
                    ]
                    delegate: Item {
                        width: sidebar.width
                        height: 52

                        Rectangle {
                            anchors.centerIn: parent
                            width: 44; height: 44
                            radius: 12
                            color: currentPage === modelData.page
                                   ? Qt.rgba(0, 0.83, 0.67, 0.12)
                                   : navMa.containsMouse
                                     ? Qt.rgba(1, 1, 1, 0.05)
                                     : "transparent"
                            Behavior on color { ColorAnimation { duration: 150 } }

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.pixelSize: 20
                            }
                        }

                        // Active indicator bar
                        Rectangle {
                            width: 3; height: 24; radius: 2
                            color: Theme.accent
                            anchors {
                                left: parent.left
                                verticalCenter: parent.verticalCenter
                            }
                            visible: currentPage === modelData.page
                        }

                        MouseArea {
                            id: navMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: currentPage = modelData.page
                        }

                        ToolTip {
                            visible: navMa.containsMouse
                            text: modelData.tip
                            delay: 500
                        }
                    }
                }
            }
        }

        // ── Content Area ──────────────────────────────────────
        StackLayout {
            id: contentStack
            width: parent.width - sidebar.width
            height: parent.height
            currentIndex: currentPage

            MousePage {}
            ScrollPage {}
        }
    }

    // ── Status toast ──────────────────────────────────────────
    Rectangle {
        id: toast
        anchors {
            bottom: parent.bottom
            horizontalCenter: parent.horizontalCenter
            bottomMargin: 24
        }
        width: toastText.implicitWidth + 32
        height: 36
        radius: 18
        color: Theme.accent
        opacity: 0
        visible: opacity > 0

        Text {
            id: toastText
            anchors.centerIn: parent
            font { family: Theme.fontFamily; pixelSize: 12; bold: true }
            color: Theme.bgSidebar
        }

        Behavior on opacity { NumberAnimation { duration: 200 } }

        function show(msg) {
            toastText.text = msg
            toast.opacity = 1
            toastTimer.restart()
        }

        Timer {
            id: toastTimer
            interval: 2000
            onTriggered: toast.opacity = 0
        }
    }

    // ── Close to tray ─────────────────────────────────────────
    onClosing: function(close) {
        close.accepted = false
        root.hide()
    }

    // ── Backend connections ────────────────────────────────────
    Connections {
        target: backend
        function onStatusMessage(msg) { toast.show(msg) }
    }
}
