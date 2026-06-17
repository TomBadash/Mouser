import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: settingsPage
    readonly property var theme: Theme.palette(uiState.darkMode)

    // Reactive shortcut — all s["key"] bindings update when lm.languageChanged fires
    property var s: lm.strings

    function updateStatusText() {
        if (backend.updateInstallStatus === "checking")
            return s["scroll.update_checking"]
        if (backend.updateInstallStatus === "downloading")
            return s["scroll.update_downloading"]
        if (backend.updateInstallStatus === "verifying")
            return s["scroll.update_verifying"]
        if (backend.updateInstallStatus === "ready_to_install")
            return s["scroll.update_ready"]
        if (backend.updateInstallStatus === "installing")
            return s["scroll.update_installing"]
        if (backend.updateInstallStatus === "installed")
            return backend.updateInstallMessage ? s["scroll.update_installed_version"].replace("%1", backend.updateInstallMessage) : s["scroll.update_installed"]
        if (backend.updateInstallStatus === "cancelled")
            return s["scroll.update_cancelled"]
        if (backend.updateInstallStatus === "manual_fallback") {
            if (backend.updateInstallMessage === "macos")
                return s["scroll.update_manual_macos"]
            if (backend.updateInstallMessage === "linux")
                return s["scroll.update_manual_linux"]
            if (backend.updateInstallMessage === "windows")
                return s["scroll.update_manual_windows"]
            if (backend.updateInstallMessage === "no_asset")
                return s["scroll.update_no_asset"]
            return s["scroll.update_manual"]
        }
        if (backend.updateInstallStatus === "error") {
            var key = "scroll.update_error_" + backend.updateInstallMessage
            if (s[key])
                return s[key]
            return s["scroll.update_error"]
        }
        if (backend.latestUpdateVersion)
            return s["scroll.update_available"].replace("%1", backend.latestUpdateVersion)
        return s["scroll.update_idle"]
    }

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

    // Pill button matching the app's button aesthetic (used for the update
    // actions so they're consistent with the rest of the UI's buttons).
    component PillButton: Rectangle {
        id: pill
        property string text: ""
        property bool enabled: true
        signal clicked()
        implicitWidth: pillText.implicitWidth + 28
        implicitHeight: 32
        radius: 8
        color: !pill.enabled
               ? settingsPage.theme.bgSubtle
               : (pillMa.containsMouse ? Qt.darker(settingsPage.theme.accent, 1.12)
                                       : settingsPage.theme.accent)
        opacity: pill.enabled ? 1 : 0.6
        Behavior on color { ColorAnimation { duration: 120 } }

        Text {
            id: pillText
            anchors.centerIn: parent
            text: pill.text
            font { family: uiState.fontFamily; pixelSize: 12; bold: true }
            color: pill.enabled ? settingsPage.theme.bgCard : settingsPage.theme.textSecondary
        }
        MouseArea {
            id: pillMa
            anchors.fill: parent
            hoverEnabled: true
            enabled: pill.enabled
            cursorShape: Qt.PointingHandCursor
            onClicked: pill.clicked()
        }
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
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.subtitle"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 13
                        }
                        color: settingsPage.theme.textSecondary
                    }
                }
            }

            Rectangle {
                width: parent.width - 72
                height: 1
                color: settingsPage.theme.border
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 24 }

            // ═══════════ Mouse settings section ═══════════
            Item {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: 24
                Row {
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    spacing: 8
                    AppIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 15; height: 15
                        name: "mouse-simple"
                        iconColor: settingsPage.theme.textSecondary
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: s["scroll.section_mouse"] || "Mouse"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true; capitalization: Font.AllUppercase }
                        color: settingsPage.theme.textSecondary
                    }
                }
            }
            Item { width: 1; height: 8 }

            // ── DPI / Pointer Speed ───────────────────────────────
            Rectangle {
                id: dpiCard
                visible: backend.hidFeaturesReady
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: dpiContent.implicitHeight + 40
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                        color: settingsPage.theme.textPrimary
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
                        color: settingsPage.theme.textSecondary
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
                            color: settingsPage.theme.textDim
                        }

                        WheelSafeSlider {
                            id: dpiSlider
                            Layout.fillWidth: true
                            from: backend.deviceDpiMin
                            to: backend.deviceDpiMax
                            stepSize: 50
                            value: backend.dpi
                            accentColor: settingsPage.theme.accent
                            accentDimColor: settingsPage.theme.accentDim
                            trackColor: settingsPage.theme.border

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
                            color: settingsPage.theme.textDim
                        }

                        Rectangle {
                            Layout.preferredWidth: 104
                            Layout.preferredHeight: 36
                            radius: 10
                            color: settingsPage.theme.accentDim

                            Text {
                                id: dpiLabel
                                anchors.centerIn: parent
                                text: backend.dpi + " DPI"
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 14
                                    bold: true
                                }
                                color: settingsPage.theme.accent
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
                            color: settingsPage.theme.textDim
                        }

                        Repeater {
                            model: settingsPage.dpiPresets

                            delegate: Rectangle {
                                width: presetText.implicitWidth + 20
                                height: 30
                                radius: 8
                                color: dpiSlider.value === modelData
                                       ? settingsPage.theme.accent
                                       : presetMouse.containsMouse
                                         ? settingsPage.theme.bgCardHover
                                         : settingsPage.theme.bgSubtle
                                border.width: 1
                                border.color: settingsPage.theme.border

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
                                           ? settingsPage.theme.bgSidebar
                                           : settingsPage.theme.textPrimary
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

                    // HID++ caveat — kept inside the DPI card.
                    Rectangle {
                        width: parent.width
                        height: noteRow.implicitHeight + 28
                        radius: 10
                        color: settingsPage.theme.bgSubtle

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
                                iconColor: settingsPage.theme.warning
                            }

                            Text {
                                width: parent.width - 28
                                text: s["scroll.dpi_note"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 12
                                }
                                color: settingsPage.theme.textDim
                                wrapMode: Text.WordWrap
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
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                                color: settingsPage.theme.textPrimary
                            }

                            Text {
                                text: s["scroll.smart_shift_desc"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 12
                                }
                                color: settingsPage.theme.textSecondary
                                wrapMode: Text.WordWrap
                                width: parent.width
                            }
                        }

                        Switch {
                            id: smartShiftToggle
                            checked: backend.smartShiftEnabled
                            focusPolicy: Qt.StrongFocus
                            Material.accent: settingsPage.theme.accent
                            Accessible.name: "SmartShift"
                            onClicked: backend.setSmartShiftEnabled(checked)
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
                            color: settingsPage.theme.textDim
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: settingsPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: smartShiftSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 50
                                stepSize: 1
                                value: backend.smartShiftThreshold
                                accentColor: settingsPage.theme.accent
                                accentDimColor: settingsPage.theme.accentDim
                                trackColor: settingsPage.theme.border

                                onMoved: {
                                    smartShiftLabel.text = Math.round(value * 2) + "%"
                                    smartShiftDebounce.restart()
                                }
                            }

                            Text {
                                text: "50"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: settingsPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: settingsPage.theme.accentDim

                                Text {
                                    id: smartShiftLabel
                                    anchors.centerIn: parent
                                    text: Math.round(backend.smartShiftThreshold * 2) + "%"
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: settingsPage.theme.accent
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
                            color: settingsPage.theme.textDim
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
                                           ? settingsPage.theme.accentDim
                                           : settingsPage.theme.bgSubtle
                                    border.width: backend.smartShiftMode === modelData.value ? 2 : 1
                                    border.color: backend.smartShiftMode === modelData.value
                                                  ? settingsPage.theme.accent
                                                  : settingsPage.theme.border

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
                                               ? settingsPage.theme.accent
                                               : settingsPage.theme.textPrimary
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

            // ── Scroll Direction ──────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: scrollContent.implicitHeight + 40
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.scroll_direction_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: settingsPage.theme.textSecondary
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: settingsPage.theme.bgSubtle

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
                                color: settingsPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: vscrollSwitch
                                checked: backend.invertVScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: settingsPage.theme.accent
                                Accessible.name: s["scroll.invert_vertical"]
                                onClicked: backend.setInvertVScroll(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: settingsPage.theme.bgSubtle

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
                                color: settingsPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: hscrollSwitch
                                checked: backend.invertHScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: settingsPage.theme.accent
                                Accessible.name: s["scroll.invert_horizontal"]
                                onClicked: backend.setInvertHScroll(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 62
                        radius: 10
                        color: settingsPage.theme.bgSubtle
                        visible: backend.isMacOS

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: s["scroll.ignore_trackpad"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 13
                                    }
                                    color: settingsPage.theme.textPrimary
                                }

                                Text {
                                    width: parent.width
                                    text: s["scroll.ignore_trackpad_desc"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: settingsPage.theme.textSecondary
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Switch {
                                id: ignoreTrackpadSwitch
                                checked: backend.ignoreTrackpad
                                Material.accent: settingsPage.theme.accent
                                Accessible.name: s["scroll.ignore_trackpad"]
                                onToggled: backend.setIgnoreTrackpad(checked)
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ═══════════ Keyboard settings section ═══════════
            Item {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: 24
                visible: backend.backlightAvailable
                Row {
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    spacing: 8
                    AppIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 15; height: 15
                        name: "keyboard-simple"
                        iconColor: settingsPage.theme.textSecondary
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: s["scroll.section_keyboard"] || "Keyboard"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true; capitalization: Font.AllUppercase }
                        color: settingsPage.theme.textSecondary
                    }
                }
            }
            Item { width: 1; height: 8; visible: backend.backlightAvailable }

            // ── Keyboard backlight (only when a backlight is present) ──
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: backlightCard.implicitHeight + 40
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border
                visible: backend.backlightAvailable

                Column {
                    id: backlightCard
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.backlight_title"] || "Keyboard backlight"
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: settingsPage.theme.textPrimary
                    }

                    Rectangle {
                        width: parent.width
                        height: backlightCol.implicitHeight + 24
                        radius: 10
                        color: settingsPage.theme.bgSubtle

                        Column {
                            id: backlightCol
                            anchors {
                                left: parent.left; right: parent.right
                                verticalCenter: parent.verticalCenter
                                leftMargin: 16; rightMargin: 16
                            }
                            spacing: 10

                            RowLayout {
                                width: parent.width
                                spacing: 12

                                Column {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        text: s["scroll.backlight_follow_theme"] || "Backlight follows system theme"
                                        font { family: uiState.fontFamily; pixelSize: 13 }
                                        color: settingsPage.theme.textPrimary
                                    }
                                    Text {
                                        width: parent.width
                                        text: s["scroll.backlight_follow_theme_desc"]
                                              || "Turns the keyboard backlight on in dark mode and off in light mode. This keyboard supports on/off only, not brightness."
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        color: settingsPage.theme.textSecondary
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                Switch {
                                    id: backlightFollowSwitch
                                    checked: backend.backlightFollowTheme
                                    Material.accent: settingsPage.theme.accent
                                    onToggled: backend.setBacklightFollowTheme(checked)
                                }
                            }

                            // Explain the manual re-enable behaviour: in light mode
                            // the backlight is off, but the backlight-up key turns
                            // it back on until the next theme change.
                            Text {
                                width: parent.width
                                visible: backend.backlightFollowTheme
                                text: s["scroll.backlight_onoff_hint"]
                                      || "In light mode the backlight is off; press the keyboard's backlight-up key to switch it on until the next theme change."
                                wrapMode: Text.WordWrap
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: settingsPage.theme.textSecondary
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ═══════════ General settings section ═══════════
            Item {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: 24
                Row {
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    spacing: 8
                    AppIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 15; height: 15
                        name: "sliders-horizontal"
                        iconColor: settingsPage.theme.textSecondary
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: s["scroll.section_general"] || "General"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true; capitalization: Font.AllUppercase }
                        color: settingsPage.theme.textSecondary
                    }
                }
            }
            Item { width: 1; height: 8 }

            // ── Appearance ────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: appearanceContent.implicitHeight + 40
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.appearance_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: settingsPage.theme.textSecondary
                    }

                    Row {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: settingsPage.appearanceOptions

                            delegate: Rectangle {
                                required property var modelData
                                width: Math.max(96, optionText.implicitWidth + 28)
                                height: 38
                                radius: 10
                                color: backend.appearanceMode === modelData.value
                                       ? settingsPage.theme.accent
                                       : optionMouse.containsMouse
                                         ? settingsPage.theme.bgCardHover
                                         : settingsPage.theme.bgSubtle
                                border.width: 1
                                border.color: backend.appearanceMode === modelData.value
                                              ? settingsPage.theme.accent
                                              : settingsPage.theme.border

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
                                           ? settingsPage.theme.bgSidebar
                                           : settingsPage.theme.textPrimary
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
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.language_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: settingsPage.theme.textSecondary
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
                                       ? settingsPage.theme.accent
                                       : langMa.containsMouse
                                         ? settingsPage.theme.bgCardHover
                                         : settingsPage.theme.bgSubtle
                                border.width: 1
                                border.color: lm.language === modelData.code
                                              ? settingsPage.theme.accent
                                              : settingsPage.theme.border

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
                                           ? settingsPage.theme.bgSidebar
                                           : settingsPage.theme.textPrimary
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
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

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
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.startup_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: settingsPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: settingsPage.theme.bgSubtle
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
                                color: settingsPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startAtLoginSwitch
                                checked: backend.startAtLogin
                                focusPolicy: Qt.StrongFocus
                                Material.accent: settingsPage.theme.accent
                                Accessible.name: s["scroll.start_at_login"]
                                onClicked: backend.setStartAtLogin(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: settingsPage.theme.bgSubtle

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
                                color: settingsPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startMinimizedSwitch
                                checked: backend.startMinimized
                                focusPolicy: Qt.StrongFocus
                                Material.accent: settingsPage.theme.accent
                                Accessible.name: s["scroll.start_minimized"]
                                onClicked: backend.setStartMinimized(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 118
                        radius: 10
                        color: settingsPage.theme.bgSubtle

                        ColumnLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                                topMargin: 10
                                bottomMargin: 10
                            }
                            spacing: 12

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                Column {
                                    Layout.fillWidth: true
                                    spacing: 3

                                    Text {
                                        text: s["scroll.check_for_updates"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: settingsPage.theme.textPrimary
                                    }

                                    Text {
                                        width: parent.width
                                        text: s["scroll.check_for_updates_desc"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 11
                                        }
                                        color: settingsPage.theme.textSecondary
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                Switch {
                                    id: checkUpdatesSwitch
                                    checked: backend.checkForUpdates
                                    focusPolicy: Qt.StrongFocus
                                    Material.accent: settingsPage.theme.accent
                                    Accessible.name: s["scroll.check_for_updates"]
                                    onClicked: backend.setCheckForUpdates(checked)
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: settingsPage.updateStatusText()
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: settingsPage.theme.textSecondary
                                    elide: Text.ElideRight
                                }

                                ProgressBar {
                                    Layout.preferredWidth: 120
                                    visible: backend.updateInstallStatus === "downloading"
                                    from: 0
                                    to: 100
                                    value: backend.updateInstallProgress
                                }

                                PillButton {
                                    text: s["scroll.update_check"]
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.manualCheckForUpdates()
                                }

                                PillButton {
                                    text: backend.isWindows ? s["scroll.update_download"] : s["scroll.update_verify"]
                                    visible: backend.latestUpdateVersion !== ""
                                             && !backend.updateInstallCanInstall
                                             && (!backend.isWindows || backend.updateInstallEnabled)
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.prepareLatestUpdate()
                                }

                                PillButton {
                                    text: s["scroll.update_cancel"]
                                    visible: backend.updateInstallStatus === "checking"
                                             || backend.updateInstallStatus === "downloading"
                                             || backend.updateInstallStatus === "verifying"
                                    onClicked: backend.cancelUpdatePreparation()
                                }

                                PillButton {
                                    text: s["scroll.update_install"]
                                    visible: backend.updateInstallCanInstall && backend.updateInstallEnabled
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.installPreparedUpdate()
                                }

                                PillButton {
                                    text: s["scroll.update_open_release"]
                                    visible: backend.latestUpdateVersion !== ""
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.openLatestReleasePage()
                                }
                            }
                        }
                    }
                }
            }

            Item {
                width: 1
                height: backend.supportsStartAtLogin ? 16 : 0
            }

            // ── Screenshots ───────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: screenshotContent.implicitHeight + 40
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

                Column {
                    id: screenshotContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.screenshots"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: settingsPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.screenshots_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: settingsPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: parent.width
                        height: 58
                        radius: 10
                        color: settingsPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 12
                            }
                            spacing: 10

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: s["scroll.screenshots_save_to"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: true
                                    }
                                    color: settingsPage.theme.textDim
                                }

                                Text {
                                    text: backend.hasCustomScreenshotDirectory
                                          ? backend.screenshotDirectoryLabel
                                          : s["scroll.screenshots_system_default"]
                                    width: parent.width
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 13
                                    }
                                    color: settingsPage.theme.textPrimary
                                    elide: Text.ElideMiddle
                                }
                            }

                            Rectangle {
                                id: chooseScreenshotButton
                                Layout.preferredWidth: Math.max(88, chooseScreenshotText.implicitWidth + 24)
                                Layout.preferredHeight: 34
                                radius: 8
                                color: chooseScreenshotMouse.containsMouse
                                       ? settingsPage.theme.bgCardHover
                                       : settingsPage.theme.bgCard
                                border.width: 1
                                border.color: settingsPage.theme.border

                                Text {
                                    id: chooseScreenshotText
                                    anchors.centerIn: parent
                                    text: s["scroll.screenshots_choose"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: settingsPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: chooseScreenshotMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.chooseScreenshotDirectory()
                                }
                            }

                            Rectangle {
                                id: resetScreenshotButton
                                Layout.preferredWidth: Math.max(102, resetScreenshotText.implicitWidth + 24)
                                Layout.preferredHeight: 34
                                radius: 8
                                opacity: backend.hasCustomScreenshotDirectory ? 1.0 : 0.45
                                color: resetScreenshotMouse.containsMouse && backend.hasCustomScreenshotDirectory
                                       ? settingsPage.theme.bgCardHover
                                       : settingsPage.theme.bgCard
                                border.width: 1
                                border.color: settingsPage.theme.border

                                Text {
                                    id: resetScreenshotText
                                    anchors.centerIn: parent
                                    text: s["scroll.screenshots_default"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: settingsPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: resetScreenshotMouse
                                    anchors.fill: parent
                                    enabled: backend.hasCustomScreenshotDirectory
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.resetScreenshotDirectory()
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Developer ─────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: calibRow.implicitHeight + 24
                radius: Theme.radius
                color: settingsPage.theme.bgCard
                border.width: 1
                border.color: settingsPage.theme.border

                RowLayout {
                    id: calibRow
                    anchors {
                        left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                        leftMargin: 16; rightMargin: 16
                    }
                    spacing: 12

                    Column {
                        Layout.fillWidth: true
                        spacing: 3

                        Text {
                            text: s["scroll.calibration_mode"] || "Layout calibration (developer)"
                            font { family: uiState.fontFamily; pixelSize: 13 }
                            color: settingsPage.theme.textPrimary
                        }

                        Text {
                            width: parent.width
                            text: s["scroll.calibration_mode_desc"]
                                  || "Overlay a grid to measure device-layout coordinates, with a layout picker and optional hotspot preview — works without the device connected."
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            color: settingsPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: openCalibText.implicitWidth + 28
                        Layout.preferredHeight: 34
                        radius: 9
                        color: openCalibMa.containsMouse
                               ? settingsPage.theme.accentHover : settingsPage.theme.accent
                        Text {
                            id: openCalibText
                            anchors.centerIn: parent
                            text: s["scroll.calibration_open"] || "Open calibration"
                            font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                            color: settingsPage.theme.bgSidebar
                        }
                        MouseArea {
                            id: openCalibMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.setCalibrationMode(true)
                        }
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
            checkUpdatesSwitch.checked = backend.checkForUpdates
            vscrollSwitch.checked = backend.invertVScroll
            hscrollSwitch.checked = backend.invertHScroll
            ignoreTrackpadSwitch.checked = backend.ignoreTrackpad
        }
    }
}
