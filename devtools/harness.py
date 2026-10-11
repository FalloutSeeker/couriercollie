"""Drive the real window off-screen for checks: run steps on a timer, click things by objectName, save screenshots.

Used by the scripts next to this file. Nothing here touches your real settings: each run uses a fresh settings file
(optionally a copy of yours). Screenshots go to RepoProject/.uicheck/ (ignored by git).

Screenshots differ from the desktop in one known way: off-screen windows don't get the desktop's font fallback, so
wrapped text in the small font looks double-spaced. On the desktop it isn't (checked 2026-10-11).

    python3 -I devtools/check_scan.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / ".uicheck"


def start(copy_settings_from: Path | None = None, settings: dict | None = None, find_icons: bool = False):
    """Start the app off-screen. `settings` (names as in Backend.settings) are applied before the window loads, as a
    real start would have them; the welcome screen is marked done unless they say otherwise."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
    # Drawn with OpenGL, as on the desktop. Off-screen windows otherwise use Qt's software renderer, which draws some
    # icons on top of open dialogs (never seen on the desktop).
    os.environ.setdefault("QT_QUICK_BACKEND", "rhi")
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    config_path = Path(tempfile.mkdtemp()) / "repos.toml"
    if copy_settings_from and copy_settings_from.exists():
        shutil.copy(copy_settings_from, config_path)
    os.environ["REPOPROJECT_CONFIG"] = str(config_path)
    os.environ["XDG_CACHE_HOME"] = str(config_path.parent / "cache")  # icons found during a check stay out of yours
    os.environ["REPOPROJECT_STATE"] = str(config_path.parent / "checks.json")  # and so do update-check results
    sys.path.insert(0, str(PROJECT))
    OUT.mkdir(exist_ok=True)
    return Harness({"firstLaunchDone": True, **(settings or {})}, find_icons)


class Harness:
    def __init__(self, settings: dict, find_icons: bool = False):
        from PySide6.QtCore import qInstallMessageHandler
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickWindow  # noqa: F401  (so the window is a QQuickWindow)
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QUrl

        from repoproject.backend import Backend

        self.messages = []
        qInstallMessageHandler(lambda _m, _c, text: self.messages.append(text))
        self.app = QApplication(sys.argv)
        self.backend = Backend(find_icons=find_icons)
        self.backend.updateSettings(settings)
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.load(QUrl.fromLocalFile(str(PROJECT / "repoproject/qml/Main.qml")))
        self.win = self.engine.rootObjects()[0]
        self.win.setProperty("width", 1150)
        self.win.setProperty("height", 800)
        self.failures = []
        self._find = self.engine.evaluate("""(function (root, name, windowHeight) {
            function walk(item) {
                // "text:Check Now" finds a button by its text (toolbar buttons made from actions have no name).
                const wanted = name.startsWith("text:") ? item.text === name.slice(5) : item.objectName === name;
                if (wanted && item.visible) return item;
                for (let i = 0; i < item.children.length; i++) {
                    const found = walk(item.children[i]);
                    if (found) return found;
                }
                return null;
            }
            const item = walk(root);
            if (!item) return null;
            // Scrolled out of sight (e.g. further down a page): scroll it into the middle, as a person would.
            let p = item.mapToItem(null, item.width / 2, item.height / 2);
            for (let f = item.parent; f && (p.y < 0 || p.y > windowHeight); f = f.parent) {
                if (f.contentY === undefined || f.contentHeight === undefined || !f.contentItem) continue;
                const inside = item.mapToItem(f.contentItem, 0, item.height / 2).y;
                const lowest = Math.max(f.originY, f.originY + f.contentHeight - f.height);
                f.contentY = Math.max(f.originY, Math.min(lowest, inside - f.height / 2));
                p = item.mapToItem(null, item.width / 2, item.height / 2);
            }
            return [p.x, p.y, !!item.checked];
        })""")

        self._box = self.engine.evaluate("""(function (root, name) {
            function walk(item) {
                if (item.objectName === name && item.visible) return item;
                for (let i = 0; i < item.children.length; i++) {
                    const found = walk(item.children[i]);
                    if (found) return found;
                }
                return null;
            }
            const item = walk(root);
            if (!item) return null;
            const p = item.mapToItem(null, 0, 0);
            return [p.x, p.y, item.width, item.height];
        })""")

    def window(self, title):
        """Another open window (e.g. "Settings"), or None."""
        from PySide6.QtGui import QGuiApplication

        return next((w for w in QGuiApplication.topLevelWindows() if w.isVisible() and w.title() == title), None)

    def find(self, name, window=None):
        """[x, y, checked] of a visible item with this objectName, or None. Looks in dialogs too."""
        from PySide6.QtQml import QJSValue

        window = window or self.win
        # The name as a QJSValue: PySide can't pass a plain str with characters beyond ASCII (e.g. ’) in the list.
        return self._find.call([self.engine.newQObject(window.contentItem()), QJSValue(name),
                                window.height()]).toVariant()

    def click(self, name, window=None):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        window = window or self.win
        where = self.find(name, window)
        if not where:
            self.fail(f"not visible: {name}")
            return
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(int(where[0]), int(where[1])))

    def double_click(self, name, window=None):
        # Not two click()s: QTest spaces separate clicks apart so they never count as a double-click.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        window = window or self.win
        where = self.find(name, window)
        if not where:
            self.fail(f"not visible: {name}")
            return
        QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(int(where[0]), int(where[1])))

    def drag(self, name, onto, where=0.5, window=None, before_letting_go=None):
        """Press on `name`, move in steps to the item `onto` (at `where` of its height: 0.25 for its top half, 0.75
        for its bottom half), and let go there. `before_letting_go()` runs while it's still held (e.g. a screenshot)."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        window = window or self.win
        start, target = self.find(name, window), self._find_box(onto, window)
        if not start or not target:
            self.fail(f"not visible: {name if not start else onto}")
            return
        x, y = int(start[0]), int(start[1])
        to_y = int(target[1] + target[3] * where)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
        for i in range(1, 11):
            QTest.mouseMove(window, QPoint(x, y + (to_y - y) * i // 10), 10)
        QTest.qWait(200)  # a few frames, as while a real hand drags
        if before_letting_go:
            before_letting_go()
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(x, to_y))

    def _find_box(self, name, window):
        """[x, y, width, height] of a visible item, in the window."""
        from PySide6.QtQml import QJSValue

        where = self.find(name, window)
        if not where:
            return None
        return self._box.call([self.engine.newQObject(window.contentItem()), QJSValue(name)]).toVariant()

    def call(self, object_name, method):
        from PySide6.QtCore import QMetaObject, QObject

        QMetaObject.invokeMethod(self.win.findChild(QObject, object_name), method)

    def shot(self, name, window=None):
        path = OUT / f"{name}.png"
        (window or self.win).grabWindow().save(str(path))
        print("screenshot:", path)

    def check(self, label, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
        if not ok:
            self.failures.append(label)

    def fail(self, message):
        print("FAIL " + message)
        self.failures.append(message)

    def visible(self, object_name) -> bool:
        from PySide6.QtCore import QObject

        obj = self.win.findChild(QObject, object_name)
        return bool(obj and obj.property("visible"))

    @staticmethod
    def until(condition, timeout_ms=120000):
        """A step that waits (checking every half second) until condition() is true, or the timeout passes."""
        return ("until", condition, timeout_ms)

    def run(self, steps):
        """steps: list of (delay in ms, function) or Harness.until(...). Returns 0 if everything passed."""
        from PySide6.QtCore import QTimer

        def go(i):
            if i == len(steps):
                self.app.quit()
                return
            if steps[i][0] == "until":
                _, condition, timeout = steps[i]

                def poll(waited=0):
                    if condition():
                        go(i + 1)
                    elif waited >= timeout:
                        self.fail(f"step {i}: timed out waiting")
                        go(i + 1)
                    else:
                        QTimer.singleShot(500, lambda: poll(waited + 500))

                poll()
                return
            delay, fn = steps[i]

            def step():
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    self.fail(f"step {i}: {e!r}")
                go(i + 1)

            QTimer.singleShot(delay, step)

        go(0)
        self.app.exec()
        self.backend.shutdown()
        noise = ("oxygen",)
        warnings = [m for m in self.messages if not any(n in m.lower() for n in noise)]
        self.check("no Qt warnings", not warnings, "; ".join(warnings))
        print("FAILURES:", self.failures or "none")
        return 1 if self.failures else 0
