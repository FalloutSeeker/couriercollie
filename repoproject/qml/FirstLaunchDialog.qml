import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Shown once, the first time the app starts (DESIGN.md §6). Everything here can be changed later in Settings.
Kirigami.Dialog {
    id: dialog

    objectName: "firstLaunch"

    signal finished(bool scanning)

    function done() {
        backend.updateSettings({
            firstLaunchDone: true,
            autoCheck: autoYes.checked,
            checkIntervalHours: backend.checkIntervals[intervalBox.currentIndex],
            scanning: scanBox.checked,
            deleteOld: deleteBox.checked,
            deleteOldDays: backend.deleteAfterDays[daysBox.currentIndex]
        });
        dialog.close();
        dialog.finished(scanBox.checked);
    }

    title: "Welcome to RepoProject"
    padding: Kirigami.Units.largeSpacing * 2
    preferredWidth: Kirigami.Units.gridUnit * 30
    closePolicy: QQC2.Popup.NoAutoClose
    showCloseButton: false
    standardButtons: Kirigami.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: "Done"
            icon.name: "dialog-ok"
            onTriggered: dialog.done()
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        // ---- Automatic checks ----

        Kirigami.Heading {
            level: 4
            text: "Check for updates automatically?"
        }

        // The two choices are in different rows, so they need a group to switch each other off.
        QQC2.ButtonGroup {
            id: autoGroup
        }

        RowLayout {
            QQC2.RadioButton {
                id: autoYes

                objectName: "autoYes"
                QQC2.ButtonGroup.group: autoGroup
                text: "Yes:"
                checked: true
            }

            QQC2.ComboBox {
                id: intervalBox

                enabled: autoYes.checked
                model: backend.checkIntervals.map(h => Labels.interval(h))
                currentIndex: backend.checkIntervals.indexOf(24)
            }
        }

        QQC2.RadioButton {
            objectName: "autoNo"
            QQC2.ButtonGroup.group: autoGroup
            text: "No, I’ll click “Check now” myself"
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: autoYes.checked ? "A notification appears when updates are found." : "Nothing runs in the background."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // ---- Scanning ----

        QQC2.CheckBox {
            id: scanBox

            objectName: "scanBox"

            text: "Scan this computer for repos I’ve already installed"
            checked: false
        }

        QQC2.Label {
            Layout.fillWidth: true
            // Long text would otherwise widen the dialog to its full, unwrapped length.
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            Layout.leftMargin: Kirigami.Units.gridUnit * 1.5
            text: scanBox.checked
                ? `Looks in ${backend.settings.scanFoldersText} for git clones and downloaded apps, and for RPMs installed from downloaded files. These folders are scanned by default; more can be added in Settings. Only the repos you choose are tracked, and others can still be added by hand. Only what your package manager can\u2019t update is listed. Anything dnf or Flatpak updates is left out: an RPM is only included if it was installed from a downloaded file and no repository you have enabled (Fedora, RPM Fusion, COPR\u2026) offers it.`
                : "Off: tracking is manual. You add repos yourself, and for each one set which version you have, or mark it as up to date."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        // ---- Old versions ----

        RowLayout {
            QQC2.CheckBox {
                id: deleteBox

                text: "Delete old versions after"
                checked: false
            }

            QQC2.ComboBox {
                id: daysBox

                enabled: deleteBox.checked
                model: backend.deleteAfterDays.map(d => `${d} days`)
                currentIndex: backend.deleteAfterDays.indexOf(30)
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit * 1.5
            text: "Kept versions let you undo an update."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: "All of this can be changed later in Settings."
            wrapMode: Text.Wrap
        }
    }
}
