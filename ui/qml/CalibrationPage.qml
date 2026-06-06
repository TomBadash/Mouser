import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

/*  Hidden developer tool: a dedicated full-page layout-calibration view.
    Opened from Settings → Developer ("Apri calibrazione layout"). Renders any
    device photo (selectable, works WITHOUT the hardware connected) with either a
    measuring grid (left-click records normalized coords, right-click undoes, the
    list is copy-pasteable) or a read-only preview of that layout's hotspots and
    crown. Normalized coords transfer directly to the live device.            */

Item {
    id: calibPage
    readonly property var theme: Theme.palette(uiState.darkMode)
    // Reactive i18n — rebinds on language change; English is the fallback.
    property var s: lm.strings

    property real nx: 0
    property real ny: 0
    property var clicks: []
    property var layouts: backend.calibrationLayouts()
    property int idx: 0
    property bool preview: false
    readonly property var layout: (layouts && layouts.length > idx) ? layouts[idx] : null

    // Active-profile mappings keyed by button, for preview action labels.
    property var mapState: ({})
    function refreshMap() {
        var arr = backend.allProfileMappings(backend.activeProfile)
        var m = ({})
        for (var i = 0; i < arr.length; i++)
            m[arr[i].key] = arr[i]
        mapState = m
    }
    Component.onCompleted: refreshMap()
    Connections {
        target: backend
        function onMappingsChanged() { calibPage.refreshMap() }
        function onActiveProfileChanged() { calibPage.refreshMap() }
    }

    Rectangle { anchors.fill: parent; color: calibPage.theme.bg }

    Image {
        id: calibImg
        source: calibPage.layout ? calibPage.layout.image : ""
        fillMode: Image.PreserveAspectFit
        readonly property real aspect:
            (calibPage.layout && calibPage.layout.imageHeight > 0)
            ? calibPage.layout.imageWidth / calibPage.layout.imageHeight : 2
        width: Math.min(parent.width - 60, (parent.height - 140) * aspect, 1300)
        height: width / aspect
        anchors.centerIn: parent
        smooth: true; mipmap: true; cache: true
        property real offX: (width - paintedWidth) / 2
        property real offY: (height - paintedHeight) / 2
    }

    // ── Measuring grid ────────────────────────────────────────
    Repeater {
        model: calibPage.preview ? 0 : 21
        delegate: Rectangle {
            required property int index
            color: index % 5 === 0 ? "#ff2020" : "#ff8080"
            opacity: 0.55
            width: 1; height: calibImg.paintedHeight
            x: calibImg.x + calibImg.offX + index / 20 * calibImg.paintedWidth
            y: calibImg.y + calibImg.offY
        }
    }
    Repeater {
        model: calibPage.preview ? 0 : 21
        delegate: Rectangle {
            required property int index
            color: index % 5 === 0 ? "#2040ff" : "#80a0ff"
            opacity: 0.5
            height: 1; width: calibImg.paintedWidth
            x: calibImg.x + calibImg.offX
            y: calibImg.y + calibImg.offY + index / 20 * calibImg.paintedHeight
        }
    }
    Repeater {
        model: calibPage.preview ? [] : calibPage.clicks
        delegate: Rectangle {
            required property var modelData
            required property int index
            width: 12; height: 12; radius: 6
            color: "#ffcc00"; border.width: 1; border.color: "#000"
            x: calibImg.x + calibImg.offX + modelData.x * calibImg.paintedWidth - 6
            y: calibImg.y + calibImg.offY + modelData.y * calibImg.paintedHeight - 6
            Text {
                anchors.centerIn: parent
                text: index + 1
                font { pixelSize: 8; bold: true }
                color: "#000"
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        enabled: !calibPage.preview
        visible: !calibPage.preview
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPositionChanged: function(m) {
            calibPage.nx = (m.x - calibImg.x - calibImg.offX) / calibImg.paintedWidth
            calibPage.ny = (m.y - calibImg.y - calibImg.offY) / calibImg.paintedHeight
        }
        onClicked: function(m) {
            if (m.button === Qt.RightButton) {
                var a = calibPage.clicks.slice(); a.pop(); calibPage.clicks = a
                return
            }
            var x = (m.x - calibImg.x - calibImg.offX) / calibImg.paintedWidth
            var y = (m.y - calibImg.y - calibImg.offY) / calibImg.paintedHeight
            var arr = calibPage.clicks.slice()
            arr.push({ x: x, y: y }); calibPage.clicks = arr
        }
    }

    // ── Hotspot preview (read-only) ───────────────────────────
    Repeater {
        model: calibPage.preview && calibPage.layout ? calibPage.layout.hotspots : []
        delegate: Item {
            required property int index
            readonly property var hs: calibPage.layout.hotspots[index]
            readonly property real bw: (hs["normW"] || 0.03) * calibImg.paintedWidth
            readonly property real bh: (hs["normH"] || 0.075) * calibImg.paintedHeight
            readonly property real bx: calibImg.x + calibImg.offX + hs["normX"] * calibImg.paintedWidth
            readonly property real by: calibImg.y + calibImg.offY + hs["normY"] * calibImg.paintedHeight
            readonly property var mp: calibPage.mapState[hs["buttonKey"]]
            readonly property bool mapped: mp && mp.actionId !== "none"

            Rectangle {
                x: bx - bw / 2; y: by - bh / 2; width: bw; height: bh
                radius: Math.min(bw, bh) * 0.28
                color: mapped ? Qt.rgba(0, 0.83, 0.67, 0.16) : "transparent"
                border.width: mapped ? 1.5 : 1
                border.color: mapped ? Qt.rgba(0, 0.83, 0.67, 0.85)
                                     : Qt.rgba(0, 0.83, 0.67, 0.4)
            }
            // Function label below the key.
            Text {
                x: bx - width / 2; y: by + bh / 2 + 3
                width: Math.max(implicitWidth, bw)
                horizontalAlignment: Text.AlignHCenter
                text: { var _l = lm.strings; return lm.trButton(hs["label"] || hs["buttonKey"]) }
                font { family: uiState.fontFamily; pixelSize: 9 }
                color: calibPage.theme.textSecondary
                elide: Text.ElideRight
            }
        }
    }
    // Crown ring (preview).
    Rectangle {
        visible: calibPage.preview && calibPage.layout && !!calibPage.layout.crown
        readonly property var cr: (calibPage.layout && calibPage.layout.crown)
                                  ? calibPage.layout.crown : null
        readonly property real rr: cr ? cr.normR * calibImg.paintedWidth : 0
        x: cr ? calibImg.x + calibImg.offX + cr.normX * calibImg.paintedWidth - rr : 0
        y: cr ? calibImg.y + calibImg.offY + cr.normY * calibImg.paintedHeight - rr : 0
        width: rr * 2; height: rr * 2; radius: rr
        color: Qt.rgba(0, 0.83, 0.67, 0.12)
        border.width: 2; border.color: Qt.rgba(0, 0.83, 0.67, 0.7)
    }

    // ── Top bar: layout selector + preview toggle ─────────────
    Flow {
        id: topBar
        z: 12
        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 10 }
        spacing: 6
        Repeater {
            model: calibPage.layouts
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: lblT.implicitWidth + 16; height: 24; radius: 6
                color: calibPage.idx === index ? calibPage.theme.accent : Qt.rgba(0, 0, 0, 0.85)
                Text {
                    id: lblT; anchors.centerIn: parent
                    text: modelData.key
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: calibPage.idx === index ? calibPage.theme.bgCard : "#ffffff"
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { calibPage.idx = index; calibPage.clicks = [] }
                }
            }
        }
        Rectangle { width: 1; height: 24; color: Qt.rgba(1, 1, 1, 0.3) }
        Rectangle {
            width: pvT.implicitWidth + 16; height: 24; radius: 6
            color: calibPage.preview ? "#ffaa00" : Qt.rgba(0, 0, 0, 0.85)
            Text {
                id: pvT; anchors.centerIn: parent
                text: (calibPage.preview ? "● " : "○ ")
                      + (calibPage.s["calib.hotspot_preview"] || "hotspot preview")
                font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                color: calibPage.preview ? "#000000" : "#ffffff"
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: calibPage.preview = !calibPage.preview
            }
        }
    }

    // ── Coordinate readout (measure mode, copy-pasteable) ─────
    Rectangle {
        z: 12
        visible: !calibPage.preview
        x: 10; y: parent.height - height - 12
        width: 280
        height: coordText.implicitHeight + listEdit.implicitHeight + 18
        color: Qt.rgba(0, 0, 0, 0.9); radius: 6
        Column {
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 6 }
            spacing: 3
            Text {
                id: coordText
                text: "x: " + calibPage.nx.toFixed(4) + "   y: " + calibPage.ny.toFixed(4)
                      + "   " + (calibPage.s["calib.measure_hint"] || "(L = save, R = undo)")
                font { family: uiState.fontFamily; pixelSize: 13; bold: true }
                color: "#00ffaa"
            }
            TextEdit {
                id: listEdit
                width: parent.width
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.NoWrap
                font { family: "Consolas, monospace"; pixelSize: 12 }
                color: "#ffffff"
                selectionColor: "#00ffaa"
                text: {
                    var lines = []
                    for (var i = 0; i < calibPage.clicks.length; i++)
                        lines.push((i + 1) + ": " + calibPage.clicks[i].x.toFixed(4)
                            + ", " + calibPage.clicks[i].y.toFixed(4))
                    return lines.join("\n")
                }
            }
        }
    }

    // ── Close button ──────────────────────────────────────────
    Rectangle {
        z: 13
        anchors { bottom: parent.bottom; right: parent.right; margins: 14 }
        width: closeT.implicitWidth + 22; height: 30; radius: 8
        color: Qt.rgba(0.80, 0.22, 0.22, 0.92)
        Text {
            id: closeT; anchors.centerIn: parent
            text: "✕  " + (calibPage.s["calib.close"] || "close calibration")
            font { family: uiState.fontFamily; pixelSize: 12; bold: true }
            color: "#ffffff"
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: backend.setCalibrationMode(false)
        }
    }
}
