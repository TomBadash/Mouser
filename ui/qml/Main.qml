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
    minimumWidth: 920
    minimumHeight: 620
    title: backend.mouseConnected
           ? "Mouser — " + backend.deviceDisplayName
           : "Mouser"

    property string appearanceMode: uiState.appearanceMode
    readonly property bool darkMode: appearanceMode === "dark"
                                    || (appearanceMode === "system"
                                        && uiState.systemDarkMode)
    readonly property var theme: Theme.palette(darkMode)
    property int currentPage: 0
    property Item hoveredNavItem: null
    property string hoveredNavText: ""
    property real hoveredNavCenterX: 0
    property real hoveredNavCenterY: 0

    color: theme.bg

    Material.theme: darkMode ? Material.Dark : Material.Light
    Material.accent: theme.accent
    Material.background: theme.bg
    Material.foreground: theme.textPrimary

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: sidebar
            Layout.preferredWidth: 72
            Layout.fillHeight: true
            color: root.theme.bgSidebar

            Column {
                anchors {
                    fill: parent
                    topMargin: 20
                }
                spacing: 6

                Rectangle {
                    width: 44
                    height: 44
                    radius: 14
                    color: root.theme.accent
                    anchors.horizontalCenter: parent.horizontalCenter

                    Text {
                        anchors.centerIn: parent
                        text: "M"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 20
                            bold: true
                        }
                        color: root.theme.bgSidebar
                    }
                }

                Item { width: 1; height: 18 }

                Repeater {
                    model: [
                        { icon: "mouse-simple", tip: "Mouse & Profiles", page: 0 },
                        { icon: "sliders-horizontal", tip: "Point & Scroll", page: 1 }
                    ]

                    delegate: FocusScope {
                        id: navItem
                        width: sidebar.width
                        height: 56
                        activeFocusOnTab: true

                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.tip
                        Accessible.description: "Open " + modelData.tip

                        Keys.onReturnPressed: root.currentPage = modelData.page
                        Keys.onEnterPressed: root.currentPage = modelData.page
                        Keys.onSpacePressed: root.currentPage = modelData.page

                        Rectangle {
                            anchors.centerIn: parent
                            width: 46
                            height: 46
                            radius: 14
                            color: root.currentPage === modelData.page
                                   ? Qt.rgba(0, 0.83, 0.67, root.darkMode ? 0.14 : 0.16)
                                   : navMouse.containsMouse || navItem.activeFocus
                                     ? Qt.rgba(1, 1, 1, root.darkMode ? 0.06 : 0.22)
                                     : "transparent"

                            border.width: navItem.activeFocus ? 1 : 0
                            border.color: root.theme.accent

                            Behavior on color { ColorAnimation { duration: 150 } }

                            AppIcon {
                                anchors.centerIn: parent
                                width: 22
                                height: 22
                                name: modelData.icon
                                iconColor: root.currentPage === modelData.page
                                           ? root.theme.accent
                                           : navMouse.containsMouse || navItem.activeFocus
                                             ? root.theme.textPrimary
                                             : root.theme.textSecondary
                            }
                        }

                        Rectangle {
                            width: 3
                            height: 24
                            radius: 2
                            color: root.theme.accent
                            anchors {
                                left: parent.left
                                verticalCenter: parent.verticalCenter
                            }
                            visible: root.currentPage === modelData.page
                        }

                        MouseArea {
                            id: navMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.currentPage = modelData.page
                            onContainsMouseChanged: {
                                if (containsMouse) {
                                    var p = navItem.mapToItem(overlayLayer, navItem.width, navItem.height / 2)
                                    root.hoveredNavItem = navItem
                                    root.hoveredNavText = modelData.tip
                                    root.hoveredNavCenterX = p.x
                                    root.hoveredNavCenterY = p.y
                                } else if (root.hoveredNavItem === navItem) {
                                    root.hoveredNavItem = null
                                    root.hoveredNavText = ""
                                }
                            }
                        }
                    }
                }
            }
        }

        StackLayout {
            id: contentStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.currentPage

            MousePage {}
            Loader {
                active: root.currentPage === 1 || item
                source: "ScrollPage.qml"
            }
        }
    }

    Item {
        id: overlayLayer
        anchors.fill: parent
        z: 999

        Rectangle {
            id: navTooltip
            x: root.hoveredNavCenterX + 10
            y: Math.max(8, Math.min(root.height - height - 8, root.hoveredNavCenterY - height / 2))
            visible: root.hoveredNavItem !== null
            opacity: visible ? 1 : 0
            radius: 10
            color: root.theme.tooltipBg
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, root.darkMode ? 0.06 : 0.12)
            width: navTooltipText.implicitWidth + 22
            height: navTooltipText.implicitHeight + 14

            Behavior on opacity { NumberAnimation { duration: 120 } }

            Text {
                id: navTooltipText
                anchors.centerIn: parent
                text: root.hoveredNavText
                font {
                    family: uiState.fontFamily
                    pixelSize: 12
                }
                color: root.theme.tooltipText
            }
        }
    }

    Rectangle {
        id: toast
        anchors {
            bottom: parent.bottom
            horizontalCenter: parent.horizontalCenter
            bottomMargin: 24
        }
        width: toastText.implicitWidth + 32
        height: 38
        radius: 19
        color: root.theme.accent
        opacity: 0
        visible: opacity > 0

        Text {
            id: toastText
            anchors.centerIn: parent
            font {
                family: uiState.fontFamily
                pixelSize: 12
                bold: true
            }
            color: root.theme.bgSidebar
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

    onClosing: function(close) {
        close.accepted = false
        root.hide()
    }

    Connections {
        target: backend
        function onStatusMessage(msg) { toast.show(msg) }
    }
}
