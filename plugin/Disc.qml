import QtQuick

Item {
    id: root

    readonly property real rotationAngle: image.rotation
    property bool spinning: false
    property bool hasDisc: true
    property color holeColor: "#161c30"

    Image {
        id: image

        anchors.fill: parent
        source: Qt.resolvedUrl("disc.svg")
        sourceSize: Qt.size(Math.max(64, root.width * 2), Math.max(64, root.height * 2))
        opacity: root.hasDisc ? 1 : 0.22
        smooth: true

        NumberAnimation on rotation {
            from: 0
            to: 360
            duration: 18000
            loops: Animation.Infinite
            running: root.visible && root.spinning
        }

        Behavior on opacity {
            NumberAnimation {
                duration: 220
            }

        }

    }

    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.125
        height: width
        radius: width / 2
        color: root.holeColor
    }

}
