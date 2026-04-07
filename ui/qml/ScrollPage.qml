import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: scrollPage
    readonly property var theme: Theme.palette(uiState.darkMode)

    // Reactive shortcut — all s["key"] bindings update when lm.languageChanged fires
    property var s: lm.strings

    readonly property var appearanceOptions: [
        { label: s["scroll.system"], value: "system" },
        { label: s["scroll.light"],  value: "light"  },
        { label: s["scroll.dark"],   value: "dark"   }
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
                        text: s["scroll.title"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 24
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.subtitle"]
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

            // ── DPI / Pointer Speed ───────────────────────────────
            Rectangle {
                id: dpiCard
                visible: backend.hidFeaturesReady
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
                        text: s["scroll.pointer_speed"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: backend.deviceDpiMin === 200 && backend.deviceDpiMax === 8000
                              ? s["scroll.pointer_speed_desc"]
                              : s["scroll.pointer_speed_desc_range_prefix"]
                                + backend.deviceDpiMin
                                + s["scroll.pointer_speed_desc_range_to"]
                                + backend.deviceDpiMax
                                + s["scroll.pointer_speed_desc_range_suffix"]
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
                            Accessible.name: s["scroll.pointer_speed"]

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
                            text: s["scroll.presets"]
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
                                Accessible.name: modelData + " DPI"

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

            Item { width: 1; height: 16; visible: backend.smartShiftSupported && backend.deviceHasSmartShift }

            // ── Scroll Wheel Mode ─────────────────────────────────
            Rectangle {
                visible: backend.smartShiftSupported && backend.deviceHasSmartShift
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: smartShiftContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: smartShiftContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 16

                    // ── SmartShift header row with toggle ───────────────
                    RowLayout {
                        width: parent.width

                        Column {
                            spacing: 4
                            Layout.fillWidth: true

                            Text {
                                text: s["scroll.smart_shift"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 16
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }

                            Text {
                                text: s["scroll.smart_shift_desc"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 12
                                }
                                color: scrollPage.theme.textSecondary
                                wrapMode: Text.WordWrap
                                width: parent.width
                            }
                        }

                        Switch {
                            id: smartShiftToggle
                            checked: backend.smartShiftEnabled
                            Material.accent: scrollPage.theme.accent
                            Accessible.name: "SmartShift"
                            onToggled: backend.setSmartShiftEnabled(checked)
                        }
                    }

                    // ── Sensitivity slider (visible when SmartShift ON) ─
                    Column {
                        visible: backend.smartShiftEnabled
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.sensitivity_value"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                                bold: true
                                letterSpacing: 0.8
                            }
                            color: scrollPage.theme.textDim
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Slider {
                                id: smartShiftSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 50
                                stepSize: 1
                                value: backend.smartShiftThreshold
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: "SmartShift sensitivity"

                                onMoved: {
                                    smartShiftLabel.text = Math.round(value * 2) + "%"
                                    smartShiftDebounce.restart()
                                }
                            }

                            Text {
                                text: "50"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: smartShiftLabel
                                    anchors.centerIn: parent
                                    text: Math.round(backend.smartShiftThreshold * 2) + "%"
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
                            id: smartShiftDebounce
                            interval: 400
                            onTriggered: backend.setSmartShiftThreshold(Math.round(smartShiftSlider.value))
                        }
                    }

                    // ── Scroll Mode (hidden when SmartShift ON) ─────────
                    Column {
                        visible: !backend.smartShiftEnabled
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.scroll_mode_section"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                                bold: true
                                letterSpacing: 0.8
                            }
                            color: scrollPage.theme.textDim
                        }

                        Row {
                            width: parent.width
                            spacing: 10

                            Repeater {
                                model: [
                                    { value: "ratchet",  labelKey: "scroll.ratchet"  },
                                    { value: "freespin", labelKey: "scroll.freespin" }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    width: Math.max(96, ssText.implicitWidth + 28)
                                    height: 38
                                    radius: 10
                                    color: backend.smartShiftMode === modelData.value
                                           ? scrollPage.theme.accentDim
                                           : scrollPage.theme.bgSubtle
                                    border.width: backend.smartShiftMode === modelData.value ? 2 : 1
                                    border.color: backend.smartShiftMode === modelData.value
                                                  ? scrollPage.theme.accent
                                                  : scrollPage.theme.border

                                    Text {
                                        id: ssText
                                        anchors.centerIn: parent
                                        text: s[modelData.labelKey] || modelData.labelKey
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 12
                                            bold: backend.smartShiftMode === modelData.value
                                        }
                                        color: backend.smartShiftMode === modelData.value
                                               ? scrollPage.theme.accent
                                               : scrollPage.theme.textPrimary
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: backend.setSmartShift(modelData.value)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Appearance ────────────────────────────────────────
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
                        text: s["scroll.appearance"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.appearance_desc"]
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
                                Accessible.name: modelData.label

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

            // ── Language ──────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: languageContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: languageContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.language"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.language_desc"]
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
                            model: lm.availableLanguages

                            delegate: Rectangle {
                                required property var modelData
                                width: Math.max(108, langText.implicitWidth + 28)
                                height: 38
                                radius: 10
                                color: lm.language === modelData.code
                                       ? scrollPage.theme.accent
                                       : langMa.containsMouse
                                         ? scrollPage.theme.bgCardHover
                                         : scrollPage.theme.bgSubtle
                                border.width: 1
                                border.color: lm.language === modelData.code
                                              ? scrollPage.theme.accent
                                              : scrollPage.theme.border

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: langText
                                    anchors.centerIn: parent
                                    text: modelData.name
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: lm.language === modelData.code
                                    }
                                    color: lm.language === modelData.code
                                           ? scrollPage.theme.bgSidebar
                                           : scrollPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: langMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: lm.setLanguage(modelData.code)
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Startup ───────────────────────────────────────────
            Rectangle {
                visible: backend.supportsStartAtLogin
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: startupContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: startupContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.startup"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.startup_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: scrollPage.theme.bgSubtle
                        visible: backend.supportsStartAtLogin

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: s["scroll.start_at_login"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startAtLoginSwitch
                                checked: backend.startAtLogin
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.start_at_login"]
                                onToggled: backend.setStartAtLogin(checked)
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
                                text: s["scroll.start_minimized"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startMinimizedSwitch
                                checked: backend.startMinimized
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.start_minimized"]
                                onToggled: backend.setStartMinimized(checked)
                            }
                        }
                    }
                }
            }

            Item {
                width: 1
                height: backend.supportsStartAtLogin ? 16 : 0
            }

            // ── Scroll Direction ──────────────────────────────────
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
                        text: s["scroll.scroll_direction"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.scroll_direction_desc"]
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
                                text: s["scroll.invert_vertical"]
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
                                Accessible.name: s["scroll.invert_vertical"]
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
                                text: s["scroll.invert_horizontal"]
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
                                Accessible.name: s["scroll.invert_horizontal"]
                                onToggled: backend.setInvertHScroll(checked)
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── DPI note ──────────────────────────────────────────
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
                        text: s["scroll.dpi_note"]
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
            if (backend.supportsStartAtLogin) {
                startAtLoginSwitch.checked = backend.startAtLogin
                startMinimizedSwitch.checked = backend.startMinimized
            }
            vscrollSwitch.checked = backend.invertVScroll
            hscrollSwitch.checked = backend.invertHScroll
        }
    }
}
