import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// All settings are global (DESIGN.md §7). Changes are saved straight away.
Kirigami.ScrollablePage {
    id: page

    readonly property var s: backend.settings

    title: "Settings"

    Kirigami.FormLayout {
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
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: page.s.autoCheck
                ? "With notifications off, updates still show in the app and as a number on its taskbar icon."
                : "Nothing runs in the background. Use “Check now” in the main window."
            wrapMode: Text.Wrap
            opacity: 0.7
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
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: page.s.scanning
                ? "Looks for git clones and downloaded apps, reads which version is installed, and lets you choose which to track. A Scan button appears in the main window. Repos can still be added by hand; if a scan later finds one on this computer, it switches to the version found there."
                : "Off: tracking is manual. You add repos yourself, and for each one set which version you have, or mark it as up to date."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        ColumnLayout {
            Kirigami.FormData.label: "Folders to scan:"
            Kirigami.FormData.labelAlignment: Qt.AlignTop
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            enabled: page.s.scanning
            spacing: 0

            Repeater {
                model: page.s.scanFolders

                delegate: RowLayout {
                    id: folderRow

                    required property var modelData

                    Layout.fillWidth: true

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: folderRow.modelData.label
                        elide: Text.ElideMiddle
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
                text: "No folders. Only RPMs will be found."
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
                    text: "Restore Defaults"
                    icon.name: "edit-reset"
                    onClicked: backend.resetScanFolders()
                }
            }
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: "Folders marked Default are scanned unless removed: they’re where software installed by hand usually lives. Subfolders are included, except hidden ones."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        // ---- Old versions ----

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Old Versions"
        }

        QQC2.Switch {
            Kirigami.FormData.label: "Clean up:"
            text: "Delete old versions automatically"
            checked: page.s.deleteOld
            onToggled: backend.updateSettings({ deleteOld: checked })
        }

        QQC2.ComboBox {
            Kirigami.FormData.label: "Delete after:"
            enabled: page.s.deleteOld
            model: backend.deleteAfterDays.map(d => `${d} days`)
            currentIndex: backend.deleteAfterDays.indexOf(page.s.deleteOldDays)
            onActivated: index => backend.updateSettings({ deleteOldDays: backend.deleteAfterDays[index] })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: "Kept versions let you undo an update. Once deleted, that update can’t be undone. Files that would need your password to delete are always left alone."
            wrapMode: Text.Wrap
            opacity: 0.7
        }
    }

    FolderDialog {
        id: folderDialog

        title: "Add Folder to Scan"
        onAccepted: backend.addScanFolder(selectedFolder.toString())
    }
}
