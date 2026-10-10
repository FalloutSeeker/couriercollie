import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    property string currentRepoId: ""

    function openRepo(repoId) {
        while (pageStack.depth > 1)
            pageStack.pop();
        currentRepoId = repoId;
        pageStack.push(detailPage, { repoId: repoId });
    }

    function closeRepo() {
        while (pageStack.depth > 1)
            pageStack.pop();
        currentRepoId = "";
    }

    function showAddDialog() {
        addDialog.open();
    }

    title: "RepoProject"
    width: Kirigami.Units.gridUnit * 56
    height: Kirigami.Units.gridUnit * 38
    minimumWidth: Kirigami.Units.gridUnit * 22
    minimumHeight: Kirigami.Units.gridUnit * 20
    pageStack.defaultColumnWidth: Kirigami.Units.gridUnit * 22
    pageStack.initialPage: RepoListPage {}

    AddRepoDialog {
        id: addDialog
    }

    Component {
        id: detailPage

        RepoDetailPage {}
    }
}
