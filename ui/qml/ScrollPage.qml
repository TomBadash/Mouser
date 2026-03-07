import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

/*  Point & Scroll settings page — DPI slider + scroll inversion.  */

Item {
    id: scrollPage

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        Flickable {
            contentHeight: mainCol.implicitHeight + 48
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: mainCol
                width: parent.width
                spacing: 0

                // ── Header ────────────────────────────────────
                Item {
                    width: parent.width; height: 90

                    Column {
                        anchors {
                            left: parent.left; leftMargin: 36
                            verticalCenter: parent.verticalCenter
                        }
                        spacing: 4

                        Text {
                            text: "Point & Scroll"
                            font { family: Theme.fontFamily; pixelSize: 24; bold: true }
                            color: Theme.textPrimary
                        }
                        Text {
                            text: "Adjust pointer speed and scroll behaviour"
                            font { family: Theme.fontFamily; pixelSize: 13 }
                            color: Theme.textSecondary
                        }
                    }
                }

                Rectangle {
                    width: parent.width - 72; height: 1
                    color: Theme.border
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Item { width: 1; height: 24 }

                // ── DPI Card ──────────────────────────────────
                Rectangle {
                    id: dpiCard
                    width: parent.width - 72
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: dpiContent.implicitHeight + 40
                    radius: Theme.radius
                    color: Theme.bgCard
                    border.width: 1; border.color: Theme.border

                    Column {
                        id: dpiContent
                        anchors {
                            left: parent.left; right: parent.right
                            top: parent.top; margins: 20
                        }
                        spacing: 12

                        Text {
                            text: "Pointer Speed (DPI)"
                            font { family: Theme.fontFamily; pixelSize: 16; bold: true }
                            color: Theme.textPrimary
                        }
                        Text {
                            text: "Adjust the tracking speed of the sensor. Higher = faster pointer."
                            font { family: Theme.fontFamily; pixelSize: 12 }
                            color: Theme.textSecondary
                        }

                        // Slider row
                        RowLayout {
                            width: parent.width
                            spacing: 12

                            Text {
                                text: "200"
                                font { family: Theme.fontFamily; pixelSize: 11 }
                                color: Theme.textDim
                            }

                            Slider {
                                id: dpiSlider
                                Layout.fillWidth: true
                                from: 200; to: 8000; stepSize: 50
                                value: backend.dpi
                                Material.accent: Theme.accent

                                onMoved: {
                                    dpiLabel.text = Math.round(value) + " DPI"
                                    dpiDebounce.restart()
                                }
                            }

                            Text {
                                text: "8000"
                                font { family: Theme.fontFamily; pixelSize: 11 }
                                color: Theme.textDim
                            }

                            Rectangle {
                                width: 100; height: 36
                                radius: 8
                                color: Theme.accentDim

                                Text {
                                    id: dpiLabel
                                    anchors.centerIn: parent
                                    text: backend.dpi + " DPI"
                                    font { family: Theme.fontFamily; pixelSize: 14; bold: true }
                                    color: Theme.accent
                                }
                            }
                        }

                        Timer {
                            id: dpiDebounce
                            interval: 400
                            onTriggered: backend.setDpi(Math.round(dpiSlider.value))
                        }

                        // DPI quick presets
                        Row {
                            spacing: 8

                            Text {
                                text: "Presets:"
                                font { family: Theme.fontFamily; pixelSize: 11 }
                                color: Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Repeater {
                                model: [400, 800, 1000, 1600, 2400, 4000, 6000, 8000]

                                delegate: Rectangle {
                                    width: presetText.implicitWidth + 20
                                    height: 30; radius: 8
                                    color: dpiSlider.value === modelData
                                           ? Theme.accent
                                           : presetMa.containsMouse
                                             ? Theme.bgCardHover
                                             : Theme.bgSidebar
                                    border.width: 1
                                    border.color: Theme.border

                                    Behavior on color { ColorAnimation { duration: 120 } }

                                    Text {
                                        id: presetText
                                        anchors.centerIn: parent
                                        text: modelData
                                        font { family: Theme.fontFamily; pixelSize: 12 }
                                        color: dpiSlider.value === modelData
                                               ? Theme.bgSidebar
                                               : Theme.textPrimary
                                    }

                                    MouseArea {
                                        id: presetMa
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

                // ── Scroll Direction Card ─────────────────────
                Rectangle {
                    width: parent.width - 72
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: scrollContent.implicitHeight + 40
                    radius: Theme.radius
                    color: Theme.bgCard
                    border.width: 1; border.color: Theme.border

                    Column {
                        id: scrollContent
                        anchors {
                            left: parent.left; right: parent.right
                            top: parent.top; margins: 20
                        }
                        spacing: 12

                        Text {
                            text: "Scroll Direction"
                            font { family: Theme.fontFamily; pixelSize: 16; bold: true }
                            color: Theme.textPrimary
                        }
                        Text {
                            text: "Invert the scroll direction (natural scrolling)"
                            font { family: Theme.fontFamily; pixelSize: 12 }
                            color: Theme.textSecondary
                        }

                        // Vertical scroll toggle
                        Rectangle {
                            width: parent.width
                            height: 52; radius: 8
                            color: Theme.bgSidebar

                            RowLayout {
                                anchors {
                                    fill: parent
                                    leftMargin: 16; rightMargin: 16
                                }

                                Text {
                                    text: "Invert vertical scroll"
                                    font { family: Theme.fontFamily; pixelSize: 13 }
                                    color: Theme.textPrimary
                                    Layout.fillWidth: true
                                }

                                Switch {
                                    id: vscrollSwitch
                                    checked: backend.invertVScroll
                                    Material.accent: Theme.accent
                                    onToggled: backend.setInvertVScroll(checked)
                                }
                            }
                        }

                        // Horizontal scroll toggle
                        Rectangle {
                            width: parent.width
                            height: 52; radius: 8
                            color: Theme.bgSidebar

                            RowLayout {
                                anchors {
                                    fill: parent
                                    leftMargin: 16; rightMargin: 16
                                }

                                Text {
                                    text: "Invert horizontal scroll"
                                    font { family: Theme.fontFamily; pixelSize: 13 }
                                    color: Theme.textPrimary
                                    Layout.fillWidth: true
                                }

                                Switch {
                                    id: hscrollSwitch
                                    checked: backend.invertHScroll
                                    Material.accent: Theme.accent
                                    onToggled: backend.setInvertHScroll(checked)
                                }
                            }
                        }
                    }
                }

                Item { width: 1; height: 16 }

                // ── Info note ─────────────────────────────────
                Rectangle {
                    width: parent.width - 72
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: noteText.implicitHeight + 28
                    radius: Theme.radius
                    color: Theme.bgCard
                    border.width: 1; border.color: Theme.border

                    Text {
                        id: noteText
                        anchors {
                            fill: parent; margins: 14
                        }
                        text: "Note: DPI changes require HID++ communication with "
                              + "the device and will take effect after a short delay."
                        font { family: Theme.fontFamily; pixelSize: 12 }
                        color: Theme.textDim
                        wrapMode: Text.WordWrap
                    }
                }

                Item { width: 1; height: 24 }
            }
        }
    }

    // ── Backend → slider sync ─────────────────────────────────
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
