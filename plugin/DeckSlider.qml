import QtQuick
import qs.Commons

Item {
    id: root

    property real value: 0

    signal moved(real fraction)

    implicitHeight: Style.space(22)
    opacity: enabled ? 1 : 0.35

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: Style.space(4)
        radius: height / 2
        color: Util.alpha(Color.foreground, 0.14)
    }

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width * Math.min(1, Math.max(0, root.value))
        height: Style.space(4)
        radius: height / 2

        gradient: Gradient {
            orientation: Gradient.Horizontal

            GradientStop {
                position: 0
                color: Color.accent
            }

            GradientStop {
                position: 1
                color: "#b8a4de"
            }

        }

    }

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        x: (parent.width - width) * Math.min(1, Math.max(0, root.value))
        width: Style.space(mouse.containsMouse || mouse.pressed ? 10 : 7)
        height: width
        radius: width / 2
        color: Color.popups.text
    }

    MouseArea {
        id: mouse

        function send(x) {
            root.moved(Math.min(1, Math.max(0, x / width)));
        }

        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onPressed: function(event) {
            send(event.x);
        }
        onPositionChanged: function(event) {
            if (pressed)
                send(event.x);

        }
    }

}
