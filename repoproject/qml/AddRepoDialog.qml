import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.Dialog {
    id: dialog

    function add() {
        if (urlField.text.trim() !== "" && !backend.adding) {
            error.visible = false;
            backend.addRepo(nameField.text, urlField.text);
        }
    }

    title: "Add Repo"
    padding: Kirigami.Units.largeSpacing
    preferredWidth: Kirigami.Units.gridUnit * 28
    standardButtons: Kirigami.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: "Add"
            icon.name: "list-add"
            enabled: urlField.text.trim() !== "" && !backend.adding
            onTriggered: dialog.add()
        },
        Kirigami.Action {
            text: "Cancel"
            icon.name: "dialog-cancel"
            onTriggered: dialog.close()
        }
    ]

    onOpened: {
        urlField.text = "";
        nameField.text = "";
        error.visible = false;
        urlField.forceActiveFocus();
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.InlineMessage {
            id: error

            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            visible: false
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.TextField {
                id: urlField

                Layout.fillWidth: true
                Kirigami.FormData.label: "Address:"
                placeholderText: "https://github.com/owner/project"
                enabled: !backend.adding
                onAccepted: dialog.add()
            }

            QQC2.TextField {
                id: nameField

                Layout.fillWidth: true
                Kirigami.FormData.label: "Name:"
                enabled: !backend.adding
                onAccepted: dialog.add()
            }
        }

        RowLayout {
            visible: backend.adding

            QQC2.BusyIndicator {
                running: backend.adding
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }

            QQC2.Label {
                text: "Looking up the project…"
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: "Name is optional; the project’s own name is used if it’s left empty. Works with GitHub, and with GitLab sites including self-hosted ones like gitgud.io."
            wrapMode: Text.Wrap
            opacity: 0.7
        }
    }

    Connections {
        function onAddFinished(repoId) {
            dialog.close();
            applicationWindow().openRepo(repoId);
        }

        function onAddFailed(message) {
            error.text = message;
            error.visible = true;
        }

        target: backend
    }
}
