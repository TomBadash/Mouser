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
    property var    selectedProfileApps: []

    Component.onCompleted: selectProfile(backend.activeProfile)

    function selectProfile(name) {
        selectedProfile = name
        var profs = backend.profiles
        for (var i = 0; i < profs.length; i++) {
            if (profs[i].name === name) {
                selectedProfileLabel = profs[i].label
                selectedProfileApps  = profs[i].apps
                break
            }
        }
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
                    selectedProfileApps  = profs[i].apps
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
        var btns = backend.getProfileMappings(selectedProfile)
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].key === key) {
                selectedButton = key
                selectedButtonName = btns[i].name
                selectedActionId = btns[i].actionId
                return
            }
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
        var btns = backend.getProfileMappings(selectedProfile)
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].key === "hscroll_left") {
                selectedActionId = btns[i].actionId
                break
            }
        }
    }

    Connections {
        id: mappingsConn
        target: backend
        function onMappingsChanged() {
            if (selectedButton === "") return
            var btns = backend.getProfileMappings(selectedProfile)
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].key === selectedButton) {
                    selectedActionId = btns[i].actionId
                    break
                }
            }
        }
    }

    function actionFor(key) {
        var btns = backend.getProfileMappings(selectedProfile)
        for (var i = 0; i < btns.length; i++)
            if (btns[i].key === key) return btns[i].actionLabel
        return "Do Nothing"
    }

    function actionFor_id(key) {
        var btns = backend.getProfileMappings(selectedProfile)
        for (var i = 0; i < btns.length; i++)
            if (btns[i].key === key) return btns[i].actionId
        return "none"
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: leftPanel
            Layout.preferredWidth: 240
            Layout.minimumWidth: 220
            Layout.fillHeight: true
            color: theme.bgCard
            border.width: 1
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 56

                    Text {
                        anchors {
                            left: parent.left
                            leftMargin: 16
                            verticalCenter: parent.verticalCenter
                        }
                        text: "Profiles"
                        font { family: uiState.fontFamily; pixelSize: 14; bold: true }
                        color: theme.textPrimary
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: theme.border
                }

                ListView {
                    id: profileList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: backend.profiles
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        width: profileList.width
                        height: 60
                        color: selectedProfile === modelData.name
                               ? Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.08 : 0.12)
                               : profItemMa.containsMouse
                                 ? Qt.rgba(1, 1, 1, uiState.darkMode ? 0.03 : 0.65)
                                 : "transparent"

                        Accessible.role: Accessible.Button
                        Accessible.name: "Profile " + modelData.label

                        Behavior on color { ColorAnimation { duration: 120 } }

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 8
                                rightMargin: 12
                            }
                            spacing: 10

                            Rectangle {
                                width: 3
                                height: 28
                                radius: 2
                                color: modelData.isActive ? theme.accent : "transparent"
                                Layout.alignment: Qt.AlignVCenter
                            }

                            Item {
                                Layout.preferredWidth: 28
                                Layout.preferredHeight: 28
                                Layout.alignment: Qt.AlignVCenter

                                Row {
                                    id: appIconRow
                                    spacing: -4
                                    anchors.centerIn: parent
                                    visible: modelData.appIcons !== undefined && modelData.appIcons.length > 0

                                    Repeater {
                                        model: modelData.appIcons
                                        delegate: Image {
                                            source: modelData
                                                    ? "file:///" + applicationDirPath + "/images/" + modelData
                                                    : ""
                                            width: 24
                                            height: 24
                                            sourceSize.width: 24
                                            sourceSize.height: 24
                                            fillMode: Image.PreserveAspectFit
                                            visible: modelData !== ""
                                            smooth: true
                                            mipmap: true
                                            asynchronous: true
                                            cache: true
                                        }
                                    }
                                }

                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 26
                                    height: 26
                                    radius: 9
                                    visible: !appIconRow.visible && modelData.apps.length > 0
                                    color: theme.bgSubtle
                                    border.width: 1
                                    border.color: theme.border

                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.label.length ? modelData.label.charAt(0).toUpperCase() : "A"
                                        font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                                        color: theme.textSecondary
                                    }
                                }
                            }

                            Column {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 2

                                Text {
                                    text: modelData.label
                                    font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                                    color: selectedProfile === modelData.name ? theme.accent : theme.textPrimary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 78
                                }

                                Text {
                                    text: modelData.apps.length ? modelData.apps.join(", ") : "All applications"
                                    font { family: uiState.fontFamily; pixelSize: 10 }
                                    color: theme.textSecondary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 78
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

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: theme.border
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 60

                    RowLayout {
                        anchors {
                            fill: parent
                            leftMargin: 10
                            rightMargin: 10
                        }
                        spacing: 6

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
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            Accessible.name: "Add profile for application"
                        }

                        Rectangle {
                            width: 40
                            height: 32
                            radius: 10
                            color: addBtnMa.containsMouse ? theme.accentHover : theme.accent

                            Accessible.role: Accessible.Button
                            Accessible.name: "Add profile"

                            AppIcon {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                name: "plus"
                                iconColor: theme.bgSidebar
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

        ScrollView {
            id: detailsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            Column {
                id: rightCol
                width: detailsScroll.availableWidth
                spacing: 0

                Item {
                    width: parent.width
                    height: headerContent.implicitHeight + 28

                    RowLayout {
                        id: headerContent
                        anchors {
                            left: parent.left
                            right: parent.right
                            leftMargin: 28
                            rightMargin: 28
                            top: parent.top
                            topMargin: 16
                        }
                        spacing: 16

                        Column {
                            Layout.fillWidth: true
                            spacing: 4

                            Row {
                                spacing: 8

                                Text {
                                    text: "MX Master 3S"
                                    font { family: uiState.fontFamily; pixelSize: 20; bold: true }
                                    color: theme.textPrimary
                                }

                                Rectangle {
                                    visible: selectedProfileLabel !== ""
                                    width: profBadgeText.implicitWidth + 16
                                    height: 24
                                    radius: 12
                                    color: Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.12 : 0.16)
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

                        Flow {
                            id: statusFlow
                            Layout.preferredWidth: Math.min(Math.max(260, rightCol.width * 0.42), 420)
                            Layout.alignment: Qt.AlignRight | Qt.AlignTop
                            width: Layout.preferredWidth
                            spacing: 8

                            Rectangle {
                                visible: selectedProfile !== "" && selectedProfile !== "default"
                                width: delRow.implicitWidth + 18
                                height: 28
                                radius: 10
                                color: delMa.containsMouse ? theme.danger : theme.dangerBg

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

                            Rectangle {
                                visible: backend.batteryLevel >= 0
                                width: battRow.implicitWidth + 16
                                height: 28
                                radius: 12
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
                                            if (lvl < 20) return "#e05555"
                                            if (lvl <= 69) return "#e0b840"
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

                            Rectangle {
                                width: statusRow.implicitWidth + 16
                                height: 28
                                radius: 12
                                color: backend.mouseConnected
                                       ? Qt.rgba(0, 0.83, 0.67, uiState.darkMode ? 0.12 : 0.16)
                                       : Qt.rgba(0.9, 0.3, 0.3, 0.15)

                                Row {
                                    id: statusRow
                                    anchors.centerIn: parent
                                    spacing: 6

                                    Rectangle {
                                        width: 8
                                        height: 8
                                        radius: 4
                                        color: backend.mouseConnected ? theme.accent : "#e05555"
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    Text {
                                        text: backend.mouseConnected ? "Connected" : "Not Connected"
                                        font { family: uiState.fontFamily; pixelSize: 11 }
                                        color: backend.mouseConnected ? theme.accent : "#e05555"
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width - 56
                    height: 1
                    color: theme.border
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Item {
                    id: mouseImageArea
                    width: parent.width
                    height: Math.max(380, Math.min(460, parent.width * 0.52))

                    Rectangle {
                        anchors.fill: parent
                        color: theme.bg
                    }

                    Image {
                        id: mouseImg
                        source: "file:///" + applicationDirPath + "/images/mouse.png"
                        fillMode: Image.PreserveAspectFit
                        width: Math.min(mouseImageArea.width - 90, 480)
                        height: Math.min(mouseImageArea.height - 56, 360)
                        anchors.centerIn: parent
                        smooth: true
                        mipmap: true
                        asynchronous: true
                        cache: true

                        property real offX: (width - paintedWidth) / 2
                        property real offY: (height - paintedHeight) / 2
                    }

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
                        sublabel: actionFor("gesture")
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

                Rectangle {
                    width: parent.width - 56
                    height: 1
                    color: theme.border
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: selectedButton !== ""
                }

                Rectangle {
                    id: actionPicker
                    width: parent.width - 56
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: selectedButton !== "" ? pickerCol.implicitHeight + 32 : 0
                    clip: true
                    color: "transparent"
                    visible: height > 0

                    Behavior on height {
                        NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                    }

                    Column {
                        id: pickerCol
                        anchors {
                            left: parent.left
                            right: parent.right
                            top: parent.top
                            topMargin: 16
                        }
                        spacing: 16

                        Row {
                            spacing: 12

                            Rectangle {
                                width: 6
                                height: pickerTitleCol.height
                                radius: 3
                                color: theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Column {
                                id: pickerTitleCol
                                spacing: 2

                                Text {
                                    text: selectedButtonName ? selectedButtonName + " — Choose Action" : ""
                                    font { family: uiState.fontFamily; pixelSize: 15; bold: true }
                                    color: theme.textPrimary
                                }

                                Text {
                                    text: selectedButton === "hscroll_left"
                                          ? "Configure separate actions for scroll left and right"
                                          : "Select what happens when you use this button"
                                    font { family: uiState.fontFamily; pixelSize: 12 }
                                    color: theme.textSecondary
                                    visible: selectedButton !== ""
                                }
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 14
                            visible: selectedButton === "hscroll_left"

                            Text {
                                text: "SCROLL LEFT"
                                font { family: uiState.fontFamily; pixelSize: 11; capitalization: Font.AllUppercase; letterSpacing: 1 }
                                color: theme.textDim
                            }

                            Flow {
                                width: parent.width
                                spacing: 8

                                Repeater {
                                    model: backend.allActions
                                    delegate: ActionChip {
                                        actionId: modelData.id
                                        actionLabel: modelData.label
                                        isCurrent: modelData.id === actionFor_id("hscroll_left")
                                        onPicked: function(aid) {
                                            backend.setProfileMapping(selectedProfile, "hscroll_left", aid)
                                        }
                                    }
                                }
                            }

                            Item { width: 1; height: 4 }

                            Text {
                                text: "SCROLL RIGHT"
                                font { family: uiState.fontFamily; pixelSize: 11; capitalization: Font.AllUppercase; letterSpacing: 1 }
                                color: theme.textDim
                            }

                            Flow {
                                width: parent.width
                                spacing: 8

                                Repeater {
                                    model: backend.allActions
                                    delegate: ActionChip {
                                        actionId: modelData.id
                                        actionLabel: modelData.label
                                        isCurrent: modelData.id === actionFor_id("hscroll_right")
                                        onPicked: function(aid) {
                                            backend.setProfileMapping(selectedProfile, "hscroll_right", aid)
                                        }
                                    }
                                }
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 14
                            visible: selectedButton !== "" && selectedButton !== "hscroll_left"

                            Repeater {
                                model: backend.actionCategories

                                delegate: Column {
                                    width: parent.width
                                    spacing: 8

                                    Text {
                                        text: modelData.category
                                        font { family: uiState.fontFamily; pixelSize: 11; capitalization: Font.AllUppercase; letterSpacing: 1 }
                                        color: theme.textDim
                                    }

                                    Flow {
                                        width: parent.width
                                        spacing: 8

                                        Repeater {
                                            model: modelData.actions
                                            delegate: ActionChip {
                                                actionId: modelData.id
                                                actionLabel: modelData.label
                                                isCurrent: modelData.id === selectedActionId
                                                onPicked: function(aid) {
                                                    backend.setProfileMapping(selectedProfile, selectedButton, aid)
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

                Item { width: 1; height: 24 }
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
