import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: hapticPage
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    readonly property var hapticLevels: [
        { label: s["haptic.level_subtle"]  || "Subtle", value: 0 },
        { label: s["haptic.level_low"]     || "Low",    value: 1 },
        { label: s["haptic.level_medium"]  || "Medium", value: 2 },
        { label: s["haptic.level_high"]    || "High",   value: 3 }
    ]

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        Column {
            id: mainCol
            width: pageScroll.availableWidth
            spacing: 0

            // ── Header ──────────────────────────────────────────────
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
                        text: s["haptic.title"] || "Haptic Feedback"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 24
                            bold: true
                        }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.subtitle"] || "Configure the haptic motor in your MX Master 4"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 13
                        }
                        color: hapticPage.theme.textSecondary
                    }
                }
            }

            Rectangle {
                width: parent.width - 72
                height: 1
                color: hapticPage.theme.border
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 20 }

            // ── Feedback Intensity Card ──────────────────────────────
            Rectangle {
                id: levelCard
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: levelContent.implicitHeight + 40
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: levelContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["haptic.level"] || "Feedback Intensity"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.level_desc"] || "Choose how strongly the haptic motor responds. Higher levels use more battery."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Flow {
                        width: parent.width
                        spacing: 8

                        Repeater {
                            model: hapticPage.hapticLevels

                            delegate: Rectangle {
                                required property int index
                                readonly property var levelData: hapticPage.hapticLevels[index]
                                readonly property bool isCurrent: backend.hapticLevel === levelData.value
                                width: levelLabel.implicitWidth + 32
                                height: 36
                                radius: 10
                                color: isCurrent
                                       ? hapticPage.theme.accent
                                       : levelMa.containsMouse
                                         ? hapticPage.theme.bgCardHover
                                         : hapticPage.theme.bgElevated
                                border.width: 1
                                border.color: isCurrent
                                              ? hapticPage.theme.accent
                                              : hapticPage.theme.border

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: levelLabel
                                    anchors.centerIn: parent
                                    text: levelData.label
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 13
                                        bold: isCurrent
                                    }
                                    color: isCurrent
                                           ? hapticPage.theme.bgSidebar
                                           : hapticPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: levelMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setHapticLevel(levelData.value)
                                }

                                Accessible.role: Accessible.Button
                                Accessible.name: levelData.label
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Test Button Card ─────────────────────────────────────
            Rectangle {
                id: testCard
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: testContent.implicitHeight + 40
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: testContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["haptic.test_title"] || "Test Haptic"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.test_desc"] || "Play a brief haptic pulse to preview the current intensity."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: testBtnLabel.implicitWidth + 32
                        height: 38
                        radius: 10
                        color: testBtnMa.containsMouse
                               ? hapticPage.theme.accentHover
                               : hapticPage.theme.accent

                        Behavior on color { ColorAnimation { duration: 120 } }

                        Text {
                            id: testBtnLabel
                            anchors.centerIn: parent
                            text: s["haptic.test"] || "Test"
                            font {
                                family: uiState.fontFamily
                                pixelSize: 14
                                bold: true
                            }
                            color: hapticPage.theme.bgSidebar
                        }

                        MouseArea {
                            id: testBtnMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.playHapticTest()
                        }

                        Accessible.role: Accessible.Button
                        Accessible.name: s["haptic.test"] || "Test"
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Experimental Note ────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: noteContent.implicitHeight + 24
                radius: Theme.radius
                color: hapticPage.theme.bgSubtle
                border.width: 1
                border.color: hapticPage.theme.border

                Row {
                    id: noteContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 14
                    }
                    spacing: 8

                    Text {
                        text: s["haptic.experimental_note"]
                              || "Haptic feedback support is experimental. Some settings may not take effect until the protocol is fully documented."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width - 28
                    }
                }
            }

            Item { width: 1; height: 32 }
        }
    }
}
