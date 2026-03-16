import QtQuick

Image {
    id: icon

    property string name: ""
    property color iconColor: "#000000"

    function iconSource() {
        var resolvedColor = encodeURIComponent("" + iconColor)
        var resolvedSize = Math.max(12, Math.round(Math.max(width, height)))
        return "image://appicons/" + name + "?color=" + resolvedColor + "&size=" + resolvedSize
    }

    width: 20
    height: 20
    source: name ? iconSource() : ""
    sourceSize.width: width
    sourceSize.height: height
    fillMode: Image.PreserveAspectFit
    smooth: true
    mipmap: true
    asynchronous: true
    cache: true
}
