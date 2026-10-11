pragma Singleton

import QtQuick

// Wording shared by more than one screen.
QtObject {
    // Text from outside (a name, a site's answer) inside styled text, so it shows as written.
    function escaped(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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
