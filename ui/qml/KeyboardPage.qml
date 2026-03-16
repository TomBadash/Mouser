import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

/*  Keyboard remapping page — MX Keys / MX Keys S.
    Left panel  — profile list (shared with mouse page).
    Right panel — F-key grid with action picker.              */

Item {
    id: keyboardPage

    readonly property var theme: Theme.palette(uiState.darkMode)

    // ── Profile state ─────────────────────────────────────────
    property string selectedProfile: backend.activeProfile
    property string selectedProfileLabel: ""

    Component.onCompleted: selectProfile(backend.activeProfile)

    function selectProfile(name) {
        selectedProfile = name
        var profs = backend.profiles
        for (var i = 0; i < profs.length; i++) {
            if (profs[i].name === name) {
                selectedProfileLabel = profs[i].label
                break
            }
        }
        clearKeySelection()
    }

    function clearKeySelection() {
        selectedKey = ""
        selectedKeyName = ""
        selectedActionId = ""
    }

    Connections {
        target: backend
        function onProfilesChanged() {
            var profs = backend.profiles
            for (var i = 0; i < profs.length; i++) {
                if (profs[i].name === selectedProfile) {
                    selectedProfileLabel = profs[i].label
                    return
                }
            }
            selectProfile(backend.activeProfile)
        }
        function onActiveProfileChanged() {
            selectProfile(backend.activeProfile)
        }
    }

    // ── Key / hotspot state ───────────────────────────────────
    property string selectedKey: ""
    property string selectedKeyName: ""
    property string selectedActionId: ""

    function selectKey(key) {
        if (selectedKey === key) {
            clearKeySelection()
            return
        }
        var keys = backend.getProfileKeyboardMappings(selectedProfile)
        for (var i = 0; i < keys.length; i++) {
            if (keys[i].key === key) {
                selectedKey = key
                selectedKeyName = keys[i].name
                selectedActionId = keys[i].actionId
                return
            }
        }
    }

    Connections {
        target: backend
        function onMappingsChanged() {
            if (selectedKey === "") return
            var keys = backend.getProfileKeyboardMappings(selectedProfile)
            for (var i = 0; i < keys.length; i++) {
                if (keys[i].key === selectedKey) {
                    selectedActionId = keys[i].actionId
                    break
                }
            }
        }
    }

    function actionFor(key) {
        var keys = backend.getProfileKeyboardMappings(selectedProfile)
        for (var i = 0; i < keys.length; i++)
            if (keys[i].key === key) return keys[i].actionLabel
        return "Do Nothing"
    }

    function actionFor_id(key) {
        var keys = backend.getProfileKeyboardMappings(selectedProfile)
        for (var i = 0; i < keys.length; i++)
            if (keys[i].key === key) return keys[i].actionId
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
            id: kbLeftPanel
            width: 220
            height: parent.height
            color: theme.bgCard
            border.width: 1; border.color: theme.border

            Column {
                anchors.fill: parent
                spacing: 0

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

                ListView {
                    id: kbProfileList
                    width: parent.width
                    height: parent.height - 110
                    model: backend.profiles
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        width: kbProfileList.width
                        height: 58
                        color: selectedProfile === modelData.name
                               ? Qt.rgba(0, 0.83, 0.67, 0.08)
                               : kbProfItemMa.containsMouse
                                 ? Qt.rgba(1, 1, 1, 0.03)
                                 : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }

                        Row {
                            anchors {
                                fill: parent
                                leftMargin: 6; rightMargin: 10
                            }
                            spacing: 8

                            Rectangle {
                                width: 3; height: 28; radius: 2
                                color: modelData.isActive
                                       ? theme.accent : "transparent"
                                anchors.verticalCenter: parent.verticalCenter
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
                                    width: kbLeftPanel.width - 50
                                }
                                Text {
                                    text: modelData.apps.length
                                          ? modelData.apps.join(", ")
                                          : "All applications"
                                    font { family: uiState.fontFamily; pixelSize: 9 }
                                    color: theme.textSecondary
                                    elide: Text.ElideRight
                                    width: kbLeftPanel.width - 50
                                }
                            }
                        }

                        MouseArea {
                            id: kbProfItemMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: selectProfile(modelData.name)
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: theme.border }

                Item {
                    width: parent.width; height: 52

                    RowLayout {
                        anchors {
                            fill: parent
                            leftMargin: 8; rightMargin: 8
                        }
                        spacing: 4

                        ComboBox {
                            id: kbAddCombo
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
                            width: 42; height: 28; radius: 8
                            color: kbAddBtnMa.containsMouse
                                   ? theme.accentHover : theme.accent

                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                font { family: uiState.fontFamily; pixelSize: 16; bold: true }
                                color: theme.bgSidebar
                            }

                            MouseArea {
                                id: kbAddBtnMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (kbAddCombo.currentText)
                                        backend.addProfile(kbAddCombo.currentText)
                                }
                            }
                        }
                    }
                }
            }
        }

        // ══════════════════════════════════════════════════════
        // ── Right panel: keyboard keys + action picker ────────
        // ══════════════════════════════════════════════════════
        ScrollView {
            width: parent.width - kbLeftPanel.width
            height: parent.height
            contentWidth: availableWidth
            clip: true

            Flickable {
                contentHeight: kbRightCol.implicitHeight + 32
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: kbRightCol
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
                                        text: backend.deviceName !== ""
                                              && backend.deviceType === "keyboard"
                                              ? backend.deviceName
                                              : "MX Keys"
                                        font { family: uiState.fontFamily; pixelSize: 20; bold: true }
                                        color: theme.textPrimary
                                    }

                                    Rectangle {
                                        visible: selectedProfileLabel !== ""
                                        width: kbProfBadgeText.implicitWidth + 16
                                        height: 22; radius: 11
                                        color: Qt.rgba(0, 0.83, 0.67, 0.12)
                                        anchors.verticalCenter: parent.verticalCenter

                                        Text {
                                            id: kbProfBadgeText
                                            anchors.centerIn: parent
                                            text: selectedProfileLabel
                                            font { family: uiState.fontFamily; pixelSize: 11 }
                                            color: theme.accent
                                        }
                                    }
                                }

                                Text {
                                    text: "Click a key to configure its action"
                                    font { family: uiState.fontFamily; pixelSize: 12 }
                                    color: theme.textSecondary
                                }
                            }
                        }

                        // Right side: delete button + connection badge
                        Row {
                            anchors {
                                right: parent.right; rightMargin: 28
                                verticalCenter: parent.verticalCenter
                            }
                            spacing: 8

                            Rectangle {
                                visible: selectedProfile !== ""
                                         && selectedProfile !== "default"
                                width: kbDelText.implicitWidth + 20
                                height: 24; radius: 8
                                color: kbDelMa.containsMouse ? "#aa3333" : "#662222"
                                Behavior on color { ColorAnimation { duration: 120 } }
                                anchors.verticalCenter: parent.verticalCenter

                                Text {
                                    id: kbDelText
                                    anchors.centerIn: parent
                                    text: "Delete Profile"
                                    font { family: uiState.fontFamily; pixelSize: 10; bold: true }
                                    color: theme.textPrimary
                                }

                                MouseArea {
                                    id: kbDelMa
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
                    }

                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: theme.border
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    // ── F-key grid ────────────────────────────
                    Item {
                        width: parent.width
                        height: fkeyGrid.implicitHeight + 48

                        Grid {
                            id: fkeyGrid
                            anchors {
                                top: parent.top; topMargin: 24
                                left: parent.left; leftMargin: 28
                            }
                            columns: 4
                            rowSpacing: 12
                            columnSpacing: 12

                            Repeater {
                                model: backend.getProfileKeyboardMappings(selectedProfile)

                                delegate: Rectangle {
                                    width: 130; height: 72
                                    radius: 12
                                    color: selectedKey === modelData.key
                                           ? Qt.rgba(0, 0.83, 0.67, 0.15)
                                           : fkeyMa.containsMouse
                                             ? Qt.rgba(1, 1, 1, 0.06)
                                             : theme.bgCard
                                    border.width: selectedKey === modelData.key ? 2 : 1
                                    border.color: selectedKey === modelData.key
                                                  ? theme.accent : theme.border

                                    Behavior on color { ColorAnimation { duration: 120 } }
                                    Behavior on border.color { ColorAnimation { duration: 120 } }

                                    Column {
                                        anchors {
                                            fill: parent
                                            margins: 10
                                        }
                                        spacing: 4

                                        Text {
                                            text: modelData.name
                                            font {
                                                family: uiState.fontFamily
                                                pixelSize: 16
                                                bold: true
                                            }
                                            color: selectedKey === modelData.key
                                                   ? theme.accent : theme.textPrimary
                                        }

                                        Text {
                                            text: modelData.actionLabel
                                            font { family: uiState.fontFamily; pixelSize: 10 }
                                            color: theme.textSecondary
                                            elide: Text.ElideRight
                                            width: parent.width
                                        }
                                    }

                                    MouseArea {
                                        id: fkeyMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: selectKey(modelData.key)
                                    }
                                }
                            }
                        }
                    }

                    // ── Separator ─────────────────────────────
                    Rectangle {
                        width: parent.width - 56; height: 1
                        color: theme.border
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: selectedKey !== ""
                    }

                    // ── Action picker ─────────────────────────
                    Rectangle {
                        id: kbActionPicker
                        width: parent.width - 56
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: selectedKey !== ""
                                ? kbPickerCol.implicitHeight + 32 : 0
                        clip: true
                        color: "transparent"
                        visible: height > 0

                        Behavior on height {
                            NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                        }

                        Column {
                            id: kbPickerCol
                            anchors {
                                left: parent.left; right: parent.right
                                top: parent.top; topMargin: 16
                            }
                            spacing: 16

                            Row {
                                spacing: 12

                                Rectangle {
                                    width: 6; height: kbPickerTitleCol.height
                                    radius: 3; color: theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Column {
                                    id: kbPickerTitleCol
                                    spacing: 2

                                    Text {
                                        text: selectedKeyName
                                              ? selectedKeyName + " — Choose Action"
                                              : ""
                                        font { family: uiState.fontFamily; pixelSize: 15; bold: true }
                                        color: theme.textPrimary
                                    }
                                    Text {
                                        text: "Select what happens when you press this key"
                                        font { family: uiState.fontFamily; pixelSize: 12 }
                                        color: theme.textSecondary
                                        visible: selectedKey !== ""
                                    }
                                }
                            }

                            // Categorized action chips
                            Column {
                                width: parent.width
                                spacing: 14
                                visible: selectedKey !== ""

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
                                                        backend.setProfileKeyboardMapping(
                                                            selectedProfile,
                                                            selectedKey, aid)
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
