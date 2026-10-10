import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    title: "Tracked repos"

    actions: [
        Kirigami.Action {
            id: addAction
            icon.name: "list-add"
            text: "Add"
            onTriggered: applicationWindow().showAddDialog()
        },
        Kirigami.Action {
            icon.name: "configure"
            text: "Settings"
            displayHint: Kirigami.DisplayHint.IconOnly
            onTriggered: applicationWindow().openSettings()
        }
    ]

    header: ColumnLayout {
        spacing: 0

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.configError !== ""
            type: Kirigami.MessageType.Error
            position: Kirigami.InlineMessage.Position.Header
            text: backend.configError + "\nChanges won't be saved until that file is fixed or moved away."
        }

        QQC2.ToolBar {
            Layout.fillWidth: true

            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    text: "Show:"
                }

                Repeater {
                    model: [
                        { key: "all", label: "All" },
                        { key: "github", label: "GitHub" },
                        { key: "gitlab", label: "GitLab" }
                    ]

                    delegate: QQC2.ToolButton {
                        required property var modelData

                        text: `${modelData.label} (${backend.counts[modelData.key]})`
                        checkable: true
                        checked: backend.filter === modelData.key
                        onClicked: backend.filter = modelData.key
                    }
                }

                Item {
                    Layout.fillWidth: true
                }
            }
        }
    }

    ListView {
        id: list

        model: backend.repos

        delegate: QQC2.ItemDelegate {
            id: row

            required property var modelData

            width: ListView.view.width
            highlighted: applicationWindow().currentRepoId === modelData.id
            onClicked: applicationWindow().openRepo(modelData.id)

            contentItem: RowLayout {
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    source: row.modelData.icon
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: row.modelData.name
                        font.bold: true
                        elide: Text.ElideRight
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: `${row.modelData.hostLabel} · ${row.modelData.domain}/${row.modelData.path}`
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                        elide: Text.ElideMiddle
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: row.modelData.followText
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                        elide: Text.ElideMiddle
                    }
                }
            }
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: list.count === 0
            icon.name: "folder-git"
            text: backend.filter === "all" ? "No repos tracked yet" : "No repos from this site"
            explanation: backend.filter === "all" ? "Add a GitHub or GitLab project to keep track of its releases." : ""
            helpfulAction: backend.filter === "all" ? addAction : null
        }
    }
}
