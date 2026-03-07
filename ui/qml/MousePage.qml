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
            color: Theme.bgCard
            border.width: 1; border.color: Theme.border

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
                        font { family: Theme.fontFamily; pixelSize: 14; bold: true }
                        color: Theme.textPrimary
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

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
                                       ? Theme.accent : "transparent"
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
                                    }
                                }
                            }

                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2

                                Text {
                                    text: modelData.label
                                    font {
                                        family: Theme.fontFamily
                                        pixelSize: 12; bold: true
                                    }
                                    color: selectedProfile === modelData.name
                                           ? Theme.accent : Theme.textPrimary
                                    elide: Text.ElideRight
                                    width: leftPanel.width - 70
                                }
                                Text {
                                    text: modelData.apps.length
                                          ? modelData.apps.join(", ")
                                          : "All applications"
                                    font { family: Theme.fontFamily; pixelSize: 9 }
                                    color: Theme.textSecondary
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

                Rectangle { width: parent.width; height: 1; color: Theme.border }

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
                            Material.accent: Theme.accent
                            font { family: Theme.fontFamily; pixelSize: 10 }
                        }

                        Rectangle {
                            width: 42; height: 28; radius: 8
                            color: addBtnMa.containsMouse
                                   ? Theme.accentHover : Theme.accent

                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                font { family: Theme.fontFamily; pixelSize: 16; bold: true }
                                color: Theme.bgSidebar
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
                                        font { family: Theme.fontFamily; pixelSize: 20; bold: true }
                                        color: Theme.textPrimary
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
                                            font { family: Theme.fontFamily; pixelSize: 11 }
                                            color: Theme.accent
                                        }
                                    }
                                }

                                Text {
                                    text: "Click a dot to configure its action"
                                    font { family: Theme.fontFamily; pixelSize: 12 }
                                    color: Theme.textSecondary
                                }
                            }
                        }

                        // Running badge
                        Rectangle {
                            anchors {
                                right: parent.right; rightMargin: 28
                                verticalCenter: parent.verticalCenter
                            }
                            width: statusRow.implicitWidth + 16
                            height: 24; radius: 12
                            color: Qt.rgba(0, 0.83, 0.67, 0.12)

                            Row {
                                id: statusRow
                                anchors.centerIn: parent
                                spacing: 5

                                Rectangle {
                                    width: 7; height: 7; radius: 4
                                    color: Theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: "Running"
                                    font { family: Theme.fontFamily; pixelSize: 11 }
                                    color: Theme.accent
                                }
                            }
                        }

                        // Delete profile button (not for default)
                        Rectangle {
                            visible: selectedProfile !== ""
                                     && selectedProfile !== "default"
                            anchors {
                                right: parent.right; rightMargin: 120
                                verticalCenter: parent.verticalCenter
                            }
                            width: delText.implicitWidth + 20
                            height: 24; radius: 8
                            color: delMa.containsMouse ? "#aa3333" : "#662222"
                            Behavior on color { ColorAnimation { duration: 120 } }

                            Text {
                                id: delText
                                anchors.centerIn: parent
                                text: "Delete Profile"
                                font { family: Theme.fontFamily; pixelSize: 10; bold: true }
                                color: Theme.textPrimary
                            }

                            MouseArea {
                                id: delMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    backend.deleteProfile(selectedProfile)
                                    selectProfile(backend.activeProfile)
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: Theme.border
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    // ── Mouse image with hotspots ─────────────
                    Item {
                        id: mouseImageArea
                        width: parent.width
                        height: 420

                        Rectangle {
                            anchors.fill: parent
                            color: Theme.bg
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

                    // ── Separator ─────────────────────────────
                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: Theme.border
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
                                    radius: 3; color: Theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Column {
                                    id: pickerTitleCol
                                    spacing: 2

                                    Text {
                                        text: selectedButtonName
                                              ? selectedButtonName + " — Choose Action"
                                              : ""
                                        font { family: Theme.fontFamily; pixelSize: 15; bold: true }
                                        color: Theme.textPrimary
                                    }
                                    Text {
                                        text: selectedButton === "hscroll_left"
                                              ? "Configure separate actions for scroll left and right"
                                              : "Select what happens when you use this button"
                                        font { family: Theme.fontFamily; pixelSize: 12 }
                                        color: Theme.textSecondary
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
                                    font { family: Theme.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: Theme.textDim
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
                                    font { family: Theme.fontFamily; pixelSize: 11;
                                           capitalization: Font.AllUppercase; letterSpacing: 1 }
                                    color: Theme.textDim
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

                            // Single button: categorized chips
                            Column {
                                width: parent.width
                                spacing: 14
                                visible: selectedButton !== ""
                                         && selectedButton !== "hscroll_left"

                                Repeater {
                                    model: backend.actionCategories

                                    delegate: Column {
                                        width: parent.width
                                        spacing: 8

                                        Text {
                                            text: modelData.category
                                            font { family: Theme.fontFamily; pixelSize: 11;
                                                   capitalization: Font.AllUppercase;
                                                   letterSpacing: 1 }
                                            color: Theme.textDim
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

                    Item { width: 1; height: 24 }
                }
            }
        }
    }
}
