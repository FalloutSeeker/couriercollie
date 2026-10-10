"""Starts the window."""

import os
import signal
import sys
from pathlib import Path

QML_DIR = Path(__file__).parent / "qml"


def main() -> int:
    # KDE's own look for buttons, lists, etc. Needs QApplication rather than QGuiApplication.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    from .backend import Backend

    app = QApplication(sys.argv)
    app.setApplicationName("RepoProject")
    app.setOrganizationName("RepoProject")
    app.setDesktopFileName("repoproject")
    app.setWindowIcon(QIcon.fromTheme("system-software-update"))
    # Let Ctrl+C in the terminal close the app.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        return 1
    code = app.exec()
    backend.shutdown()
    return code
