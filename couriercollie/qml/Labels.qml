pragma Singleton

import QtQuick

// Wording shared by more than one screen.
QtObject {
    // Text from outside (a name, a site's answer) inside styled text, so it shows as written.
    function escaped(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // For a Kirigami.InlineMessage, which can't be told to show plain text: Qt guesses, and would read "<…>" in a
    // message (a release tag can hold one, and git's or a package manager's output anything a server sends) as
    // HTML: a picture loaded from anywhere, a link. Escaped and marked as HTML, it shows as written.
    function plain(text) {
        return text ? `<html>${escaped(text).replace(/\n/g, "<br>")}</html>` : "";
    }

    // A link in text from outside (release notes, a README): web pages only. A "file:" or other link would be opened
    // by whatever handles it on this computer, which a project's notes shouldn't be able to choose.
    function openLink(link) {
        if (isWebLink(link))
            Qt.openUrlExternally(link);
    }

    function isWebLink(link) {
        return /^https?:\/\//i.test(link);
    }

    function interval(hours) {
        return {
            "24": "Daily",
            "168": "Every 7 days",
            "336": "Every 14 days",
            "672": "Monthly"
        }[hours] || `Every ${hours} hours`;
    }
}
