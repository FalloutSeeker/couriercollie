"""Starts the window."""

import os
import signal
import sys
from pathlib import Path

QML_DIR = Path(__file__).parent / "qml"


def main() -> int:
    if "--reset" in sys.argv[1:]:
        from . import config

        backup = config.reset()
        print(f"Settings reset. The old ones were saved as {backup}." if backup else "Nothing to reset.")
        sys.argv.remove("--reset")

    # KDE's own look for buttons, lists, etc. Needs QApplication rather than QGuiApplication.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    from PySide6.QtCore import QStandardPaths, QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    from .backend import Backend

    app = QApplication(sys.argv)
    app.setApplicationName("RepoProject")
    app.setOrganizationName("RepoProject")
    # The desktop file name tells KDE which menu entry this window belongs to. Without an installed entry, KDE's
    # portal logs "App info not found", so it's only set once the entry exists (added in a later stage).
    if QStandardPaths.locate(QStandardPaths.StandardLocation.ApplicationsLocation, "repoproject.desktop"):
        app.setDesktopFileName("repoproject")
    app.setWindowIcon(QIcon.fromTheme("system-software-update"))
    # Let Ctrl+C in the terminal close the app.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    backend = Backend(find_icons=True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        return 1
    code = app.exec()
    backend.shutdown()
    return code
