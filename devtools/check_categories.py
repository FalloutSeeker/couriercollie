"""Categories in the list, with a simulated mouse: make one in the New Category dialog, drag repos into and around
categories, drag a category above another, rename one from its ⋮ menu and by double-clicking its name, and delete one
(its repos stay, in Uncategorized). No network needed.

    python3 -I devtools/check_categories.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

REPOS = {"github.com/a/alpha": "Alpha", "github.com/a/bravo": "Bravo", "gitlab.com/a/charlie": "Charlie",
         "github.com/a/delta": "Delta"}
settings = Path(tempfile.mkdtemp()) / "repos.toml"
settings.write_text("".join(
    f'[[repos]]\nid = "{i}"\nname = "{n}"\nurl = "https://{i}"\nhost = "{i.split(".")[0]}"\nkind = "git"\n'
    f'follow = "branch"\nbranch = "main"\n\n' for i, n in REPOS.items()))

h = harness.start(copy_settings_from=settings)
b = h.backend


def in_category(name):
    return [r.name for r in b._config.repos if r.category == name]


def type_name(text, then="Enter"):
    """Types into whatever has focus, then presses Enter (or `then`: "Esc", or "" for nothing). "\b" is Backspace."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QGuiApplication, QKeyEvent

    def press(key, char=""):
        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
            QGuiApplication.sendEvent(h.win, QKeyEvent(kind, key, Qt.NoModifier, char))

    for char in text:
        if char == "\b":
            press(Qt.Key_Backspace)
        else:
            press(Qt.Key_A + ord(char.upper()) - ord("A") if char.isalpha() else Qt.Key_unknown, char)
    if then:
        press({"Enter": Qt.Key_Return, "Esc": Qt.Key_Escape}[then])


h.run([
    (700, lambda: h.check("no headings without categories", h.find("category:Uncategorized") is None)),
    (0, lambda: h.click("newCategory")),
    (500, lambda: type_name("Themes")),
    (500, lambda: h.check("New Category dialog added it", b.categories == ["Themes"], f"got {b.categories}")),
    (0, lambda: h.check("headings shown", h.find("category:Uncategorized") is not None
                        and h.find("category:Themes") is not None)),
    (0, lambda: h.check("empty category says so", h.find("text:Empty. Drag repos here by their handles.") is not None)),
    (0, lambda: h.click("newCategory")),
    (500, lambda: type_name("themes")),
    (500, lambda: h.check("same name refused", b.categories == ["Themes"])),
    (0, lambda: h.shot("categories-0-same-name")),
    (0, lambda: type_name("\b" * 6 + "Tools")),
    (500, lambda: h.check("second category", b.categories == ["Themes", "Tools"], f"got {b.categories}")),
    # Onto a heading: the top of that category.
    (0, lambda: h.drag("dragRepo:github.com/a/alpha", "category:Themes")),
    (500, lambda: h.check("Alpha dragged into Themes", in_category("Themes") == ["Alpha"], f"{in_category('Themes')}")),
    # Onto the top half of a repo: just above it.
    (0, lambda: h.drag("dragRepo:github.com/a/delta", "repo:github.com/a/alpha", 0.25)),
    (500, lambda: h.check("Delta dropped above Alpha", in_category("Themes") == ["Delta", "Alpha"],
                          f"{in_category('Themes')}")),
    # Onto the bottom half of a repo: just below it.
    (0, lambda: h.drag("dragRepo:github.com/a/bravo", "repo:github.com/a/delta", 0.75,
                       before_letting_go=lambda: h.shot("categories-dragging"))),
    (500, lambda: h.check("Bravo dropped below Delta", in_category("Themes") == ["Delta", "Bravo", "Alpha"],
                          f"{in_category('Themes')}")),
    (0, lambda: h.drag("dragRepo:github.com/a/alpha", "category:Tools")),
    (500, lambda: h.check("Alpha moved on to Tools", in_category("Tools") == ["Alpha"])),
    (0, lambda: h.drag("dragCategory:Tools", "category:Themes")),
    (500, lambda: h.check("Tools dragged above Themes", b.categories == ["Tools", "Themes"], f"got {b.categories}")),
    (0, lambda: h.check("…taking its repos", in_category("Tools") == ["Alpha"])),
    (0, lambda: h.drag("dragCategory:Tools", "category:Uncategorized")),
    (500, lambda: h.check("Uncategorized stays first", b.rows[0]["label"] == "Uncategorized")),
    (0, lambda: h.shot("categories-1-sorted")),
    # Rename from the ⋮ menu: the name turns into a text box with the old name selected.
    (0, lambda: h.click("categoryMenu:Tools")),
    (400, lambda: h.click("renameCategory:Tools")),
    (400, lambda: h.check("rename shows a text box", h.find("renameField:Tools") is not None)),
    (0, lambda: type_name("Utilities")),
    (500, lambda: h.check("renamed from the menu, in the same place", b.categories == ["Utilities", "Themes"],
                          f"got {b.categories}")),
    (0, lambda: h.check("…with its repos", in_category("Utilities") == ["Alpha"])),
    # Double-click the name; a name that's taken is refused and says why; Esc gives up.
    (0, lambda: h.double_click("categoryName:Themes")),
    (400, lambda: h.check("double-click renames", h.find("renameField:Themes") is not None)),
    (0, lambda: type_name("utilities")),
    (400, lambda: h.check("taken name refused, and says why", h.find("renameError") is not None
                          and b.categories == ["Utilities", "Themes"])),
    (0, lambda: h.shot("categories-rename-refused")),
    (0, lambda: type_name("", then="Esc")),
    (400, lambda: h.check("Esc cancels", h.find("renameField:Themes") is None and b.categories == ["Utilities", "Themes"])),
    (0, lambda: h.click("categoryMenu:Themes")),
    (400, lambda: h.shot("categories-menu")),
    (0, lambda: h.click("deleteCategory:Themes")),
    (500, lambda: h.check("asks before deleting a category with repos", h.visible("deleteCategoryDialog"))),
    (0, lambda: h.shot("categories-2-delete")),
    (0, lambda: h.call("deleteCategoryDialog", "accept")),
    (500, lambda: h.check("Themes deleted", b.categories == ["Utilities"], f"got {b.categories}")),
    (0, lambda: h.check("its repos kept, in Uncategorized", in_category("") == ["Charlie", "Delta", "Bravo"],
                        f"{in_category('')}")),
    (0, lambda: h.check("all 4 still tracked", len(b._config.repos) == 4)),
    (0, lambda: h.shot("categories-3-deleted")),
])
