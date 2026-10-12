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
    readonly property string currentBranch: ((details.branches || []).find(b => b.selected) || {}).name || ""
    readonly property bool ready: details.state === "ready"
    // Installed by the package manager or Flatpak: only its version is shown. Nothing here installs, updates or sets
    // its version: two updaters would fight over the same files.
    readonly property bool managed: (details.managedBy || "") !== ""
    // A scanned repo's version is read from disk, so it isn't set by hand.
    readonly property bool canMarkUpToDate: ready && !managed && !details.versionFromDisk && !details.updating
                                            && details.status !== "" && details.status !== "Up to date"
    // Built only for other systems: it can never be installed here, so it's never "not installed" either.
    readonly property bool otherSystems: (details.otherSystems || "") !== ""
    readonly property bool canMarkNotInstalled: ready && !managed && !otherSystems && !details.versionFromDisk
                                                && !details.updating && details.versionText !== ""
                                                && details.installed !== "-"
    // Update pulls a clone's new commits or moves it to the newest release; for an AppImage it downloads the newest,
    // or installs it if you don't have it yet.
    // Install rather than Update: you don't have it, or couriercollie doesn't know where your copy is (newCopy).
    readonly property bool installing: details.newCopy === true
                                       || ((details.isDownload === true || details.installClones === true)
                                           && details.statusKind === "notInstalled")
    // A clone on another branch than the one followed: Follow <its branch> is offered.
    readonly property bool canFollowDisk: ready && !managed && (details.followDiskBranch || "") !== "" && !details.updating
    readonly property bool canUpdate: ready && details.canUpdate === true && !details.updating
                                      && (details.updateAvailable === true || installing)

    function reload() {
        repo = backend.repo(repoId);
        details = backend.details(repoId);
        // Let go while open (a check found something newer than the page had): load it again. Does nothing if it's
        // already loading or loaded.
        if (details.state === "loading")
            backend.loadDetails(repoId, false);
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
            shortcut: "Ctrl+R"
            enabled: page.details.state !== "loading"
            onTriggered: backend.loadDetails(page.repoId, true)
        },
        Kirigami.Action {
            text: "Rename\u2026"
            icon.name: "edit-rename"
            onTriggered: renameDialog.open()
        },
        Kirigami.Action {
            text: "Open Project Page"
            icon.name: "internet-services"
            onTriggered: Qt.openUrlExternally(page.repo.url)
        },
        Kirigami.Action {
            text: "Stop Tracking…"
            icon.name: "edit-delete-remove"
            onTriggered: removeDialog.open()
        }
    ]

    // Rebuilt just after the current click or key press is handled, not in the middle of it (the clicked item may be
    // one that's rebuilt). Several changes in a row rebuild once.
    Connections {
        function onDetailsChanged(id) {
            if (id === page.repoId)
                Qt.callLater(page.reload);
        }

        function onReposChanged() {
            Qt.callLater(page.reload);
        }

        target: backend
    }

    // Your own name for the repo (the list's and the page's); its address stays as it is.
    Kirigami.Dialog {
        id: renameDialog

        function rename() {
            const problem = backend.renameRepo(page.repoId, nameField.text);
            renameError.text = problem;
            if (problem === "")
                renameDialog.close();
        }

        objectName: "renameDialog"
        title: "Rename"
        padding: Kirigami.Units.largeSpacing
        preferredWidth: Kirigami.Units.gridUnit * 22
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Rename"
                icon.name: "edit-rename"
                enabled: nameField.text.trim() !== ""
                onTriggered: renameDialog.rename()
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: renameDialog.close()
            }
        ]
        onOpened: {
            nameField.text = page.repo.name || "";
            renameError.text = "";
            nameField.selectAll();
            nameField.forceActiveFocus();
        }

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            Kirigami.InlineMessage {
                id: renameError

                Layout.fillWidth: true
                type: Kirigami.MessageType.Error
                visible: text !== ""
            }

            QQC2.TextField {
                id: nameField

                objectName: "renameField"
                Layout.fillWidth: true
                maximumLength: 80
                onAccepted: renameDialog.rename()
            }

            QQC2.Label {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: `Only how it\u2019s shown here. It\u2019s still ${page.repo.domain}/${page.repo.path}.`
                wrapMode: Text.Wrap
                opacity: 0.7
            }
        }
    }

    // Approving a clone's step after updates (applying.py): the command and the files it names, read first (D6).
    Kirigami.Dialog {
        id: stepDialog

        property string command

        function review(command) {
            stepDialog.command = command.trim();
            reviewText.text = backend.reviewStep(page.repoId, stepDialog.command);
            open();
        }

        objectName: "stepDialog"
        title: "Run this after each update?"
        padding: Kirigami.Units.largeSpacing
        preferredWidth: Kirigami.Units.gridUnit * 40
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            // Approved, it runs straight away (then after each update): no second click.
            Kirigami.Action {
                text: "Approve and Run"
                icon.name: "media-playback-start"
                onTriggered: {
                    backend.approveStep(page.repoId, stepDialog.command);
                    afterUpdating.editing = false;
                    stepDialog.close();
                    backend.runStep(page.repoId);
                }
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: stepDialog.close()
            }
        ]

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: `Runs now and after every update, in ${page.repo.shownPath}. Read it first: it can change anything you can. You\u2019ll be asked again if it changes.`
                wrapMode: Text.Wrap
            }

            // As tall as the text, up to about 20 lines; longer ones scroll.
            QQC2.ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(reviewText.implicitHeight, Kirigami.Units.gridUnit * 20)

                QQC2.TextArea {
                    id: reviewText

                    objectName: "reviewText"
                    readOnly: true
                    font: Kirigami.Theme.fixedWidthFont
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                }
            }
        }
    }

    Kirigami.PromptDialog {
        id: removeDialog

        title: `Stop Tracking \u201c${page.repo.name}\u201d?`
        subtitle: "It’s only removed from this list. Nothing on this computer is changed or deleted."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Stop Tracking"
                icon.name: "edit-delete-remove"
                onTriggered: removeDialog.accept()
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: removeDialog.reject()
            }
        ]
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
            text: Labels.plain(page.details.error)
            actions: [
                Kirigami.Action {
                    text: "Try Again"
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

        // ---- Name, what it is, and where -------------------------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            RepoIcon {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                Layout.preferredHeight: Kirigami.Units.iconSizes.large
                source: page.repo.icon || ""
                letter: page.repo.monogram || ""
                color: page.repo.monogramColor || "transparent"
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing / 2

                Kirigami.Heading {
                    objectName: "repoName"
                    Layout.fillWidth: true
                    level: 1
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.6
                    text: page.repo.name || ""
                    textFormat: Text.PlainText
                    elide: Text.ElideRight

                    // Double-click the name to rename it, as with a category.
                    TapHandler {
                        onDoubleTapped: renameDialog.open()
                    }
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 34
                    visible: text !== ""
                    text: page.details.description || ""
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    text: `<a href="${Labels.escaped(page.repo.url)}">${Labels.escaped(page.repo.domain + "/" + page.repo.path)}</a>`
                    textFormat: Text.StyledText
                    elide: Text.ElideMiddle
                    onLinkActivated: link => Labels.openLink(link)
                }
            }
        }

        // The package manager (or Flatpak) installed this project: it's theirs to update, so nothing here does.
        Kirigami.InlineMessage {
            objectName: "managedElsewhere"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            visible: page.ready && (page.details.managedElsewhere || "") !== ""
            type: Kirigami.MessageType.Warning
            text: Labels.plain(page.details.managedElsewhere)
        }

        // Another person's clone (in a shared folder): what's new is shown, but updating it is up to them.
        Kirigami.InlineMessage {
            objectName: "theirs"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            visible: page.ready && (page.details.theirs || "") !== ""
            type: Kirigami.MessageType.Information
            text: Labels.plain(`This clone belongs to ${page.details.theirs}, so updating it is up to them. What\u2019s new is still shown here.`)
        }

        // Built only for other systems (Android, Windows, etc.): nothing here can install it.
        Kirigami.InlineMessage {
            objectName: "otherSystems"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            visible: page.ready && page.otherSystems
            type: Kirigami.MessageType.Information
            text: Labels.plain(page.details.otherSystems)
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            visible: page.ready && page.details.localMissing === true
            type: Kirigami.MessageType.Warning
            text: Labels.plain(`It\u2019s no longer at ${page.repo.shownPath}. If it moved, scan again; if it was removed, stop tracking it.`)
        }

        // ---- Status: your version next to the newest, coloured by how they compare ------------------------------

        Rectangle {
            id: statusBox

            readonly property string kind: page.details.statusKind || ""
            readonly property color tone: kind === "update" ? Kirigami.Theme.highlightColor
                                        : kind === "current" ? Kirigami.Theme.positiveTextColor
                                        : kind === "problem" ? Kirigami.Theme.neutralTextColor
                                        : Kirigami.Theme.disabledTextColor

            objectName: "statusBox"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            Layout.topMargin: Kirigami.Units.largeSpacing
            visible: page.ready && kind !== ""
            implicitHeight: statusContent.implicitHeight + Kirigami.Units.gridUnit * 2
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, tone, 0.12)
            border.width: 1
            border.color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, tone, 0.6)

            ColumnLayout {
                id: statusContent

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Kirigami.Units.gridUnit
                spacing: Kirigami.Units.largeSpacing

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        source: ({ update: "update-low", current: "update-none", problem: "dialog-warning",
                                   ahead: "go-up", checking: "view-refresh", notInstalled: "package-x-generic",
                                   managed: "package-x-generic" })[statusBox.kind] || ""
                    }

                    Kirigami.Heading {
                        objectName: "statusHeadline"
                        Layout.fillWidth: true
                        level: 3
                        type: Kirigami.Heading.Type.Primary
                        textFormat: Text.PlainText
                        text: page.details.headline || ""
                        wrapMode: Text.Wrap
                    }
                }

                // Your version and the newest, side by side. Up to date shows yours only: they're the same.
                RowLayout {
                    spacing: Kirigami.Units.gridUnit

                    ColumnLayout {
                        spacing: 0

                        QQC2.Label {
                            text: "Your version"
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                        }

                        // Large, so the two versions can be compared at a glance.
                        Kirigami.Heading {
                            objectName: "yourVersion"
                            level: 2
                            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.5
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            text: page.details.versionText || ""
                        }
                    }

                    Kirigami.Icon {
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                        visible: statusBox.kind === "update"
                        source: "go-next"
                    }

                    ColumnLayout {
                        visible: statusBox.kind !== "current" && (page.details.newestText || "") !== ""
                        spacing: 0

                        QQC2.Label {
                            textFormat: Text.PlainText
                            text: page.followsReleases || !page.currentBranch ? "Newest" : `Newest on ${page.currentBranch}`
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                        }

                        Kirigami.Heading {
                            objectName: "newestVersion"
                            level: 2
                            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.5
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            text: page.details.newestText || ""
                        }
                    }
                }

                // Why it couldn't be compared, or what "ahead" means here, in full.
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: statusBox.kind === "problem" || statusBox.kind === "ahead" || page.canFollowDisk
                    textFormat: Text.PlainText
                    text: page.details.status || ""
                    wrapMode: Text.Wrap
                }

                // What's new on the branch since your version. One label rather than a row per commit: rows added and
                // removed as the list changes crash Qt's layout code.
                QQC2.Label {
                    objectName: "newCommits"
                    Layout.fillWidth: true
                    visible: page.details.newCommitsTotal > 0
                    text: {
                        const total = page.details.newCommitsTotal;
                        const shown = page.details.newCommits;
                        const lines = [total === 1 ? "1 new commit:" : `${total} new commits, newest first:`];
                        shown.forEach(c => lines.push(`    ${c.sha}  ${c.title}`));
                        if (total > shown.length)
                            lines.push(`    and ${total - shown.length} more`);
                        return lines.join("\n");
                    }
                    font: Kirigami.Theme.smallFont
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                }

                // Updating now, and how the last update went.
                RowLayout {
                    Layout.fillWidth: true
                    visible: page.details.updating === true
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.BusyIndicator {
                        running: parent.visible
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }

                    QQC2.Label {
                        textFormat: Text.PlainText
                        text: page.details.updatePhase === "installing" ? `Installing with ${page.details.packageTool}\u2026`
                            : page.details.isDownload ? (page.details.progress >= 0
                                  ? `Downloading\u2026 ${Math.round(page.details.progress * 100)}%` : "Downloading\u2026")
                            : page.details.installClones ? "Cloning\u2026"
                            : page.followsReleases ? "Moving to the new release\u2026" : "Pulling the new commits\u2026"
                    }

                    QQC2.ProgressBar {
                        objectName: "downloadProgress"
                        Layout.fillWidth: true
                        visible: backend.styleDrawsProgress && page.details.isDownload === true
                                 && page.details.progress >= 0 && page.details.updatePhase !== "installing"
                        value: Math.max(page.details.progress, 0)
                    }

                    // Where the style leaves progress bars blank (Fusion), one drawn here in its colors.
                    Rectangle {
                        objectName: "downloadProgressDrawn"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.smallSpacing * 2
                        visible: !backend.styleDrawsProgress && page.details.isDownload === true
                                 && page.details.progress >= 0 && page.details.updatePhase !== "installing"
                        radius: height / 2
                        color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)

                        Rectangle {
                            width: parent.width * Math.max(page.details.progress, 0)
                            height: parent.height
                            radius: parent.radius
                            color: Kirigami.Theme.highlightColor
                        }
                    }
                }

                Kirigami.InlineMessage {
                    objectName: "updateNote"
                    Layout.fillWidth: true
                    visible: !page.details.updating && (page.details.updateNote || "") !== ""
                    type: page.details.updateNoteKind === "error" ? Kirigami.MessageType.Error
                        : page.details.updateNoteKind === "warning" ? Kirigami.MessageType.Warning
                        : Kirigami.MessageType.Positive
                    text: Labels.plain(page.details.updateNote)
                }

                // couriercollie itself, updated while running.
                Kirigami.InlineMessage {
                    objectName: "restartNeeded"
                    Layout.fillWidth: true
                    visible: page.details.restartNeeded === true
                    type: Kirigami.MessageType.Information
                    text: Labels.plain(`couriercollie ${page.details.versionText} is installed. Restart it to use the new version.`
                                       + (page.details.othersUpdating ? " Once the other updates have finished." : ""))
                    actions: [
                        Kirigami.Action {
                            text: "Restart"
                            icon.name: "view-refresh"
                            enabled: !page.details.othersUpdating
                            onTriggered: backend.restartApp()
                        }
                    ]
                }

                // The archive has several programs: which one to run.
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: (page.details.programChoices || []).length > 0
                    spacing: 0

                    Repeater {
                        model: page.details.programChoices || []

                        delegate: QQC2.RadioButton {
                            required property string modelData

                            objectName: "program:" + modelData
                            text: modelData
                            onClicked: backend.chooseProgram(page.repoId, modelData)
                        }
                    }
                }

                RowLayout {
                    visible: page.canUpdate || page.canMarkUpToDate || page.canMarkNotInstalled || page.canFollowDisk

                    // Only from this click: nothing is ever updated on its own (DECISIONS.md, D4).
                    QQC2.Button {
                        objectName: "updateNow"
                        visible: page.canUpdate
                        highlighted: true
                        // What it really does: a project with nothing to install gets its source code (Inkscape's
                        // releases have no files: a user expecting the app shouldn't get a clone unawares).
                        text: (page.details.installClones ? "Clone Source Code" : page.installing ? "Install" : "Update")
                              + (page.details.updateNeedsPassword ? "\u2026" : "")
                        icon.name: page.installing ? "download" : "system-software-update"
                        onClicked: backend.updateRepo(page.repoId)
                    }

                    // A clone on another branch than the one followed: follow the one it's on.
                    QQC2.Button {
                        objectName: "followDiskBranch"
                        visible: page.canFollowDisk
                        highlighted: true
                        text: `Follow ${page.details.followDiskBranch}`
                        icon.name: "vcs-branch"
                        onClicked: backend.setBranch(page.repoId, page.details.followDiskBranch)
                    }

                    QQC2.Button {
                        objectName: "markUpToDate"
                        visible: page.canMarkUpToDate
                        text: "Mark as Up to Date"
                        icon.name: "dialog-ok-apply"
                        onClicked: backend.markUpToDate(page.repoId)
                    }

                    QQC2.Button {
                        objectName: "markNotInstalled"
                        visible: page.canMarkNotInstalled
                        flat: true
                        // No icon: a quiet, secondary choice (a red ✗ read as an error, or as deleting something).
                        text: "Mark as Not Installed"
                        onClicked: backend.setInstalled(page.repoId, "-")
                    }
                }

                Hint {
                    visible: page.canUpdate && page.installing
                    text: (page.details.newCopy
                           ? "couriercollie doesn\u2019t know where your copy is (it was added by hand), so this installs a new one, and updates that from then on. A scan finds the copy you have, so Update replaces it instead. "
                           : "")
                          + (page.details.installClones
                          ? (page.followsReleases ? `Clones the project at ${page.details.newestText} into a folder in ${page.details.clonesFolder}.`
                                                  : `Clones the project\u2019s ${page.currentBranch} branch into a folder in ${page.details.clonesFolder}.`)
                          : page.details.isPackage
                          ? `Downloads the newest release\u2019s ${page.repo.assetPattern} and installs it with ${page.details.packageTool}.`
                          : page.details.isFlatpak
                          ? `Downloads the newest release\u2019s ${page.repo.assetPattern} and installs it with Flatpak, for you only.`
                          : page.details.isProgram
                          ? `Downloads the newest release\u2019s ${page.repo.assetPattern}, unpacks it into ${page.details.programsFolder}, and puts a link to its program in ${page.details.binFolder}, so it runs as a command.`
                          : `Downloads the newest release\u2019s ${page.repo.assetPattern || "file"} into ${page.details.installFolder}, and adds it to the menu.`)
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    visible: page.canUpdate && page.details.updateNeedsPassword === true
                    textFormat: Text.PlainText
                    text: page.details.isPackage
                          ? `${page.details.packageTool} installs it for the whole system, so it asks for your password.`
                          : "This clone belongs to the system, so Update asks for your password."
                    font: Kirigami.Theme.smallFont
                    wrapMode: Text.Wrap
                }

                Hint {
                    visible: page.details.versionFromDisk === true && !page.details.localMissing
                    text: "Your version is read from this computer when the page first opens, and again on Refresh."
                }
            }
        }

        // ---- After updating (a clone): one step, approved once, run after each Update (applying.py) --------------

        ColumnLayout {
            id: afterUpdating

            readonly property bool hasStep: (page.details.step || "") !== ""
            readonly property bool running: page.details.stepRunning === true
            readonly property string result: page.details.stepResult || ""
            // Choosing or changing the step.
            property bool editing: false

            objectName: "afterUpdating"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            Layout.topMargin: Kirigami.Units.gridUnit
            visible: page.ready && page.details.afterUpdating === true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                level: 3
                text: "After Updating"
            }

            Kirigami.InlineMessage {
                objectName: "applyReminder"
                Layout.fillWidth: true
                visible: (page.details.applyReminder || "") !== "" && page.details.stepChanged !== true
                type: Kirigami.MessageType.Information
                text: Labels.plain(page.details.applyReminder)
                actions: [
                    Kirigami.Action {
                        text: "Run Now"
                        icon.name: "media-playback-start"
                        visible: afterUpdating.hasStep
                        onTriggered: backend.runStep(page.repoId)
                    },
                    Kirigami.Action {
                        text: "Mark as Applied"
                        icon.name: "dialog-ok-apply"
                        onTriggered: backend.markApplied(page.repoId)
                    }
                ]
            }

            Kirigami.InlineMessage {
                objectName: "stepChanged"
                Layout.fillWidth: true
                visible: page.details.stepChanged === true
                type: Kirigami.MessageType.Warning
                text: "This step changed since you approved it. Review it to run it again."
                actions: [
                    Kirigami.Action {
                        text: "Review\u2026"
                        icon.name: "document-preview"
                        onTriggered: stepDialog.review(page.details.step)
                    }
                ]
            }

            // Choosing the step: suggestions fill in the command, which can be changed before approving it.
            QQC2.Label {
                Layout.fillWidth: true
                visible: !afterUpdating.hasStep || afterUpdating.editing
                text: "What should run after each update is downloaded?"
                wrapMode: Text.Wrap
                opacity: 0.8
            }

            Flow {
                Layout.fillWidth: true
                visible: (!afterUpdating.hasStep || afterUpdating.editing) && (page.details.stepSuggestions || []).length > 0
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: page.details.stepSuggestions || []

                    delegate: QQC2.Button {
                        required property var modelData

                        objectName: "suggestion:" + modelData.label
                        text: modelData.label
                        onClicked: stepField.text = modelData.command
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: !afterUpdating.hasStep || afterUpdating.editing

                QQC2.TextField {
                    id: stepField

                    objectName: "stepField"
                    Layout.fillWidth: true
                    placeholderText: "A command, run in the clone\u2019s folder"
                    font: Kirigami.Theme.fixedWidthFont
                }

                QQC2.Button {
                    objectName: "reviewStep"
                    enabled: stepField.text.trim() !== ""
                    text: "Review and Approve\u2026"
                    icon.name: "document-preview"
                    onClicked: stepDialog.review(stepField.text)
                }

                QQC2.Button {
                    visible: afterUpdating.editing
                    text: "Cancel"
                    onClicked: afterUpdating.editing = false
                }
            }

            // The step: what runs, and how it last went.
            QQC2.Label {
                visible: afterUpdating.hasStep && !afterUpdating.editing
                text: "After each update, this runs:"
                opacity: 0.7
            }

            QQC2.Label {
                objectName: "stepCommand"
                Layout.fillWidth: true
                visible: afterUpdating.hasStep && !afterUpdating.editing
                text: page.details.step || ""
                textFormat: Text.PlainText
                font: Kirigami.Theme.fixedWidthFont
                wrapMode: Text.WrapAnywhere
            }

            RowLayout {
                visible: afterUpdating.hasStep && !afterUpdating.editing

                QQC2.Button {
                    objectName: "runStep"
                    visible: !afterUpdating.running
                    enabled: page.details.stepChanged !== true && !page.details.updating
                    text: "Run Now"
                    icon.name: "media-playback-start"
                    onClicked: backend.runStep(page.repoId)
                }

                QQC2.Button {
                    objectName: "stopStep"
                    visible: afterUpdating.running
                    text: "Stop"
                    icon.name: "media-playback-stop"
                    onClicked: backend.stopStep(page.repoId)
                }

                QQC2.BusyIndicator {
                    visible: afterUpdating.running
                    running: visible
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }

                QQC2.Button {
                    objectName: "changeStep"
                    visible: !afterUpdating.running
                    flat: true
                    text: "Change\u2026"
                    icon.name: "document-edit"
                    onClicked: {
                        stepField.text = page.details.step;
                        afterUpdating.editing = true;
                    }
                }

                QQC2.Button {
                    visible: !afterUpdating.running
                    flat: true
                    text: "Remove"
                    icon.name: "edit-delete-remove"
                    onClicked: backend.removeStep(page.repoId)
                }
            }

            Kirigami.InlineMessage {
                objectName: "stepResult"
                Layout.fillWidth: true
                visible: afterUpdating.result !== "" && !afterUpdating.running
                type: afterUpdating.result === "applied" ? Kirigami.MessageType.Positive
                    : afterUpdating.result === "failed" ? Kirigami.MessageType.Error
                    : afterUpdating.result === "password" ? Kirigami.MessageType.Warning
                    : Kirigami.MessageType.Information
                text: afterUpdating.result === "applied" ? "Applied."
                    : afterUpdating.result === "password" ? "It asked for a password, and none was given. Run it again to type it, or copy the command to run it in a terminal, then Mark as Applied."
                    : afterUpdating.result === "stopped" ? "Stopped."
                    : `Failed (exit code ${page.details.stepCode}). The end of its output is below.`
                actions: [
                    Kirigami.Action {
                        text: "Copy Command"
                        icon.name: "edit-copy"
                        visible: afterUpdating.result === "password"
                        onTriggered: backend.copyText(page.details.stepTerminalLine)
                    }
                ]
            }

            // Its output as it runs, scrolled to the end; the last lines are kept after.
            QQC2.ScrollView {
                id: outputView

                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(stepOutput.implicitHeight, Kirigami.Units.gridUnit * 12)
                visible: (page.details.stepOutput || "") !== ""
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

                QQC2.TextArea {
                    id: stepOutput

                    objectName: "stepOutput"
                    readOnly: true
                    text: page.details.stepOutput || ""
                    textFormat: TextEdit.PlainText
                    font: Kirigami.Theme.fixedWidthFont
                    // Long lines (paths, mostly) wrap rather than scroll sideways.
                    wrapMode: TextEdit.WrapAnywhere
                    onTextChanged: cursorPosition = length
                }
            }

            // The project's own steps, quoted to help choose (so only while choosing): read, never followed by the app.
            QQC2.Label {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: (page.details.applySteps || "") !== "" && (!afterUpdating.hasStep || afterUpdating.editing)
                text: (page.details.readmeUrl || "") !== ""
                      ? `The project\u2019s README says (<a href="${Labels.escaped(page.details.readmeUrl)}">open it</a>):`
                      : "The project\u2019s README says:"
                textFormat: Text.StyledText
                opacity: 0.7
                onLinkActivated: link => Labels.openLink(link)
            }

            Rectangle {
                Layout.fillWidth: true
                visible: (page.details.applySteps || "") !== "" && (!afterUpdating.hasStep || afterUpdating.editing)
                implicitHeight: steps.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.05)
                border.width: 1
                border.color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)

                QQC2.Label {
                    id: steps

                    objectName: "applySteps"
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    text: page.details.applySteps || ""
                    textFormat: Text.MarkdownText
                    wrapMode: Text.Wrap
                    onLinkActivated: link => Labels.openLink(link)
                }
            }
        }

        // ---- Tracking: what's followed, and where the repo came from ------------------------------------------------

        // Only once the page has loaded: what it says depends on the project's releases and branches.
        Kirigami.Heading {
            Layout.topMargin: Kirigami.Units.gridUnit
            visible: page.ready
            level: 3
            text: "Tracking"
        }

        // Labels on the left, lined up, so each setting can be found at a glance. Each label and its value are shown
        // or hidden together, so the two columns stay paired.
        GridLayout {
            Layout.fillWidth: true
            visible: page.ready
            Layout.maximumWidth: Kirigami.Units.gridUnit * 34
            Layout.leftMargin: Kirigami.Units.largeSpacing
            columns: 2
            columnSpacing: Kirigami.Units.gridUnit
            rowSpacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: Kirigami.Units.smallSpacing
                text: "Follow"
                opacity: 0.7
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.ComboBox {
                    // As wide as its longest choice, in every style.
                    implicitContentWidthPolicy: QQC2.ComboBox.WidestText
                    model: ["Releases", "A branch (new commits)"]
                    currentIndex: page.followsReleases ? 0 : 1
                    enabled: page.ready && page.details.hasReleases
                    onActivated: index => backend.setFollow(page.repoId, index === 1 ? "branch" : "releases")
                }

                Hint {
                    visible: page.ready && !page.details.hasReleases
                    text: "This project doesn’t publish releases, so new commits on a branch are followed instead."
                }
            }

            QQC2.Label {
                textFormat: Text.PlainText
                text: !page.followsReleases ? "Branch" : page.details.isClone ? "Releases" : "Build file"
                opacity: 0.7
            }

            QQC2.Label {
                objectName: "followedValue"
                Layout.fillWidth: true
                // The saved branch while branches load, or if they couldn't be listed.
                textFormat: Text.PlainText
                text: !page.followsReleases ? (page.currentBranch || page.repo.branch
                                               || (page.ready ? "The default branch" : "Loading\u2026"))
                    : page.details.isClone ? "Each release\u2019s source code: Update moves the clone to its tag"
                    : page.repo.assetPattern ? page.repo.assetPattern
                    : page.details.versionOnly === true ? "None (versions only)"
                    : "Not chosen yet. Choose one below."
                // A name (the branch, the build file) in bold; a sentence or a placeholder not.
                font.bold: !page.followsReleases ? page.currentBranch !== "" : !page.details.isClone && page.repo.assetPattern !== ""
                elide: Text.ElideMiddle
            }

            QQC2.Label {
                visible: (page.details.command || "") !== ""
                text: "Command"
                opacity: 0.7
            }

            QQC2.Label {
                objectName: "programCommand"
                Layout.fillWidth: true
                visible: (page.details.command || "") !== ""
                text: `<b>${Labels.escaped(page.details.command)}</b> (a link in ${Labels.escaped(page.details.binFolder)})`
                textFormat: Text.StyledText
                elide: Text.ElideMiddle
            }

            QQC2.Label {
                visible: page.followsReleases
                text: "Pre-releases"
                opacity: 0.7
            }

            QQC2.CheckBox {
                visible: page.followsReleases
                text: "Show test versions"
                checked: page.repo.prereleases
                onToggled: backend.setPrereleases(page.repoId, checked)
            }

            // The same as dragging it in the list, from the keyboard too. Once there are categories to choose.
            QQC2.Label {
                visible: backend.categories.length > 0
                text: "Category"
                opacity: 0.7
            }

            QQC2.ComboBox {
                objectName: "category"
                visible: backend.categories.length > 0
                model: ["Uncategorized", ...backend.categories]
                currentIndex: Math.max(0, backend.categories.indexOf(page.repo.category || "") + 1)
                onActivated: index => backend.moveRepo(page.repoId, index === 0 ? "" : backend.categories[index - 1], "")
            }

            QQC2.Label {
                Layout.alignment: Qt.AlignTop
                text: "Source"
                opacity: 0.7
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                QQC2.Label {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: page.repo.scanned ? "Found on this computer" : "Added by hand"
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: page.repo.scanned ? page.repo.shownPath
                        : page.managed ? "Your version is the one your package manager installed."
                        : page.followsReleases ? "You set your version: with the buttons above, or Set as My Version on a release."
                        : "You set your version, with the buttons above."
                    font: Kirigami.Theme.smallFont
                    wrapMode: page.repo.scanned ? Text.WrapAnywhere : Text.Wrap
                    opacity: 0.7
                }
            }
        }

        // ---- Your build file: the one place to choose -------------------------------------------------------------

        ColumnLayout {
            id: picker

            readonly property var choices: page.details.fileChoices || []

            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit
            visible: page.followsReleases && page.ready && choices.length > 0 && !page.details.isClone
            spacing: 0

            Kirigami.Heading {
                level: 3
                text: "Your Build File"
            }

            QQC2.Label {
                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                Layout.maximumWidth: Kirigami.Units.gridUnit * 30
                textFormat: Text.PlainText
                text: `Choose the file you use; the same file is then followed in every new release. Listed from ${page.details.latestTag}, the newest release.`
                wrapMode: Text.Wrap
                opacity: 0.7
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: page.details.yourFileMissing === true
                type: Kirigami.MessageType.Warning
                text: Labels.plain(`The newest release doesn’t include your file (${page.repo.assetPattern}). The project may have renamed it. Choose it again below.`)
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
                    // The style's own indicator is replaced by one at the row's start: some styles (Fusion) draw
                    // theirs on the right, over the row's content.
                    indicator: Item {}

                    contentItem: RowLayout {
                        QQC2.RadioButton {
                            checkable: false
                            checked: choice.checked
                            focusPolicy: Qt.NoFocus
                            onClicked: choice.clicked()
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            QQC2.Label {
                                Layout.fillWidth: true
                                text: choice.modelData.name
                                textFormat: Text.PlainText
                                font.bold: choice.modelData.selected
                                elide: Text.ElideMiddle
                            }

                            QQC2.Label {
                                Layout.fillWidth: true
                                visible: text !== ""
                                textFormat: Text.PlainText
                                text: choice.modelData.details
                                font: Kirigami.Theme.smallFont
                                opacity: 0.8
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }

        // Nothing in the newest release runs on this computer: versions only, as with scanning off.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit
            // Not when the banner above already says why (built for other systems).
            visible: page.followsReleases && page.ready && page.details.versionOnly === true && !page.details.isClone
                     && !page.otherSystems
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                level: 3
                text: "Tracking Versions Only"
            }

            QQC2.Label {
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 30
                text: "None of this project’s files run on this computer, so only its versions are tracked."
                      + (page.details.installClones ? " Clone Source Code, above, gets its source code at the newest release instead." : "")
                wrapMode: Text.Wrap
                opacity: 0.8
            }
        }

        // ---- Releases (for reading; the file is chosen above) ------------------------------------------------------

        Kirigami.Heading {
            Layout.topMargin: Kirigami.Units.gridUnit
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
                            textFormat: Text.PlainText
                            text: release.modelData.tag
                            font.bold: true
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: release.modelData.title !== release.modelData.tag ? release.modelData.title : ""
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            opacity: 0.8
                        }

                        Tag {
                            visible: release.modelData.isInstalled
                            text: "Your version"
                            highlighted: true
                        }

                        Tag {
                            visible: release.modelData.isLatest
                            text: "Newest"
                        }

                        Tag {
                            visible: release.modelData.prerelease
                            text: "Pre-release"
                        }

                        QQC2.Label {
                            textFormat: Text.PlainText
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

                    // Files don't apply to a clone: it's moved to the release's tag.
                    QQC2.Label {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        visible: !page.details.isClone
                        textFormat: Text.PlainText
                        text: release.modelData.assets.length === 0 ? "No download files in this release (only the source code)."
                            : page.details.versionOnly === true ? `${release.modelData.assets.length} files, none for this computer.`
                            : page.repo.assetPattern === "" ? `${release.modelData.assets.length} files. Choose yours under \u201cYour Build File\u201d.`
                            : release.yourFile ? `Your file: ${release.yourFile.name}` + (release.yourFile.details ? ` (${release.yourFile.details})` : "")
                            : "Your file isn’t in this release."
                        wrapMode: Text.Wrap
                    }

                    QQC2.Button {
                        objectName: "mine:" + release.modelData.tag
                        // A scanned repo's version is what's on disk, so it isn't set by hand.
                        visible: !release.modelData.isInstalled && !page.details.versionFromDisk && !page.managed
                        text: "Set as My Version"
                        icon.name: "tag"
                        onClicked: backend.setInstalled(page.repoId, release.modelData.tag)
                    }

                    QQC2.Button {
                        visible: release.modelData.assets.length > 0
                        flat: true
                        icon.name: release.filesShown ? "go-up-symbolic" : "view-list-details"
                        text: release.filesShown ? "Hide Files" : `Show All ${release.modelData.assets.length} Files`
                        onClicked: release.filesShown = !release.filesShown
                    }

                    Repeater {
                        model: release.filesShown ? release.modelData.assets : []

                        delegate: QQC2.Label {
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.leftMargin: Kirigami.Units.largeSpacing
                            text: modelData.name + (modelData.details ? `  \u00b7  ${modelData.details}` : "")
                            textFormat: Text.PlainText
                            font: Kirigami.Theme.smallFont
                            opacity: modelData.suits ? 0.9 : 0.5
                            elide: Text.ElideMiddle
                        }
                    }

                    QQC2.Button {
                        visible: release.modelData.notes !== ""
                        flat: true
                        icon.name: release.notesShown ? "go-up-symbolic" : "documentinfo"
                        text: release.notesShown ? "Hide Release Notes" : "Show Release Notes"
                        onClicked: release.notesShown = !release.notesShown
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        Layout.bottomMargin: Kirigami.Units.largeSpacing
                        visible: release.notesShown
                        // Only once asked for: Qt lays out Markdown as soon as it's given it, shown or not, and a
                        // page has up to 30 releases' notes (some very long).
                        text: release.notesShown ? release.modelData.notes : ""
                        textFormat: Text.MarkdownText
                        wrapMode: Text.Wrap
                        onLinkActivated: link => Labels.openLink(link)
                    }
                }
            }
        }

        QQC2.Button {
            objectName: "olderReleases"
            visible: page.followsReleases && page.ready && page.details.moreReleases === true
            enabled: !page.details.loadingMore
            flat: true
            text: page.details.loadingMore ? "Loading\u2026" : "Show Older Releases"
            icon.name: "go-down"
            onClicked: backend.loadOlderReleases(page.repoId)
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.followsReleases && (page.details.moreError || "") !== ""
            textFormat: Text.PlainText
            text: page.details.moreError || ""
            wrapMode: Text.Wrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.Label {
            visible: page.followsReleases && page.ready && page.details.releases.length === 0 && page.details.hasReleases
            text: "Only pre-releases so far. Tick “Show test versions” to see them."
            opacity: 0.7
        }

        // ---- Branches -----------------------------------------------------------------------------------------------

        Kirigami.Heading {
            Layout.topMargin: Kirigami.Units.gridUnit
            visible: !page.followsReleases && page.ready
            level: 3
            text: "Branches"
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.followsReleases && page.ready
            textFormat: Text.PlainText
            text: page.details.branchError !== "" ? page.details.branchError
                : "Choose the branch to follow for new commits." + (page.details.isClone && page.details.branchOnDisk
                  ? ` Your clone is on ${page.details.branchOnDisk}; Update only pulls the branch it\u2019s on.` : "")
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
                // The style's own indicator is replaced by one at the row's start: some styles (Fusion) draw
                // theirs on the right, over the row's content.
                indicator: Item {}

                contentItem: RowLayout {
                    QQC2.RadioButton {
                        checkable: false
                        checked: branch.checked
                        focusPolicy: Qt.NoFocus
                        onClicked: branch.clicked()
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: branch.modelData.name
                        textFormat: Text.PlainText
                        font.bold: branch.modelData.selected
                        elide: Text.ElideRight
                    }

                    Tag {
                        visible: branch.modelData.name === page.details.branchOnDisk
                        text: "On this computer"
                        highlighted: true
                    }

                    Tag {
                        visible: branch.modelData.isDefault
                        text: "Default"
                    }

                    QQC2.Label {
                        textFormat: Text.PlainText
                        text: branch.modelData.sha
                        font.family: "monospace"
                        opacity: 0.7
                    }
                }
            }
        }
    }
}
