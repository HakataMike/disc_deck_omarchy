import QtQuick
import qs.Commons

Rectangle {
    id: root

    property string text: ""
    property string tooltip: ""
    property bool primary: false

    signal clicked()

    implicitWidth: Style.space(primary ? 48 : 38)
    implicitHeight: Style.space(primary ? 48 : 36)
    radius: primary ? width / 2 : Style.space(8)
    color: primary ? Color.accent : (mouse.containsMouse ? Util.alpha(Color.foreground, 0.12) : Util.alpha(Color.foreground, 0.045))
    opacity: enabled ? 1 : 0.35
    Accessible.role: Accessible.Button
    Accessible.name: tooltip || text

    Text {
        anchors.centerIn: parent
        text: root.text
        textFormat: Text.PlainText
        color: root.primary ? Color.background : Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.title
    }

    MouseArea {
        id: mouse

        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    Behavior on color {
        ColorAnimation {
            duration: 120
        }

    }

}
