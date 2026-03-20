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
    property var selectedProfileMappingState: ({})
    property string appSearchText: ""
    property var filteredKnownApps: []
    property var suggestedKnownApps: []
    property var selectedKnownApp: null

    Component.onCompleted: {
        selectProfile(backend.activeProfile)
        refreshSuggestedApps()
        refreshAppSearch()
    }

    function refreshSelectedProfileMappings() {
        var mappings = backend.getProfileMappings(selectedProfile)
        var mappingState = ({})
        for (var i = 0; i < mappings.length; i++) {
            var mapping = mappings[i]
            mappingState[mapping.key] = mapping
        }
        selectedProfileMappingState = mappingState
    }

    function mappingFor(key) {
        return selectedProfileMappingState[key] || null
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

    function appMatchesSearch(app, query) {
        if (!query)
            return false
        var lowered = query.toLowerCase()
        if ((app.label || "").toLowerCase().indexOf(lowered) !== -1)
            return true
        if ((app.id || "").toLowerCase().indexOf(lowered) !== -1)
            return true
        var aliases = app.aliases || []
        for (var i = 0; i < aliases.length; i++) {
            if ((aliases[i] || "").toLowerCase().indexOf(lowered) !== -1)
                return true
        }
        return false
    }

    function appIsSystem(app) {
        var path = (app && app.path) ? app.path : ""
        return path.indexOf("/System/") === 0
    }

    function appLocationLabel(app) {
        if (!app || !app.path)
            return "Installed app"
        if (app.path.indexOf("/Applications/") === 0)
            return "Applications"
        if (app.path.indexOf("/System/Applications/") === 0)
            return "System Applications"
        if (app.path.indexOf("/System/Library/CoreServices/") === 0)
            return "macOS CoreServices"
        if (app.path.indexOf("/Users/") === 0)
            return app.path
        return app.path
    }

    function isPreferredAppLabel(label) {
        var preferred = [
            "Google Chrome", "Safari", "Arc", "Firefox", "Visual Studio Code",
            "Cursor", "Terminal", "iTerm2", "Warp", "Finder", "Figma",
            "Slack", "Discord", "Spotify", "Notion", "Preview", "Calendar",
            "Messages", "Music", "App Store", "System Settings"
        ]
        return preferred.indexOf(label || "") !== -1
    }

    function preferredAppRank(label) {
        var preferred = [
            "Google Chrome", "Safari", "Arc", "Firefox", "Visual Studio Code",
            "Cursor", "Terminal", "iTerm2", "Warp", "Finder", "Figma",
            "Slack", "Discord", "Spotify", "Notion", "Preview", "Calendar",
            "Messages", "Music", "App Store", "System Settings"
        ]
        var idx = preferred.indexOf(label || "")
        return idx === -1 ? 999 : idx
    }

    function suggestedAppScore(app) {
        var score = preferredAppRank(app.label)
        if (score === 999) {
            if (app.path && app.path.indexOf("/Applications/") === 0)
                score = 200
            else if (app.path && app.path.indexOf("/Users/") === 0)
                score = 260
            else if (appIsSystem(app))
                score = 500
            else
                score = 350
        }

        if (app.path && app.path.indexOf("/System/Library/CoreServices/") === 0)
            score += 100
        return score
    }

    function shouldSuggestApp(app) {
        if (!app || !app.label)
            return false
        if (isPreferredAppLabel(app.label))
            return true
        if (app.path && app.path.indexOf("/Applications/") === 0)
            return true
        if (app.path && app.path.indexOf("/Users/") === 0)
            return true
        return false
    }

    function refreshSuggestedApps() {
        var apps = backend.knownApps || []
        var matches = []
        for (var i = 0; i < apps.length; i++) {
            if (!shouldSuggestApp(apps[i]))
                continue
            matches.push({
                app: apps[i],
                score: suggestedAppScore(apps[i])
            })
        }

        matches.sort(function(a, b) {
            if (a.score !== b.score)
                return a.score - b.score
            return (a.app.label || "").localeCompare(b.app.label || "")
        })

        var results = []
        for (var j = 0; j < matches.length && j < 14; j++)
            results.push(matches[j].app)
        suggestedKnownApps = results
    }

    function appResultScore(app, query) {
        var lowered = query.toLowerCase()
        var label = (app.label || "").toLowerCase()
        var score = 50

        if (label === lowered)
            score = 0
        else if (label.indexOf(lowered) === 0)
            score = 1
        else if (label.indexOf(lowered) !== -1)
            score = 2

        var aliases = app.aliases || []
        for (var i = 0; i < aliases.length; i++) {
            var alias = (aliases[i] || "").toLowerCase()
            if (alias === lowered)
                score = Math.min(score, 3)
            else if (alias.indexOf(lowered) === 0)
                score = Math.min(score, 4)
            else if (alias.indexOf(lowered) !== -1)
                score = Math.min(score, 5)
        }

        if (appIsSystem(app))
            score += 10
        return score
    }

    function refreshAppSearch() {
        var query = (appSearchText || "").trim()
        var apps = backend.knownApps || []
        var matches = []

        if (query.length === 0) {
            filteredKnownApps = []
            return
        }

        for (var i = 0; i < apps.length; i++) {
            if (appMatchesSearch(apps[i], query)) {
                matches.push({
                    app: apps[i],
                    score: appResultScore(apps[i], query)
                })
            }
        }

        matches.sort(function(a, b) {
            if (a.score !== b.score)
                return a.score - b.score
            return (a.app.label || "").localeCompare(b.app.label || "")
        })

        var results = []
        for (var j = 0; j < matches.length && j < 12; j++)
            results.push(matches[j].app)

        filteredKnownApps = results
    }

    function selectKnownApp(app) {
        selectedKnownApp = app
    }

    function syncSelectedKnownApp() {
        if (!selectedKnownApp || !selectedKnownApp.id)
            return
        var apps = backend.knownApps || []
        for (var i = 0; i < apps.length; i++) {
            if (apps[i].id === selectedKnownApp.id) {
                selectedKnownApp = apps[i]
                return
            }
        }
        selectedKnownApp = null
    }

    function openAddProfileDialog() {
        selectedKnownApp = null
        appSearchText = ""
        filteredKnownApps = []
        refreshSuggestedApps()
        if (appSearchInput)
            appSearchInput.text = ""
        addAppDialog.open()
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
        function onKnownAppsChanged() {
            syncSelectedKnownApp()
            refreshSuggestedApps()
            refreshAppSearch()
            if (addAppDialog.visible)
                addAppDialog.ensureSelection()
        }
    }

    // ── Button / hotspot state ────────────────────────────────
    property string selectedButton: ""
    property string selectedButtonName: ""
    property string selectedActionId: ""
    readonly property string hscrollLeftActionId: selectedProfileMappingState.hscroll_left
                                             ? selectedProfileMappingState.hscroll_left.actionId
                                             : "none"
    readonly property string hscrollLeftActionLabel: selectedProfileMappingState.hscroll_left
                                                ? selectedProfileMappingState.hscroll_left.actionLabel
                                                : "Do Nothing"
    readonly property string hscrollRightActionId: selectedProfileMappingState.hscroll_right
                                              ? selectedProfileMappingState.hscroll_right.actionId
                                              : "none"
    readonly property string hscrollRightActionLabel: selectedProfileMappingState.hscroll_right
                                                 ? selectedProfileMappingState.hscroll_right.actionLabel
                                                 : "Do Nothing"
    readonly property string gestureTapActionId: selectedProfileMappingState.gesture
                                            ? selectedProfileMappingState.gesture.actionId
                                            : "none"
    readonly property string gestureTapActionLabel: selectedProfileMappingState.gesture
                                               ? selectedProfileMappingState.gesture.actionLabel
                                               : "Do Nothing"
    readonly property string gestureLeftActionId: selectedProfileMappingState.gesture_left
                                             ? selectedProfileMappingState.gesture_left.actionId
                                             : "none"
    readonly property string gestureRightActionId: selectedProfileMappingState.gesture_right
                                              ? selectedProfileMappingState.gesture_right.actionId
                                              : "none"
    readonly property string gestureUpActionId: selectedProfileMappingState.gesture_up
                                           ? selectedProfileMappingState.gesture_up.actionId
                                           : "none"
    readonly property string gestureDownActionId: selectedProfileMappingState.gesture_down
                                             ? selectedProfileMappingState.gesture_down.actionId
                                             : "none"
    readonly property bool hasGestureSwipeAction: gestureLeftActionId !== "none"
                                             || gestureRightActionId !== "none"
                                             || gestureUpActionId !== "none"
                                             || gestureDownActionId !== "none"

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
        if (!hasGestureSwipeAction)
            return "Tap: " + gestureTapActionLabel
        return "Tap: " + gestureTapActionLabel + " | Swipes configured"
    }

    function hotspotSublabel(hotspot) {
        if (!hotspot)
            return ""
        if (hotspot.summaryType === "gesture")
            return gestureSummary()
        if (hotspot.summaryType === "hscroll")
            return "L: " + hscrollLeftActionLabel + " | R: " + hscrollRightActionLabel
        return actionFor(hotspot.buttonKey)
    }

    function layoutHasButton(buttonKey) {
        var hotspots = backend.deviceHotspots
        for (var i = 0; i < hotspots.length; i++) {
            if (hotspots[i].buttonKey === buttonKey)
                return true
        }
        return false
    }

    function manualLayoutChoiceIndex(layoutKey) {
        var choices = backend.manualLayoutChoices
        for (var i = 0; i < choices.length; i++) {
            if (choices[i].key === layoutKey)
                return i
        }
        return 0
    }

    function currentLayoutChoiceLabel() {
        var idx = manualLayoutChoiceIndex(backend.deviceLayoutOverrideKey)
        var choices = backend.manualLayoutChoices
        if (idx >= 0 && idx < choices.length)
            return choices[idx].label
        return "Auto-detect"
    }

    Connections {
        target: backend
        function onDeviceLayoutChanged() {
            if (selectedButton !== "" && !layoutHasButton(selectedButton)) {
                selectedButton = ""
                selectedButtonName = ""
                selectedActionId = ""
            }
        }
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
            width: 248
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
                    height: parent.height - 54 - addProfileSection.height
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
                                        source: modelData || ""
                                        width: 24; height: 24
                                        sourceSize { width: 24; height: 24 }
                                        fillMode: Image.PreserveAspectFit
                                        visible: source !== ""
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
                                    text: modelData.displayApps.length
                                          ? modelData.displayApps.join(", ")
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
                    id: addProfileSection
                    width: parent.width
                    height: 88

                    Rectangle {
                        anchors {
                            fill: parent
                            leftMargin: 8
                            rightMargin: 8
                            topMargin: 10
                            bottomMargin: 10
                        }
                        radius: 14
                        color: theme.bgSubtle
                        border.width: 1
                        border.color: theme.border

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10

                            Rectangle {
                                width: 30
                                height: 30
                                radius: 10
                                anchors.verticalCenter: parent.verticalCenter
                                color: Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.16 : 0.14)

                                Text {
                                    anchors.centerIn: parent
                                    text: "+"
                                    font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                                    color: theme.accent
                                }
                            }

                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2

                                Text {
                                    text: "Add App Profile"
                                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                    color: theme.textPrimary
                                }

                                Text {
                                    text: "Search installed apps or browse for one manually"
                                    font { family: uiState.fontFamily; pixelSize: 9 }
                                    color: theme.textSecondary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 110
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: openAddProfileDialog()
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
                                        text: backend.deviceDisplayName
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
                                    text: !backend.mouseConnected
                                          ? "Turn on your Logitech mouse to start customizing buttons"
                                          : backend.hasInteractiveDeviceLayout
                                            ? "Click a dot to configure its action"
                                            : "Choose a layout mode below while we build a dedicated overlay"
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

                    Rectangle {
                        visible: backend.mouseConnected
                                 && (!backend.hasInteractiveDeviceLayout
                                 || backend.deviceLayoutOverrideKey !== ""
                                 )
                        width: Math.min(parent.width - 56, 700)
                        anchors.left: parent.left
                        anchors.leftMargin: 28
                        height: layoutModeCol.implicitHeight + 28
                        radius: 14
                        color: theme.bgCard
                        border.width: 1
                        border.color: theme.border

                        Column {
                            id: layoutModeCol
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8

                            Text {
                                text: "Layout mode"
                                font { family: uiState.fontFamily; pixelSize: 13; bold: true }
                                color: theme.textPrimary
                            }

                            Text {
                                width: parent.width
                                wrapMode: Text.WordWrap
                                text: backend.deviceLayoutOverrideKey !== ""
                                      ? "Experimental override active: " + currentLayoutChoiceLabel()
                                        + ". Switch back to Auto-detect if the hotspot map does not line up."
                                      : backend.deviceLayoutNote
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: theme.textSecondary
                            }

                            ComboBox {
                                id: layoutOverrideCombo
                                width: Math.min(parent.width, 320)
                                model: backend.manualLayoutChoices
                                textRole: "label"
                                Material.accent: theme.accent
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                currentIndex: manualLayoutChoiceIndex(backend.deviceLayoutOverrideKey)
                                onActivated: function(index) {
                                    backend.setDeviceLayoutOverride(
                                        backend.manualLayoutChoices[index].key
                                    )
                                }
                            }
                        }
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
                            source: "file:///" + applicationDirPath + "/images/" + backend.deviceImageAsset
                            fillMode: Image.PreserveAspectFit
                            width: backend.deviceImageWidth
                            height: backend.deviceImageHeight
                            anchors.centerIn: parent
                            visible: backend.mouseConnected
                            smooth: true
                            mipmap: true
                            asynchronous: true
                            cache: true

                            property real offX: (width - paintedWidth) / 2
                            property real offY: (height - paintedHeight) / 2
                        }

                        Rectangle {
                            visible: !backend.mouseConnected
                            width: Math.min(parent.width - 120, 760)
                            height: emptyStateCol.implicitHeight + 52
                            radius: 24
                            anchors.centerIn: parent
                            color: theme.bgCard
                            border.width: 1
                            border.color: theme.border

                            Column {
                                id: emptyStateCol
                                anchors.fill: parent
                                anchors.margins: 26
                                spacing: 14

                                Rectangle {
                                    width: waitingRow.implicitWidth + 16
                                    height: 28
                                    radius: 14
                                    color: Qt.rgba(0.9, 0.3, 0.3, uiState.darkMode ? 0.18 : 0.10)

                                    Row {
                                        id: waitingRow
                                        anchors.centerIn: parent
                                        spacing: 8

                                        Rectangle {
                                            width: 8
                                            height: 8
                                            radius: 4
                                            color: "#e05555"
                                            anchors.verticalCenter: parent.verticalCenter
                                        }

                                        Text {
                                            text: "Waiting for connection"
                                            font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                            color: "#e05555"
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    text: "Connect your Logitech mouse"
                                    wrapMode: Text.WordWrap
                                    font { family: uiState.fontFamily; pixelSize: 26; bold: true }
                                    color: theme.textPrimary
                                }

                                Text {
                                    width: Math.min(parent.width, 680)
                                    text: "Mouser will detect the active device, unlock button mapping, and enable the correct layout mode as soon as the mouse is available."
                                    wrapMode: Text.WordWrap
                                    font { family: uiState.fontFamily; pixelSize: 13 }
                                    color: theme.textSecondary
                                }

                                Flow {
                                    width: parent.width
                                    spacing: 10

                                    Rectangle {
                                        width: firstHint.implicitWidth + 20
                                        height: 30
                                        radius: 15
                                        color: theme.bgSubtle
                                        border.width: 1
                                        border.color: theme.border

                                        Text {
                                            id: firstHint
                                            anchors.centerIn: parent
                                            text: "Layout mode appears automatically"
                                            font { family: uiState.fontFamily; pixelSize: 11 }
                                            color: theme.textSecondary
                                        }
                                    }

                                    Rectangle {
                                        width: secondHint.implicitWidth + 20
                                        height: 30
                                        radius: 15
                                        color: theme.bgSubtle
                                        border.width: 1
                                        border.color: theme.border

                                        Text {
                                            id: secondHint
                                            anchors.centerIn: parent
                                            text: "Per-device settings stay separate"
                                            font { family: uiState.fontFamily; pixelSize: 11 }
                                            color: theme.textSecondary
                                        }
                                    }
                                }
                            }
                        }

                        Repeater {
                            model: backend.deviceHotspots

                            delegate: HotspotDot {
                                required property int index
                                readonly property var hotspot: backend.deviceHotspots[index]
                                anchors.fill: mouseImageArea
                                imgItem: mouseImg
                                normX: Number(hotspot["normX"] || 0)
                                normY: Number(hotspot["normY"] || 0)
                                buttonKey: String(hotspot["buttonKey"] || "")
                                isHScroll: hotspot["isHScroll"] === true
                                label: String(hotspot["label"] || hotspot["buttonKey"] || "")
                                sublabel: hotspotSublabel(hotspot)
                                labelSide: String(hotspot["labelSide"] || "right")
                                labelOffX: hotspot["labelOffX"] === undefined ? 120 : Number(hotspot["labelOffX"])
                                labelOffY: hotspot["labelOffY"] === undefined ? -30 : Number(hotspot["labelOffY"])
                            }
                        }

                        Rectangle {
                            visible: backend.mouseConnected && !backend.hasInteractiveDeviceLayout
                            width: Math.min(420, parent.width - 48)
                            height: fallbackCol.implicitHeight + 32
                            radius: 16
                            color: theme.bgCard
                            border.width: 1
                            border.color: theme.border
                            anchors.centerIn: parent

                            Column {
                                id: fallbackCol
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10

                                Text {
                                    text: "Interactive layout coming later"
                                    width: parent.width
                                    font { family: uiState.fontFamily; pixelSize: 15; bold: true }
                                    color: theme.textPrimary
                                }

                                Text {
                                    text: backend.deviceLayoutNote
                                    width: parent.width
                                    wrapMode: Text.WordWrap
                                    font { family: uiState.fontFamily; pixelSize: 12 }
                                    color: theme.textSecondary
                                }

                            }
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
                                            isCurrent: modelData.id === hscrollLeftActionId
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
                                            isCurrent: modelData.id === hscrollRightActionId
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
                                    currentIndex: actionIndexForId(gestureTapActionId)
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
                                        currentIndex: actionIndexForId(gestureLeftActionId)
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
                                        currentIndex: actionIndexForId(gestureRightActionId)
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
                                        currentIndex: actionIndexForId(gestureUpActionId)
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
                                        currentIndex: actionIndexForId(gestureDownActionId)
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
        id: addAppDialog
        parent: Overlay.overlay
        modal: true
        focus: true
        title: ""
        width: 720
        height: 520
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        padding: 0
        property bool searching: appSearchText.trim().length > 0
        property var visibleApps: searching ? filteredKnownApps : suggestedKnownApps

        function ensureSelection() {
            var apps = visibleApps || []
            if (!apps.length) {
                selectedKnownApp = null
                return
            }

            if (!selectedKnownApp || !selectedKnownApp.id) {
                selectedKnownApp = apps[0]
                return
            }

            for (var i = 0; i < apps.length; i++) {
                if (apps[i].id === selectedKnownApp.id)
                    return
            }

            selectedKnownApp = apps[0]
        }

        function selectedIndex() {
            var apps = visibleApps || []
            if (!selectedKnownApp || !selectedKnownApp.id)
                return -1
            for (var i = 0; i < apps.length; i++) {
                if (apps[i].id === selectedKnownApp.id)
                    return i
            }
            return -1
        }

        function moveSelection(delta) {
            var apps = visibleApps || []
            if (!apps.length)
                return

            var current = selectedIndex()
            if (current === -1)
                current = 0

            var next = current + delta
            if (next < 0)
                next = 0
            if (next >= apps.length)
                next = apps.length - 1

            selectedKnownApp = apps[next]
            if (appResultsList)
                appResultsList.positionViewAtIndex(next, ListView.Contain)
        }

        onOpened: {
            if (appSearchInput) {
                appSearchInput.text = ""
                appSearchInput.forceActiveFocus()
            }
            refreshSuggestedApps()
            refreshAppSearch()
            ensureSelection()
            backend.refreshKnownAppsSilently()
        }
        onVisibleAppsChanged: ensureSelection()

        background: Rectangle {
            radius: 24
            color: theme.bgElevated
            border.width: 1
            border.color: theme.border
        }

        contentItem: Item {
            width: addAppDialog.width
            height: addAppDialog.height

            Item {
                id: addDialogHeader
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.topMargin: 14
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                height: 42

                Column {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3

                    Text {
                        text: "Add App Profile"
                        font { family: uiState.fontFamily; pixelSize: 17; bold: true }
                        color: theme.textPrimary
                    }

                    Text {
                        text: "Choose an app. Mouser will switch to this profile when that app is focused."
                        font { family: uiState.fontFamily; pixelSize: 11 }
                        color: theme.textSecondary
                    }
                }

                Rectangle {
                    width: 34
                    height: 34
                    radius: 12
                    anchors.right: parent.right
                    anchors.rightMargin: 0
                    anchors.verticalCenter: parent.verticalCenter
                    color: closeAddDialogMa.containsMouse
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
                        id: closeAddDialogMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: addAppDialog.close()
                    }
                }
            }

            Rectangle {
                id: searchField
                anchors.top: addDialogHeader.bottom
                anchors.topMargin: 12
                anchors.left: parent.left
                anchors.leftMargin: 24
                anchors.right: browseButton.left
                anchors.rightMargin: 12
                height: 46
                radius: 16
                color: theme.bgSubtle
                border.width: 1
                border.color: appSearchInput.activeFocus ? theme.accent : theme.border

                TextInput {
                    id: appSearchInput
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    color: theme.textPrimary
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    verticalAlignment: TextInput.AlignVCenter
                    selectByMouse: true
                    clip: true

                    onTextChanged: {
                        appSearchText = text
                        refreshAppSearch()
                        addAppDialog.ensureSelection()
                    }

                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Down) {
                            addAppDialog.moveSelection(1)
                            event.accepted = true
                        } else if (event.key === Qt.Key_Up) {
                            addAppDialog.moveSelection(-1)
                            event.accepted = true
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (selectedKnownApp) {
                                backend.addProfile(selectedKnownApp.id)
                                addAppDialog.close()
                            }
                            event.accepted = true
                        }
                    }
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Search apps by name"
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    color: theme.textDim
                    visible: !appSearchInput.text.length
                }
            }

            Rectangle {
                id: browseButton
                anchors.top: searchField.top
                anchors.right: parent.right
                anchors.rightMargin: 24
                width: 112
                height: 46
                radius: 16
                color: browseDialogMa.containsMouse
                       ? Qt.rgba(1, 1, 1, uiState.darkMode ? 0.08 : 0.55)
                       : theme.bgSubtle
                border.width: 1
                border.color: theme.border

                Text {
                    anchors.centerIn: parent
                    text: "Browse"
                    font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                    color: theme.textPrimary
                }

                MouseArea {
                    id: browseDialogMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        addAppDialog.close()
                        backend.browseForAppProfile()
                    }
                }
            }

            Item {
                id: resultsBlock
                anchors.top: searchField.bottom
                anchors.topMargin: 18
                anchors.left: parent.left
                anchors.leftMargin: 24
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.bottom: footerRow.top
                anchors.bottomMargin: 20

                Row {
                    id: resultsHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    height: 22
                    spacing: 10

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: addAppDialog.searching ? "Search Results" : "Suggested Apps"
                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                        color: theme.textPrimary
                    }

                    Rectangle {
                        width: resultCountText.implicitWidth + 16
                        height: 22
                        radius: 11
                        color: Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.12 : 0.14)

                        Text {
                            id: resultCountText
                            anchors.centerIn: parent
                            text: addAppDialog.visibleApps.length
                            font { family: uiState.fontFamily; pixelSize: 10; bold: true }
                            color: theme.accent
                        }
                    }
                }

                Rectangle {
                    anchors.top: resultsHeader.bottom
                    anchors.topMargin: 12
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    radius: 20
                    color: theme.bg
                    border.width: 1
                    border.color: theme.border

                    ListView {
                        id: appResultsList
                        anchors.fill: parent
                        anchors.margins: 10
                        clip: true
                        model: addAppDialog.visibleApps
                        spacing: 6
                        visible: addAppDialog.visibleApps.length > 0
                        boundsBehavior: Flickable.StopAtBounds

                        delegate: Rectangle {
                            width: ListView.view.width
                            height: 58
                            radius: 15
                            color: selectedKnownApp && selectedKnownApp.id === modelData.id
                                   ? Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.16 : 0.12)
                                   : appRowMa.containsMouse
                                     ? Qt.rgba(1, 1, 1, uiState.darkMode ? 0.06 : 0.6)
                                     : "transparent"
                            border.width: selectedKnownApp && selectedKnownApp.id === modelData.id ? 1 : 0
                            border.color: theme.accent

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                spacing: 12

                                Image {
                                    anchors.verticalCenter: parent.verticalCenter
                                    source: modelData.iconSource || ""
                                    width: 24
                                    height: 24
                                    sourceSize.width: 24
                                    sourceSize.height: 24
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    visible: source !== ""
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2

                                    Text {
                                        text: modelData.label || ""
                                        font { family: uiState.fontFamily; pixelSize: 13; bold: true }
                                        color: theme.textPrimary
                                        elide: Text.ElideRight
                                        width: 470
                                    }

                                    Text {
                                        text: appLocationLabel(modelData)
                                        font { family: uiState.fontFamily; pixelSize: 10 }
                                        color: theme.textSecondary
                                        elide: Text.ElideRight
                                        width: 470
                                    }
                                }

                                Item {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 1
                                    height: 1
                                }
                            }

                            MouseArea {
                                id: appRowMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: selectedKnownApp = modelData
                                onDoubleClicked: {
                                    selectedKnownApp = modelData
                                    backend.addProfile(modelData.id)
                                    addAppDialog.close()
                                }
                            }
                        }
                    }

                    Column {
                        width: parent.width - 48
                        anchors.centerIn: parent
                        spacing: 8
                        visible: addAppDialog.visibleApps.length === 0

                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: addAppDialog.searching
                                  ? "No apps matched that search."
                                  : "No suggested apps available."
                            font { family: uiState.fontFamily; pixelSize: 13; bold: true }
                            color: theme.textPrimary
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: addAppDialog.searching
                                  ? "Try a different name, or use Browse to choose the app directly."
                                  : "Use the search box above, or browse to choose an app directly."
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            color: theme.textSecondary
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            Item {
                id: footerRow
                anchors.left: parent.left
                anchors.leftMargin: 24
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 24
                height: 48

                Rectangle {
                    id: createButton
                    anchors.right: parent.right
                    width: 160
                    height: parent.height
                    radius: 16
                    color: selectedKnownApp
                           ? (createDialogMa.containsMouse ? theme.accentHover : theme.accent)
                           : Qt.rgba(0, 0.83, 0.67, 0.22)

                    Text {
                        anchors.centerIn: parent
                        text: "Create Profile"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                        color: selectedKnownApp ? theme.bgSidebar : theme.textSecondary
                    }

                    MouseArea {
                        id: createDialogMa
                        anchors.fill: parent
                        enabled: !!selectedKnownApp
                        hoverEnabled: enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (selectedKnownApp) {
                                backend.addProfile(selectedKnownApp.id)
                                addAppDialog.close()
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.right: createButton.left
                    anchors.rightMargin: 10
                    width: 108
                    height: parent.height
                    radius: 16
                    color: cancelDialogMa.containsMouse
                           ? Qt.rgba(1, 1, 1, uiState.darkMode ? 0.08 : 0.55)
                           : theme.bgSubtle
                    border.width: 1
                    border.color: theme.border

                    Text {
                        anchors.centerIn: parent
                        text: "Cancel"
                        font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                        color: theme.textPrimary
                    }

                    MouseArea {
                        id: cancelDialogMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: addAppDialog.close()
                    }
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
