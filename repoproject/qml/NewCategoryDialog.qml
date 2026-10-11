import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.Dialog {
    id: dialog

    function add() {
        const problem = backend.addCategory(nameField.text);
        if (problem === "")
            dialog.close();
        else {
            error.text = problem;
            error.visible = true;
        }
    }

    title: "New Category"
    padding: Kirigami.Units.largeSpacing
    preferredWidth: Kirigami.Units.gridUnit * 22
    standardButtons: Kirigami.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: "Add"
            icon.name: "list-add"
            enabled: nameField.text.trim() !== ""
            onTriggered: dialog.add()
        },
        Kirigami.Action {
            text: "Cancel"
            icon.name: "dialog-cancel"
            onTriggered: dialog.close()
        }
    ]

    onOpened: {
        nameField.text = "";
        error.visible = false;
        nameField.forceActiveFocus();
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
                id: nameField

                objectName: "categoryName"
                Layout.fillWidth: true
                Kirigami.FormData.label: "Name:"
                placeholderText: "e.g. Themes"
                onAccepted: dialog.add()
                onTextChanged: error.visible = false
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: "It’s added at the bottom of the list. Drag repos onto it, and drag its handle to move it."
            wrapMode: Text.Wrap
            opacity: 0.7
        }
    }
}
