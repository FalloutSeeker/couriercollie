import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    property string repoId

    objectName: "repoDetailPage"
    property var repo: backend.repo(repoId)
    property var details: backend.details(repoId)
    // Which releases are opened up, by tag. Kept here so they stay open when the list is refreshed.
    property var expanded: ({})
    readonly property bool followsReleases: repo.follow === "releases"
    readonly property bool ready: details.state === "ready"
    readonly property bool canMarkUpToDate: ready && details.status !== "" && details.status !== "Up to date"
    readonly property bool canMarkNotInstalled: ready && details.versionText !== "" && details.installed !== "-"

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

            QQC2.Label {
                Kirigami.FormData.label: "Tracking:"
                Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                text: page.repo.scanned ? `Found on this computer: ${page.repo.localPath}`
                    : page.details.versionOnly === true && page.followsReleases ? "Versions only. Set your version yourself."
                    : "Added by hand. Set your version yourself."
                wrapMode: Text.WrapAnywhere
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

            // Set from the releases list ("This is my version"), or with the buttons below.
            QQC2.Label {
                Kirigami.FormData.label: "Your version:"
                visible: page.ready && page.details.versionText !== ""
                text: page.details.versionText
                font.bold: true
            }

            QQC2.Label {
                Kirigami.FormData.label: "Status:"
                Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                visible: page.ready && page.details.status !== ""
                text: page.details.status
                font.bold: page.details.updateAvailable
                color: page.details.updateAvailable ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
                wrapMode: Text.Wrap
            }

            RowLayout {
                visible: page.canMarkUpToDate || page.canMarkNotInstalled

                QQC2.Button {
                    objectName: "markUpToDate"
                    visible: page.canMarkUpToDate
                    text: "Mark as up to date"
                    icon.name: "dialog-ok-apply"
                    onClicked: backend.markUpToDate(page.repoId)
                }

                QQC2.Button {
                    objectName: "markNotInstalled"
                    visible: page.canMarkNotInstalled
                    flat: true
                    text: "Mark as not installed"
                    icon.name: "edit-clear"
                    onClicked: backend.setInstalled(page.repoId, "-")
                }
            }

            QQC2.CheckBox {
                Kirigami.FormData.label: "Pre-releases:"
                visible: page.followsReleases
                text: "Show test versions"
                checked: page.repo.prereleases
                onToggled: backend.setPrereleases(page.repoId, checked)
            }
        }

        // ---- Which file you use: the one place to choose ----------------------------------------------------------

        ColumnLayout {
            id: picker

            readonly property var choices: page.details.fileChoices || []

            Layout.fillWidth: true
            visible: page.followsReleases && page.ready && choices.length > 0
            spacing: 0

            Kirigami.Heading {
                level: 3
                text: "Which file you use"
            }

            QQC2.Label {
                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                text: `A release can come in several files. Choose yours, and the same file is followed in every new release. These are the files in ${page.details.latestTag}, the newest release, that run on this computer.`
                wrapMode: Text.Wrap
                opacity: 0.7
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: page.details.yourFileMissing === true
                type: Kirigami.MessageType.Warning
                text: `The newest release doesn't include your file (${page.repo.assetPattern}). The project may have renamed it. Choose it again below.`
            }

            Repeater {
                model: picker.choices

                delegate: QQC2.RadioDelegate {
                    id: choice

                    required property var modelData

                    objectName: "asset:" + modelData.name
                    Layout.fillWidth: true
                    // Shows the saved choice only; a click asks the app, and its answer decides what's marked.
                    checkable: false
                    checked: modelData.selected
                    onClicked: backend.pickAsset(page.repoId, page.details.latestTag, modelData.name)

                    contentItem: ColumnLayout {
                        spacing: 0

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: choice.modelData.name
                            font.bold: choice.modelData.selected
                            elide: Text.ElideMiddle
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: choice.modelData.details
                            font: Kirigami.Theme.smallFont
                            opacity: 0.8
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        // Nothing in the newest release runs on this computer: versions only, as with scanning off.
        ColumnLayout {
            Layout.fillWidth: true
            visible: page.followsReleases && page.ready && page.details.versionOnly === true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                level: 3
                text: "Tracking versions only"
            }

            QQC2.Label {
                Layout.fillWidth: true
                text: "None of this project's files run on this computer (they're for other systems, such as Android or Windows). So only its versions are tracked: you'll hear about new releases, and you set your version yourself or mark it as up to date. Nothing is downloaded or installed."
                wrapMode: Text.Wrap
                opacity: 0.8
            }
        }

        // ---- Releases (for reading; the file is chosen above) ------------------------------------------------------

        Kirigami.Heading {
            visible: page.followsReleases && page.ready
            level: 3
            text: "Releases"
        }

        Repeater {
            model: page.followsReleases ? page.details.releases : []

            delegate: ColumnLayout {
                id: release

                required property var modelData
                required property int index
                readonly property bool open: page.isExpanded(modelData.tag, index)
                property bool notesShown: false
                property bool filesShown: false
                readonly property var yourFile: modelData.assets.find(a => a.selected) || null

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
                            visible: release.modelData.isInstalled
                            text: "your version"
                            highlighted: true
                        }

                        Tag {
                            visible: release.modelData.isLatest
                            text: "newest"
                        }

                        Tag {
                            visible: release.modelData.prerelease
                            text: "pre-release"
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
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        text: release.modelData.assets.length === 0 ? "No download files in this release (only the source code)."
                            : page.details.versionOnly === true ? `${release.modelData.assets.length} files, none for this computer.`
                            : page.repo.assetPattern === "" ? `${release.modelData.assets.length} files. Choose yours under \u201cWhich file you use\u201d.`
                            : release.yourFile ? `Your file: ${release.yourFile.name}` + (release.yourFile.details ? ` (${release.yourFile.details})` : "")
                            : "Your file isn't in this release."
                        wrapMode: Text.Wrap
                    }

                    QQC2.Button {
                        objectName: "mine:" + release.modelData.tag
                        visible: !release.modelData.isInstalled
                        text: "This is my version"
                        icon.name: "tag"
                        onClicked: backend.setInstalled(page.repoId, release.modelData.tag)
                    }

                    QQC2.Button {
                        visible: release.modelData.assets.length > 0
                        flat: true
                        icon.name: release.filesShown ? "go-up-symbolic" : "view-list-details"
                        text: release.filesShown ? "Hide files" : `Show all ${release.modelData.assets.length} files`
                        onClicked: release.filesShown = !release.filesShown
                    }

                    Repeater {
                        model: release.filesShown ? release.modelData.assets : []

                        delegate: QQC2.Label {
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.leftMargin: Kirigami.Units.largeSpacing
                            text: modelData.name + (modelData.details ? `  \u00b7  ${modelData.details}` : "")
                            font: Kirigami.Theme.smallFont
                            opacity: modelData.suits ? 0.9 : 0.5
                            elide: Text.ElideMiddle
                        }
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

                objectName: "branch:" + modelData.name
                Layout.fillWidth: true
                checkable: false
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
