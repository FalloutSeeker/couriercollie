"""The list from the keyboard: Tab comes into it (after the toolbar), Up and Down go from repo to repo past the
category headings, Enter opens one. No network.

    python3 -I devtools/check_keyboard.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

settings = Path(tempfile.mkdtemp()) / "repos.toml"
settings.write_text('categories = ["Tools"]\n' + "".join(
    f'[[repos]]\nid = "github.com/o/p{i}"\nname = "Project {i}"\nurl = ""\nhost = "github"\nfollow = "releases"\n'
    f'installed = "v1"\ncategory = "{"Tools" if i == 2 else ""}"\n\n' for i in range(4)))
h = harness.start(copy_settings_from=settings)
b = h.backend
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402


def key(k):
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QCoreApplication.sendEvent(h.win, QKeyEvent(kind, k, Qt.KeyboardModifier.NoModifier))


def the_list():
    return h.win.findChild(QObject, "repoList")


def selected():
    i = the_list().property("currentIndex")
    return b.rows[i].get("id") if i is not None and 0 <= i < len(b.rows) else None


def tab_into_the_list():
    for _ in range(12):
        key(Qt.Key.Key_Tab)
        if the_list().property("activeFocus"):
            return True
    return False


h.run([
    (500, lambda: h.win.requestActivate()),
    (300, lambda: h.check("Tab comes into the list", tab_into_the_list())),
    (200, lambda: h.check("…on the first repo", selected() == "github.com/o/p0", str(selected()))),
    (0, lambda: key(Qt.Key.Key_Down)),
    (0, lambda: key(Qt.Key.Key_Down)),
    (200, lambda: h.check("Down goes from repo to repo", selected() == "github.com/o/p3", str(selected()))),
    (0, lambda: key(Qt.Key.Key_Down)),
    (200, lambda: h.check("…past a category's heading", selected() == "github.com/o/p2", str(selected()))),
    (0, lambda: key(Qt.Key.Key_Up)),
    (200, lambda: h.check("Up goes back", selected() == "github.com/o/p3", str(selected()))),
    (0, lambda: h.shot("keyboard-list")),
    (0, lambda: key(Qt.Key.Key_Return)),
    (500, lambda: h.check("Enter opens it", h.win.property("currentRepoId") == "github.com/o/p3")),
])
