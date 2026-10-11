import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// A line of explanation under or beside a control: smaller and fainter than what it explains, so the page can be
// read by its headings and values alone.
QQC2.Label {
    Layout.fillWidth: true
    font: Kirigami.Theme.smallFont
    wrapMode: Text.Wrap
    opacity: 0.7
}
