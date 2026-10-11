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
            scanning: scanBox.checked
        });
        dialog.close();
        dialog.finished(scanBox.checked);
    }

    title: "Welcome to couriercollie"
    // Finds the desktop's password store, which signing in needs.
    onOpened: backend.refreshGitHub()
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
            text: "No, I’ll click “Check Now” myself"
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
                ? `Looks in ${backend.settings.scanFoldersText} for git clones, downloaded apps and packages installed from downloaded files. Only what your package manager can\u2019t update is listed; anything it or Flatpak updates is left out. You choose which to track; others can still be added by hand.`
                : "Off: tracking is manual. You add repos yourself, and for each one set which version you have, or mark it as up to date."
            wrapMode: Text.Wrap
            opacity: 0.7
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // ---- GitHub account ----

        Kirigami.Heading {
            level: 4
            text: "Sign in to GitHub (optional)"
        }

        GitHubSignIn {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
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
