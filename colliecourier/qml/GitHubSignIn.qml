import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Signing in to GitHub (optional; DESIGN.md §8), in Settings and on the welcome screen. Whoever shows it calls
// backend.refreshGitHub() when it opens, to offer the GitHub CLI's login if there is one.
ColumnLayout {
    id: root

    readonly property var gh: backend.github

    spacing: Kirigami.Units.smallSpacing

    // Why sign in at all, in a sentence.
    QQC2.Label {
        Layout.fillWidth: true
        visible: root.gh.way === ""
        text: "Only needed if you track a lot of GitHub projects: GitHub answers 60 requests an hour without signing in, and 5,000 with."
        wrapMode: Text.Wrap
    }

    // ---- Not signed in ----

    Flow {
        Layout.fillWidth: true
        visible: root.gh.way === "" && root.gh.signIn === ""
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            objectName: "githubSignIn"
            // The login is kept in the desktop's password store; without one it couldn't be kept safely.
            enabled: root.gh.store !== ""
            text: "Sign In…"
            icon.name: "internet-services"
            onClicked: backend.startSignIn()
        }

        QQC2.Button {
            objectName: "githubUseGh"
            visible: root.gh.ghUser !== ""
            text: `Use the GitHub CLI’s Login (${root.gh.ghUser})`
            icon.name: "utilities-terminal"
            onClicked: backend.useGhLogin()
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.gh.way === "" && root.gh.signIn === ""
        text: root.gh.store !== ""
              ? `Read-only: it can see public information only. Kept in ${root.gh.store}.`
              : "Signing in needs a password store to keep the login safely, and this desktop has none running." + (root.gh.ghUser !== "" ? " The GitHub CLI’s login works without one." : "")
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    // ---- Signing in: the code to enter on GitHub ----

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.gh.signIn !== ""
        text: root.gh.signIn === "starting" ? "Asking GitHub for a code…"
            : `Enter this code at ${root.gh.verifyUrl}, then approve colliecourier there:`
        wrapMode: Text.Wrap
    }

    RowLayout {
        visible: root.gh.code !== ""

        QQC2.Label {
            objectName: "githubUserCode"
            text: root.gh.code
            font.family: "monospace"
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.6
            font.bold: true
            textFormat: Text.PlainText
        }

        QQC2.Button {
            text: "Copy"
            icon.name: "edit-copy"
            onClicked: backend.copyText(root.gh.code)
        }
    }

    Flow {
        Layout.fillWidth: true
        visible: root.gh.signIn !== ""
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            objectName: "githubOpen"
            visible: root.gh.code !== ""
            highlighted: true
            text: "Copy Code and Open GitHub"
            icon.name: "internet-services"
            onClicked: {
                backend.copyText(root.gh.code);
                Qt.openUrlExternally(root.gh.verifyUrl);
            }
        }

        QQC2.Button {
            objectName: "githubCancel"
            text: "Cancel"
            icon.name: "dialog-cancel"
            onClicked: backend.cancelSignIn()
        }
    }

    RowLayout {
        visible: root.gh.code !== ""

        QQC2.BusyIndicator {
            running: parent.visible
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
        }

        QQC2.Label {
            text: "Waiting for you to approve it on GitHub…"
            opacity: 0.7
        }
    }

    // ---- Signed in ----

    QQC2.Label {
        objectName: "githubSignedIn"
        Layout.fillWidth: true
        visible: root.gh.way !== ""
        text: root.gh.way === "gh" ? `Signed in as ${root.gh.user}, with the GitHub CLI’s login.`
                                   : `Signed in as ${root.gh.user}.`
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: root.gh.rejected === true
        type: Kirigami.MessageType.Warning
        text: "GitHub turned the login down (it may have been revoked, or gh signed out), so requests go without it. Sign out, then sign in again."
    }

    QQC2.Button {
        objectName: "githubSignOut"
        visible: root.gh.way !== ""
        text: "Sign Out"
        icon.name: "system-log-out"
        onClicked: backend.signOut()
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.gh.way !== ""
        text: root.gh.way === "gh"
              ? "Signing out here only stops colliecourier using it; the GitHub CLI stays signed in."
              : `Signing out removes the login from ${root.gh.store || "this computer"}. To remove colliecourier’s access on GitHub too: Settings → Applications on github.com.`
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    Kirigami.InlineMessage {
        objectName: "githubError"
        Layout.fillWidth: true
        visible: root.gh.error !== ""
        type: Kirigami.MessageType.Error
        text: root.gh.error
    }
}
