import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Scan results (DESIGN.md §1): new finds ticked to start with; Select all / Select none; Track selected.
Kirigami.Dialog {
    id: dialog

    // Ticked finds, by key. Only finds that can be tracked can be ticked.
    property var picked: ({})
    // Once a scan finishes, its new finds are ticked: you untick what you don't want. Finds that look like a repo
    // you track (a mirror, say) are left for you to decide.
    property bool tickWhenDone: false
    readonly property var choosable: backend.scanItems.filter(i => i.status !== "problem" && i.status !== "default")
    // couriercollie itself is shown, greyed out, as "Added by default": it's on the list from the first start.
    readonly property int newCount: backend.scanItems.filter(i => i.status !== "default").length
    readonly property int pickedCount: choosable.filter(i => picked[i.key]).length

    function openAndScan() {
        picked = {};
        tickWhenDone = true;
        open();
        backend.startScan();
    }

    function setAll(on) {
        const all = {};
        if (on)
            choosable.forEach(i => all[i.key] = true);
        picked = all;
    }

    function toggle(key) {
        const copy = Object.assign({}, picked);
        copy[key] = !copy[key];
        picked = copy;
    }

    objectName: "scanDialog"

    Connections {
        function onScanChanged() {
            if (dialog.tickWhenDone && backend.scanState !== "scanning") {
                dialog.tickWhenDone = false;
                const all = {};
                backend.scanItems.filter(i => i.status === "new").forEach(i => all[i.key] = true);
                dialog.picked = all;
            }
        }

        target: backend
    }

    title: "Scan This Computer"
    padding: Kirigami.Units.largeSpacing
    preferredWidth: Kirigami.Units.gridUnit * 36
    // A fixed height: the list can be long, and scrolls inside the dialog.
    preferredHeight: Kirigami.Units.gridUnit * 30
    standardButtons: Kirigami.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: `Track Selected (${dialog.pickedCount})`
            icon.name: "list-add"
            enabled: dialog.pickedCount > 0
            onTriggered: {
                backend.trackFound(Object.keys(dialog.picked).filter(k => dialog.picked[k]).map(Number));
                dialog.picked = {};
            }
        },
        Kirigami.Action {
            text: "Close"
            icon.name: "window-close"
            onTriggered: dialog.close()
        }
    ]

    // One line is always shown: Kirigami sizes the dialog from its content when it opens, and content that's all
    // hidden at that moment leaves the dialog empty for good.
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true

            QQC2.BusyIndicator {
                visible: backend.scanState === "scanning"
                running: visible
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }

            QQC2.Label {
                objectName: "scanStatus"
                Layout.fillWidth: true
                text: backend.scanState === "scanning" ? `Looking in ${backend.settings.scanFoldersText} for git clones and downloaded apps, and for packages installed from downloaded files, then checking each with its site…`
                    : backend.scanError !== "" ? "The scan didn’t finish."
                    : dialog.newCount === 0 ? "Nothing new found. Everything found is already tracked."
                    : `Found ${dialog.newCount} new. Only ticked ones are tracked.`
                font.bold: backend.scanState === "done"
                wrapMode: Text.Wrap
            }
        }

        Hint {
            objectName: "scanOnlyUnmanaged"
            // Long text would otherwise widen the dialog to its full, unwrapped length.
            Layout.maximumWidth: Kirigami.Units.gridUnit * 36
            text: "Only what your package manager can\u2019t update is listed. Anything it or Flatpak updates is left out: a package is only included if it was installed from a downloaded file and no repository you have enabled offers it."
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.scanError !== ""
            type: Kirigami.MessageType.Error
            text: backend.scanError
        }

        // Folders the scan couldn't look in: it runs as you, without asking for a password.
        Kirigami.InlineMessage {
            readonly property var skipped: backend.settings.scanFolders.filter(f => f.problem !== "").map(f => f.path)

            objectName: "skippedFolders"
            Layout.fillWidth: true
            visible: backend.scanState === "done" && skipped.length > 0
            type: Kirigami.MessageType.Warning
            text: `Not looked in: ${skipped.join(", ")}. A folder you can\u2019t open is skipped (scans never ask for a password); Settings says why for each.`
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.scanState === "done" && backend.scanUpdated.length > 0
            type: Kirigami.MessageType.Positive
            text: `Updated ${backend.scanUpdated.length === 1 ? "1 tracked repo" : backend.scanUpdated.length + " tracked repos"} with what’s on this computer: ${backend.scanUpdated.join(", ")}.`
        }

        RowLayout {
            Layout.fillWidth: true
            visible: backend.scanState === "done" && dialog.choosable.length > 0

            Item {
                Layout.fillWidth: true
            }

            QQC2.Button {
                objectName: "selectAll"
                text: "Select All"
                icon.name: "edit-select-all"
                onClicked: dialog.setAll(true)
            }

            QQC2.Button {
                objectName: "selectNone"
                text: "Select None"
                icon.name: "edit-select-none"
                onClicked: dialog.setAll(false)
            }
        }

        Repeater {
            model: backend.scanState === "done" ? backend.scanItems : []

            delegate: QQC2.CheckDelegate {
                id: row

                required property var modelData

                objectName: "found:" + modelData.address
                Layout.fillWidth: true
                enabled: modelData.status !== "problem" && modelData.status !== "default"
                // Shows the ticked state only; a click toggles it in `picked`, so Select all / none stay in charge.
                checkable: false
                checked: !!dialog.picked[modelData.key]
                onClicked: dialog.toggle(modelData.key)
                // The style's own indicator is replaced by one at the row's start: some styles (Fusion) draw
                // theirs on the right, over the row's content.
                indicator: Item {}

                contentItem: RowLayout {
                    spacing: Kirigami.Units.largeSpacing

                    QQC2.CheckBox {
                        checkable: false
                        checked: row.checked
                        enabled: row.enabled
                        focusPolicy: Qt.NoFocus
                        onClicked: row.clicked()
                    }

                    RepoIcon {
                        source: ""  // finds have no picture yet: it's looked up once one is tracked
                        letter: row.modelData.monogram
                        color: row.modelData.monogramColor
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: row.modelData.name
                            textFormat: Text.PlainText
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            text: `${row.modelData.address} · ${row.modelData.path}`
                            textFormat: Text.PlainText
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                            elide: Text.ElideMiddle
                        }

                        QQC2.Label {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: row.modelData.note
                            textFormat: Text.PlainText
                            font: Kirigami.Theme.smallFont
                            color: row.modelData.status === "problem" ? Kirigami.Theme.negativeTextColor
                                 : row.modelData.status === "similar" ? Kirigami.Theme.neutralTextColor
                                 : Kirigami.Theme.textColor
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
