import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

/*  Unified Mouse + Profiles page.
    Left panel  — profile list with add/delete.
    Right panel — interactive mouse image with hotspot overlay & action picker.
    Selecting a profile switches which mappings are shown / edited.            */

Item {
    id: mousePage
    readonly property var theme: Theme.palette(uiState.darkMode)
    property string pendingDeleteProfile: ""

    // ── Profile state ─────────────────────────────────────────
    property string selectedProfile: backend.activeProfile
    property string selectedProfileLabel: ""
    property var selectedProfileMappings: []

    Component.onCompleted: selectProfile(backend.activeProfile)

    function refreshSelectedProfileMappings() {
        selectedProfileMappings = backend.getProfileMappings(selectedProfile)
    }

    function mappingFor(key) {
        for (var i = 0; i < selectedProfileMappings.length; i++) {
            if (selectedProfileMappings[i].key === key)
                return selectedProfileMappings[i]
        }
        return null
    }

    function selectProfile(name) {
        selectedProfile = name
        selectedProfileLabel = ""
        var profs = backend.profiles
        for (var i = 0; i < profs.length; i++) {
            if (profs[i].name === name) {
                selectedProfileLabel = profs[i].label
                break
            }
        }
        refreshSelectedProfileMappings()
        // Clear hotspot selection when switching profiles
        selectedButton = ""
        selectedButtonName = ""
        selectedActionId = ""
    }

    Connections {
        target: backend
        function onProfilesChanged() {
            // Refresh label/apps if current profile still exists
            var profs = backend.profiles
            for (var i = 0; i < profs.length; i++) {
                if (profs[i].name === selectedProfile) {
                    selectedProfileLabel = profs[i].label
                    return
                }
            }
            // Profile deleted — fall back to active
            selectProfile(backend.activeProfile)
        }
        function onActiveProfileChanged() {
            // Auto-select when engine switches profile
            selectProfile(backend.activeProfile)
        }
    }

    // ── Button / hotspot state ────────────────────────────────
    property string selectedButton: ""
    property string selectedButtonName: ""
    property string selectedActionId: ""

    function selectButton(key) {
        if (selectedButton === key) {
            selectedButton = ""
            selectedButtonName = ""
            selectedActionId = ""
            return
        }
        var mapping = mappingFor(key)
        if (mapping) {
            selectedButton = key
            selectedButtonName = mapping.name
            selectedActionId = mapping.actionId
        }
    }

    function selectHScroll() {
        if (selectedButton === "hscroll_left") {
            selectedButton = ""
            selectedButtonName = ""
            selectedActionId = ""
            return
        }
        selectedButton = "hscroll_left"
        selectedButtonName = "Horizontal Scroll"
        var mapping = mappingFor("hscroll_left")
        selectedActionId = mapping ? mapping.actionId : "none"
    }

    Connections {
        id: mappingsConn
        target: backend
        function onMappingsChanged() {
            refreshSelectedProfileMappings()
            if (selectedButton === "") return
            var mapping = mappingFor(selectedButton)
            if (mapping) {
                selectedActionId = mapping.actionId
            }
        }
    }

    function actionFor(key) {
        var mapping = mappingFor(key)
        if (mapping)
            return mapping.actionLabel
        return "Do Nothing"
    }

    function actionFor_id(key) {
        var mapping = mappingFor(key)
        if (mapping)
            return mapping.actionId
        return "none"
    }

    function actionIndexForId(actionId) {
        var actions = backend.allActions
        for (var i = 0; i < actions.length; i++)
            if (actions[i].id === actionId) return i
        return 0
    }

    function gestureSummary() {
        if (!backend.supportsGestureDirections)
            return actionFor("gesture")

        var hasSwipeAction =
                actionFor_id("gesture_left") !== "none"
                || actionFor_id("gesture_right") !== "none"
                || actionFor_id("gesture_up") !== "none"
                || actionFor_id("gesture_down") !== "none"

        if (!hasSwipeAction)
            return "Tap: " + actionFor("gesture")

        return "Tap: " + actionFor("gesture") + " | Swipes configured"
    }

    // ── Main two-column layout ────────────────────────────────
    Row {
        anchors.fill: parent
        spacing: 0

        // ══════════════════════════════════════════════════════
        // ── Left panel: profile list ─────────────────────────
        // ══════════════════════════════════════════════════════
        Rectangle {
            id: leftPanel
            width: 220
            height: parent.height
            color: theme.bgCard
            border.width: 1; border.color: theme.border

            Column {
                anchors.fill: parent
                spacing: 0

                // Title bar
                Item {
                    width: parent.width; height: 52

                    Text {
                        anchors {
                            left: parent.left; leftMargin: 16
                            verticalCenter: parent.verticalCenter
                        }
                        text: "Profiles"
                        font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                        color: theme.textPrimary
                    }
                }

                Rectangle { width: parent.width; height: 1; color: theme.border }

                // Profile items
                ListView {
                    id: profileList
                    width: parent.width
                    height: parent.height - 110
                    model: backend.profiles
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        width: profileList.width
                        height: 58
                        color: selectedProfile === modelData.name
                               ? Qt.rgba(0, 0.83, 0.67, 0.08)
                               : profItemMa.containsMouse
                                 ? Qt.rgba(1, 1, 1, 0.03)
                                 : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }

                        Row {
                            anchors {
                                fill: parent
                                leftMargin: 6; rightMargin: 10
                            }
                            spacing: 8

                            // Active indicator
                            Rectangle {
                                width: 3; height: 28; radius: 2
                                color: modelData.isActive
                                       ? theme.accent : "transparent"
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            // App icons
                            Row {
                                spacing: -4
                                anchors.verticalCenter: parent.verticalCenter
                                visible: modelData.appIcons !== undefined
                                         && modelData.appIcons.length > 0

                                Repeater {
                                    model: modelData.appIcons
                                    delegate: Image {
                                        source: modelData
                                                ? "file:///" + applicationDirPath
                                                  + "/images/" + modelData
                                                : ""
                                        width: 24; height: 24
                                        sourceSize { width: 24; height: 24 }
                                        fillMode: Image.PreserveAspectFit
                                        visible: modelData !== ""
                                        smooth: true; mipmap: true
                                        asynchronous: true
                                        cache: true
                                    }
                                }
                            }

                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2

                                Text {
                                    text: modelData.label
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12; bold: true
                                    }
                                    color: selectedProfile === modelData.name
                                           ? theme.accent : theme.textPrimary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 70
                                }
                                Text {
                                    text: modelData.apps.length
                                          ? modelData.apps.join(", ")
                                          : "All applications"
                                    font { family: uiState.fontFamily; pixelSize: 9 }
                                    color: theme.textSecondary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 70
                                }
                            }
                        }

                        MouseArea {
                            id: profItemMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: selectProfile(modelData.name)
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: theme.border }

                // Add profile controls
                Item {
                    width: parent.width; height: 52

                    RowLayout {
                        anchors {
                            fill: parent
                            leftMargin: 8; rightMargin: 8
                        }
                        spacing: 4

                        ComboBox {
                            id: addCombo
                            Layout.fillWidth: true
                            model: {
                                var apps = backend.knownApps
                                var labels = []
                                for (var i = 0; i < apps.length; i++)
                                    labels.push(apps[i].label)
                                return labels
                            }
                            Material.accent: theme.accent
                            font { family: uiState.fontFamily; pixelSize: 10 }
                        }

                        Rectangle {
                            Layout.preferredWidth: 42
                            Layout.preferredHeight: 28
                            radius: 8
                            color: addBtnMa.containsMouse
                                   ? theme.accentHover : theme.accent

                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                                color: theme.bgSidebar
                            }

                            MouseArea {
                                id: addBtnMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (addCombo.currentText)
                                        backend.addProfile(addCombo.currentText)
                                }
                            }
                        }
                    }
                }
            }
        }

        // ══════════════════════════════════════════════════════
        // ── Right panel: mouse image + hotspots + picker ─────
        // ══════════════════════════════════════════════════════
        ScrollView {
            width: parent.width - leftPanel.width
            height: parent.height
            contentWidth: availableWidth
            clip: true

            Flickable {
                contentHeight: rightCol.implicitHeight + 32
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: rightCol
                    width: parent.width
                    spacing: 0

                    // ── Header ────────────────────────────────
                    Item {
                        width: parent.width; height: 70

                        Row {
                            anchors {
                                left: parent.left; leftMargin: 28
                                verticalCenter: parent.verticalCenter
                            }
                            spacing: 12

                            Column {
                                spacing: 3
                                anchors.verticalCenter: parent.verticalCenter

                                Row {
                                    spacing: 8

                                    Text {
                                        text: "MX Master 3S"
                                        font { family: uiState.fontFamily; pixelSize: 20; bold: true }
                                        color: theme.textPrimary
                                    }

                                    // Profile badge
                                    Rectangle {
                                        visible: selectedProfileLabel !== ""
                                        width: profBadgeText.implicitWidth + 16
                                        height: 22; radius: 11
                                        color: Qt.rgba(0, 0.83, 0.67, 0.12)
                                        anchors.verticalCenter: parent.verticalCenter

                                        Text {
                                            id: profBadgeText
                                            anchors.centerIn: parent
                                            text: selectedProfileLabel
                                            font { family: uiState.fontFamily; pixelSize: 11 }
                                            color: theme.accent
                                        }
                                    }
                                }

                                Text {
                                    text: "Click a dot to configure its action"
                                    font { family: uiState.fontFamily; pixelSize: 12 }
                                    color: theme.textSecondary
                                }
                            }
                        }

                        // Right-side status row: delete button + battery + connection
                        Row {
                            anchors {
                                right: parent.right; rightMargin: 28
                                verticalCenter: parent.verticalCenter
                            }
                            spacing: 8

                            // Delete profile button (not for default)
                            Rectangle {
                                visible: selectedProfile !== ""
                                         && selectedProfile !== "default"
                                width: delRow.implicitWidth + 18
                                height: 28
                                radius: 10
                                color: delMa.containsMouse ? theme.danger : theme.dangerBg
                                Behavior on color { ColorAnimation { duration: 120 } }
                                anchors.verticalCenter: parent.verticalCenter

                                Row {
                                    id: delRow
                                    anchors.centerIn: parent
                                    spacing: 6

                                    AppIcon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 14
                                        height: 14
                                        name: "trash"
                                        iconColor: uiState.darkMode ? theme.textPrimary : theme.danger
                                    }

                                    Text {
                                        text: "Delete Profile"
                                        font { family: uiState.fontFamily; pixelSize: 10; bold: true }
                                        color: uiState.darkMode ? theme.textPrimary : theme.danger
                                    }
                                }

                                MouseArea {
                                    id: delMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        pendingDeleteProfile = selectedProfile
                                        deleteDialog.open()
                                    }
                                }
                            }

                            // Battery badge
                            Rectangle {
                                visible: backend.batteryLevel >= 0
                                width: battRow.implicitWidth + 16
                                height: 24; radius: 12
                                anchors.verticalCenter: parent.verticalCenter
                                color: {
                                    var lvl = backend.batteryLevel
                                    if (lvl <= 20) return Qt.rgba(0.88, 0.2, 0.2, 0.18)
                                    if (lvl <= 40) return Qt.rgba(0.9, 0.56, 0.1, 0.18)
                                    return Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.12 : 0.16)
                                }

                                Row {
                                    id: battRow
                                    anchors.centerIn: parent
                                    spacing: 6

                                    AppIcon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 14
                                        height: 14
                                        name: "battery-high"
                                        iconColor: {
                                            var lvl = backend.batteryLevel
                                            if (lvl <= 20) return "#e05555"
                                            if (lvl <= 40) return "#e09045"
                                            return theme.accent
                                        }
                                    }

                                    Text {
                                        text: backend.batteryLevel + "%"
                                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                        color: {
                                            var lvl = backend.batteryLevel
                                            if (lvl <= 20) return "#e05555"
                                            if (lvl <= 40) return "#e09045"
                                            return theme.accent
                                        }
                                    }
                                }
                            }

                            // Connection status badge
                            Rectangle {
                                width: statusRow.implicitWidth + 16
                                height: 24; radius: 12
                                anchors.verticalCenter: parent.verticalCenter
                                color: backend.mouseConnected
                                       ? Qt.rgba(0, 0.83, 0.67, 0.12)
                                       : Qt.rgba(0.9, 0.3, 0.3, 0.15)

                                Row {
                                    id: statusRow
                                    anchors.centerIn: parent
                                    spacing: 5

                                    Rectangle {
                                        width: 7; height: 7; radius: 4
                                        color: backend.mouseConnected
                                               ? theme.accent : "#e05555"
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: backend.mouseConnected
                                              ? "Connected" : "Not Connected"
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        color: backend.mouseConnected
                                               ? theme.accent : "#e05555"
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: theme.border
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    // ── Mouse image with hotspots ─────────────
                    Item {
                        id: mouseImageArea
                        width: parent.width
                        height: 420

                        Rectangle {
                            anchors.fill: parent
                            color: theme.bg
                        }

                        Image {
                            id: mouseImg
                            source: "file:///" + applicationDirPath + "/images/mouse.png"
                            fillMode: Image.PreserveAspectFit
                            width: 460
                            height: 360
                            anchors.centerIn: parent
                            smooth: true
                            mipmap: true
                            asynchronous: true
                            cache: true

                            property real offX: (width - paintedWidth) / 2
                            property real offY: (height - paintedHeight) / 2
                        }

                        // Hotspot dots
                        HotspotDot {
                            anchors.fill: mouseImageArea
                            imgItem: mouseImg
                            normX: 0.35; normY: 0.4
                            buttonKey: "middle"
                            label: "Middle button"
                            sublabel: actionFor("middle")
                            labelSide: "right"
                            labelOffX: 100; labelOffY: -160
                        }

                        HotspotDot {
                            anchors.fill: mouseImageArea
                            imgItem: mouseImg
                            normX: 0.7; normY: 0.63
                            buttonKey: "gesture"
                            label: "Gesture button"
                            sublabel: gestureSummary()
                            labelSide: "left"
                            labelOffX: -200; labelOffY: 60
                        }

                        HotspotDot {
                            anchors.fill: mouseImageArea
                            imgItem: mouseImg
                            normX: 0.6; normY: 0.48
                            buttonKey: "xbutton2"
                            label: "Forward button"
                            sublabel: actionFor("xbutton2")
                            labelSide: "left"
                            labelOffX: -300; labelOffY: 0
                        }

                        HotspotDot {
                            anchors.fill: mouseImageArea
                            imgItem: mouseImg
                            normX: 0.65; normY: 0.4
                            buttonKey: "xbutton1"
                            label: "Back button"
                            sublabel: actionFor("xbutton1")
                            labelSide: "right"
                            labelOffX: 200; labelOffY: 50
                        }

                        HotspotDot {
                            anchors.fill: mouseImageArea
                            imgItem: mouseImg
                            normX: 0.6; normY: 0.375
                            buttonKey: "hscroll_left"
                            isHScroll: true
                            label: "Horizontal scroll"
                            sublabel: "L: " + actionFor("hscroll_left") + " | R: " + actionFor("hscroll_right")
                            labelSide: "right"
                            labelOffX: 200; labelOffY: -50
                        }
                    }

                    // ── Separator ─────────────────────────────
                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: theme.border
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: selectedButton !== ""
                    }

                    // ── Action picker ─────────────────────────
                    Rectangle {
                        id: actionPicker
                        width: parent.width - 56
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: selectedButton !== ""
                                ? pickerCol.implicitHeight + 32 : 0
                        clip: true
                        color: "transparent"
                        visible: height > 0

                        Behavior on height {
                            NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                        }

                        Column {
                            id: pickerCol
                            anchors {
                                left: parent.left; right: parent.right
                                top: parent.top; topMargin: 16
                            }
                            spacing: 16

                            Row {
                                spacing: 12

                                Rectangle {
                                    width: 6; height: pickerTitleCol.height
                                    radius: 3; color: theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Column {
                                    id: pickerTitleCol
                                    spacing: 2

                                    Text {
                                        text: selectedButtonName
                                              ? selectedButtonName + " — Choose Action"
                                              : ""
                                        font { family: uiState.fontFamily; pixelSize: 15; bold: true }
                                        color: theme.textPrimary
                                    }
                                    Text {
                                        text: selectedButton === "hscroll_left"
                                              ? "Configure separate actions for scroll left and right"
                                              : selectedButton === "gesture"
                                                && backend.supportsGestureDirections
                                                ? "Configure tap behavior plus swipe actions for the gesture button"
                                              : "Select what happens when you use this button"
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textSecondary
                                        visible: selectedButton !== ""
                                    }
                                }
                            }

                            // Horizontal scroll: left + right rows
                            Column {
                                width: parent.width
                                spacing: 14
                                visible: selectedButton === "hscroll_left"

                                Text {
                                    text: "SCROLL LEFT"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: theme.textDim
                                }

                                Flow {
                                    width: parent.width; spacing: 8
                                    Repeater {
                                        model: backend.allActions
                                        delegate: ActionChip {
                                            actionId: modelData.id
                                            actionLabel: modelData.label
                                            isCurrent: modelData.id === actionFor_id("hscroll_left")
                                            onPicked: function(aid) {
                                                backend.setProfileMapping(
                                                    selectedProfile, "hscroll_left", aid)
                                            }
                                        }
                                    }
                                }

                                Item { width: 1; height: 4 }

                                Text {
                                    text: "SCROLL RIGHT"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: theme.textDim
                                }

                                Flow {
                                    width: parent.width; spacing: 8
                                    Repeater {
                                        model: backend.allActions
                                        delegate: ActionChip {
                                            actionId: modelData.id
                                            actionLabel: modelData.label
                                            isCurrent: modelData.id === actionFor_id("hscroll_right")
                                            onPicked: function(aid) {
                                                backend.setProfileMapping(
                                                    selectedProfile, "hscroll_right", aid)
                                            }
                                        }
                                    }
                                }
                            }

                            Column {
                                width: parent.width
                                spacing: 14
                                visible: selectedButton === "gesture"
                                         && backend.supportsGestureDirections

                                Text {
                                    text: "TAP ACTION"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: theme.textDim
                                }

                                ComboBox {
                                    width: parent.width
                                    model: backend.allActions
                                    textRole: "label"
                                    Material.accent: theme.accent
                                    font { family: uiState.fontFamily; pixelSize: 11 }
                                    currentIndex: actionIndexForId(actionFor_id("gesture"))
                                    onActivated: function(index) {
                                        var aid = backend.allActions[index].id
                                        backend.setProfileMapping(selectedProfile, "gesture", aid)
                                        selectedActionId = aid
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 1
                                    color: theme.border
                                }

                                Row {
                                    width: parent.width
                                    spacing: 12

                                    Text {
                                        text: "Threshold"
                                        font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                                        color: theme.textPrimary
                                    }

                                    Text {
                                        text: backend.gestureThreshold + " px"
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textSecondary
                                    }
                                }

                                Slider {
                                    width: parent.width
                                    from: 20
                                    to: 400
                                    stepSize: 5
                                    value: backend.gestureThreshold
                                    Material.accent: theme.accent
                                    onMoved: backend.setGestureThreshold(value)
                                }

                                Text {
                                    text: "SWIPE ACTIONS"
                                    font { family: uiState.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: theme.textDim
                                }

                                RowLayout {
                                    width: parent.width
                                    spacing: 12

                                    Text {
                                        text: "Swipe left"
                                        Layout.preferredWidth: 100
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textPrimary
                                    }

                                    ComboBox {
                                        Layout.fillWidth: true
                                        model: backend.allActions
                                        textRole: "label"
                                        Material.accent: theme.accent
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        currentIndex: actionIndexForId(actionFor_id("gesture_left"))
                                        onActivated: function(index) {
                                            backend.setProfileMapping(
                                                selectedProfile,
                                                "gesture_left",
                                                backend.allActions[index].id)
                                        }
                                    }
                                }

                                RowLayout {
                                    width: parent.width
                                    spacing: 12

                                    Text {
                                        text: "Swipe right"
                                        Layout.preferredWidth: 100
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textPrimary
                                    }

                                    ComboBox {
                                        Layout.fillWidth: true
                                        model: backend.allActions
                                        textRole: "label"
                                        Material.accent: theme.accent
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        currentIndex: actionIndexForId(actionFor_id("gesture_right"))
                                        onActivated: function(index) {
                                            backend.setProfileMapping(
                                                selectedProfile,
                                                "gesture_right",
                                                backend.allActions[index].id)
                                        }
                                    }
                                }

                                RowLayout {
                                    width: parent.width
                                    spacing: 12

                                    Text {
                                        text: "Swipe up"
                                        Layout.preferredWidth: 100
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textPrimary
                                    }

                                    ComboBox {
                                        Layout.fillWidth: true
                                        model: backend.allActions
                                        textRole: "label"
                                        Material.accent: theme.accent
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        currentIndex: actionIndexForId(actionFor_id("gesture_up"))
                                        onActivated: function(index) {
                                            backend.setProfileMapping(
                                                selectedProfile,
                                                "gesture_up",
                                                backend.allActions[index].id)
                                        }
                                    }
                                }

                                RowLayout {
                                    width: parent.width
                                    spacing: 12

                                    Text {
                                        text: "Swipe down"
                                        Layout.preferredWidth: 100
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textPrimary
                                    }

                                    ComboBox {
                                        Layout.fillWidth: true
                                        model: backend.allActions
                                        textRole: "label"
                                        Material.accent: theme.accent
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        currentIndex: actionIndexForId(actionFor_id("gesture_down"))
                                        onActivated: function(index) {
                                            backend.setProfileMapping(
                                                selectedProfile,
                                                "gesture_down",
                                                backend.allActions[index].id)
                                        }
                                    }
                                }
                            }

                            // Single button: categorized chips
                            Column {
                                width: parent.width
                                spacing: 14
                                visible: selectedButton !== ""
                                         && selectedButton !== "hscroll_left"
                                         && !(selectedButton === "gesture"
                                              && backend.supportsGestureDirections)

                                Repeater {
                                    model: backend.actionCategories

                                    delegate: Column {
                                        width: parent.width
                                        spacing: 8

                                        Text {
                                            text: modelData.category
                                            font { family: uiState.fontFamily; pixelSize: 11;
                                                   capitalization: Font.AllUppercase;
                                                   letterSpacing: 1 }
                                            color: theme.textDim
                                        }

                                        Flow {
                                            width: parent.width; spacing: 8
                                            Repeater {
                                                model: modelData.actions
                                                delegate: ActionChip {
                                                    actionId: modelData.id
                                                    actionLabel: modelData.label
                                                    isCurrent: modelData.id === selectedActionId
                                                    onPicked: function(aid) {
                                                        backend.setProfileMapping(
                                                            selectedProfile,
                                                            selectedButton, aid)
                                                        selectedActionId = aid
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Item { width: 1; height: 8 }
                        }
                    }

                    Rectangle {
                        width: parent.width - 56
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: debugCol.implicitHeight + 24
                        radius: 14
                        color: theme.bgCard
                        border.width: 1
                        border.color: theme.border
                        visible: backend.debugMode

                        Column {
                            id: debugCol
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 12

                            RowLayout {
                                width: parent.width
                                spacing: 12

                                Column {
                                    Layout.fillWidth: true
                                    spacing: 3

                                    Text {
                                        text: "Debug Events"
                                        font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                                        color: theme.textPrimary
                                    }

                                    Text {
                                        text: "Collects detected buttons, gestures, and mapped actions"
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        color: theme.textSecondary
                                    }
                                }

                                Switch {
                                    checked: backend.debugEventsEnabled
                                    text: checked ? "On" : "Off"
                                    Material.accent: theme.accent
                                    onToggled: backend.setDebugEventsEnabled(checked)
                                }

                                Switch {
                                    checked: backend.recordMode
                                    text: checked ? "Rec" : "Record"
                                    Material.accent: "#e46f4e"
                                    onToggled: backend.setRecordMode(checked)
                                }

                                Rectangle {
                                    Layout.preferredWidth: clearText.implicitWidth + 20
                                    Layout.preferredHeight: 28
                                    radius: 8
                                    color: clearMa.containsMouse
                                           ? Qt.rgba(1, 1, 1, 0.08)
                                           : Qt.rgba(1, 1, 1, 0.04)

                                    Text {
                                        id: clearText
                                        anchors.centerIn: parent
                                        text: "Clear"
                                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                        color: theme.textPrimary
                                    }

                                    MouseArea {
                                        id: clearMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: backend.clearDebugLog()
                                    }
                                }

                                Rectangle {
                                    Layout.preferredWidth: clearRecText.implicitWidth + 20
                                    Layout.preferredHeight: 28
                                    radius: 8
                                    color: clearRecMa.containsMouse
                                           ? Qt.rgba(1, 1, 1, 0.08)
                                           : Qt.rgba(1, 1, 1, 0.04)

                                    Text {
                                        id: clearRecText
                                        anchors.centerIn: parent
                                        text: "Clear Rec"
                                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                        color: theme.textPrimary
                                    }

                                    MouseArea {
                                        id: clearRecMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: backend.clearGestureRecords()
                                    }
                                }
                            }

                            Rectangle {
                                width: parent.width
                                radius: 10
                                color: Qt.rgba(1, 1, 1, 0.03)
                                border.width: 1
                                border.color: theme.border
                                height: monitorCol.implicitHeight + 20

                                Column {
                                    id: monitorCol
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 8

                                    Text {
                                        text: "Live Gesture Monitor"
                                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                        color: theme.textPrimary
                                    }

                                    Row {
                                        spacing: 8

                                        Rectangle {
                                            width: activeText.implicitWidth + 16
                                            height: 24
                                            radius: 12
                                            color: backend.gestureActive
                                                   ? Qt.rgba(0.89, 0.45, 0.25, 0.18)
                                                   : Qt.rgba(1, 1, 1, 0.05)

                                            Text {
                                                id: activeText
                                                anchors.centerIn: parent
                                                text: backend.gestureActive ? "Held" : "Idle"
                                                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                                color: backend.gestureActive ? "#f39c6b" : theme.textSecondary
                                            }
                                        }

                                        Rectangle {
                                            width: moveText.implicitWidth + 16
                                            height: 24
                                            radius: 12
                                            color: backend.gestureMoveSeen
                                                   ? Qt.rgba(0, 0.83, 0.67, 0.12)
                                                   : Qt.rgba(1, 1, 1, 0.05)

                                            Text {
                                                id: moveText
                                                anchors.centerIn: parent
                                                text: backend.gestureMoveSeen ? "Move Seen" : "No Move"
                                                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                                color: backend.gestureMoveSeen ? theme.accent : theme.textSecondary
                                            }
                                        }
                                    }

                                    Text {
                                        text: "Source: "
                                              + (backend.gestureMoveSource ? backend.gestureMoveSource : "n/a")
                                              + " | dx: " + backend.gestureMoveDx
                                              + " | dy: " + backend.gestureMoveDy
                                        font { family: "Menlo"; pixelSize: 11 }
                                        color: theme.textSecondary
                                    }

                                    Text {
                                        text: backend.gestureStatus
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        color: theme.textPrimary
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }

                            Rectangle {
                                width: parent.width
                                height: 160
                                radius: 10
                                color: Qt.rgba(0, 0, 0, 0.18)
                                border.width: 1
                                border.color: theme.border

                                ScrollView {
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    clip: true

                                    TextArea {
                                        id: debugLogArea
                                        text: backend.debugLog.length
                                              ? backend.debugLog
                                              : "Turn on debug mode, then press buttons or use the gesture button."
                                        readOnly: true
                                        wrapMode: TextEdit.NoWrap
                                        selectByMouse: true
                                        color: backend.debugLog.length
                                               ? theme.textPrimary
                                               : theme.textSecondary
                                        font.pixelSize: 11
                                        font.family: "Menlo"
                                        background: null
                                        padding: 10

                                        onTextChanged: {
                                            cursorPosition = length
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                width: parent.width
                                height: 180
                                radius: 10
                                color: Qt.rgba(0, 0, 0, 0.18)
                                border.width: 1
                                border.color: theme.border

                                ScrollView {
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    clip: true

                                    TextArea {
                                        text: backend.gestureRecords.length
                                              ? backend.gestureRecords
                                              : "Turn on Record and perform a few gesture attempts."
                                        readOnly: true
                                        wrapMode: TextEdit.Wrap
                                        selectByMouse: true
                                        color: backend.gestureRecords.length
                                               ? theme.textPrimary
                                               : theme.textSecondary
                                        font.pixelSize: 11
                                        font.family: "Menlo"
                                        background: null
                                        padding: 10
                                    }
                                }
                            }
                        }
                    }

                    Item { width: 1; height: 24 }
                }
            }
        }
    }

    Dialog {
        id: deleteDialog
        parent: Overlay.overlay
        modal: true
        focus: true
        title: "Delete profile?"
        width: 380
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        standardButtons: Dialog.Ok | Dialog.Cancel

        function confirmDelete() {
            if (pendingDeleteProfile && pendingDeleteProfile !== "default") {
                backend.deleteProfile(pendingDeleteProfile)
                selectProfile(backend.activeProfile)
            }
            pendingDeleteProfile = ""
        }

        function cancelDelete() {
            pendingDeleteProfile = ""
        }

        onAccepted: confirmDelete()
        onRejected: cancelDelete()

        contentItem: Column {
            width: deleteDialog.availableWidth
            spacing: 10

            Text {
                width: parent.width
                text: pendingDeleteProfile
                      ? "Delete the profile for " + selectedProfileLabel + "?"
                      : ""
                font { family: uiState.fontFamily; pixelSize: 13; bold: true }
                color: theme.textPrimary
                wrapMode: Text.WordWrap
            }

            Text {
                width: parent.width
                text: "This removes its custom button mappings. The default profile will remain."
                font { family: uiState.fontFamily; pixelSize: 12 }
                color: theme.textSecondary
                wrapMode: Text.WordWrap
            }
        }
    }
}
