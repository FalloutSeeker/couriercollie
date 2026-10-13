"""A tour of every screen, for looking over: the welcome screen, the list (wide and narrow), a repo page in each state
(update, up to date, not installed, new commits on a clone, versions only, an error), the dialogs, Settings from top to
bottom, and signing in. No network: the projects and the sites' answers are made up. Screenshots go to .uicheck/look-*.

    python3 -I devtools/check_look.py          # in your desktop's theme
    python3 -I devtools/check_look.py dark     # in Breeze Dark

The README's screenshot is taken from real projects instead: devtools/readme_shot.sh.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DARK = "dark" in sys.argv[1:]
work = Path(tempfile.mkdtemp())
if DARK:
    # KDE's style reads its colours from kdeglobals: a copy with Breeze Dark's, in a folder of its own.
    config = work / "config"
    config.mkdir()
    scheme = Path("/usr/share/color-schemes/BreezeDark.colors").read_text()
    (config / "kdeglobals").write_text(scheme + "\n[General]\nColorScheme=BreezeDark\n[Icons]\nTheme=breeze-dark\n"
                                       "[KDE]\nwidgetStyle=Breeze\n")
    os.environ["XDG_CONFIG_HOME"] = str(config)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


# A clone on this computer, with an install script, a commit behind the project.
clone = work / "aerothemeplasma"
clone.mkdir()
git("init", "-q", "-b", "main", cwd=clone)
(clone / "install.sh").write_text("#!/bin/sh\n# Copies the theme's files into place.\ncp -r plasma ~/.local/share/\n")
(clone / "README.md").write_text("# AeroThemePlasma\n\nA theme.\n\n## Updating\n\nPull the newest commits, then run "
                                 "`install.sh` again and log out and back in.\n\n## License\n\nGPL\n")
git("add", ".", cwd=clone)
git("commit", "-q", "-m", "first", cwd=clone)
git("remote", "add", "origin", "https://gitgud.io/aeroshell/atp/aerothemeplasma.git", cwd=clone)
yours = git("rev-parse", "HEAD", cwd=clone)
# LocalSend's AppImage, found on this computer (its version is read from the file's name).
appimage = Path(os.environ["HOME"]) / "Applications" / "LocalSend-1.17.0-linux-x86-64.AppImage"
appimage.parent.mkdir(parents=True, exist_ok=True)
appimage.write_bytes(b"\x7fELF" + b"\0" * 4 + b"AI\x02")
NEWEST = "9" * 40

REPOS = [
    # id, name, extra settings
    ("github.com/localsend/localsend", "LocalSend", 'follow = "releases"\nasset_pattern = "LocalSend-*-linux-x86-64.AppImage"'
     f'\nkind = "AppImage"\ninstalled = "v1.17.0"\nsource = "scanned"\nlocal_path = "{appimage}"'
     '\ndescription = "An open-source cross-platform alternative to AirDrop"'),
    # An AppImage added by hand: where yours is isn't known, so Install puts a new copy in place.
    ("github.com/neovim/neovim", "Neovim", 'follow = "releases"\nasset_pattern = "nvim-linux-x86_64.appimage"'
     '\nkind = "AppImage"\ninstalled = "v0.11.3"\ndescription = "Vim-fork focused on extensibility and usability"'),
    ("github.com/BurntSushi/ripgrep", "ripgrep", 'follow = "releases"\nasset_pattern = "ripgrep-*-x86_64-unknown-linux-musl.tar.gz"'
     '\nkind = "Program"\ninstalled = "14.1.1"\ndescription = "ripgrep recursively searches directories for a regex pattern"'),
    ("github.com/zed-industries/zed", "Zed", 'follow = "releases"\nasset_pattern = "zed-linux-x86_64.tar.gz"\nkind = "Program"'
     '\ninstalled = "-"\ndescription = "Code at the speed of thought"\ncategory = "Tools"'),
    ("gitgud.io/aeroshell/atp/aerothemeplasma", "AeroThemePlasma", f'follow = "branch"\nbranch = "main"\nkind = "git"'
     f'\ninstalled = "{yours}"\nsource = "scanned"\nlocal_path = "{clone}"\nhost = "gitlab"'
     '\ndescription = "An alternative shell for KDE Plasma that aims to replicate the look and feel of Windows 7."'),
    ("github.com/ImranR98/Obtainium", "Obtainium", 'follow = "releases"\nkind = "versions"\ninstalled = "v1.1.0"'
     '\ndescription = "Get Android app updates straight from the source"\ncategory = "Tools"'),
    # Installed by the package manager, with a version set by hand too: shown only, never updated here.
    ("github.com/KDE/dolphin", "Dolphin", 'follow = "releases"\ninstalled = "v26.04.0"'
     '\ndescription = "File manager by KDE"'),
    ("github.com/example/gone", "Gone Project", 'follow = "releases"\ninstalled = "v1"'),
    ("github.com/example/notes", "Notes", 'follow = "branch"\nbranch = "main"\ninstalled = "-"'),
]

settings = work / "repos.toml"
lines = ['categories = ["Tools"]\n']
for repo_id, name, extra in REPOS:
    host = "gitlab" if "gitgud" in repo_id else "github"
    extra_lines = extra if "host =" in extra else f'host = "{host}"\n{extra}'
    lines.append(f'[[repos]]\nid = "{repo_id}"\nname = "{name}"\nurl = "https://{repo_id}"\n{extra_lines}\n')
settings.write_text("\n".join(lines))

h = harness.start(copy_settings_from=settings, settings={"firstLaunchDone": False, "scanning": True,
                                                         "autoCheck": True})
b = h.backend

from couriercollie import account, checker, github_login, sources  # noqa: E402
from couriercollie import backend as backend_module  # noqa: E402

from PySide6.QtCore import QObject  # noqa: E402

DATE = datetime(2026, 9, 30, tzinfo=timezone.utc)


def asset(name, size=60_000_000):
    return sources.Asset(name, f"https://example.invalid/{name}", size)


def release(tag, files, notes="", prerelease=False):
    return sources.Release(tag, tag, DATE, prerelease,
                           notes or "### What's new\n- Faster startup\n- Fixes a crash when the window is resized",
                           f"https://example.invalid/{tag}", [asset(f) for f in files])


RELEASES = {
    "github.com/localsend/localsend": [release(t, [f"LocalSend-{t[1:]}-linux-x86-64.AppImage",
                                                   f"LocalSend-{t[1:]}-linux-x86-64.tar.gz",
                                                   f"LocalSend-{t[1:]}-windows-x86-64.exe"])
                                       for t in ("v1.18.2", "v1.18.0", "v1.17.0")],
    "github.com/BurntSushi/ripgrep": [release("14.1.1", ["ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz",
                                                         "ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz",
                                                         "ripgrep_14.1.1-1_amd64.deb"])],
    "github.com/neovim/neovim": [release(t, ["nvim-linux-x86_64.appimage", "nvim-linux-arm64.appimage",
                                             "nvim-win64.zip"]) for t in ("v0.11.4", "v0.11.3")],
    "github.com/zed-industries/zed": [release("v0.160.4", ["zed-linux-x86_64.tar.gz", "zed-linux-aarch64.tar.gz",
                                                           "Zed-aarch64.dmg"])],
    "github.com/ImranR98/Obtainium": [release("v1.2.0", ["app-arm64-v8a-release.apk", "app-x86_64-release.apk"]),
                                      release("v1.1.0", ["app-arm64-v8a-release.apk"])],
    "gitgud.io/aeroshell/atp/aerothemeplasma": [],
    "github.com/KDE/dolphin": [release("v26.08.2", []), release("v26.08.1", [])],
    "github.com/example/notes": [],
}


def fake_releases(ref, host, count=30, **_):
    if ref.id == "github.com/example/gone":
        raise sources.NotFound("Project not found. Check the address, and that the project is public.")
    return RELEASES.get(ref.id, [])[:count]


sources.releases = fake_releases
sources.branches = lambda ref: ("main", [sources.Branch("main", NEWEST), sources.Branch("plasma-6.6", "8" * 40)])
sources.compare = lambda ref, host, yours, head: sources.Comparison(sources.BEHIND, 3, [
    sources.Commit(NEWEST, "Fix the taskbar thumbnails on HiDPI screens"),
    sources.Commit("7" * 40, "Update translations"),
    sources.Commit("6" * 40, "Make the start menu open faster")])
account.password_store = lambda: "KDE Wallet"
# Its containers, as if running (applying.py asks podman or docker on a real computer).
from couriercollie import applying  # noqa: E402

applying.running_compose = lambda path: applying.Compose(["podman-compose"], "aerothemeplasma",
                                                         [f"{path}/docker-compose.yml"], ["app"]) \
    if Path(path).name == "aerothemeplasma" else None
# Not this computer's package manager: only Dolphin is "installed with dnf".
backend_module._managed_elsewhere = lambda ids, website="": (("Your package manager keeps this up to date.", "dnf", "26.08.1")
                                                 if "github.com/KDE/dolphin" in ids else ("", "", ""))


def checked():
    results = {
        "github.com/localsend/localsend": checker.Result(checker.UPDATE, "Update available: v1.18.2", "v1.18.2"),
        "github.com/BurntSushi/ripgrep": checker.Result(checker.UP_TO_DATE, "Up to date", "14.1.1"),
        "github.com/neovim/neovim": checker.Result(checker.UPDATE, "Update available: v0.11.4", "v0.11.4"),
        "github.com/zed-industries/zed": checker.Result(checker.NOT_INSTALLED_YET, "Not installed · newest v0.160.4",
                                                        "v0.160.4"),
        "gitgud.io/aeroshell/atp/aerothemeplasma": checker.Result(checker.UPDATE, "3 new commits on main", NEWEST),
        "github.com/ImranR98/Obtainium": checker.Result(checker.UPDATE, "Update available: v1.2.0", "v1.2.0"),
        "github.com/example/gone": checker.Result(checker.FAILED, "Couldn’t check: Project not found. Check the address, "
                                                  "and that the project is public."),
    }
    b._checks = checker.State(last_run=checker.now().isoformat(timespec="seconds"), results=results)
    b._save_checks()  # as a real check does: the app reloads the results file when it changes
    b.reposChanged.emit()


def page(repo_id, name):
    def ready():
        return b.details(repo_id)["state"] in ("ready", "error")
    return [
        (0, lambda: h.win.openRepo(repo_id)),
        h.until(ready, 10000),
        (600, lambda: h.shot(f"look-{'dark-' if DARK else ''}{name}")),
    ]


def shot(name, window=None):
    return lambda: h.shot(f"look-{'dark-' if DARK else ''}{name}", window() if window else None)


def settings_window():
    return h.window("Settings")


def scroll_settings(to):
    return lambda: h.find(to, settings_window())


def signing_in():
    github_login.start = lambda: github_login.DeviceCode("d", "WDJB-MJHT", github_login.VERIFY_URL, 5, 900)
    github_login.wait = lambda code, cancelled: (cancelled.wait(), (_ for _ in ()).throw(github_login.LoginError("x")))
    b.startSignIn()


h.run([
    (800, shot("0-welcome")),
    (0, lambda: h.call("firstLaunch", "done")),
    (300, lambda: h.call("scanDialog", "close")),
    (0, checked),
    (500, shot("1-list")),
    *page("github.com/localsend/localsend", "2-update"),
    *page("github.com/BurntSushi/ripgrep", "3-current"),
    *page("github.com/neovim/neovim", "3b-new-copy"),
    *page("github.com/zed-industries/zed", "4-not-installed"),
    *page("gitgud.io/aeroshell/atp/aerothemeplasma", "5-clone-behind"),
    # The first Update asks what runs after it downloads, showing it to read.
    (0, lambda: h.click("updateNow")),
    (600, shot("5b-update-asks")),
    (0, lambda: h.press("stepDialog", "Cancel")),
    # Chosen from Tracking instead (Change…), then run: the fake project has no compose file, so it fails, with its
    # output shown.
    (600, lambda: h.click("changeStep")),  # (once the closing dialog has gone)
    (500, lambda: h.press("stepDialog", "Use This")),
    (500, shot("5c-step-chosen")),
    (0, lambda: b.runStep("gitgud.io/aeroshell/atp/aerothemeplasma")),
    h.until(lambda: b.details("gitgud.io/aeroshell/atp/aerothemeplasma")["stepResult"] != "", 30000),
    (500, shot("5d-step-failed")),
    *page("github.com/ImranR98/Obtainium", "6-versions-only"),
    # Renaming: double-click the name, type, Enter.
    (0, lambda: h.double_click("repoName")),
    (500, lambda: h.check("rename opens on a double-click", h.visible("renameDialog"))),
    (0, lambda: h.win.findChild(QObject, "renameField").setProperty("text", "Obtainium (phone)")),
    (300, shot("6c-rename")),
    (0, lambda: h.call("renameDialog", "rename")),
    (500, lambda: h.check("renamed in the list and on the page", b.repo("github.com/ImranR98/Obtainium")["name"]
                          == "Obtainium (phone)" and h.find("text:Obtainium (phone)") is not None)),
    (0, lambda: b.renameRepo("github.com/ImranR98/Obtainium", "Obtainium")),
    *page("github.com/KDE/dolphin", "6b-package-manager"),
    *page("github.com/example/gone", "7-error"),
    *page("github.com/example/notes", "8-branch-not-installed"),
    (0, lambda: h.win.closeRepo()),
    (0, lambda: h.win.showAddDialog()),
    (600, shot("9-add")),
    (0, lambda: h.call("addDialog", "close")),
    (300, lambda: h.click("text:New Category…")),
    (600, shot("10-new-category")),
    (0, lambda: h.call("newCategoryDialog", "close")),
    (300, lambda: h.win.openSettings()),
    (600, lambda: settings_window().setHeight(1250)),  # all of it at once
    (900, shot("11-settings", settings_window)),
    (0, signing_in),
    (0, scroll_settings("githubUserCode")),
    (600, shot("14-signing-in", settings_window)),
    (0, lambda: b.cancelSignIn()),
    (0, lambda: settings_window().close()),
    (300, lambda: (h.win.setProperty("width", 560))),
    (600, shot("15-narrow-list")),
    *page("github.com/localsend/localsend", "16-narrow-page"),
])
