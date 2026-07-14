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

            // ── Enable / Disable Toggle Card ─────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: 56
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Row {
                    anchors {
                        left: parent.left
                        right: parent.right
                        verticalCenter: parent.verticalCenter
                        leftMargin: 20
                        rightMargin: 20
                    }

                    Text {
                        text: s["haptic.enabled"] || "Enable Haptic Feedback"
                        font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                        color: hapticPage.theme.textPrimary
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - hapticEnableSwitch.width
                    }

                    Switch {
                        id: hapticEnableSwitch
                        checked: backend.hapticEnabled
                        anchors.verticalCenter: parent.verticalCenter
                        onToggled: backend.setHapticEnabled(checked)
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Feedback Intensity Card ──────────────────────────────
            Rectangle {
                id: levelCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
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
                                    hoverEnabled: backend.hapticEnabled
                                    enabled: backend.hapticEnabled
                                    cursorShape: backend.hapticEnabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: backend.setHapticLevel(levelData.value)
                                }

                                Accessible.role: Accessible.Button
                                Accessible.name: levelData.label
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16; visible: backend.forceSensingSupported }

            // ── Gesture Button Sensitivity Card ─────────────────────
            Rectangle {
                id: forceSensingCard
                visible: backend.forceSensingSupported
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: forceSensingContent.implicitHeight + 40
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                readonly property var forcePresets: {
                    var lo = backend.forceSensingMin
                    var hi = backend.forceSensingMax
                    return [
                        { label: s["haptic.force_light"] || "Light",  value: Math.round(lo + (hi - lo) * 0.00) },
                        { label: s["haptic.force_low"]   || "Low",    value: Math.round(lo + (hi - lo) * 0.33) },
                        { label: s["haptic.force_medium"]|| "Medium", value: Math.round(lo + (hi - lo) * 0.66) },
                        { label: s["haptic.force_firm"]  || "Firm",   value: Math.round(lo + (hi - lo) * 1.00) }
                    ]
                }

                readonly property int nearestPresetIndex: {
                    var val = backend.forceSensitivity
                    var best = 0
                    var bestDist = Math.abs(val - forcePresets[0].value)
                    for (var i = 1; i < forcePresets.length; i++) {
                        var d = Math.abs(val - forcePresets[i].value)
                        if (d < bestDist) { bestDist = d; best = i }
                    }
                    return best
                }

                Column {
                    id: forceSensingContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["haptic.force_title"] || "Gesture Button Sensitivity"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.force_desc"] || "Adjust how hard you need to press the gesture button to activate it."
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
                            model: forceSensingCard.forcePresets

                            delegate: Rectangle {
                                required property int index
                                readonly property var presetData: forceSensingCard.forcePresets[index]
                                readonly property bool isCurrent: index === forceSensingCard.nearestPresetIndex
                                width: forcePresetLabel.implicitWidth + 32
                                height: 36
                                radius: 10
                                color: isCurrent
                                       ? hapticPage.theme.accent
                                       : forcePresetMa.containsMouse
                                         ? hapticPage.theme.bgCardHover
                                         : hapticPage.theme.bgElevated
                                border.width: 1
                                border.color: isCurrent
                                              ? hapticPage.theme.accent
                                              : hapticPage.theme.border

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: forcePresetLabel
                                    anchors.centerIn: parent
                                    text: presetData.label
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
                                    id: forcePresetMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setForceSensitivity(presetData.value)
                                }

                                Accessible.role: Accessible.Button
                                Accessible.name: presetData.label
                            }
                        }
                    }

                    Text {
                        visible: backend.forceSensitivity < backend.forceSensingDefault
                        text: s["haptic.force_warning"] || "A lighter setting may cause accidental activations during normal use."
                        font {
                            family: uiState.fontFamily
                            pixelSize: 11
                            italic: true
                        }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Test Button Card ─────────────────────────────────────
            Rectangle {
                id: testCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
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
                            hoverEnabled: backend.hapticEnabled
                            enabled: backend.hapticEnabled
                            cursorShape: backend.hapticEnabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: backend.playHapticTest()
                        }

                        Accessible.role: Accessible.Button
                        Accessible.name: s["haptic.test"] || "Test"
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Per-Action Picker Card ───────────────────────────────
            Rectangle {
                id: actionsCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: actionsContent.implicitHeight + 40
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: actionsContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 16

                    Text {
                        text: s["haptic.actions_title"] || "Haptic for Actions"
                        font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.actions_desc"]
                              || "Pick which actions fire haptic feedback. Click an action to move it between Enabled and Available."
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    RowLayout {
                        width: parent.width
                        spacing: 16

                        // ── Enabled column (left) ────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1   // equal share
                            Layout.alignment: Qt.AlignTop
                            color: hapticPage.theme.bgElevated
                            radius: 10
                            border.width: 1
                            border.color: hapticPage.theme.border
                            implicitHeight: enabledCol.implicitHeight + 24

                            Column {
                                id: enabledCol
                                anchors {
                                    left: parent.left
                                    right: parent.right
                                    top: parent.top
                                    margins: 12
                                }
                                spacing: 10

                                Text {
                                    text: s["haptic.actions_enabled"] || "Enabled"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: hapticPage.theme.textSecondary
                                }

                                Text {
                                    visible: enabledFlow.children.length === 0
                                    text: s["haptic.actions_empty"]
                                          || "No actions selected. Pick from Available."
                                    font { family: uiState.fontFamily; pixelSize: 12;
                                           italic: true }
                                    color: hapticPage.theme.textSecondary
                                    wrapMode: Text.WordWrap
                                    width: parent.width
                                }

                                Flow {
                                    id: enabledFlow
                                    width: parent.width
                                    spacing: 8

                                    Repeater {
                                        model: backend.hapticEnabledActions
                                        delegate: ActionChip {
                                            actionId: modelData.id
                                            actionLabel: modelData.label
                                            isCurrent: true
                                            enabled: backend.hapticEnabled
                                            onPicked: backend.setActionHaptic(modelData.id, false)
                                        }
                                    }
                                }
                            }
                        }

                        // ── Available column (right) ─────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            color: hapticPage.theme.bgElevated
                            radius: 10
                            border.width: 1
                            border.color: hapticPage.theme.border
                            implicitHeight: availableCol.implicitHeight + 24

                            Column {
                                id: availableCol
                                anchors {
                                    left: parent.left
                                    right: parent.right
                                    top: parent.top
                                    margins: 12
                                }
                                spacing: 10

                                Text {
                                    text: s["haptic.actions_available"] || "Available"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: hapticPage.theme.textSecondary
                                }

                                Flow {
                                    width: parent.width
                                    spacing: 8

                                    Repeater {
                                        model: backend.hapticAvailableActions
                                        delegate: ActionChip {
                                            actionId: modelData.id
                                            actionLabel: modelData.label
                                            isCurrent: false
                                            enabled: backend.hapticEnabled
                                            onPicked: backend.setActionHaptic(modelData.id, true)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Per-Button Picker Card ───────────────────────────────
            Rectangle {
                id: buttonsCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: buttonsContent.implicitHeight + 40
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: buttonsContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 16

                    Text {
                        text: s["haptic.buttons_title"] || "Haptic per Button"
                        font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                        color: hapticPage.theme.textPrimary
                    }

                    Text {
                        text: s["haptic.buttons_desc"]
                              || "Choose which buttons fire haptic feedback, in addition to the action picker above."
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    RowLayout {
                        width: parent.width
                        spacing: 16

                        // ── Enabled column (left) ────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            color: hapticPage.theme.bgElevated
                            radius: 10
                            border.width: 1
                            border.color: hapticPage.theme.border
                            implicitHeight: btnEnabledCol.implicitHeight + 24

                            Column {
                                id: btnEnabledCol
                                anchors {
                                    left: parent.left
                                    right: parent.right
                                    top: parent.top
                                    margins: 12
                                }
                                spacing: 10

                                Text {
                                    text: s["haptic.buttons_enabled"] || "Enabled"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: hapticPage.theme.textSecondary
                                }

                                Text {
                                    visible: btnEnabledFlow.children.length === 0
                                    text: s["haptic.buttons_empty"]
                                          || "No buttons selected. Pick from Available."
                                    font { family: uiState.fontFamily; pixelSize: 12;
                                           italic: true }
                                    color: hapticPage.theme.textSecondary
                                    wrapMode: Text.WordWrap
                                    width: parent.width
                                }

                                Flow {
                                    id: btnEnabledFlow
                                    width: parent.width
                                    spacing: 8

                                    Repeater {
                                        model: backend.hapticEnabledButtons
                                        delegate: ActionChip {
                                            actionId: modelData.key
                                            actionLabel: modelData.label
                                            isCurrent: true
                                            enabled: backend.hapticEnabled
                                            onPicked: backend.setButtonHaptic(modelData.key, false)
                                        }
                                    }
                                }
                            }
                        }

                        // ── Available column (right) ─────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            color: hapticPage.theme.bgElevated
                            radius: 10
                            border.width: 1
                            border.color: hapticPage.theme.border
                            implicitHeight: btnAvailableCol.implicitHeight + 24

                            Column {
                                id: btnAvailableCol
                                anchors {
                                    left: parent.left
                                    right: parent.right
                                    top: parent.top
                                    margins: 12
                                }
                                spacing: 10

                                Text {
                                    text: s["haptic.buttons_available"] || "Available"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: hapticPage.theme.textSecondary
                                }

                                Flow {
                                    width: parent.width
                                    spacing: 8

                                    Repeater {
                                        model: backend.hapticAvailableButtons
                                        delegate: ActionChip {
                                            actionId: modelData.key
                                            actionLabel: modelData.label
                                            isCurrent: false
                                            enabled: backend.hapticEnabled
                                            onPicked: backend.setButtonHaptic(modelData.key, true)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Dedup Toggle Card ────────────────────────────────────
            Rectangle {
                id: dedupCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: dedupRow.implicitHeight + 32
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: dedupRow
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 6

                    Row {
                        width: parent.width

                        Text {
                            text: s["haptic.dedup_title"] || "Prevent Duplicate Haptics"
                            font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                            color: hapticPage.theme.textPrimary
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - dedupSwitch.width
                        }

                        Switch {
                            id: dedupSwitch
                            checked: backend.hapticDedup
                            anchors.verticalCenter: parent.verticalCenter
                            enabled: backend.hapticEnabled
                            onToggled: backend.setHapticDedup(checked)
                        }
                    }

                    Text {
                        text: s["haptic.dedup_desc"]
                              || "When two haptic events fire close together, play only one pulse. Disable to allow both."
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }
                }
            }

            // Ring Hover Haptic Toggle Card
            Rectangle {
                id: ringHoverCard
                opacity: backend.hapticEnabled ? 1.0 : 0.4
                Behavior on opacity { NumberAnimation { duration: 150 } }
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: ringHoverRow.implicitHeight + 32
                radius: Theme.radius
                color: hapticPage.theme.bgCard
                border.width: 1
                border.color: hapticPage.theme.border

                Column {
                    id: ringHoverRow
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 6

                    Row {
                        width: parent.width

                        Text {
                            text: s["haptic.ring_hover_title"] || "Actions Ring Slot Feedback"
                            font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                            color: hapticPage.theme.textPrimary
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - ringHoverSwitch.width
                        }

                        Switch {
                            id: ringHoverSwitch
                            checked: backend.actionsRingHoverHaptic
                            anchors.verticalCenter: parent.verticalCenter
                            enabled: backend.hapticEnabled
                            onToggled: backend.setActionsRingHoverHaptic(checked)
                        }
                    }

                    Text {
                        text: s["haptic.ring_hover_desc"]
                              || "Fire a haptic pulse each time the cursor lands on a slot while the Actions Ring is open."
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: hapticPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
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
