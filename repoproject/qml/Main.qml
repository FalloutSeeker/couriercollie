import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    property string currentRepoId: ""
    property Item settingsPageItem: null

    // Pages are created here, with a parent, rather than by Kirigami: Kirigami's way logs "Created graphical object
    // was not placed in the graphics scene". So they're also deleted here when closed.
    function openRepo(repoId) {
        closeRepo();
        currentRepoId = repoId;
        pageStack.push(detailPage.createObject(root, { repoId: repoId }));
    }

    function closeRepo() {
        while (pageStack.depth > 1) {
            const page = pageStack.pop();
            if (page)
                page.destroy();
        }
        currentRepoId = "";
    }

    function showAddDialog() {
        addDialog.open();
    }

    function showScanDialog() {
        scanDialog.openAndScan();
    }

    // A separate window, as in other KDE apps. It blocks the main window while open, so it can't be opened twice.
    // The page belongs to this window rather than the Settings window: if it were deleted along with the Settings
    // window, a calculation inside Kirigami would run on the half-deleted page and log a TypeError. A page can only be
    // shown once, so each opening gets a new one and the previous is deleted.
    function openSettings() {
        if (settingsPageItem)
            settingsPageItem.destroy();
        settingsPageItem = settingsPage.createObject(root);
        pageStack.pushDialogLayer(settingsPageItem, {}, {
            title: "Settings",
            width: Kirigami.Units.gridUnit * 36,
            height: Kirigami.Units.gridUnit * 30
        });
    }

    title: "RepoProject"
    width: Kirigami.Units.gridUnit * 56
    height: Kirigami.Units.gridUnit * 38
    minimumWidth: Kirigami.Units.gridUnit * 22
    minimumHeight: Kirigami.Units.gridUnit * 20
    pageStack.defaultColumnWidth: Kirigami.Units.gridUnit * 22
    pageStack.initialPage: RepoListPage {}

    // First start: ask the setup questions. Skipped if the settings file is broken, since answers couldn't be saved.
    // Opened after the first frame is drawn: before that the window has no size yet, so the dialog can't be centred
    // (Kirigami logs a "binding loop").
    property bool firstFrameShown: false

    onFrameSwapped: {
        if (firstFrameShown)
            return;
        firstFrameShown = true;
        if (!backend.settings.firstLaunchDone && backend.configError === "")
            firstLaunch.open();
    }

    FirstLaunchDialog {
        id: firstLaunch

        // Ticking "Scan this computer" on the welcome screen runs a scan straight away.
        onFinished: scanning => {
            if (scanning)
                scanDialog.openAndScan();
        }
    }

    ScanDialog {
        id: scanDialog
    }

    AddRepoDialog {
        id: addDialog
    }

    Component {
        id: settingsPage

        SettingsPage {}
    }

    Component {
        id: detailPage

        RepoDetailPage {}
    }
}
