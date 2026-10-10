import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    property string repoId
    property var repo: backend.repo(repoId)
    property var details: backend.details(repoId)
    // Which releases are opened up, by tag. Kept here so they stay open when the list is refreshed.
    property var expanded: ({})
    readonly property bool followsReleases: repo.follow === "releases"
    readonly property bool ready: details.state === "ready"

    function reload() {
        repo = backend.repo(repoId);
        details = backend.details(repoId);
    }

    function isExpanded(tag, index) {
        return expanded[tag] !== undefined ? expanded[tag] : index === 0;
    }

    function toggle(tag, index) {
        const copy = Object.assign({}, expanded);
        copy[tag] = !isExpanded(tag, index);
        expanded = copy;
    }

    title: repo.name || ""
    Component.onCompleted: backend.loadDetails(repoId, false)

    actions: [
        Kirigami.Action {
            text: "Refresh"
            icon.name: "view-refresh"
            enabled: page.details.state !== "loading"
            onTriggered: backend.loadDetails(page.repoId, true)
        },
        Kirigami.Action {
            text: "Open project page"
            icon.name: "internet-services"
            onTriggered: Qt.openUrlExternally(page.repo.url)
        },
        Kirigami.Action {
            text: "Stop tracking"
            icon.name: "edit-delete-remove"
            onTriggered: removeDialog.open()
        }
    ]

    Connections {
        function onDetailsChanged(id) {
            if (id === page.repoId)
                page.reload();
        }

        function onReposChanged() {
            page.reload();
        }

        target: backend
    }

    Kirigami.PromptDialog {
        id: removeDialog

        title: `Stop tracking ${page.repo.name}?`
        subtitle: "It's only removed from this list. Nothing on your computer is changed or deleted."
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel
        onAccepted: {
            const id = page.repoId;
            applicationWindow().closeRepo();
            backend.removeRepo(id);
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.details.state === "error"
            type: Kirigami.MessageType.Error
            text: page.details.error
            actions: [
                Kirigami.Action {
                    text: "Try again"
                    icon.name: "view-refresh"
                    onTriggered: backend.loadDetails(page.repoId, true)
                }
            ]
        }

        RowLayout {
            visible: page.details.state === "loading"

            QQC2.BusyIndicator {
                running: page.details.state === "loading"
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }

            QQC2.Label {
                text: "Loading releases and branches…"
            }
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.Label {
                Kirigami.FormData.label: "Project:"
                text: `<a href="${page.repo.url}">${page.repo.url}</a>`
                textFormat: Text.StyledText
                onLinkActivated: link => Qt.openUrlExternally(link)
            }

            QQC2.Label {
                Kirigami.FormData.label: "About:"
                Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                visible: text !== ""
                text: page.details.description
                wrapMode: Text.Wrap
            }

            QQC2.ComboBox {
                Kirigami.FormData.label: "Follow:"
                model: ["Releases", "A branch (new commits)"]
                currentIndex: page.followsReleases ? 0 : 1
                enabled: page.ready && page.details.hasReleases
                onActivated: index => backend.setFollow(page.repoId, index === 1 ? "branch" : "releases")
            }

            QQC2.Label {
                Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                visible: page.ready && !page.details.hasReleases
                text: "This project doesn't publish releases, so new commits on a branch are followed instead."
                wrapMode: Text.Wrap
                opacity: 0.7
            }

            QQC2.Label {
                Kirigami.FormData.label: "Build file:"
                Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                visible: page.followsReleases
                text: page.repo.assetPattern ? page.repo.assetPattern : "Not picked yet. Choose the file you use from a release below."
                wrapMode: Text.WrapAnywhere
            }

            QQC2.CheckBox {
                Kirigami.FormData.label: "Pre-releases:"
                visible: page.followsReleases
                text: "Show test versions"
                checked: page.repo.prereleases
                onToggled: backend.setPrereleases(page.repoId, checked)
            }
        }

        // ---- Releases -----------------------------------------------------------------------------------------------

        Kirigami.Heading {
            visible: page.followsReleases && page.ready
            level: 3
            text: "Releases"
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.followsReleases && page.ready
            text: "Each release can have several build files. Pick the one you use, and the newest version of that same file is followed from then on."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        Repeater {
            model: page.followsReleases ? page.details.releases : []

            delegate: ColumnLayout {
                id: release

                required property var modelData
                required property int index
                readonly property bool open: page.isExpanded(modelData.tag, index)
                property bool notesShown: false
                property bool othersShown: false
                readonly property var forThisPC: modelData.assets.filter(a => a.suits || a.selected)
                readonly property int otherCount: modelData.assets.length - forThisPC.length

                Layout.fillWidth: true
                spacing: 0

                QQC2.ItemDelegate {
                    Layout.fillWidth: true
                    onClicked: page.toggle(release.modelData.tag, release.index)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: release.open ? "go-down-symbolic" : "go-next-symbolic"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        }

                        QQC2.Label {
                            text: release.modelData.tag
                            font.bold: true
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: release.modelData.title !== release.modelData.tag ? release.modelData.title : ""
                            elide: Text.ElideRight
                            opacity: 0.8
                        }

                        Tag {
                            visible: release.modelData.isLatest
                            text: "latest"
                        }

                        Tag {
                            visible: release.modelData.prerelease
                            text: "pre-release"
                        }

                        Tag {
                            visible: release.modelData.hasSelected
                            text: "has your file"
                            highlighted: true
                        }

                        QQC2.Label {
                            text: release.modelData.date
                            opacity: 0.7
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 1.5
                    visible: release.open
                    spacing: 0

                    QQC2.Label {
                        visible: release.modelData.assets.length === 0
                        text: "No download files in this release (only the source code)."
                        opacity: 0.7
                    }

                    QQC2.Label {
                        visible: release.modelData.assets.length > 0 && release.forThisPC.length === 0
                        text: "No files for this computer in this release."
                        opacity: 0.7
                    }

                    Repeater {
                        model: release.othersShown ? release.modelData.assets : release.forThisPC

                        delegate: QQC2.RadioDelegate {
                            id: file

                            required property var modelData

                            Layout.fillWidth: true
                            checked: modelData.selected
                            opacity: modelData.suits || modelData.selected ? 1 : 0.5
                            onClicked: backend.pickAsset(page.repoId, release.modelData.tag, modelData.name)

                            contentItem: ColumnLayout {
                                spacing: 0

                                QQC2.Label {
                                    Layout.fillWidth: true
                                    text: file.modelData.name
                                    font.bold: file.modelData.selected
                                    elide: Text.ElideMiddle
                                }

                                QQC2.Label {
                                    Layout.fillWidth: true
                                    visible: text !== ""
                                    text: [file.modelData.selected ? "✓ the one you use" : "", file.modelData.details].filter(s => s).join(" · ")
                                    font: Kirigami.Theme.smallFont
                                    opacity: 0.8
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    QQC2.Button {
                        visible: release.otherCount > 0
                        flat: true
                        icon.name: release.othersShown ? "go-up-symbolic" : "view-more-symbolic"
                        text: release.othersShown ? "Hide files for other systems" : `Show ${release.otherCount} files for other systems`
                        onClicked: release.othersShown = !release.othersShown
                    }

                    QQC2.Button {
                        visible: release.modelData.notes !== ""
                        flat: true
                        icon.name: release.notesShown ? "go-up-symbolic" : "documentinfo"
                        text: release.notesShown ? "Hide release notes" : "Show release notes"
                        onClicked: release.notesShown = !release.notesShown
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        Layout.bottomMargin: Kirigami.Units.largeSpacing
                        visible: release.notesShown
                        text: release.modelData.notes
                        textFormat: Text.MarkdownText
                        wrapMode: Text.Wrap
                        onLinkActivated: link => Qt.openUrlExternally(link)
                    }
                }
            }
        }

        QQC2.Label {
            visible: page.followsReleases && page.ready && page.details.releases.length === 0 && page.details.hasReleases
            text: "Only pre-releases so far. Tick “Show test versions” to see them."
            opacity: 0.7
        }

        // ---- Branches -----------------------------------------------------------------------------------------------

        Kirigami.Heading {
            visible: !page.followsReleases && page.ready
            level: 3
            text: "Branches"
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.followsReleases && page.ready
            text: page.details.branchError !== "" ? page.details.branchError : "Pick the branch whose new commits you want to hear about."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        Repeater {
            model: page.followsReleases ? [] : page.details.branches

            delegate: QQC2.RadioDelegate {
                id: branch

                required property var modelData

                Layout.fillWidth: true
                checked: modelData.selected
                onClicked: backend.setBranch(page.repoId, modelData.name)

                contentItem: RowLayout {
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: branch.modelData.name
                        font.bold: branch.modelData.selected
                        elide: Text.ElideRight
                    }

                    Tag {
                        visible: branch.modelData.isDefault
                        text: "default"
                    }

                    QQC2.Label {
                        text: branch.modelData.sha
                        font.family: "monospace"
                        opacity: 0.7
                    }
                }
            }
        }
    }
}
