pragma Singleton

import QtQuick

// Wording shared by more than one screen.
QtObject {
    function interval(hours) {
        return {
            "24": "Daily",
            "168": "Every 7 days",
            "336": "Every 14 days",
            "672": "Monthly"
        }[hours] || `Every ${hours} hours`;
    }
}
