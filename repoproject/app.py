"""Starts the window, or (with --check) checks for updates without one.

    run.sh                  open the window (or bring the open one to the front)
    run.sh --check          check every repo for updates now
    run.sh --check --if-due only if automatic checks are on and the interval has passed (what the timer runs)
    run.sh --reset          start over: the settings file is renamed to a dated backup
"""

import os
import signal
import sys
from pathlib import Path

QML_DIR = Path(__file__).parent / "qml"


def check(if_due: bool) -> int:
    """Check for updates without the window. If the app is open, it does the check instead: it knows whether its
    window is in front, which decides whether to send a notification (DECISIONS.md, D5)."""
    from . import checker, config, integration

    try:
        cfg = config.load()
    except config.ConfigError as e:
        print(e, file=sys.stderr)
        return 1
    state = checker.load_state()
    if if_due and not checker.due(cfg.settings, state):
        return 0
    if integration.tell_running_app("check"):
        print("RepoProject is open; it's checking.")
        return 0
    state, fresh = checker.check_all(cfg.repos, state)
    checker.save_state(state)
    names = {r.id: r.name for r in cfg.repos}
    for repo_id, result in state.results.items():
        print(f"{names.get(repo_id, repo_id)}: {result.text}")
    if fresh and cfg.settings.toasts:
        integration.notify_and_open_on_click(*integration.updates_message([names[i] for i in fresh]))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--reset" in args:
        from . import config

        backup = config.reset()
        print(f"Settings reset. The old ones were saved as {backup}." if backup else "Nothing to reset.")
        args.remove("--reset")
    if "--check" in args:
        return check(if_due="--if-due" in args)

    from . import integration

    # Already open: bring that window to the front instead of opening a second one.
    if integration.tell_running_app("show"):
        return 0
    integration.install_menu_entry()

    # KDE's own look for buttons, lists, etc. Needs QApplication rather than QGuiApplication.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    from .backend import Backend

    app = QApplication([sys.argv[0], *args])
    app.setApplicationName("RepoProject")
    app.setOrganizationName("RepoProject")
    # Ties the window, its notifications and its taskbar badge to the menu entry.
    app.setDesktopFileName(integration.APP_ID)
    app.setWindowIcon(QIcon.fromTheme(integration.ICON))
    # Let Ctrl+C in the terminal close the app.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    backend = Backend(find_icons=True, desktop=True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        return 1

    # Listen for a second launch ("show") and the background checker ("check").
    server = QLocalServer()
    path = str(integration.socket_path())
    QLocalServer.removeServer(path)  # left over if the app didn't close cleanly last time

    def on_connection():
        while (conn := server.nextPendingConnection()) is not None:
            conn.waitForReadyRead(1000)
            backend.handleRequest(bytes(conn.readAll()).decode(errors="replace").strip())
            conn.disconnectFromServer()

    server.newConnection.connect(on_connection)
    server.listen(path)

    code = app.exec()
    server.close()
    backend.shutdown()
    return code
