import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    title: "Tracked Repos"

    // The Scan button is only in the list while scanning is allowed. Listing it hidden instead makes Kirigami log
    // "Could not create delegate for ToolBarLayout" at start-up.
    actions: backend.settings.scanning ? [addAction, scanAction, checkAction, settingsAction]
                                       : [addAction, checkAction, settingsAction]

    Kirigami.Action {
        id: addAction

        icon.name: "list-add"
        text: "Add…"
        shortcut: StandardKey.New
        onTriggered: applicationWindow().showAddDialog()
    }

    Kirigami.Action {
        id: scanAction

        icon.name: "edit-find"
        text: "Scan…"
        onTriggered: applicationWindow().showScanDialog()
    }

    Kirigami.Action {
        id: checkAction

        objectName: "checkNow"
        icon.name: "system-software-update"
        text: backend.checking ? "Checking\u2026" : "Check Now"
        enabled: !backend.checking
        onTriggered: backend.checkNow()
    }

    Kirigami.Action {
        id: settingsAction

        icon.name: "configure"
        text: "Settings"
        shortcut: StandardKey.Preferences
        displayHint: Kirigami.DisplayHint.IconOnly
        onTriggered: applicationWindow().openSettings()
    }

    header: ColumnLayout {
        spacing: 0

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.configError !== ""
            type: Kirigami.MessageType.Error
            position: Kirigami.InlineMessage.Position.Header
            text: backend.configError + "\nChanges won’t be saved until that file is fixed or moved away."
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.saveError !== ""
            type: Kirigami.MessageType.Warning
            position: Kirigami.InlineMessage.Position.Header
            text: backend.saveError
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
                        id: filterButton

                        required property var modelData

                        objectName: "filter:" + modelData.key
                        text: `${modelData.label} (${backend.counts[modelData.key]})`
                        // Checkable so KDE's style draws the highlight. A click would toggle it on its own, so after
                        // each click it's tied back to the saved filter.
                        checkable: true
                        checked: backend.filter === modelData.key
                        onClicked: {
                            backend.filter = modelData.key;
                            checked = Qt.binding(() => backend.filter === filterButton.modelData.key);
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                }
            }
        }

        // How many updates, and when it last checked and checks next.
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            QQC2.BusyIndicator {
                visible: backend.checking
                running: visible
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            Kirigami.Icon {
                visible: !backend.checking && backend.checks.updates > 0
                source: "update-low"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            QQC2.Label {
                objectName: "checkSummary"
                Layout.fillWidth: true
                text: {
                    const c = backend.checks;
                    if (backend.checking)
                        return "Checking for updates\u2026";
                    const parts = [];
                    if (c.lastChecked)
                        parts.push(c.updates === 1 ? "1 update" : `${c.updates} updates`, `checked ${c.lastChecked}`);
                    else
                        parts.push("Not checked yet");
                    parts.push(c.autoCheck ? (c.nextCheck ? `next check ${c.nextCheck}` : "checks automatically")
                                           : "automatic checks are off");
                    return parts.join(" \u00b7 ");
                }
                font.bold: !backend.checking && backend.checks.updates > 0
                elide: Text.ElideRight
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.checks.error !== ""
            type: Kirigami.MessageType.Error
            text: `Couldn\u2019t check for updates: ${backend.checks.error}`
        }

        Kirigami.InlineMessage {
            objectName: "rateLimitBar"
            Layout.fillWidth: true
            visible: !backend.checking && backend.checks.rateLimited > 0
            type: Kirigami.MessageType.Warning
            showCloseButton: true
            text: {
                const c = backend.checks;
                const which = c.rateLimited === 1 ? "1 repo wasn\u2019t checked" : `${c.rateLimited} repos weren\u2019t checked`;
                const when = c.rateLimitEnds ? ` It can be checked again after ${c.rateLimitEnds}.` : "";
                return `The site\u2019s hourly limit for requests was reached, so ${which}; it keeps its last result.${when}`;
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

                // The repo's icon (icons.py), with a corner mark when it was found on this computer by a scan.
                Item {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium

                    Kirigami.Icon {
                        anchors.fill: parent
                        source: row.modelData.icon
                    }

                    Kirigami.Icon {
                        objectName: "scannedMark:" + row.modelData.id
                        visible: row.modelData.scanned
                        source: "emblem-mounted"
                        width: Kirigami.Units.iconSizes.small
                        height: Kirigami.Units.iconSizes.small
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.rightMargin: -Kirigami.Units.smallSpacing
                        anchors.bottomMargin: -Kirigami.Units.smallSpacing
                    }
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

                // The last check's result; an update gets the update icon.
                ColumnLayout {
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 10
                    visible: row.modelData.checkText !== ""
                    spacing: 0

                    Kirigami.Icon {
                        objectName: "updateIcon:" + row.modelData.id
                        Layout.alignment: Qt.AlignRight
                        visible: row.modelData.updateAvailable
                        source: "update-low"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }

                    QQC2.Label {
                        Layout.alignment: Qt.AlignRight
                        Layout.maximumWidth: Kirigami.Units.gridUnit * 10
                        horizontalAlignment: Text.AlignRight
                        // Bold through the text itself: setting font.bold here would replace the small font.
                        text: {
                            const t = row.modelData.checkText.replace(/&/g, "&amp;").replace(/</g, "&lt;");
                            return row.modelData.updateAvailable ? `<b>${t}</b>` : t;
                        }
                        textFormat: Text.StyledText
                        font: Kirigami.Theme.smallFont
                        opacity: row.modelData.updateAvailable ? 1 : 0.7
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
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
