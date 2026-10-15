"""Dragging a repo in a long list, with a simulated mouse: hold it past the bottom of the window while the list
scrolls to the end, and past the top while it scrolls back. The drag mustn't be lost when its own row scrolls far out
of sight, and the dragged row stays in sight and comes back under the pointer. Let go at the end, it's dropped there.
No network needed.

    python3 -I devtools/check_drag_scroll.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

# 60 repos: 10 uncategorized, then 10 each in C1 to C5.
settings = Path(tempfile.mkdtemp()) / "repos.toml"
settings.write_text("".join(
    f'[[repos]]\nid = "github.com/a/r{i:02}"\nname = "R{i:02}"\nurl = "https://github.com/a/r{i:02}"\n'
    f'host = "github"\nkind = "git"\nfollow = "branch"\nbranch = "main"\n'
    + (f'category = "C{i // 10}"\n' if i >= 10 else "") + "\n" for i in range(60)))

h = harness.start(copy_settings_from=settings)
h.win.setProperty("height", 500)
pointer = {}


def item(name):
    from PySide6.QtCore import QObject

    return h.win.findChild(QObject, name)


def move_to(y):
    """Moves the held pointer to y in the window, in steps; past the window's edges too."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    step = 20 if y > pointer["y"] else -20
    for to in [*range(pointer["y"], y, step), y]:
        QTest.mouseMove(h.win, QPoint(pointer["x"], to), 10)
    pointer["y"] = y


def press():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    x, y, _ = h.find("dragRepo:github.com/a/r03")
    pointer.update(x=int(x), y=int(y))
    QTest.mousePress(h.win, Qt.LeftButton, Qt.NoModifier, QPoint(pointer["x"], pointer["y"]))
    move_to(h.win.height() + 80)


def release():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    QTest.mouseRelease(h.win, Qt.LeftButton, Qt.NoModifier, QPoint(pointer["x"], pointer["y"]))


def picture():
    """The dragged row's picture: [top, bottom] in the window, and where its grabbed point is."""
    p = item("dragPicture")
    top = p.mapToItem(h.win.contentItem(), 0, 0).y()
    return top, top + p.height(), top + item("repoList").property("grabOffset")


def list_box():
    lst = item("repoList")
    top = lst.mapToItem(h.win.contentItem(), 0, 0).y()
    return top, top + lst.height()


def in_sight(label):
    top, bottom, _ = picture()
    shown_top, shown_bottom = list_box()
    h.check(f"{label}: still dragging", item("repoList").property("dragged") is not None)
    h.check(f"{label}: the dragged row stays in sight", item("dragPicture").property("visible")
            and shown_top <= top and bottom <= shown_bottom, f"{top}..{bottom} in {shown_top}..{shown_bottom}")


def under_pointer(label):
    move_to(250)
    h.check(f"{label}: back under the pointer", abs(picture()[2] - 250) < 2, f"{picture()[2]}")


def scrolled(to_end):
    lst = item("repoList")
    y, lowest = lst.property("contentY"), lst.property("originY") + lst.property("contentHeight") - lst.height()
    return y >= lowest - 1 if to_end else y <= lst.property("originY") + 1


def dropped():
    r03 = next(r for r in h.backend._config.repos if r.id == "github.com/a/r03")
    h.check("let go at the end: dropped in the last category", r03.category == "C5", r03.category or "Uncategorized")
    h.check("the drag is over", item("repoList").property("dragged") is None)
    # Moving the mouse past the window here is the point; Qt's test tool warns about each such move.
    h.messages[:] = [m for m in h.messages if "outside target window" not in m]


sys.exit(h.run([
    (800, press),
    h.until(lambda: scrolled(to_end=True), 30000),
    (0, lambda: in_sight("past the bottom")),
    (0, lambda: h.shot("drag-scroll-past-bottom")),
    (0, lambda: under_pointer("past the bottom")),
    (0, lambda: move_to(-60)),
    h.until(lambda: scrolled(to_end=False), 30000),
    (0, lambda: in_sight("past the top")),
    (0, lambda: under_pointer("past the top")),
    (0, lambda: move_to(h.win.height() + 80)),
    h.until(lambda: scrolled(to_end=True), 30000),
    (0, release),
    (300, dropped),
]))
