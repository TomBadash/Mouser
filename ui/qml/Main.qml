import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

ApplicationWindow {
    id: root
    visible: !launchHidden
    width: 1060
    height: 700
    minimumWidth: 920
    minimumHeight: 620
    readonly property string versionLabel: "v" + appVersion
    title: backend.mouseConnected
           ? "Mouser " + versionLabel + " — " + backend.deviceDisplayName
           : "Mouser " + versionLabel

    property string appearanceMode: uiState.appearanceMode
    readonly property bool darkMode: appearanceMode === "dark"
                                    || (appearanceMode === "system"
                                        && uiState.systemDarkMode)
    readonly property var theme: Theme.palette(darkMode)
    readonly property string monoFontFamily: Qt.platform.os === "osx"
                                               ? "Menlo"
                                               : (Qt.platform.os === "windows"
                                                  ? "Consolas"
                                                  : "monospace")
    property int currentPage: 0
    property Item hoveredNavItem: null
    property string hoveredNavText: ""
    property string hoveredNavTipKey: ""
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

            Item {
                anchors {
                    fill: parent
                    topMargin: 20
                    bottomMargin: 16
                }

                Column {
                    anchors {
                        top: parent.top
                        left: parent.left
                        right: parent.right
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
                            { icon: "mouse-simple", tipKey: "nav.mouse_profiles", page: 0 },
                            { icon: "sliders-horizontal", tipKey: "nav.point_scroll", page: 1 }
                        ]

                        delegate: FocusScope {
                            id: navItem
                            width: sidebar.width
                            height: 56
                            activeFocusOnTab: true

                            Accessible.role: Accessible.Button
                            Accessible.name: lm.strings[modelData.tipKey] || modelData.tipKey
                            Accessible.description: "Open " + (lm.strings[modelData.tipKey] || modelData.tipKey)

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
                                        root.hoveredNavTipKey = modelData.tipKey
                                        root.hoveredNavText = lm.strings[modelData.tipKey] || modelData.tipKey
                                        root.hoveredNavCenterX = p.x
                                        root.hoveredNavCenterY = p.y
                                    } else if (root.hoveredNavItem === navItem) {
                                        root.hoveredNavItem = null
                                        root.hoveredNavTipKey = ""
                                        root.hoveredNavText = ""
                                    }
                                }
                            }
                        }
                    }
                }

                FocusScope {
                    id: aboutButton
                    anchors {
                        bottom: parent.bottom
                        horizontalCenter: parent.horizontalCenter
                    }
                    width: sidebar.width
                    height: 56
                    activeFocusOnTab: true

                    Accessible.role: Accessible.Button
                    Accessible.name: lm.strings["nav.about"] || "About"
                    Accessible.description: "Open " + (lm.strings["nav.about"] || "About")

                    Keys.onReturnPressed: aboutDialog.open()
                    Keys.onEnterPressed: aboutDialog.open()
                    Keys.onSpacePressed: aboutDialog.open()

                    Rectangle {
                        anchors.centerIn: parent
                        width: 46
                        height: 46
                        radius: 14
                        color: aboutMouse.containsMouse || aboutButton.activeFocus || aboutDialog.visible
                               ? Qt.rgba(1, 1, 1, root.darkMode ? 0.06 : 0.22)
                               : "transparent"

                        border.width: aboutButton.activeFocus ? 1 : 0
                        border.color: root.theme.accent

                        Behavior on color { ColorAnimation { duration: 150 } }

                        AppIcon {
                            anchors.centerIn: parent
                            width: 20
                            height: 20
                            name: "info"
                            iconColor: aboutMouse.containsMouse || aboutButton.activeFocus || aboutDialog.visible
                                       ? root.theme.textPrimary
                                       : root.theme.textSecondary
                        }
                    }

                    MouseArea {
                        id: aboutMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: aboutDialog.open()
                        onContainsMouseChanged: {
                            if (containsMouse) {
                                var p = aboutButton.mapToItem(overlayLayer, aboutButton.width, aboutButton.height / 2)
                                root.hoveredNavItem = aboutButton
                                root.hoveredNavTipKey = "nav.about"
                                root.hoveredNavText = lm.strings["nav.about"] || "About"
                                root.hoveredNavCenterX = p.x
                                root.hoveredNavCenterY = p.y
                            } else if (root.hoveredNavItem === aboutButton) {
                                root.hoveredNavItem = null
                                root.hoveredNavTipKey = ""
                                root.hoveredNavText = ""
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
                text: root.hoveredNavTipKey
                      ? (lm.strings[root.hoveredNavTipKey] || root.hoveredNavTipKey)
                      : root.hoveredNavText
                font {
                    family: uiState.fontFamily
                    pixelSize: 12
                }
                color: root.theme.tooltipText
            }
        }
    }

    Dialog {
        id: aboutDialog
        parent: Overlay.overlay
        modal: true
        focus: true
        title: ""
        width: 500
        height: 430
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        padding: 0

        background: Rectangle {
            radius: 24
            color: theme.bgElevated
            border.width: 1
            border.color: theme.border
        }

        contentItem: Item {
            width: aboutDialog.width
            height: aboutDialog.height

            Item {
                id: aboutHeader
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.topMargin: 16
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                height: 44

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12

                    Rectangle {
                        width: 36
                        height: 36
                        radius: 12
                        color: root.theme.accentDim

                        AppIcon {
                            anchors.centerIn: parent
                            width: 18
                            height: 18
                            name: "info"
                            iconColor: root.theme.accent
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3

                        Text {
                            text: lm.strings["about.title"] || "About Mouser"
                            font { family: uiState.fontFamily; pixelSize: 17; bold: true }
                            color: theme.textPrimary
                        }

                        Text {
                            text: lm.strings["about.subtitle"] || ""
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            color: theme.textSecondary
                        }
                    }
                }

                Rectangle {
                    width: 34
                    height: 34
                    radius: 12
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: closeAboutMouse.containsMouse
                           ? Qt.rgba(1, 1, 1, uiState.darkMode ? 0.08 : 0.65)
                           : "transparent"

                    AppIcon {
                        anchors.centerIn: parent
                        width: 14
                        height: 14
                        name: "x"
                        iconColor: theme.textSecondary
                    }

                    MouseArea {
                        id: closeAboutMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: aboutDialog.close()
                    }
                }
            }

            Column {
                anchors {
                    top: aboutHeader.bottom
                    topMargin: 20
                    left: parent.left
                    right: parent.right
                    leftMargin: 24
                    rightMargin: 24
                }
                spacing: 14

                Rectangle {
                    width: parent.width
                    height: versionHero.implicitHeight + 24
                    radius: 20
                    color: root.theme.accentDim
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, root.darkMode ? 0.0 : 0.04)

                    Column {
                        id: versionHero
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        Text {
                            text: lm.strings["about.version"] || "Version"
                            font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                            color: root.theme.textSecondary
                        }

                        Row {
                            spacing: 10

                            Text {
                                text: root.versionLabel
                                font { family: uiState.fontFamily; pixelSize: 28; bold: true }
                                color: root.theme.textPrimary
                            }

                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 999
                                color: Qt.rgba(1, 1, 1, root.darkMode ? 0.08 : 0.6)
                                border.width: 1
                                border.color: Qt.rgba(1, 1, 1, root.darkMode ? 0.05 : 0.18)
                                width: buildModeChipLabel.implicitWidth + 22
                                height: 30

                                Text {
                                    id: buildModeChipLabel
                                    anchors.centerIn: parent
                                    text: appBuildMode
                                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                    color: root.theme.textPrimary
                                }
                            }
                        }

                        Text {
                            text: (lm.strings["about.commit"] || "Commit") + ": " + appCommit
                            font { family: root.monoFontFamily; pixelSize: 12 }
                            color: root.theme.textSecondary
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: metadataColumn.implicitHeight + 2
                    radius: 18
                    color: theme.bgSubtle
                    border.width: 1
                    border.color: theme.border

                    Column {
                        id: metadataColumn
                        anchors.fill: parent
                        spacing: 0

                        Item {
                            width: parent.width
                            height: 64

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                width: 92
                                text: lm.strings["about.build_mode"] || "Build mode"
                                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                color: theme.textSecondary
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 126
                                anchors.right: parent.right
                                anchors.rightMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                text: appBuildMode
                                font { family: uiState.fontFamily; pixelSize: 14 }
                                color: theme.textPrimary
                            }
                        }

                        Rectangle {
                            width: parent.width - 36
                            height: 1
                            x: 18
                            color: theme.border
                            opacity: 0.9
                        }

                        Item {
                            width: parent.width
                            height: 64

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                width: 92
                                text: lm.strings["about.commit"] || "Commit"
                                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                color: theme.textSecondary
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 126
                                anchors.right: parent.right
                                anchors.rightMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                text: appCommit
                                font { family: root.monoFontFamily; pixelSize: 13 }
                                color: theme.textPrimary
                            }
                        }

                        Rectangle {
                            width: parent.width - 36
                            height: 1
                            x: 18
                            color: theme.border
                            opacity: 0.9
                        }

                        Item {
                            width: parent.width
                            height: launchPathValue.implicitHeight + 34

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.top: parent.top
                                anchors.topMargin: 18
                                width: 92
                                text: lm.strings["about.launch_path"] || "Launch path"
                                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                color: theme.textSecondary
                            }

                            Text {
                                id: launchPathValue
                                anchors.left: parent.left
                                anchors.leftMargin: 126
                                anchors.right: parent.right
                                anchors.rightMargin: 18
                                anchors.top: parent.top
                                anchors.topMargin: 18
                                text: appLaunchPath
                                wrapMode: Text.WrapAnywhere
                                font { family: root.monoFontFamily; pixelSize: 12 }
                                color: theme.textPrimary
                            }
                        }
                    }
                }
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
