import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: scrollPage
    readonly property var theme: Theme.palette(uiState.darkMode)
    readonly property var appearanceOptions: [
        { label: "System", value: "system" },
        { label: "Light", value: "light" },
        { label: "Dark", value: "dark" }
    ]
    readonly property var allDpiPresets: [400, 800, 1000, 1600, 2400, 4000, 6000, 8000]
    readonly property var dpiPresets: {
        var presets = []
        for (var i = 0; i < allDpiPresets.length; i++) {
            var preset = allDpiPresets[i]
            if (preset >= backend.deviceDpiMin && preset <= backend.deviceDpiMax)
                presets.push(preset)
        }
        return presets
    }

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        Column {
            id: mainCol
            width: pageScroll.availableWidth
            spacing: 0

            Item {
                width: parent.width
                height: 96

                Column {
                    anchors {
                        left: parent.left
                        leftMargin: 36
                        verticalCenter: parent.verticalCenter
                    }
                    spacing: 4

                    Text {
                        text: "Point & Scroll"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 24
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: "Adjust pointer speed, appearance, and scroll behaviour"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 13
                        }
                        color: scrollPage.theme.textSecondary
                    }
                }
            }

            Rectangle {
                width: parent.width - 72
                height: 1
                color: scrollPage.theme.border
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 24 }

            Rectangle {
                id: dpiCard
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: dpiContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: dpiContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: "Pointer Speed (DPI)"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: backend.deviceDpiMin === 200 && backend.deviceDpiMax === 8000
                              ? "Adjust the tracking speed of the sensor. Higher = faster pointer."
                              : "Adjust the tracking speed of the sensor. This device supports "
                                + backend.deviceDpiMin + " to " + backend.deviceDpiMax + " DPI."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    RowLayout {
                        width: parent.width
                        spacing: 12

                        Text {
                            text: backend.deviceDpiMin
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: scrollPage.theme.textDim
                        }

                        Slider {
                            id: dpiSlider
                            Layout.fillWidth: true
                            from: backend.deviceDpiMin
                            to: backend.deviceDpiMax
                            stepSize: 50
                            value: backend.dpi
                            Material.accent: scrollPage.theme.accent
                            Accessible.name: "Pointer speed"

                            onMoved: {
                                dpiLabel.text = Math.round(value) + " DPI"
                                dpiDebounce.restart()
                            }
                        }

                        Text {
                            text: backend.deviceDpiMax
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: scrollPage.theme.textDim
                        }

                        Rectangle {
                            Layout.preferredWidth: 104
                            Layout.preferredHeight: 36
                            radius: 10
                            color: scrollPage.theme.accentDim

                            Text {
                                id: dpiLabel
                                anchors.centerIn: parent
                                text: backend.dpi + " DPI"
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 14
                                    bold: true
                                }
                                color: scrollPage.theme.accent
                            }
                        }
                    }

                    Timer {
                        id: dpiDebounce
                        interval: 400
                        onTriggered: backend.setDpi(Math.round(dpiSlider.value))
                    }

                    Flow {
                        width: parent.width
                        spacing: 8

                        Text {
                            text: "Presets:"
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: scrollPage.theme.textDim
                        }

                        Repeater {
                            model: scrollPage.dpiPresets

                            delegate: Rectangle {
                                width: presetText.implicitWidth + 20
                                height: 30
                                radius: 8
                                color: dpiSlider.value === modelData
                                       ? scrollPage.theme.accent
                                       : presetMouse.containsMouse
                                         ? scrollPage.theme.bgCardHover
                                         : scrollPage.theme.bgSubtle
                                border.width: 1
                                border.color: scrollPage.theme.border

                                Accessible.role: Accessible.Button
                                Accessible.name: "Set DPI to " + modelData

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: presetText
                                    anchors.centerIn: parent
                                    text: modelData
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: dpiSlider.value === modelData
                                           ? scrollPage.theme.bgSidebar
                                           : scrollPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: presetMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        dpiSlider.value = modelData
                                        dpiLabel.text = modelData + " DPI"
                                        backend.setDpi(modelData)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: appearanceContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: appearanceContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: "Appearance"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: "Choose whether Mouser follows the system, stays light, or stays dark."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    Row {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: scrollPage.appearanceOptions

                            delegate: Rectangle {
                                required property var modelData
                                width: Math.max(96, optionText.implicitWidth + 28)
                                height: 38
                                radius: 10
                                color: backend.appearanceMode === modelData.value
                                       ? scrollPage.theme.accent
                                       : optionMouse.containsMouse
                                         ? scrollPage.theme.bgCardHover
                                         : scrollPage.theme.bgSubtle
                                border.width: 1
                                border.color: backend.appearanceMode === modelData.value
                                              ? scrollPage.theme.accent
                                              : scrollPage.theme.border

                                Accessible.role: Accessible.Button
                                Accessible.name: "Appearance " + modelData.label

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: optionText
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: backend.appearanceMode === modelData.value
                                    }
                                    color: backend.appearanceMode === modelData.value
                                           ? scrollPage.theme.bgSidebar
                                           : scrollPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: optionMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setAppearanceMode(modelData.value)
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: scrollContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: scrollContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: "Scroll Direction"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: "Invert the scroll direction (natural scrolling)"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: "Invert vertical scroll"
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: vscrollSwitch
                                checked: backend.invertVScroll
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: "Invert vertical scroll"
                                onToggled: backend.setInvertVScroll(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: "Invert horizontal scroll"
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: hscrollSwitch
                                checked: backend.invertHScroll
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: "Invert horizontal scroll"
                                onToggled: backend.setInvertHScroll(checked)
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: noteRow.implicitHeight + 28
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Row {
                    id: noteRow
                    anchors {
                        fill: parent
                        margins: 14
                    }
                    spacing: 10

                    AppIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18
                        height: 18
                        name: "warning"
                        iconColor: scrollPage.theme.warning
                    }

                    Text {
                        width: parent.width - 28
                        text: "DPI changes require HID++ communication with the device and will take effect after a short delay."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textDim
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Item { width: 1; height: 24 }
        }
    }

    Connections {
        target: backend
        function onDpiFromDevice(dpi) {
            if (!dpiSlider.pressed) {
                dpiSlider.value = dpi
                dpiLabel.text = dpi + " DPI"
            }
        }
        function onSettingsChanged() {
            if (!dpiSlider.pressed) {
                dpiSlider.value = backend.dpi
                dpiLabel.text = backend.dpi + " DPI"
            }
            vscrollSwitch.checked = backend.invertVScroll
            hscrollSwitch.checked = backend.invertHScroll
        }
    }
}
