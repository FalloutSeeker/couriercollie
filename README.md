# RepoProject

**Working name.** Something like Obtainium, but for Fedora KDE: a desktop app that keeps track of software you got
straight from GitHub or GitLab (git clones, release downloads, AppImages, loose programs), checks for new versions on a
schedule, and lets you update with a click.

## Status

**Stages 1–5 of PLAN.md are built.** You can add GitHub/GitLab repos by hand or scan this computer for them, sort
them into categories, browse their releases, build files and branches, set which version you have, check for updates
(by hand or in the background, with notifications), and update with a click: git clones are pulled (or moved to the
newest release), AppImages and programs from release archives are downloaded, checked and swapped in, and RPMs are
installed with dnf. Stage 6 (GitHub sign-in, packaging, GNOME) and stage 7 (release) aren't built yet.

## Running it

```sh
~/claudework/RepoProject/run.sh
```

Needs only what Fedora KDE already has: Python 3, PySide6 (`python3-pyside6`) and Kirigami. Your tracked repos are
saved in `~/.config/repoproject/repos.toml`.

Other ways to run it:

```sh
~/claudework/RepoProject/run.sh --check   # check every repo for updates now, without the window
```

**What it adds outside this folder** (all removable):

- `~/.local/share/applications/repoproject.desktop`: the menu entry (written when the app starts).
- `~/.config/systemd/user/repoproject-check.{timer,service}`: background checks, only while automatic checks are on
  (Settings). Turning them off removes the timer. To remove it by hand:
  `systemctl --user disable --now repoproject-check.timer`.
- `~/.local/state/repoproject/checks.json`: the last check's results. `~/.cache/repoproject/icons/`: repo icons.
- Only when you install or update something: AppImages in `~/Applications` (or beside the one you had), with a menu
  entry `~/.local/share/applications/repoproject-<repo>.desktop`; programs unpacked in
  `~/.local/share/repoproject/programs/`, with a link in `~/.local/bin`; RPMs through dnf (downloaded first to
  `~/.cache/repoproject/downloads/`, then deleted); projects you install by cloning, in `~/src`.

To start over as if newly installed (the welcome screen shows again), run it with `--reset`. Your settings file is
renamed to a dated backup next to it, not deleted:

```sh
~/claudework/RepoProject/run.sh --reset
```

## Tests

```sh
cd ~/claudework/RepoProject && python3 -m unittest discover -s tests -t .
```

They don't use the network: GitHub and GitLab answers are saved in `tests/fixtures/`, and downloads come from a
small local server the tests start.

`devtools/` has checks that drive the real window off-screen (clicks, screenshots in `.uicheck/`), using a temporary
copy of your settings:

```sh
python3 -I devtools/check_scan.py   # scans this computer and asks GitHub/GitLab about new finds
python3 -I devtools/check_pages.py  # clicks through the welcome screen, list, repo page and Settings
python3 -I devtools/check_settings.py        # the folder list in Settings
python3 -I devtools/check_scanned_repo.py    # a scanned clone's page: version from disk, new commits, branches
python3 -I devtools/check_icons.py           # looks up icons for your repos (temporary cache folder)
python3 -I devtools/check_updates.py         # Check Now, the status line, results, the rate-limit bar
python3 -I devtools/check_categories.py      # new category, dragging, renaming, deleting one
python3 -I devtools/check_update_clone.py    # Update on a temporary clone, refusals, showing and running a script
python3 -I devtools/check_install_clone.py   # Install clones a project added by hand, into a temporary folder
python3 -I devtools/check_appimage.py        # installs then updates LocalSend's AppImage, in temporary folders
python3 -I devtools/check_program.py         # installs then updates ripgrep from its .tar.gz, in temporary folders
python3 -I devtools/check_rpm.py             # bottom's real .rpm up to dnf, which is a stand-in: nothing is installed
```

## Code layout

| File                       | What it does                                                                   |
| -------------------------- | ------------------------------------------------------------------------------ |
| `repoproject/config.py`    | The settings file: global settings and tracked repos                           |
| `repoproject/sources.py`   | Talking to GitHub and GitLab: addresses, releases, branches                    |
| `repoproject/assets.py`    | Build files: which kind, whether it suits this PC, remembering your pick       |
| `repoproject/scan.py`      | Scanning: finding clones, RPMs and AppImages; matching them to tracked repos     |
| `repoproject/icons.py`     | Repo icons: from this computer, the project's site, or the default (D13)          |
| `repoproject/checker.py`   | Checking every repo for updates; results kept apart from settings                 |
| `repoproject/integration.py` | Menu entry, notifications, taskbar badge, background timer, one copy at a time |
| `repoproject/backend.py`   | Connects the window to the above; runs network work in the background          |
| `repoproject/qml/`         | The window: list page, repo page, Add dialog                                   |

## Files

| File                         | What's in it                                                      |
| ---------------------------- | ----------------------------------------------------------------- |
| [DESIGN.md](DESIGN.md)       | What the app does: features, screens, and how it works underneath |
| [DECISIONS.md](DECISIONS.md) | The choices made, and why                                         |
| [PLAN.md](PLAN.md)           | The build order, in stages                                        |
| [LOG.md](LOG.md)             | Dated notes on what we decided and did, newest first              |

## Background

- Started 2026-10-10 from a conversation about tracking GitHub updates on Fedora.
- First idea was a "custom dnf": a local package repo filled from GitHub releases, so plain `dnf upgrade` sees them.
  That idea still lives on as one way to install RPM updates (see DECISIONS.md, D4), but the main product is now a GUI.
