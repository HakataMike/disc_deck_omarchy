import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root

    readonly property string helper: String(Qt.resolvedUrl("disc_deck.py")).replace(/^file:\/\//, "")
    property var state: ({
        "present": false,
        "tracks": [],
        "kind": "none",
        "status": "disconnected",
        "volume": 65
    })
    property string commandError: ""
    // Used only by the standalone visual-check harness; the installed widget defaults to live hardware.
    property bool previewMode: false
    property var queue: []
    readonly property bool hasDisc: state.status === "ready"
    readonly property bool audio: state.kind === "audio" || state.kind === "mixed"
    readonly property var tracks: state.tracks || []
    readonly property int trackIndex: Math.max(0, Math.min(tracks.length - 1, state.track || 0))
    readonly property var track: tracks.length ? tracks[trackIndex] : null
    readonly property bool playing: !!state.playing
    readonly property real animationAngle: heroDisc.rotationAngle
    readonly property color fg: Color.popups.text
    readonly property color muted: Util.alpha(fg, 0.6)

    function timeLabel(seconds) {
        var n = Math.max(0, Math.floor(Number(seconds) || 0));
        return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0");
    }

    function command(action, value) {
        if (previewMode)
            return ;

        commandError = "";
        var next = queue.slice();
        // Coalesce slider motion while a command is in flight.
        if (action === "volume" || action === "seek")
            next = next.filter(function(q) {
            return q.action !== action;
        });

        next.push({
            "action": action,
            "value": value === undefined ? null : value
        });
        queue = next;
        sendNext();
    }

    function sendNext() {
        if (control.running || !queue.length)
            return ;

        var next = queue.slice();
        var request = next.shift();
        queue = next;
        control.command = ["python3", helper, "request", JSON.stringify(request)];
        control.running = true;
    }

    moduleName: "hakatamike.disc-deck"
    ipcTarget: "hakatamike.disc-deck"
    visible: !!state.present
    implicitWidth: visible ? button.implicitWidth : 0
    implicitHeight: visible ? button.implicitHeight : 0
    onVisibleChanged: {
        if (!visible)
            close();

    }
    onOpenedChanged: {
        if (opened)
            command("refresh");

    }

    Process {
        id: backend

        command: ["python3", root.helper, "watch"]
        running: !root.previewMode
        onExited: {
            if (!root.previewMode)
                restart.start();

        }

        stdout: SplitParser {
            onRead: function(line) {
                try {
                    root.state = JSON.parse(line);
                } catch (e) {
                }
            }
        }

    }

    Timer {
        id: restart

        interval: 2000
        onTriggered: backend.running = true
    }

    Process {
        id: control

        onExited: Qt.callLater(root.sendNext)

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text);
                    if (!result.ok)
                        root.commandError = result.error || "Drive operation failed";

                } catch (e) {
                    root.commandError = "Could not contact the player";
                }
            }
        }

    }

    WidgetButton {
        id: button

        bar: root.bar
        labelVisible: false
        hasVisualContent: true
        fixedWidth: vertical ? -1 : Style.space(root.playing ? 130 : 28)
        fixedHeight: vertical ? Style.space(root.playing ? 44 : 28) : -1
        tooltipText: "Disc Deck · " + (root.playing && root.track ? root.track.title : root.state.title || "Insert a disc")
        onPressed: function(b) {
            if (b === Qt.MiddleButton && root.audio)
                root.command("play");
            else
                root.toggle();
        }
        onWheelMoved: function(delta) {
            root.command("volume", Math.min(100, Math.max(0, Number(root.state.volume || 0) + (delta > 0 ? 5 : -5))));
        }

        Row {
            anchors.centerIn: parent
            spacing: Style.space(7)

            Disc {
                width: Style.space(17)
                height: width
                anchors.verticalCenter: parent.verticalCenter
                hasDisc: root.hasDisc
                spinning: root.playing
                holeColor: Color.bar.background
            }

            Text {
                visible: root.playing && !button.vertical
                text: String(root.track ? root.track.number : 1).padStart(2, "0") + " · Playing"
                color: Color.bar.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                anchors.verticalCenter: parent.verticalCenter
            }

        }

    }

    KeyboardPanel {
        id: popup

        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened && root.visible
        focusTarget: keys
        contentWidth: fittedContentWidth(Style.space(480))
        contentHeight: fittedContentHeight(body.implicitHeight)

        PanelKeyCatcher {
            id: keys

            anchors.fill: parent
            onCloseRequested: root.close()
            onTabRequested: function(direction) {
                root.switchPanel(direction);
            }
            onActivateRequested: {
                if (root.audio)
                    root.command("play");

            }
            onMoveRequested: function(dx, dy) {
                if (dx)
                    root.command(dx > 0 ? "next" : "previous");
                else
                    root.command("volume", Number(root.state.volume || 0) - dy * 5);
            }
            onTextKey: function(text) {
                if (text === "r")
                    root.command("refresh");

            }

            Flickable {
                anchors.fill: parent
                contentWidth: width
                contentHeight: body.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: body

                    width: parent.width
                    spacing: Style.space(14)

                    Item {
                        width: parent.width
                        height: Style.space(42)

                        Text {
                            text: "DISC DECK"
                            color: Color.accent
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            font.letterSpacing: 2.2
                        }

                        Text {
                            anchors.right: parent.right
                            text: root.state.loading ? "READING…" : root.playing ? "● PLAYING" : "● CONNECTED"
                            color: root.playing ? Color.accent : root.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }

                        Text {
                            y: Style.space(25)
                            width: parent.width
                            text: root.state.model || "Optical drive"
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }

                    }

                    PanelSeparator {
                        foreground: root.fg
                    }

                    Item {
                        width: parent.width
                        height: Style.space(180)

                        Disc {
                            id: heroDisc

                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(Style.space(166), parent.width * 0.4)
                            height: width
                            hasDisc: root.hasDisc
                            spinning: root.playing && root.opened
                            holeColor: Color.popups.background
                        }

                        Column {
                            width: parent.width * 0.56
                            spacing: Style.space(8)

                            Rectangle {
                                width: badge.implicitWidth + Style.space(20)
                                height: Style.space(23)
                                radius: height / 2
                                color: Util.alpha(Color.accent, 0.12)

                                Text {
                                    id: badge

                                    anchors.centerIn: parent
                                    text: root.audio ? "AUDIO CD" : root.hasDisc ? "DATA DISC" : "OPTICAL DRIVE"
                                    color: Color.accent
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.caption
                                    font.letterSpacing: 0.8
                                }

                            }

                            Text {
                                width: parent.width
                                text: root.state.title || "Insert a disc"
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                color: root.fg
                                font.family: Style.font.family
                                font.pixelSize: Style.font.display
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                visible: root.hasDisc
                                text: root.audio ? root.tracks.length + " tracks · " + root.timeLabel(root.state.total) : root.hasDisc ? "Browse the files on your disc." : ""
                                wrapMode: Text.Wrap
                                color: root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                            }

                            Item {
                                width: 1
                                height: Style.space(4)
                            }

                            Text {
                                visible: root.audio
                                text: root.state.loading ? "READING AUDIO…" : root.playing ? "NOW PLAYING" : root.state.loaded ? "PAUSED" : "READY TO PLAY"
                                color: Color.accent
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                                font.letterSpacing: 1.1
                            }

                            Text {
                                visible: root.audio
                                text: root.track ? root.track.title : ""
                                textFormat: Text.PlainText
                                color: root.fg
                                font.family: Style.font.family
                                font.pixelSize: Style.font.heading
                            }

                        }

                    }

                    Column {
                        visible: root.audio
                        width: parent.width
                        spacing: Style.space(2)

                        DeckSlider {
                            width: parent.width
                            enabled: !!root.state.loaded
                            value: root.track && root.track.duration ? Number(root.state.position || 0) / root.track.duration : 0
                            onMoved: function(fraction) {
                                root.command("seek", fraction);
                            }
                        }

                        Item {
                            width: parent.width
                            height: Style.space(15)

                            Text {
                                text: root.timeLabel(root.state.position)
                                color: root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                            }

                            Text {
                                anchors.right: parent.right
                                text: root.timeLabel(root.track ? root.track.duration : 0)
                                color: root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                            }

                        }

                    }

                    Item {
                        width: parent.width
                        height: Style.space(root.audio ? 50 : 36)

                        Row {
                            visible: root.audio
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Style.space(6)

                            Text {
                                text: "VOL"
                                color: root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            DeckSlider {
                                width: Style.space(55)
                                value: Number(root.state.volume || 0) / 100
                                anchors.verticalCenter: parent.verticalCenter
                                onMoved: function(fraction) {
                                    root.command("volume", Math.round(fraction * 100));
                                }
                            }

                        }

                        Row {
                            visible: root.audio
                            anchors.centerIn: parent
                            spacing: Style.space(8)

                            DeckButton {
                                text: "󰒮"
                                tooltip: "Previous track"
                                enabled: !!root.state.loaded
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: root.command("previous")
                            }

                            DeckButton {
                                text: root.state.loading ? "…" : root.playing ? "Ⅱ" : "▶"
                                tooltip: "Play or pause"
                                primary: true
                                enabled: !root.state.loading
                                onClicked: root.command("play")
                            }

                            DeckButton {
                                text: "󰒭"
                                tooltip: "Next track"
                                enabled: !!root.state.loaded
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: root.command("next")
                            }

                        }

                        DeckButton {
                            anchors.left: parent.left
                            visible: !root.audio && root.hasDisc
                            implicitWidth: Style.space(125)
                            text: "Open files"
                            onClicked: {
                                root.command("open-files");
                                root.close();
                            }
                        }

                        DeckButton {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: Style.space(78)
                            text: root.state.status === "tray" ? "Close tray" : "󰇪 Eject"
                            tooltip: "Eject disc or close tray"
                            onClicked: root.command(root.state.status === "tray" ? "close-tray" : "eject")
                        }

                    }

                    Text {
                        width: parent.width
                        visible: text !== ""
                        text: root.commandError || root.state.error || ""
                        wrapMode: Text.Wrap
                        color: Color.urgent
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        textFormat: Text.PlainText
                    }

                    PanelSeparator {
                        visible: root.audio
                        foreground: root.fg
                    }

                    Text {
                        visible: root.audio
                        text: "ON THIS DISC"
                        color: root.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        font.letterSpacing: 1.4
                    }

                    ListView {
                        id: trackList

                        visible: root.audio
                        width: parent.width
                        height: Math.min(Style.space(180), count * Style.space(36))
                        model: root.tracks
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        currentIndex: root.trackIndex
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                        delegate: Rectangle {
                            id: row

                            required property var modelData
                            required property int index
                            readonly property bool selected: index === root.trackIndex && !!root.state.loaded

                            width: trackList.width
                            height: Style.space(36)
                            radius: Style.space(7)
                            color: selected ? Util.alpha(Color.accent, 0.17) : trackMouse.containsMouse ? Util.alpha(root.fg, 0.07) : "transparent"

                            Text {
                                x: Style.space(12)
                                anchors.verticalCenter: parent.verticalCenter
                                text: row.selected && root.playing ? "♫" : String(row.modelData.number).padStart(2, "0")
                                color: row.selected ? Color.accent : root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.body
                            }

                            Text {
                                x: Style.space(52)
                                width: parent.width - Style.space(120)
                                anchors.verticalCenter: parent.verticalCenter
                                text: row.modelData.title + (row.modelData.audio ? "" : " · Data")
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: row.selected ? Color.accent : root.fg
                                font.family: Style.font.family
                                font.pixelSize: Style.font.body
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: Style.space(12)
                                anchors.verticalCenter: parent.verticalCenter
                                text: root.timeLabel(row.modelData.duration)
                                color: row.selected ? Color.accent : root.muted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                            }

                            MouseArea {
                                id: trackMouse

                                anchors.fill: parent
                                hoverEnabled: true
                                enabled: row.modelData.audio && !root.state.loading
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.command("track", row.index)
                            }

                        }

                    }

                    Item {
                        width: parent.width
                        height: Style.space(18)

                        Text {
                            text: root.audio ? "SPACE play/pause · ← → tracks" : "R refresh"
                            color: root.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }

                        Text {
                            anchors.right: parent.right
                            text: "ESC close"
                            color: root.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }

                    }

                }

            }

        }

    }

}
