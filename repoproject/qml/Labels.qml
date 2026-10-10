pragma Singleton

import QtQuick

// Wording shared by more than one screen.
QtObject {
    function interval(hours) {
        return {
            "1": "hour",
            "6": "6 hours",
            "12": "12 hours",
            "24": "day",
            "168": "week"
        }[hours] || `${hours} hours`;
    }
}
