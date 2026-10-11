import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// A repo's icon: its own picture when one is known for sure (icons.py), else its monogram, the first letter on a
// colour of its own. The same look on every icon theme, and never a wrong guess.
Item {
    id: root

    property string source  // "" for none
    property string letter
    property color color

    Kirigami.Icon {
        anchors.fill: parent
        visible: root.source !== ""
        source: root.source
    }

    Rectangle {
        anchors.fill: parent
        visible: root.source === ""
        radius: width * 0.22
        color: root.color

        QQC2.Label {
            anchors.centerIn: parent
            text: root.letter
            color: "white"
            font.bold: true
            font.pixelSize: parent.height * 0.55
        }
    }
}
