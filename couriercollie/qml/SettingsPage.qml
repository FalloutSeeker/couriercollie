import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// All settings are global (DESIGN.md §7). Changes are saved straight away.
Kirigami.ScrollablePage {
    id: page

    readonly property var s: backend.settings
    readonly property var gh: backend.github

    title: "Settings"
    // Which password store the desktop has: signing in needs one.
    Component.onCompleted: backend.refreshGitHub()

    Kirigami.FormLayout {
        // More room between rows, and between labels and what they label, than the form's own (its grid is
        // children[0], as Kirigami itself uses it). The folder list keeps its own spacing.
        Component.onCompleted: {
            children[0].rowSpacing = Kirigami.Units.largeSpacing;
            children[0].columnSpacing = Kirigami.Units.gridUnit;
        }

        // ---- Updates ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Checking for Updates"
        }

        QQC2.Switch {
            Kirigami.FormData.label: "Automatic checks:"
            text: "Check in the background"
            checked: page.s.autoCheck
            onToggled: backend.updateSettings({ autoCheck: checked })
        }

        QQC2.ComboBox {
            Kirigami.FormData.label: "How often:"
            enabled: page.s.autoCheck
            model: backend.checkIntervals.map(h => Labels.interval(h))
            currentIndex: backend.checkIntervals.indexOf(page.s.checkIntervalHours)
            onActivated: index => backend.updateSettings({ checkIntervalHours: backend.checkIntervals[index] })
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: "Notifications:"
            enabled: page.s.autoCheck
            text: "Show a notification when updates are found"
            checked: page.s.toasts
            onToggled: backend.updateSettings({ toasts: checked })
        }

        QQC2.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: page.s.autoCheck
                ? "Updates also show in the app and as a number on its taskbar icon."
                : "Nothing runs in the background. Use Check Now in the main window."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        // ---- Startup and tray ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Startup and Tray"
        }

        QQC2.Switch {
            objectName: "startAtLogin"
            Kirigami.FormData.label: "Start at login:"
            text: "Open couriercollie when you log in"
            checked: page.s.startAtLogin
            onToggled: backend.updateSettings({ startAtLogin: checked })
        }

        QQC2.Switch {
            objectName: "keepInTray"
            Kirigami.FormData.label: "Tray:"
            // Can always be turned off; on only where the desktop shows tray icons.
            enabled: page.s.trayAvailable || page.s.keepInTray
            text: "Enable tray icon"
            checked: page.s.keepInTray
            onToggled: backend.updateSettings({ keepInTray: checked })
        }

        QQC2.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: !page.s.trayAvailable
                ? "Your desktop doesn’t show tray icons. On GNOME, install the AppIndicator extension."
                : page.s.keepInTray
                ? "Closing the window keeps couriercollie in the tray. Quit from the tray icon’s menu." + (page.s.startAtLogin ? " At login, it starts in the tray." : "")
                : "Closing the window quits couriercollie. Automatic checks still run."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        // ---- GitHub account (DESIGN.md §8) ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "GitHub Account (optional)"
        }

        GitHubSignIn {
            Kirigami.FormData.label: "Account:"
            Kirigami.FormData.labelAlignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        }

        // ---- Scanning ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Finding Installed Repos"
        }

        QQC2.Switch {
            Kirigami.FormData.label: "Scanning:"
            text: "Allow scanning this computer"
            checked: page.s.scanning
            onToggled: backend.updateSettings({ scanning: checked })
        }

        QQC2.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: page.s.scanning
                ? "Looks for git clones, downloaded apps and packages installed from downloaded files, and lets you choose which to track (Scan, in the main window). Only what your package manager can\u2019t update is listed; anything it or Flatpak updates is left out. Repos added by hand that a scan later finds switch to the version found."
                : "Off: tracking is manual. You add repos yourself, and for each one set which version you have, or mark it as up to date."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        ColumnLayout {
            Kirigami.FormData.label: "Folders to scan:"
            Kirigami.FormData.labelAlignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            enabled: page.s.scanning
            spacing: 0

            Repeater {
                model: page.s.scanFolders

                delegate: RowLayout {
                    id: folderRow

                    required property var modelData

                    Layout.fillWidth: true

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: folderRow.modelData.label
                            textFormat: Text.PlainText
                            elide: Text.ElideMiddle
                        }

                        QQC2.Label {
                            objectName: "folderProblem:" + folderRow.modelData.path
                            Layout.fillWidth: true
                            visible: text !== ""
                            textFormat: Text.PlainText
                            text: folderRow.modelData.problem
                            font: Kirigami.Theme.smallFont
                            color: Kirigami.Theme.neutralTextColor
                            wrapMode: Text.Wrap
                        }
                    }

                    Tag {
                        visible: folderRow.modelData.isDefault
                        text: "Default"
                    }

                    QQC2.ToolButton {
                        objectName: "removeFolder:" + folderRow.modelData.path
                        icon.name: "edit-delete-remove"
                        text: `Remove ${folderRow.modelData.label}`
                        display: QQC2.AbstractButton.IconOnly
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                        QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                        onClicked: backend.removeScanFolder(folderRow.modelData.path)
                    }
                }
            }

            QQC2.Label {
                visible: page.s.scanFolders.length === 0
                text: "No folders. Only packages installed from downloaded files will be found."
                opacity: 0.7
            }

            RowLayout {
                Layout.topMargin: Kirigami.Units.smallSpacing

                QQC2.Button {
                    text: "Add Folder…"
                    icon.name: "folder-add"
                    onClicked: folderDialog.open()
                }

                QQC2.Button {
                    objectName: "restoreFolders"
                    visible: !page.s.scanFoldersAreDefault
                    text: "Reset Scan Folders"
                    icon.name: "edit-reset"
                    onClicked: backend.resetScanFolders()
                }
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: "Folders marked Default are scanned unless removed: they’re where software installed by hand usually lives. Subfolders are included, except hidden ones."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        // ---- Feedback ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Feedback"
        }

        QQC2.Button {
            objectName: "sendFeedback"
            Kirigami.FormData.label: "Problems or ideas:"
            text: "Send Feedback…"
            icon.name: "tools-report-bug"
            onClicked: feedbackDialog.open()
        }

        // ---- Back to a fresh start ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Reset"
        }

        QQC2.Button {
            objectName: "restoreDefaults"
            Kirigami.FormData.label: "All settings:"
            enabled: !page.s.areDefault
            text: "Restore to Defaults…"
            icon.name: "edit-reset"
            onClicked: restoreDialog.open()
        }

        // ---- Supporting couriercollie ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Support"
        }

        QQC2.Button {
            objectName: "donate"
            Kirigami.FormData.label: "Like couriercollie?"
            text: "Donate on Ko-fi"
            // The app's own heart: a theme without a donate icon would show its "help" icon (a question mark).
            icon.source: Qt.resolvedUrl(`../icons/${Kirigami.ColorUtils.brightnessForColor(Kirigami.Theme.backgroundColor) === Kirigami.ColorUtils.Dark ? "dark" : "light"}/help-donate.svg`)
            onClicked: Qt.openUrlExternally("https://ko-fi.com/couriercollie")
        }
    }

    Kirigami.PromptDialog {
        id: restoreDialog

        objectName: "restoreDefaultsDialog"
        // Over the Settings window, where it was asked for (a page is first made in the main window, then moved).
        parent: page.QQC2.Overlay.overlay
        preferredWidth: Kirigami.Units.gridUnit * 22
        title: "Restore to defaults?"
        subtitle: "Settings go back to how they start: automatic checks daily, scanning off and the default folders, no start at login or tray. Your tracked repos, categories and GitHub sign-in are kept."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Restore Defaults"
                icon.name: "edit-reset"
                onTriggered: restoreDialog.accept()
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: restoreDialog.reject()
            }
        ]
        onAccepted: backend.restoreDefaults()
    }

    Kirigami.PromptDialog {
        id: feedbackDialog

        objectName: "feedbackDialog"
        parent: page.QQC2.Overlay.overlay
        preferredWidth: Kirigami.Units.gridUnit * 22
        title: "Send feedback"
        subtitle: "Opens a new GitHub issue in your browser, with your couriercollie version, distro and desktop filled in. Nothing is sent until you submit it there."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Open GitHub"
                icon.name: "internet-services"
                onTriggered: feedbackDialog.accept()
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: feedbackDialog.reject()
            }
        ]
        onAccepted: Qt.openUrlExternally(backend.feedbackUrl(includeRepos.checked))

        QQC2.CheckBox {
            id: includeRepos

            objectName: "includeRepos"
            text: "Include the list of repos I track"
        }
    }

    FolderDialog {
        id: folderDialog

        title: "Add Folder to Scan"
        onAccepted: backend.addScanFolder(selectedFolder.toString())
    }
}
