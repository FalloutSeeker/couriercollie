import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// A small rounded label, e.g. "latest" next to a release.
QQC2.Label {
    id: tag

    property bool highlighted: false

    leftPadding: Kirigami.Units.smallSpacing * 1.5
    rightPadding: Kirigami.Units.smallSpacing * 1.5
    topPadding: Kirigami.Units.smallSpacing / 2
    bottomPadding: Kirigami.Units.smallSpacing / 2
    font: Kirigami.Theme.smallFont
    color: highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor

    background: Rectangle {
        radius: height / 2
        color: tag.highlighted ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.12)
    }
}
