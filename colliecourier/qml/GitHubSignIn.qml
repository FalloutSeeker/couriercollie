import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Signing in to GitHub (optional; DESIGN.md §8), in Settings and on the welcome screen. Whoever shows it calls
// backend.refreshGitHub() when it opens, to find the desktop's password store (without one, no signing in).
ColumnLayout {
    id: root

    readonly property var account: backend.github

    spacing: Kirigami.Units.smallSpacing

    // Why sign in at all, in a sentence.
    QQC2.Label {
        Layout.fillWidth: true
        visible: root.account.way === ""
        text: "Only needed if you track a lot of GitHub projects: GitHub answers 60 requests an hour without signing in, and 5,000 with."
        wrapMode: Text.Wrap
    }

    // ---- Not signed in ----

    Flow {
        Layout.fillWidth: true
        visible: root.account.way === "" && root.account.signIn === ""
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            objectName: "githubSignIn"
            // The login is kept in the desktop's password store; without one it couldn't be kept safely.
            enabled: root.account.store !== ""
            text: "Sign In…"
            icon.name: "internet-services"
            onClicked: backend.startSignIn()
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.account.way === "" && root.account.signIn === ""
        text: root.account.store !== ""
              ? `Read-only: it can see public information only. Kept in ${root.account.store}.`
              : "Signing in needs a password store to keep the login safely, and this desktop has none running."
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    // ---- Signing in: the code to enter on GitHub ----

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.account.signIn !== ""
        text: root.account.signIn === "starting" ? "Asking GitHub for a code…"
            : `Enter this code at ${root.account.verifyUrl}, then approve colliecourier there:`
        wrapMode: Text.Wrap
    }

    RowLayout {
        visible: root.account.code !== ""

        QQC2.Label {
            objectName: "githubUserCode"
            text: root.account.code
            font.family: "monospace"
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.6
            font.bold: true
            textFormat: Text.PlainText
        }

        QQC2.Button {
            text: "Copy"
            icon.name: "edit-copy"
            onClicked: backend.copyText(root.account.code)
        }
    }

    Flow {
        Layout.fillWidth: true
        visible: root.account.signIn !== ""
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            objectName: "githubOpen"
            visible: root.account.code !== ""
            highlighted: true
            text: "Copy Code and Open GitHub"
            icon.name: "internet-services"
            onClicked: {
                backend.copyText(root.account.code);
                Qt.openUrlExternally(root.account.verifyUrl);
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
        visible: root.account.code !== ""

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
        visible: root.account.way !== ""
        text: `Signed in as ${root.account.user}.`
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: root.account.rejected === true
        type: Kirigami.MessageType.Warning
        text: "GitHub turned the login down (it may have been revoked), so requests go without it. Sign out, then sign in again."
    }

    QQC2.Button {
        objectName: "githubSignOut"
        visible: root.account.way !== ""
        text: "Sign Out"
        icon.name: "system-log-out"
        onClicked: backend.signOut()
    }

    QQC2.Label {
        Layout.fillWidth: true
        visible: root.account.way !== ""
        text: `Signing out removes the login from ${root.account.store || "this computer"}. To remove colliecourier’s access on GitHub too: Settings → Applications on github.com.`
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    Kirigami.InlineMessage {
        objectName: "githubError"
        Layout.fillWidth: true
        visible: root.account.error !== ""
        type: Kirigami.MessageType.Error
        text: root.account.error
    }
}
