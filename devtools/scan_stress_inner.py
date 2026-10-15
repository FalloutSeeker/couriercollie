"""Scanning and adding, the hard way, in a container (devtools/check_scan_stress.sh), through the real window
(off-screen), as a person would: clicks, the keyboard, the footer buttons. Backend slots are only read, never called
in the window's place (except where noted: a folder picked in the folder dialog).

A messy, realistic home folder is made first (real clones of real projects from /cache, AppImages, a package
installed from a downloaded file, symlink loops, a deep tree, an unreadable folder, hidden folders, …), then:

    main     1. the first scan from the welcome screen; 2. scanning from Settings later, with things changing between
             scans; 3. the Add dialog, with many kinds of address; 4. stress: 40+ finds, rapid scans, a scan and a
             check at once; and last, quitting in the middle of a scan.
    restart  the app started again with the same settings, after quitting mid-scan: nothing lost or stuck.
    package  a short first scan, with the INSTALLED app (not /app's copy).

    python3 scan_stress_inner.py main|restart|package       (as a normal user; HOME is made first by `main`)
    python3 -I scan_stress_inner.py --clones                 (what /cache must hold: "url folder" lines)
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

GH = "https://github.com/"
# Real projects, cloned once (shallow) into the cache by check_scan_stress.sh. Their cache folders: owner_name.
FIRST = ["junegunn/vim-plug", "tpope/vim-surround", "tpope/vim-commentary", "tpope/vim-repeat", "tpope/vim-abolish",
         "tpope/vim-sensible", "Suvratam/vim-sensible", "tpope/vim-unimpaired", "dylanaraps/pfetch",
         "junegunn/fzf.vim", "junegunn/limelight.vim", "mhinz/vim-startify", "nvim-tree/nvim-web-devicons",
         "editorconfig/editorconfig-vim", "junegunn/goyo.vim", "junegunn/vim-easy-align", "fernandogmo/vim-sensible",
         "tpope/vim-eunuch"]
STRESS = ["tpope/vim-unimpaired", "tpope/vim-eunuch", "preservim/nerdcommenter", "airblade/vim-gitgutter",
          "itchyny/lightline.vim", "tmux-plugins/tpm", "tmux-plugins/tmux-sensible", "tmux-plugins/tmux-resurrect",
          "nvim-lua/plenary.nvim", "folke/which-key.nvim", "numToStr/Comment.nvim", "kylechui/nvim-surround",
          "windwp/nvim-autopairs", "stevearc/oil.nvim", "ggandor/leap.nvim", "nvim-lualine/lualine.nvim",
          "zsh-users/zsh-autosuggestions", "zsh-users/zsh-syntax-highlighting", "fatih/color", "pkg/errors",
          "BurntSushi/toml", "rs/xid", "mitchellh/mapstructure", "sindresorhus/slugify", "isaacs/once",
          "tpope/vim-fugitive", "tpope/vim-rhubarb", "tpope/vim-dispatch", "tpope/vim-obsession", "tpope/vim-vinegar",
          "tpope/vim-speeddating", "tpope/vim-endwise", "tpope/vim-sleuth", "junegunn/seoul256.vim",
          "junegunn/vim-peekaboo", "junegunn/gv.vim", "morhetz/gruvbox", "dracula/vim", "sjl/gundo.vim",
          "godlygeek/tabular", "easymotion/vim-easymotion", "christoomey/vim-tmux-navigator", "wellle/targets.vim",
          "machakann/vim-sandwich", "mbbill/undotree", "Yggdroot/indentLine"][2:]  # (the first two: in FIRST)
OTHER = ["https://gitlab.com/pages/plain-html", "https://gitlab.com/gitlab-org/frontend/eslint-plugin",
         "https://gitlab.freedesktop.org/xdg/xdg-specs", "https://github.com/google/uuid"]
# Asked of GitHub too (the relay's allow-list is every github.com/owner/name in this file): a renamed project's old
# name, an AppImage's old owner, a project that doesn't exist, the test package's homepage, the Add dialog's targets.
ALSO_ASKED = ["github.com/kyazdani42/nvim-web-devicons", "github.com/AppImage/AppImageUpdate",
              "github.com/AppImageCommunity/AppImageUpdate", "github.com/FalloutSeeker/cc-no-such-project",
              "github.com/neovim/neovim", "github.com/sharkdp/hyperfine", "github.com/FalloutSeeker/couriercollie",
              "github.com/rupa/z", "github.com/dylanaraps/pure-sh-bible", "github.com/dylanaraps/pure-bash-bible",
              "github.com/romkatv/zsh-defer", "github.com/zsh-users/zsh-completions", "github.com/spf13/pflag",
              "github.com/mattn/go-isatty", "github.com/kr/pretty", "github.com/sethwoodworth/vim-sensible",
              "github.com/junegunn/VIM-PLUG"]


def cache_name(url):
    return url.split("://")[-1].replace("github.com/", "").replace("/", "_")


if sys.argv[1:] == ["--clones"]:
    for p in FIRST + STRESS:
        print(GH + p, cache_name(GH + p))
    for u in OTHER:
        print(u, cache_name(u))
    sys.exit(0)

PHASE = sys.argv[1]
HOME = Path(os.environ["HOME"])
CACHE = Path("/cache")
STATE = HOME / ".stress-state"  # the app's settings for this run: kept from one phase to the next (a restart)
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}
PACKAGE = os.environ.get("TEST_PACKAGE", "")  # "rpm"/"deb": cc-test-tool, installed from a file, homepage hyperfine
T0 = time.monotonic()


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=ENV).stdout.strip()


def real_clone(folder, project, remotes=None):
    """A copy of a real (shallow) clone, with its remotes as given ({name: url}; default: origin, https, .git)."""
    src = CACHE / cache_name(project if "://" in project else GH + project)
    dest = HOME / folder
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=True)
    remotes = remotes or {"origin": (project if "://" in project else GH + project) + ".git"}
    git(dest, "remote", "remove", "origin")
    for name, url in remotes.items():
        git(dest, "remote", "add", name, url)
    return dest


def fake_clone(folder, remote=""):
    """A clone of a project that isn't (or can't be) fetched: one commit, and its remote, if any."""
    dest = HOME / folder
    dest.mkdir(parents=True)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "commit", "-q", "--allow-empty", "-m", "first")
    if remote:
        git(dest, "remote", "add", "origin", remote)


def make_home():
    real_clone("code/vim-plug", "junegunn/vim-plug")  # https, .git
    real_clone("code/vim-surround", "tpope/vim-surround", {"origin": "git@github.com:tpope/vim-surround.git"})
    real_clone("code/vim-commentary", "tpope/vim-commentary", {"origin": "https://github.com/tpope/vim-commentary"})
    real_clone("code/plain-html", "https://gitlab.com/pages/plain-html")  # GitLab
    real_clone("code/eslint-plugin", "https://gitlab.com/gitlab-org/frontend/eslint-plugin")  # a GitLab subgroup
    real_clone("code/xdg-specs", "https://gitlab.freedesktop.org/xdg/xdg-specs")  # a self-hosted GitLab
    fake_clone("code/foot", "https://codeberg.org/dnkl/foot.git")  # Codeberg: not supported
    fake_clone("code/hare", "https://git.sr.ht/~sircmpwn/hare")  # an unknown site
    fake_clone("code/gone", "https://github.com/FalloutSeeker/cc-no-such-project")  # deleted, or private
    fake_clone("code/scratch")  # no remote
    # Renamed: kyazdani42/nvim-web-devicons is nvim-tree/nvim-web-devicons now.
    real_clone("code/devicons", "nvim-tree/nvim-web-devicons",
               {"origin": "https://github.com/kyazdani42/nvim-web-devicons.git"})
    real_clone("code/vim-repeat", "tpope/vim-repeat",  # several remotes: origin counts
               {"upstream": "https://github.com/tpope/vim-eunuch.git", "origin": "https://github.com/tpope/vim-repeat"})
    real_clone("code/abolish", "tpope/vim-abolish", {"github": "https://github.com/tpope/vim-abolish.git"})  # no origin
    real_clone("code/vim-sensible", "tpope/vim-sensible")
    real_clone("forks/vim-sensible", "Suvratam/vim-sensible",  # a fork, its upstream above
               {"origin": "git@github.com:Suvratam/vim-sensible.git", "upstream": "https://github.com/tpope/vim-sensible"})
    real_clone("code/unimpaired", "tpope/vim-unimpaired")
    real_clone("code/unimpaired/extra/pfetch", "dylanaraps/pfetch")  # a clone inside a clone
    real_clone("code/fzf.vim", "junegunn/fzf.vim")
    real_clone("old/fzf.vim", "junegunn/fzf.vim")  # the same project, twice
    real_clone("deep/d1/d2/d3/limelight.vim", "junegunn/limelight.vim")  # 5 deep: found
    real_clone("deep/d1/d2/d3/d4/d5/d6/goyo.vim", "junegunn/goyo.vim")  # 7 deep: past the scan's depth
    real_clone(".hidden/editorconfig-vim", "editorconfig/editorconfig-vim")  # hidden: not looked in
    real_clone(".config/nvim/pack/plugins/start/goyo.vim", "junegunn/goyo.vim")
    # A huge tree: 15 x 15 x 15 folders.
    for a in range(15):
        for b in range(15):
            for c in range(15):
                (HOME / f"tree/a{a}/b{b}/c{c}").mkdir(parents=True)
    # Symlink loops.
    (HOME / "code/loop").symlink_to(HOME / "code")
    (HOME / "self").symlink_to(HOME)
    (HOME / "deep/d1/back").symlink_to("../..")
    (HOME / "dangling").symlink_to(HOME / "nowhere")
    # AppImages: real ones, one renamed without its version (and found twice), one without update info, a fake.
    apps, downloads = HOME / "Applications", HOME / "Downloads"
    apps.mkdir()
    downloads.mkdir()
    (HOME / ".local/bin").mkdir(parents=True, exist_ok=True)
    for name, where in (("nvim-linux-x86_64.appimage", apps / "nvim-linux-x86_64.appimage"),
                        ("nvim-linux-x86_64.appimage", downloads / "Neovim.AppImage"),
                        ("appimagetool-x86_64.AppImage", apps / "appimagetool-x86_64.AppImage"),
                        ("appimageupdatetool-x86_64.AppImage", HOME / ".local/bin/appimageupdatetool.AppImage")):
        shutil.copy(CACHE / "appimages" / name, where)
        where.chmod(0o755)
    (apps / "notes.AppImage").write_text("not an AppImage at all\n")
    (HOME / "bin").mkdir()
    (HOME / "bin/nvim.AppImage").symlink_to(apps / "nvim-linux-x86_64.appimage")


GHID = "github.com/"
NEW = {GHID + p.lower() for p in ["junegunn/vim-plug", "tpope/vim-surround", "tpope/vim-commentary",
                                  "nvim-tree/nvim-web-devicons", "tpope/vim-repeat", "tpope/vim-abolish",
                                  "tpope/vim-sensible", "Suvratam/vim-sensible", "tpope/vim-unimpaired",
                                  "dylanaraps/pfetch", "junegunn/fzf.vim", "junegunn/limelight.vim",
                                  "mhinz/vim-startify", "neovim/neovim", "AppImageCommunity/AppImageUpdate"]}
NEW |= {"gitlab.com/pages/plain-html", "gitlab.com/gitlab-org/frontend/eslint-plugin",
        "gitlab.freedesktop.org/xdg/xdg-specs"}
if PACKAGE:
    NEW.add("github.com/sharkdp/hyperfine")
PROBLEM = {"codeberg.org/dnkl/foot", "git.sr.ht/~sircmpwn/hare", "github.com/falloutseeker/cc-no-such-project"}
MYSELF = "github.com/falloutseeker/couriercollie"
NOT_LISTED = {GHID + p for p in ["editorconfig/editorconfig-vim", "junegunn/goyo.vim", "junegunn/vim-easy-align",
                                 "appimage/appimagetool"]}

if PHASE in ("main", "package"):
    make_home()
    print(f"home made in {time.monotonic() - T0:.1f}s", flush=True)

sys.path.insert(0, "/app/devtools")
import harness  # noqa: E402

import tempfile  # noqa: E402

STATE.mkdir(exist_ok=True)
harness.OUT = Path("/out") if Path("/out").is_dir() else HOME / "shots"  # screenshots
tempfile.mkdtemp = lambda *a, **k: str(STATE)  # the harness's settings folder: the same one, phase after phase
if PHASE == "package":
    # The installed app, not /app's copy: where the package put it.
    found = subprocess.run(["python3", "-I", "-c", "import sys; sys.path.insert(0, '/usr/share/couriercollie'); "
                            "import couriercollie, os; print(os.path.dirname(os.path.dirname(couriercollie.__file__)))"],
                           capture_output=True, text=True, cwd="/").stdout.strip()
    harness.PROJECT = Path(found)
    print("the installed app, from", found, flush=True)
first = PHASE in ("main", "package")
h = harness.start(settings={"firstLaunchDone": False} if first else None)
b, app, win = h.backend, h.app, h.win
import couriercollie  # noqa: E402

print("app from:", couriercollie.__file__, flush=True)
from couriercollie import updater  # noqa: E402

updater.ROOT = []
from PySide6.QtCore import QEvent, QMetaObject, QObject, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

if first:
    b._track_myself()  # as the app's first start does (the harness skips the desktop's start-up)
    b.reposChanged.emit()
win.resize(1100, 800)
fails = []
add_errors = []
b.addFailed.connect(lambda m: add_errors.append(m))


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""), flush=True)
    if not ok:
        fails.append(label)


def note(*a):
    print("  ..", *a, flush=True)


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    app.processEvents()
    return cond()


def dialog():
    return win.findChild(QObject, "scanDialog")


def items():
    return {i["address"].lower(): i for i in b.scanItems}


def picked():
    return dialog().property("pickedCount")


def ticked(address):
    item = items().get(address.lower())
    where = item and h.find("found:" + item["address"])
    return bool(where and where[2])


def tracked():
    return [r.id.lower() for r in b._config.repos]


def no_duplicates(label):
    ids = tracked()
    aliases = [a.lower() for r in b._config.repos for a in r.aliases]
    dup = sorted({i for i in ids if ids.count(i) > 1} | (set(ids) & set(aliases)))
    check(label, not dup, dup)


def click(name, window=None):
    # Where it is once it's stopped moving (a dialog can still be settling: Kirigami re-centres it as it grows).
    where = h.find(name, window)
    for _ in range(20):
        pump(seconds=0.1)
        if (now := h.find(name, window)) == where:
            break
        where = now
    before = len(h.failures)
    h.click(name, window)
    if len(h.failures) > before:
        fails.append(h.failures[-1])
    pump(seconds=0.25)


def press(dialog_name, text):
    before = len(h.failures)
    h.press(dialog_name, text)
    if len(h.failures) > before:
        fails.append(h.failures[-1])
    pump(seconds=0.25)


def track_selected():
    press("scanDialog", f"Track Selected ({picked()})")


def focused_name():
    item = win.activeFocusItem()
    return item.objectName() if item else ""


def tab_to(name, limit=120):
    """Tab (and nothing else) until the keyboard is on the item with this name. True if it got there."""
    for _ in range(limit):
        if focused_name() == name:
            return True
        QTest.keyClick(win, Qt.Key.Key_Tab)
        pump(seconds=0.03)
    return focused_name() == name


def overflow():
    """[x, y] of the toolbar's ⋮ button (Kirigami's overflow menu: it has no text or name), or None."""
    return h.engine.evaluate("""(function (root) {
        function walk(i) {
            if (i.visible && i.icon && i.icon.name === "overflow-menu") return i;
            for (let k = 0; k < i.children.length; k++) { const f = walk(i.children[k]); if (f) return f; }
            return null;
        }
        const m = walk(root);
        if (!m) return null;
        const p = m.mapToItem(null, m.width / 2, m.height / 2);
        return [p.x, p.y];
    })""").call([h.engine.newQObject(win.contentItem())]).toVariant()


def toolbar(text):
    """A toolbar button, or the item in its ⋮ menu if it's there (Scan… usually is)."""
    if not h.find("text:" + text) and (more := overflow()):
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(more[0]), int(more[1])))
        pump(seconds=0.5)
    click("text:" + text)


def scan_available():
    """Whether Scan… is in the toolbar or its ⋮ menu."""
    if h.find("text:Scan…"):
        return True
    more = overflow()
    if not more:
        return False
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(more[0]), int(more[1])))
    pump(seconds=0.5)
    there = h.find("text:Scan…") is not None
    QTest.keyClick(win, Qt.Key.Key_Escape)
    pump(seconds=0.3)
    if h.find("text:Settings") is not None and overflow() and h.find("text:Scan…"):
        click("checkSummary")  # (a click elsewhere closes the menu)
    return there


def scan_from_toolbar(wait=True):
    toolbar("Scan…")
    pump(lambda: b.scanState == "scanning", 5)
    if wait:
        return pump(lambda: b.scanState == "done", 600)
    return True


def close_scan():
    press("scanDialog", "Close")
    pump(lambda: not dialog().property("visible"), 3)


def checks_ok(label, timeout=600):
    pump(lambda: not b.checking, timeout)
    c = b.checks
    bad = {r.id: b.repo(r.id).get("checkText") for r in b._config.repos
           if b._checks.results.get(r.id) and b._checks.results[r.id].status in ("failed", "unreachable")}
    check(label, not b.checking and not c.get("error") and not c.get("failed"),
          f"checking={b.checking} error={c.get('error')!r} failed={c.get('failed')} {bad}")


def list_rows_shown(ids, label):
    """In the list's rows (its model: rows scrolled out of sight aren't made)."""
    view = win.findChild(QObject, "repoList")
    model = view.property("model") or []
    shown = {(r.toVariant() if hasattr(r, "toVariant") else r).get("id", "").lower() for r in model}
    missing = [i for i in ids if i not in shown]
    check(label, not missing and view.property("count") == len(model), (missing, view.property("count"), len(model)))


def all_checked(label):
    """Every tracked repo has a check result (the list says something for each)."""
    unchecked = [r.id for r in b._config.repos if not b.repo(r.id).get("checkText")]
    check(label, not unchecked, unchecked)


def summary(label):
    note(label, [(i["address"], i["status"], i["note"][:60]) for i in b.scanItems])


def settings_window():
    return h.window("Settings")


# ---------------------------------------------------------------------------------------------------------------------
def first_scan(short=False):
    pump(lambda: h.visible("firstLaunch"), 10)
    check("the welcome screen opens", h.visible("firstLaunch"))
    click("scanBox")
    press("firstLaunch", "Done")
    check("Done on the welcome screen starts the scan", pump(lambda: b.scanState == "scanning", 5))
    t = time.monotonic()
    pump(lambda: b.scanState == "done", 600)
    note(f"first scan took {time.monotonic() - t:.1f}s")
    pump(seconds=0.8)
    h.shot("scan-stress-first")
    summary("first scan")
    check("the scan finished without an error", b.scanError == "", b.scanError)
    got = items()
    news = {a for a, i in got.items() if i["status"] == "new"}
    check("every new project is listed as new", news == NEW, f"missing {sorted(NEW - news)}, extra {sorted(news - NEW)}")
    problems = {a for a, i in got.items() if i["status"] == "problem"}
    check("finds that can't be tracked are listed as problems", problems == PROBLEM,
          f"missing {sorted(PROBLEM - problems)}, extra {sorted(problems - PROBLEM)} "
          f"{[(a, got[a]['note']) for a in problems - PROBLEM]}")
    if PACKAGE:
        check("couriercollie's own package: listed as added by default", got.get(MYSELF, {}).get("status") == "default",
              got.get(MYSELF))
    check("hidden, too deep, unreadable, and AppImages without update info: not listed",
          not (NOT_LISTED & set(got)), sorted(NOT_LISTED & set(got)))
    check("nothing listed twice", len(b.scanItems) == len(got), len(b.scanItems))
    for a, why in (("codeberg.org/dnkl/foot", "supported"), ("git.sr.ht/~sircmpwn/hare", "supported"),
                   ("github.com/falloutseeker/cc-no-such-project", "Not found")):
        check(f"{a} says why it can't be tracked", why in got.get(a, {}).get("note", ""), got.get(a))
    fzf = got.get("github.com/junegunn/fzf.vim", {})
    check("a project cloned twice: one row, 'Also in 1 other place'", "1 other place" in fzf.get("note", ""), fzf)
    nv = got.get("github.com/neovim/neovim", {})
    check("Neovim's AppImage (found 3 times: renamed copy, symlink): one row", "other place" in nv.get("note", ""), nv)
    dev = got.get("github.com/nvim-tree/nvim-web-devicons", {})
    check("a renamed project is listed under its new name", dev.get("name") == "nvim-web-devicons", dev)
    st = got.get("github.com/mhinz/vim-startify", {})
    check("a clone the system owns (/opt) says updating will ask for a password", "password" in st.get("note", ""), st)
    check("every new find is ticked to start with", all(ticked(a) for a in news), [a for a in news if not ticked(a)])
    check("problems aren't ticked", not any(ticked(a) for a in problems))
    check("Track Selected counts the ticked", picked() == len(news), f"{picked()} vs {len(news)}")
    note("keyboard on, when the results show:", repr(focused_name()), win.activeFocusItem())
    skipped = h.find("skippedFolders")
    note("skipped folders message:", bool(skipped))
    if short:
        click("selectAll")
        track_selected()
        pump(lambda: len(b._config.repos) >= len(news) + 1, 10)
        check("Track Selected tracks every ticked find", set(tracked()) >= news, sorted(news - set(tracked())))
        close_scan()
        checks_ok("then the check finishes without failures")
        return

    # Untick by click, and by the keyboard (Tab to the row, Space).
    click("found:github.com/tpope/vim-commentary")
    check("a click unticks a row", not ticked("github.com/tpope/vim-commentary") and picked() == len(news) - 1)
    reached = tab_to("found:github.com/junegunn/fzf.vim")
    check("Tab reaches a row", reached, focused_name())
    QTest.keyClick(win, Qt.Key.Key_Space)
    pump(seconds=0.3)
    check("Space unticks it", not ticked("github.com/junegunn/fzf.vim") and picked() == len(news) - 2,
          picked())
    QTest.keyClick(win, Qt.Key.Key_Space)
    pump(seconds=0.3)
    check("Space again ticks it", ticked("github.com/junegunn/fzf.vim") and picked() == len(news) - 1, picked())
    reached = tab_to("found:codeberg.org/dnkl/foot", limit=60)
    note("Tab reaches a problem row (disabled):", reached)
    click("selectNone")
    check("Select None: nothing ticked, button disabled", picked() == 0)
    press("scanDialog", "Track Selected (0)")
    check("Track Selected (0) does nothing", len(b._config.repos) == 1, tracked())
    # Three ticked by hand: exactly those.
    three = ["gitlab.com/pages/plain-html", "github.com/tpope/vim-sensible", "github.com/neovim/neovim"]
    for a in three:
        click("found:" + items()[a]["address"])
    check("three ticked: the button says 3", picked() == 3, picked())
    track_selected()
    pump(lambda: len(b._config.repos) == 4, 10)
    check("Track Selected tracks exactly the ticked ones", sorted(tracked()) == sorted([MYSELF] + three),
          sorted(tracked()))
    left = items()
    check("…they leave the list, the rest stays, unticked",
          not any(a in left for a in three) and len(left) == len(got) - 3 and picked() == 0,
          (len(left), len(got), picked()))
    click("selectAll")
    check("Select All ticks every trackable find, and nothing else", picked() == len(news) - 3
          and not any(ticked(a) for a in PROBLEM), picked())
    track_selected()
    pump(lambda: len(b._config.repos) == len(news) + 1, 10)
    check("Track Selected (all): everything new is tracked", set(tracked()) == news | {MYSELF},
          f"missing {sorted(news - set(tracked()))}")
    no_duplicates("nothing tracked twice")
    left = items()
    check("only problems (and couriercollie) are left in the window",
          all(i["status"] in ("problem", "default") for i in left.values()), [(a, i["status"]) for a, i in left.items()])
    check("…and the counter is 0", picked() == 0)
    h.shot("scan-stress-tracked")
    close_scan()
    pump(seconds=1)
    list_rows_shown(news, "the list shows a row for each")
    checks_ok("the check after Track Selected finishes without failures")
    all_checked("…and every repo tracked has been checked (the list says something for each)")
    pump(lambda: not b.checking, 600)
    toolbar("Check Now")
    pump(lambda: b.checking, 3)
    checks_ok("Check Now finishes without failures")
    all_checked("…and after it, every repo has been checked")
    nv = b._config.find("github.com/neovim/neovim")
    note("neovim tracked as:", nv.kind, nv.asset_pattern, nv.installed, nv.local_path)
    au = next((r for r in b._config.repos if r.id.lower() == "github.com/appimagecommunity/appimageupdate"), None)
    note("AppImageUpdate tracked as:", au and (au.kind, au.asset_pattern, au.installed, au.aliases))
    dv = b._config.find("github.com/nvim-tree/nvim-web-devicons")
    check("the renamed project keeps its old address as an alias",
          dv and "github.com/kyazdani42/nvim-web-devicons" in [a.lower() for a in dv.aliases], dv and dv.aliases)
    for r in b._config.repos:
        note(f"{r.id}: {b.repo(r.id).get('checkText')!r}")


# ---------------------------------------------------------------------------------------------------------------------
def settings_and_rescans():
    toolbar("Settings")
    pump(lambda: settings_window() is not None, 5)
    sw = settings_window()
    check("Settings opens from the toolbar", sw is not None)
    if not sw:
        return
    click("removeFolder:/srv", sw)
    check("removing a default folder (/srv)", "/srv" not in b._config.settings.scan_folders,
          b._config.settings.scan_folders)
    check("…offers Reset Scan Folders", h.find("restoreFolders", sw) is not None)
    # Add Folder…: the folder dialog, picked as a person would pick (its selectedFolder, then accepted).
    click("text:Add Folder…", sw)
    pump(seconds=0.5)
    picker = next((o for o in win.findChildren(QObject) + sw.findChildren(QObject)
                   if "FolderDialog" in o.metaObject().className()
                   and "Impl" not in o.metaObject().className()), None)
    note("folder dialog:", picker and picker.metaObject().className(), picker and picker.property("visible"))
    driven = False
    if picker is not None:
        driven = picker.setProperty("selectedFolder", QUrl.fromLocalFile("/root"))
        if driven:
            QMetaObject.invokeMethod(picker, "accept")
            pump(seconds=0.5)
    if not driven or "/root" not in b._config.settings.scan_folders:
        note("the folder dialog couldn't be driven off-screen: the folder goes in as the dialog's onAccepted does")
        b.addScanFolder("file:///root")
    else:
        note("folder added through the folder dialog itself")
    b.addScanFolder("file:///nonexistent/folder")  # (a folder that's gone since: the dialog can't pick one)
    pump(seconds=0.5)
    check("an unreadable folder (/root) says scans skip it",
          h.find("folderProblem:/root", sw) is not None
          and "can’t open" in next(f["problem"] for f in b.settings["scanFolders"] if f["path"] == "/root"))
    check("a folder that isn't there says so", h.find("folderProblem:/nonexistent/folder", sw) is not None)
    # Scanning off: the Scan button goes; back on: it's back.
    click("text:Allow scanning this computer", sw)
    pump(seconds=0.3)
    check("the switch turns scanning off", not b._config.settings.scanning)
    # (The main window's ⋮ menu is looked in with Settings closed: off-screen, a click on the main window while
    # Settings has the focus only gives it back.)
    sw.close()
    pump(seconds=0.5)
    check("…and Scan… leaves the toolbar (and its ⋮ menu)", not scan_available())
    toolbar("Settings")
    pump(lambda: settings_window() is not None, 5)
    sw = settings_window()
    click("text:Allow scanning this computer", sw)
    pump(seconds=0.3)
    sw.close()
    pump(seconds=0.5)
    check("…and back on, Scan… with it", b._config.settings.scanning and scan_available())

    # Scan again: nothing new; the folders it couldn't look in are named.
    n = len(b._config.repos)
    scan_from_toolbar()
    pump(seconds=0.5)
    summary("rescan")
    check("rescan: nothing already tracked is offered as new", not any(i["status"] == "new" for i in b.scanItems),
          [i["address"] for i in b.scanItems if i["status"] == "new"])
    check("rescan: nothing added", len(b._config.repos) == n)
    check("rescan: the folders not looked in are named", h.find("skippedFolders") is not None)
    note("updated by the rescan:", b.scanUpdated)
    close_scan()
    pump(lambda: not b.checking, 300)

    # Things change between scans.
    (HOME / "moved").mkdir()
    shutil.move(str(HOME / "code/vim-plug"), str(HOME / "moved/vim-plug"))
    shutil.rmtree(HOME / "code/vim-surround")
    git(HOME / "code/vim-commentary", "remote", "set-url", "origin", "https://github.com/tpope/vim-eunuch.git")
    real_clone("mirrors/vim-sensible", "fernandogmo/vim-sensible")
    scan_from_toolbar()
    pump(seconds=0.5)
    summary("after changes")
    got = items()
    vp = b._config.find("github.com/junegunn/vim-plug")
    check("a moved clone: found where it is now", vp.local_path == str(HOME / "moved/vim-plug"), vp.local_path)
    check("a moved clone: not offered again", "github.com/junegunn/vim-plug" not in got)
    vs = b._config.find("github.com/tpope/vim-surround")
    note("deleted clone: still tracked:", vs is not None, "| list says:", vs and b.repo(vs.id).get("checkText"))
    eun = got.get("github.com/tpope/vim-eunuch", {})
    check("a clone whose remote now points at another project: offered as that project", eun.get("status") == "new",
          eun)
    vc = b._config.find("github.com/tpope/vim-commentary")
    note("…and vim-commentary, tracked at that folder, now:", vc.local_path, b.repo(vc.id).get("checkText"))
    mir = got.get("github.com/fernandogmo/vim-sensible", {})
    check("a mirror of a tracked project: 'similar', not ticked", mir.get("status") == "similar"
          and not ticked("github.com/fernandogmo/vim-sensible"), mir)
    click("selectNone")
    click("found:github.com/fernandogmo/vim-sensible")
    n = len(b._config.repos)
    track_selected()
    pump(seconds=1)
    vsen = b._config.find("github.com/tpope/vim-sensible")
    check("ticked and tracked, the mirror is linked to it, not added", len(b._config.repos) == n
          and "github.com/fernandogmo/vim-sensible" in [a.lower() for a in vsen.aliases], (len(b._config.repos), n))
    note("vim-sensible's folder after linking the mirror:", vsen.local_path)
    close_scan()
    pump(lambda: not b.checking, 300)

    pump(lambda: not b.checking, 300)
    note("once checked: deleted clone (vim-surround) says", repr(b.repo("github.com/tpope/vim-surround").get("checkText")),
         "| moved vim-plug says", repr(b.repo("github.com/junegunn/vim-plug").get("checkText")))
    # Closing mid-scan, opening again; Scan while a scan runs.
    toolbar("Scan…")
    pump(lambda: b.scanState == "scanning", 5)
    close_scan()
    check("closed mid-scan: the scan carries on (or has finished)", b.scanState in ("scanning", "done")
          and b.scanError == "", (b.scanState, b.scanError))
    toolbar("Scan…")  # again, while it runs
    # (Running, or just done: Arch scans no packages, and its scan can finish before the ⋮ menu has been opened.)
    check("Scan while one runs: the window opens on the running scan", h.visible("scanDialog")
          and b.scanState in ("scanning", "done") and b.scanError == "", (b.scanState, b.scanError))
    pump(lambda: b.scanState == "done", 600)
    pump(seconds=0.5)
    check("…and shows its results, new ones ticked", ticked("github.com/tpope/vim-eunuch"), items().keys())
    close_scan()
    pump(lambda: not b.checking, 300)


# ---------------------------------------------------------------------------------------------------------------------
def add_dialog():
    def open_add():
        click("text:Add…")
        pump(lambda: h.visible("addDialog"), 3)
        return h.visible("addDialog")

    def attempt(text, how="enter"):
        """Type an address into Add's field with the keyboard and press Enter (or click Add). Returns
        ("added", id) or ("error", message) or ("nothing", "")."""
        if not h.visible("addDialog") and not open_add():
            return ("no dialog", "")
        field = win.findChild(QObject, "addUrl")
        if focused_name() != "addUrl":
            click("addUrl")
        QTest.keyClick(win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(win, Qt.Key.Key_Delete)
        for ch in text:  # typed, a key at a time
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(kind, 0, Qt.KeyboardModifier.NoModifier, ch))
        pump(seconds=0.1)
        typed = field.property("text")
        before, errors = set(tracked()), len(add_errors)
        if how == "enter":
            QTest.keyClick(win, Qt.Key.Key_Return)
        else:
            press("addDialog", "Add")
        pump(lambda: b.adding, 1)
        pump(lambda: not b.adding and (len(add_errors) > errors or set(tracked()) != before
                                       or not h.visible("addDialog")), 90)
        pump(seconds=0.3)
        new = set(tracked()) - before
        if new:
            win.closeRepo()  # (Add opens the new repo's page)
            pump(seconds=0.3)
            return ("added", new.pop())
        if len(add_errors) > errors:
            return ("error", add_errors[-1])
        return ("nothing", typed)

    open_add()
    check("Add: the address field has the keyboard", focused_name() == "addUrl", focused_name())
    cases = [
        ("https://github.com/rupa/z", "button", "added", "github.com/rupa/z"),
        ("github.com/dylanaraps/pure-sh-bible", "enter", "added", "github.com/dylanaraps/pure-sh-bible"),
        ("dylanaraps/pure-bash-bible", "enter", "error", "owner"),
        ("https://github.com/dylanaraps/pure-bash-bible.git/", "enter", "added", "github.com/dylanaraps/pure-bash-bible"),
        ("https://www.github.com/romkatv/zsh-defer/tree/master", "enter", "added", "github.com/romkatv/zsh-defer"),
        ("https://github.com/zsh-users/zsh-completions/releases", "enter", "added",
         "github.com/zsh-users/zsh-completions"),
        ("https://github.com/spf13/pflag/releases/tag/v1.0.5", "button", "added", "github.com/spf13/pflag"),
        ("HTTPS://GITHUB.COM/MATTN/GO-ISATTY", "enter", "added", "github.com/mattn/go-isatty"),
        ("git@github.com:kr/pretty.git", "enter", "added", "github.com/kr/pretty"),
        ("https://gitlab.com/gitlab-org/ci-cd/codequality", "enter", "added", "gitlab.com/gitlab-org/ci-cd/codequality"),
        ("https://gitlab.com/gitlab-org/cloud-native/gitlab-operator/-/releases", "enter", "added",
         "gitlab.com/gitlab-org/cloud-native/gitlab-operator"),
        ("https://invent.kde.org/sdk/kdesrc-build/-/tree/master", "enter", "added", "invent.kde.org/sdk/kdesrc-build"),
        ("https://gitlab.com/pages/plain-html/-/tree/main", "enter", "error", "Already tracking"),
        ("https://GitHub.com/JUNEGUNN/VIM-PLUG/", "enter", "error", "Already tracking"),
        ("https://github.com/kyazdani42/nvim-web-devicons", "enter", "error", "Already tracking"),
        ("https://codeberg.org/dnkl/foot", "enter", "error", "supported"),
        ("https://bitbucket.org/atlassian/python-bitbucket", "enter", "error", "supported"),
        ("hello world", "enter", "error", ""),
        ("   ", "enter", "nothing", ""),
        ("", "button", "nothing", ""),
        ("https://github.com/sethwoodworth/vim-sensible", "enter", "added", "github.com/sethwoodworth/vim-sensible"),
    ]
    for text, how, want, detail in cases:
        got, what = attempt(text, how)
        ok = got == want and (want != "added" or what == detail) and (want != "error" or detail in what)
        check(f"Add {text!r} ({how}): {want}", ok, f"{got}: {what}")
    if h.visible("addDialog"):
        press("addDialog", "Cancel")
    sv = b._config.find("github.com/sethwoodworth/vim-sensible")
    note("Add didn't say a mirror looks like vim-sensible (a scan would): added as its own repo:", sv is not None)
    # GitLab's sub-pages without "/-/" (GitLab's site takes these too).
    got, what = attempt("https://gitlab.com/gitlab-org/frontend/eslint-plugin/tree/main")
    note("gitlab address with /tree/main (no /-/):", got, what)
    if h.visible("addDialog"):
        press("addDialog", "Cancel")
    no_duplicates("after adding: nothing tracked twice")

    # Adding while a scan runs, of something the scan will find: it isn't offered by that scan, nor the next.
    real_clone("later/uuid", "https://github.com/google/uuid")
    toolbar("Scan…")
    pump(lambda: b.scanState == "scanning", 5)
    close_scan()
    got, what = attempt("https://github.com/google/uuid")
    during = b.scanState == "scanning"
    check("Add while a scan runs", got == "added", f"{got} {what}")
    note("…the add finished while the scan was still running:", during)
    if h.visible("addDialog"):
        press("addDialog", "Cancel")
    pump(lambda: b.scanState == "done", 600)
    stale = items().get("github.com/google/uuid", {}).get("status") == "new"
    if during:
        check("…the running scan doesn't offer it as new", not stale, items().get("github.com/google/uuid"))
    else:
        note("…the scan ended before the add: it lists it as new:", stale)
    pump(lambda: not b.checking, 300)
    scan_from_toolbar()
    check("…nor the next one", "github.com/google/uuid" not in items(), items().get("github.com/google/uuid"))
    uu = b._config.find("github.com/google/uuid")
    check("…which links the added repo to the clone it found", uu and uu.local_path == str(HOME / "later/uuid"),
          uu and uu.local_path)
    close_scan()
    pump(lambda: not b.checking, 300)
    no_duplicates("after add + scan: nothing tracked twice")


# ---------------------------------------------------------------------------------------------------------------------
def stress():
    for p in STRESS:
        dest = Path("/data/stress") / p.replace("/", "_")
        shutil.copytree(CACHE / cache_name(GH + p), dest, symlinks=True)
    b.addScanFolder("/data/stress")  # (as the folder dialog does)
    n = len(b._config.repos)
    t = time.monotonic()
    scan_from_toolbar()
    note(f"scan with {len(STRESS)} more clones: {time.monotonic() - t:.1f}s")
    want = {GHID + p.lower() for p in STRESS}
    news = {a for a, i in items().items() if i["status"] == "new"}
    check(f"{len(STRESS)}+ finds at once: all listed as new", want <= news, sorted(want - news))
    check("…all ticked, and counted", picked() == len(news), (picked(), len(news)))
    track_selected()
    pump(lambda: len(b._config.repos) >= n + len(news), 20)
    check("Track Selected on all of them", set(tracked()) >= want and len(b._config.repos) == n + len(news),
          (len(b._config.repos), n, len(news)))
    no_duplicates("…nothing tracked twice")
    close_scan()
    checks_ok(f"the check of {len(b._config.repos)} repos finishes without failures", 900)
    all_checked("…and every one of them was checked")
    pump(seconds=1)
    list_rows_shown(sorted(want)[:5] + sorted(want)[-5:], "their rows are in the list")

    # Ten scans in a row, fast.
    n, t = len(b._config.repos), time.monotonic()
    for i in range(10):
        toolbar("Scan…")
        pump(lambda: b.scanState == "scanning", 3)
        if i % 3 == 0:
            close_scan()
            toolbar("Scan…")  # (Scan again while it runs)
        pump(lambda: b.scanState == "done", 600)
        close_scan()
    note(f"10 scans: {time.monotonic() - t:.1f}s")
    pump(lambda: not b.checking, 300)
    check("10 scans: nothing added, nothing new", len(b._config.repos) == n
          and not any(i["status"] == "new" for i in b.scanItems), [i["address"] for i in b.scanItems
                                                                    if i["status"] == "new"])
    no_duplicates("10 scans: nothing tracked twice")

    # A scan and Check Now at once.
    pump(lambda: not b.checking, 600)
    toolbar("Check Now")
    pump(lambda: b.checking, 3)
    toolbar("Scan…")
    pump(lambda: b.scanState == "done", 600)
    close_scan()
    checks_ok("Check Now with a scan running: the check finishes without failures", 900)
    check("…and the scan too", b.scanState == "done" and b.scanError == "", b.scanError)
    scan_from_toolbar()
    close_scan()
    pump(lambda: not b.checking, 600)
    toolbar("Check Now")  # (and the other way round)
    checks_ok("a scan then Check Now: fine", 900)
    no_duplicates("nothing tracked twice")


# ---------------------------------------------------------------------------------------------------------------------
def quit_mid_scan():
    """As the app quits (app.py: after its event loop ends): with a scan running."""
    (HOME / ".stress-before-quit").write_text("\n".join(sorted(tracked())) + "\n")
    toolbar("Scan…")
    pump(lambda: b.scanState == "scanning", 5)
    print("quitting mid-scan:", b.scanState, flush=True)
    b.finish_updates()
    b.shutdown()
    print(f"QUIT_AT {time.time():.2f}", flush=True)


def restart():
    pump(seconds=2)
    before = (HOME / ".stress-before-quit").read_text().split()
    check("after quitting mid-scan: every repo is still tracked", sorted(tracked()) == before,
          f"lost {sorted(set(before) - set(tracked()))}, extra {sorted(set(tracked()) - set(before))}")
    check("…no settings problem", b.configError == "" and b.saveError == "", (b.configError, b.saveError))
    check("…the welcome screen isn't shown again", not h.visible("firstLaunch"))
    check("…scanning is still on, with the same folders", b._config.settings.scanning
          and "/data/stress" in b._config.settings.scan_folders, b._config.settings.scan_folders)
    check("…no scan stuck", b.scanState == "idle", b.scanState)
    scan_from_toolbar()
    check("…a scan runs, and offers nothing new", b.scanError == "" and not any(i["status"] == "new"
                                                                                 for i in b.scanItems),
          [i["address"] for i in b.scanItems if i["status"] == "new"])
    close_scan()
    checks_ok("…and Check Now works", 900)


def run(step):
    try:
        step()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(f"{step.__name__} ran to the end", False, repr(e))


if PHASE == "main":
    for step in (first_scan, settings_and_rescans, add_dialog, stress):
        print(f"--- {step.__name__} ({time.monotonic() - T0:.0f}s)", flush=True)
        run(step)
elif PHASE == "package":
    run(lambda: first_scan(short=True))
else:
    run(restart)
warnings = [m for m in h.messages if "oxygen" not in m.lower() and "breeze-internal" not in m]  # (icons: container)
# KDE's own, inside its own files (Kirigami, and KDE's style), which some distros' versions log (Ubuntu's toolbar when
# the actions change, "Could not create delegate for ToolBarLayout"; Debian's menus): noted, not failed. Anything
# that starts in couriercollie's code fails.
theirs = [m for m in warnings if m.startswith("qrc:/qt/qml/org/kde/")
          or m.startswith("Could not create delegate for ToolBarLayout")]
warnings = [m for m in warnings if m not in theirs]
if theirs:
    note(f"Kirigami's own messages (not failed): {len(theirs)}, e.g. {theirs[0][:120]!r}")
print("qt messages:", warnings[:15], flush=True)
check("no Qt warnings from couriercollie's code", not warnings, len(warnings))
print("FAILURES:", fails or "none", flush=True)
if PHASE == "main":
    run(quit_mid_scan)
    sys.stdout.flush()
    sys.exit(1 if fails else 0)  # (as the app returns from main(): whatever's still running finishes first)
b.shutdown()
sys.exit(1 if fails else 0)
