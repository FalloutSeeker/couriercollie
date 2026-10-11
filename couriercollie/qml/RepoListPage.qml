import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    title: "Tracked Repos"

    // The Scan button is only in the list while scanning is allowed. Listing it hidden instead makes Kirigami log
    // "Could not create delegate for ToolBarLayout" at start-up.
    // Check Now before Scan: when the column is narrow, the last ones go into the overflow menu, and Scan is the
    // occasional one.
    actions: backend.settings.scanning ? [addAction, checkAction, scanAction, settingsAction]
                                       : [addAction, checkAction, settingsAction]

    // The category whose name is being edited in its heading, and why the typed name can't be used.
    property string renaming: ""
    property string renameError: ""

    function startRename(category) {
        renameError = "";
        renaming = category;
    }

    // Enter saves the name, or says why it can't. Clicking elsewhere saves it if it can, and otherwise gives up.
    function finishRename(text, pressedEnter) {
        const from = renaming;
        if (!from)
            return;
        const problem = backend.categoryNameProblem(text, from);
        if (problem && pressedEnter) {
            renameError = problem;
            return;
        }
        renaming = "";
        renameError = "";
        // Later, as the rows are rebuilt with the new name and this field is one of them.
        if (!problem)
            Qt.callLater(backend.renameCategory, from, text);
    }

    function askDelete(heading) {
        // An empty category goes straight away; one with repos asks first. Later, so the heading's button isn't
        // deleted with the list's rows while it's still handling the click.
        if (heading.total === 0) {
            Qt.callLater(backend.deleteCategory, heading.category);
            return;
        }
        deleteDialog.category = heading.category;
        deleteDialog.total = heading.total;
        deleteDialog.open();
    }

    Kirigami.Action {
        id: addAction

        icon.name: "list-add"
        text: "Add…"
        shortcut: StandardKey.New
        onTriggered: applicationWindow().showAddDialog()
    }

    Kirigami.Action {
        id: scanAction

        icon.name: "edit-find"
        text: "Scan…"
        onTriggered: applicationWindow().showScanDialog()
    }

    Kirigami.Action {
        id: checkAction

        objectName: "checkNow"
        icon.name: "system-software-update"
        text: backend.checking ? "Checking\u2026" : "Check Now"
        enabled: !backend.checking
        onTriggered: backend.checkNow()
    }

    Kirigami.Action {
        id: settingsAction

        icon.name: "configure"
        text: "Settings"
        shortcut: StandardKey.Preferences
        displayHint: Kirigami.DisplayHint.IconOnly | Kirigami.DisplayHint.KeepVisible
        onTriggered: applicationWindow().openSettings()
    }

    header: ColumnLayout {
        spacing: 0

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.configError !== ""
            type: Kirigami.MessageType.Error
            position: Kirigami.InlineMessage.Position.Header
            text: backend.configError + "\nChanges won’t be saved until that file is fixed or moved away."
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.saveError !== ""
            type: Kirigami.MessageType.Warning
            position: Kirigami.InlineMessage.Position.Header
            text: backend.saveError
        }

        QQC2.ToolBar {
            Layout.fillWidth: true

            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    text: "Show:"
                }

                Repeater {
                    model: [
                        { key: "all", label: "All" },
                        { key: "github", label: "GitHub" },
                        { key: "gitlab", label: "GitLab" }
                    ]

                    delegate: QQC2.ToolButton {
                        id: filterButton

                        required property var modelData

                        objectName: "filter:" + modelData.key
                        text: `${modelData.label} (${backend.counts[modelData.key]})`
                        // Checkable so KDE's style draws the highlight. A click would toggle it on its own, so after
                        // each click it's tied back to the saved filter.
                        checkable: true
                        checked: backend.filter === modelData.key
                        onClicked: {
                            backend.filter = modelData.key;
                            checked = Qt.binding(() => backend.filter === filterButton.modelData.key);
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                // Here rather than with the page's actions, where it would push Check Now into the overflow menu.
                QQC2.ToolButton {
                    objectName: "newCategory"
                    icon.name: "folder-new"
                    text: "New Category…"
                    onClicked: newCategoryDialog.open()
                }
            }
        }

        // How many updates, and when it last checked and checks next.
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            QQC2.BusyIndicator {
                visible: backend.checking
                running: visible
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            Kirigami.Icon {
                visible: !backend.checking && backend.checks.updates > 0
                source: "update-low"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            QQC2.Label {
                objectName: "checkSummary"
                Layout.fillWidth: true
                text: {
                    const c = backend.checks;
                    if (backend.checking)
                        return "Checking for updates\u2026";
                    const parts = [];
                    if (c.lastChecked)
                        parts.push(c.checked > 0 && c.failed === c.checked
                                   ? "Couldn\u2019t check any" + (c.updates > 0 ? ` (${c.updates} known from before)` : "")
                                   : c.updates === 0 && c.failed === 0 ? "All up to date"
                                   : c.updates === 0 ? "No updates" : c.updates === 1 ? "1 update" : `${c.updates} updates`,
                                   ...(c.failed > 0 && c.failed < c.checked ? [`${c.failed} couldn\u2019t be checked`] : []),
                                   `checked ${c.lastChecked}`);
                    else
                        parts.push("Not checked yet");
                    parts.push(c.autoCheck ? (c.nextCheck ? `next check ${c.nextCheck}` : "checks automatically")
                                           : "automatic checks are off");
                    return parts.join(" \u00b7 ");
                }
                font.bold: !backend.checking && backend.checks.updates > 0
                // Beside a repo's page the list is narrow: two lines rather than cutting off the next check's time.
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.checks.error !== ""
            type: Kirigami.MessageType.Error
            text: `Couldn\u2019t check for updates: ${backend.checks.error}`
        }

        Kirigami.InlineMessage {
            objectName: "rateLimitBar"
            Layout.fillWidth: true
            visible: !backend.checking && backend.checks.rateLimited > 0
            type: Kirigami.MessageType.Warning
            showCloseButton: true
            text: {
                const c = backend.checks;
                const which = c.rateLimited === 1 ? "1 repo wasn\u2019t checked" : `${c.rateLimited} repos weren\u2019t checked`;
                const when = c.rateLimitEnds ? ` It can be checked again after ${c.rateLimitEnds}.` : "";
                return `The site\u2019s hourly limit for requests was reached, so ${which}; it keeps its last result.${when}`;
            }
            // Signing in raises GitHub's limit from 60 requests an hour to 5,000.
            actions: backend.github.way === "" ? [signInAction] : []

            Kirigami.Action {
                id: signInAction

                text: "Sign In to GitHub\u2026"
                icon.name: "internet-services"
                onTriggered: applicationWindow().openSettings()
            }
        }
    }

    // The handle for dragging a repo or category. While it's held, the list shows where it would go; the move is
    // made when it's let go.
    component DragHandle: Kirigami.Icon {
        id: handle

        required property ListView view
        required property var what
        required property Item bar  // the row it drags: shown under the pointer while dragging

        source: "handle-sort"
        implicitWidth: Kirigami.Units.iconSizes.smallMedium
        implicitHeight: Kirigami.Units.iconSizes.smallMedium
        opacity: area.containsMouse || area.pressed ? 1 : 0.6

        MouseArea {
            id: area

            function yInList(mouse) {
                return mapToItem(handle.view.contentItem, mouse.x, mouse.y).y;
            }

            anchors.fill: parent
            anchors.margins: -Kirigami.Units.smallSpacing
            hoverEnabled: true
            preventStealing: true
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            onPressed: mouse => handle.view.startDrag(handle.what, yInList(mouse), handle.bar)
            onPositionChanged: mouse => {
                if (pressed)
                    handle.view.moveDrag(yInList(mouse));
            }
            onReleased: handle.view.endDrag(true)
            onCanceled: handle.view.endDrag(false)
        }
    }

    Kirigami.PromptDialog {
        id: deleteDialog

        objectName: "deleteCategoryDialog"

        property string category
        property int total

        title: `Delete \u201c${category}\u201d?`
        subtitle: (total === 1 ? "Its repo moves to Uncategorized and stays tracked."
                               : `Its ${total} repos move to Uncategorized and stay tracked.`) +
                  " Nothing on this computer is changed."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Delete Category"
                icon.name: "edit-delete"
                onTriggered: deleteDialog.accept()
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: deleteDialog.reject()
            }
        ]
        onAccepted: backend.deleteCategory(category)
    }

    NewCategoryDialog {
        id: newCategoryDialog

        objectName: "newCategoryDialog"
    }

    ListView {
        id: list

        objectName: "repoList"

        // While something is dragged: what it is ({ kind, id, category, label }), the pointer's height in the list,
        // and where it would go if let go here ({ category, before, lineY }), or null for nowhere new.
        property var dragged: null
        property real dragY: 0
        property var drop: null
        // A picture of the dragged row, which follows the pointer, held where it was grabbed.
        property var picture: null
        property real grabOffset: 0
        property real barHeight: 0

        // The repo just after row i in the same category, or "" if row i is the category's last.
        function nextRepo(i) {
            const next = model[i + 1];
            return next && next.kind === "repo" ? next.id : "";
        }

        function headingY(category) {
            const i = model.findIndex(r => r.kind === "category" && r.category === category);
            const item = i >= 0 ? itemAtIndex(i) : null;
            return item ? item.y : -1;
        }

        function dropFor(y) {
            const rows = model;
            if (!dragged || rows.length === 0)
                return null;
            let i = indexAt(width / 2, y);
            const pastEnd = i < 0 && y >= 0;
            if (i < 0)
                i = y < 0 ? 0 : rows.length - 1;
            const row = rows[i], item = itemAtIndex(i);
            if (!item)
                return null;
            const top = item.y, bottom = item.y + item.height;
            if (dragged.kind === "repo") {
                // Onto a heading: the top of that category. Onto a repo: above or below it, by which half.
                if (row.kind === "repo" && !pastEnd && y < (top + bottom) / 2)
                    return { category: row.category, before: row.id, lineY: top };
                return { category: row.category, before: nextRepo(i), lineY: bottom };
            }
            // A category goes before the one pointed at if that's above it, or after it if it's below.
            // Uncategorized always stays first.
            const cats = backend.categories;
            const from = cats.indexOf(dragged.category), at = cats.indexOf(row.category);
            const to = at < from ? Math.max(at, 0) : at + 1;
            if (at === from || to === from)
                return null;
            const before = to < cats.length ? cats[to] : "";
            return { category: "", before: before, lineY: before ? headingY(before) : contentHeight + originY };
        }

        function startDrag(what, y, bar) {
            dragged = what;
            picture = null;
            grabOffset = y - bar.y;
            barHeight = bar.height;
            moveDrag(y);
            bar.grabToImage(result => {
                if (dragged === what)
                    picture = result;
            });
        }

        function moveDrag(y) {
            dragY = y;
            drop = dropFor(y);
        }

        function endDrag(commit) {
            const what = dragged, where = drop;
            dragged = null;
            drop = null;
            picture = null;
            if (!commit || !what || !where)
                return;
            // Later, so the rows aren't rebuilt while the handle that was let go is still handling it.
            if (what.kind === "repo")
                Qt.callLater(backend.moveRepo, what.id, where.category, where.before);
            else
                Qt.callLater(backend.moveCategory, what.category, where.before);
        }

        model: backend.rows
        // The rows are rebuilt when the list changes (e.g. a check finishes), which drops a drag in progress.
        onModelChanged: dragged = drop = picture = null

        delegate: Loader {
            id: row

            required property var modelData

            width: ListView.view.width
            sourceComponent: modelData.kind === "category" ? headingRow : repoRow
            // What's being dragged is dimmed, once its picture is taken: a repo, or a category with its repos.
            opacity: {
                const d = list.dragged;
                if (!d || !list.picture)
                    return 1;
                const mine = d.kind === "repo" ? modelData.id === d.id : modelData.category === d.category;
                return mine ? 0.4 : 1;
            }

            // The list's own background, so the picture taken of a row for dragging isn't see-through.
            Rectangle {
                z: -1
                anchors.fill: parent
                Kirigami.Theme.colorSet: Kirigami.Theme.View
                Kirigami.Theme.inherit: false
                color: Kirigami.Theme.backgroundColor
            }

            Component {
                id: headingRow

                ColumnLayout {
                    id: heading

                    readonly property bool editing: page.renaming !== "" && page.renaming === row.modelData.category

                    objectName: "category:" + row.modelData.label
                    spacing: 0

                    // Right-click a heading for the same menu as its ⋮ button.
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        enabled: row.modelData.category !== "" && !heading.editing
                        onTapped: menu.popup()
                    }

                    QQC2.Menu {
                        id: menu

                        QQC2.MenuItem {
                            objectName: "renameCategory:" + row.modelData.category
                            text: "Rename"
                            icon.name: "edit-rename"
                            onTriggered: page.startRename(row.modelData.category)
                        }

                        QQC2.MenuItem {
                            objectName: "deleteCategory:" + row.modelData.category
                            text: "Delete Category…"
                            icon.name: "edit-delete"
                            onTriggered: page.askDelete(row.modelData)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumHeight: Kirigami.Units.iconSizes.medium
                        Layout.topMargin: Kirigami.Units.largeSpacing
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        Layout.rightMargin: Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing

                        DragHandle {
                            objectName: "dragCategory:" + row.modelData.category
                            visible: row.modelData.category !== ""
                            view: list
                            bar: row
                            what: ({ kind: "category", id: "", category: row.modelData.category,
                                     label: row.modelData.label })
                        }

                        // A long name is cut short; its count stays beside it.
                        Kirigami.Heading {
                            objectName: "categoryName:" + row.modelData.category
                            Layout.fillWidth: true
                            // Rounded up: a fraction of a pixel short would cut off the name's last letters.
                            Layout.maximumWidth: Math.ceil(implicitWidth)
                            visible: !heading.editing
                            level: 4
                            text: row.modelData.label
                            textFormat: Text.PlainText
                            elide: Text.ElideRight

                            // Double-click the name to rename it.
                            TapHandler {
                                enabled: row.modelData.category !== ""
                                onDoubleTapped: page.startRename(row.modelData.category)
                            }
                        }

                        // Takes the room left over, so the name only shrinks when there isn't enough.
                        Kirigami.Heading {
                            Layout.fillWidth: true
                            Layout.minimumWidth: implicitWidth
                            visible: !heading.editing
                            level: 4
                            text: row.modelData.count
                            color: Kirigami.Theme.disabledTextColor
                        }

                        // Enter saves, Esc cancels.
                        QQC2.TextField {
                            objectName: "renameField:" + row.modelData.category
                            Layout.fillWidth: true
                            visible: heading.editing
                            onVisibleChanged: {
                                if (visible) {
                                    text = row.modelData.category;
                                    selectAll();
                                    forceActiveFocus();
                                }
                            }
                            onTextEdited: page.renameError = ""
                            onAccepted: page.finishRename(text, true)
                            onActiveFocusChanged: {
                                if (!activeFocus && visible)
                                    page.finishRename(text, false);
                            }
                            Keys.onEscapePressed: page.renaming = ""
                        }

                        QQC2.ToolButton {
                            objectName: "categoryMenu:" + row.modelData.category
                            visible: row.modelData.category !== "" && !heading.editing
                            icon.name: "overflow-menu"
                            text: "Rename or Delete"
                            display: QQC2.AbstractButton.IconOnly
                            QQC2.ToolTip.text: text
                            QQC2.ToolTip.visible: hovered
                            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                            onClicked: menu.popup(this, 0, height)
                        }
                    }

                    QQC2.Label {
                        objectName: "renameError"
                        Layout.fillWidth: true
                        Layout.leftMargin: Kirigami.Units.largeSpacing + Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                        visible: heading.editing && page.renameError !== ""
                        text: page.renameError
                        color: Kirigami.Theme.negativeTextColor
                        font: Kirigami.Theme.smallFont
                        wrapMode: Text.Wrap
                    }

                    Hint {
                        Layout.leftMargin: Kirigami.Units.largeSpacing + Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                        visible: row.modelData.total === 0 && row.modelData.category !== ""
                        text: "Empty. Drag repos here by their handles."
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                    }
                }
            }

            Component {
                id: repoRow

                QQC2.ItemDelegate {
                    objectName: "repo:" + row.modelData.id
                    highlighted: applicationWindow().currentRepoId === row.modelData.id
                    topPadding: Kirigami.Units.largeSpacing
                    bottomPadding: Kirigami.Units.largeSpacing
                    onClicked: applicationWindow().openRepo(row.modelData.id)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.largeSpacing

                        DragHandle {
                            objectName: "dragRepo:" + row.modelData.id
                            view: list
                            bar: row
                            what: ({ kind: "repo", id: row.modelData.id, category: row.modelData.category,
                                     label: row.modelData.name })
                        }

                        RepoIcon {
                            objectName: "repoIcon:" + row.modelData.id
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                            source: row.modelData.icon
                            letter: row.modelData.monogram
                            color: row.modelData.monogramColor
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing / 2

                            QQC2.Label {
                                Layout.fillWidth: true
                                text: row.modelData.name
                                textFormat: Text.PlainText
                                font.bold: true
                                elide: Text.ElideRight
                            }

                            QQC2.Label {
                                Layout.fillWidth: true
                                text: `${row.modelData.domain}/${row.modelData.path}`
                                textFormat: Text.PlainText
                                font: Kirigami.Theme.smallFont
                                opacity: 0.7
                                elide: Text.ElideMiddle
                            }

                            QQC2.Label {
                                Layout.fillWidth: true
                                text: row.modelData.followText
                                font: Kirigami.Theme.smallFont
                                opacity: 0.7
                                elide: Text.ElideMiddle
                            }
                        }

                        // The last check's result, with the update icon (or Update button) beside it.
                        RowLayout {
                            visible: row.modelData.checkText !== ""
                            spacing: Kirigami.Units.smallSpacing

                            Kirigami.Icon {
                                objectName: "updateIcon:" + row.modelData.id
                                visible: row.modelData.updateAvailable && !row.modelData.canUpdate
                                source: "update-low"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                            }

                            // Repos Update can handle: the icon is the Update button (DECISIONS.md, D4).
                            QQC2.ToolButton {
                                objectName: "updateButton:" + row.modelData.id
                                visible: row.modelData.updateAvailable && row.modelData.canUpdate
                                         && !row.modelData.updating
                                icon.name: "update-low"
                                text: "Update"
                                display: QQC2.AbstractButton.IconOnly
                                QQC2.ToolTip.text: row.modelData.updateNeedsPassword ? "Update (asks for your password)" : "Update"
                                QQC2.ToolTip.visible: hovered
                                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                                onClicked: backend.updateRepo(row.modelData.id)
                            }

                            QQC2.BusyIndicator {
                                visible: row.modelData.updating
                                running: visible
                                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                            }

                            QQC2.Label {
                                // Narrow (a repo's page open beside the list): two short lines, so the name keeps room.
                                Layout.maximumWidth: Kirigami.Units.gridUnit * (narrow ? 6 : 10)
                                horizontalAlignment: Text.AlignRight
                                // Bold through the text itself: setting font.bold here would replace the small font.
                                // Narrow, an update says what and which on a line each ("Update available" over
                                // "v1.18.2", "3 new commits" over "on main"), rather than breaking wherever the line
                                // runs out.
                                text: {
                                    const t = Labels.escaped(row.modelData.checkText);
                                    if (!row.modelData.updateAvailable)
                                        return t;
                                    const colon = t.indexOf(": "), on = t.indexOf(" on ");
                                    return !narrow ? `<b>${t}</b>`
                                        : colon > 0 ? `<b>${t.slice(0, colon)}</b><br>${t.slice(colon + 2)}`
                                        : on > 0 ? `<b>${t.slice(0, on)}</b><br>${t.slice(on + 1)}`
                                        : `<b>${t}</b>`;
                                }
                                readonly property bool narrow: row.width < Kirigami.Units.gridUnit * 26
                                textFormat: Text.StyledText
                                font: Kirigami.Theme.smallFont
                                opacity: row.modelData.updateAvailable ? 1 : 0.7
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight

                                // Why a check failed, on hover.
                                HoverHandler {
                                    id: resultHover
                                }

                                QQC2.ToolTip.text: row.modelData.checkDetail || ""
                                QQC2.ToolTip.visible: resultHover.hovered && QQC2.ToolTip.text !== ""
                                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                            }
                        }
                    }
                }
                }
        }

        // Where a dragged repo or category would go; above the dragged row, which often covers that spot.
        Rectangle {
            z: 12
            visible: list.drop !== null && list.drop.lineY >= 0
            y: list.drop ? list.drop.lineY - height / 2 : 0
            width: list.width
            height: 3
            color: Kirigami.Theme.highlightColor
        }

        // The dragged row itself follows the pointer.
        Kirigami.ShadowedRectangle {
            objectName: "dragPicture"
            z: 11
            Kirigami.Theme.colorSet: Kirigami.Theme.View
            Kirigami.Theme.inherit: false
            visible: list.picture !== null
            y: list.dragY - list.grabOffset
            width: list.width
            height: list.barHeight
            color: Kirigami.Theme.backgroundColor
            border.width: 2
            border.color: Kirigami.Theme.highlightColor
            shadow.size: Kirigami.Units.gridUnit
            shadow.yOffset: Kirigami.Units.smallSpacing / 2
            shadow.color: Qt.rgba(0, 0, 0, 0.3)

            // Inside the outline, so the outline shows on every theme.
            Image {
                anchors.fill: parent
                anchors.margins: parent.border.width
                source: list.picture ? list.picture.url : ""
            }
        }

        // Near the top or bottom while dragging, the list scrolls.
        Timer {
            running: list.dragged !== null
            interval: 30
            repeat: true
            onTriggered: {
                const edge = Kirigami.Units.gridUnit * 2, inView = list.dragY - list.contentY;
                let step = 0;
                if (inView < edge)
                    step = -Math.ceil((edge - inView) / 4);
                else if (inView > list.height - edge)
                    step = Math.ceil((inView - list.height + edge) / 4);
                const lowest = Math.max(list.originY, list.originY + list.contentHeight - list.height);
                const to = Math.max(list.originY, Math.min(lowest, list.contentY + step));
                if (to !== list.contentY) {
                    list.moveDrag(list.dragY + to - list.contentY);
                    list.contentY = to;
                }
            }
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: list.count === 0
            icon.name: "folder-git"
            text: backend.filter === "all" ? "No repos tracked yet" : "No repos from this site"
            explanation: backend.filter === "all" ? "Add a GitHub or GitLab project to keep track of its releases." : ""
            helpfulAction: backend.filter === "all" ? addAction : null
        }
    }
}
