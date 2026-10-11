# colliecourier

Something like Obtainium, but for Fedora KDE: a desktop app that keeps track of software you got
straight from GitHub or GitLab (git clones, release downloads, AppImages, loose programs), checks for new versions on a
schedule, and lets you update with a click.

Tools already exist for pieces of this: Topgrade runs your updaters from a terminal, Gear Lever handles AppImages,
eget fetches release programs, nvchecker reports new versions. colliecourier brings these jobs together in one simple
window, so there's one app to install and learn instead of several tools and their commands.

## Status

**Stages 1–5 of PLAN.md are built.** You can add GitHub/GitLab repos by hand or scan this computer for them, sort
them into categories, browse their releases, build files and branches, set which version you have, check for updates
(by hand or in the background, with notifications), and update with a click: git clones are pulled (or moved to the
newest release), AppImages and programs from release archives are downloaded, checked and swapped in, and packages
(RPMs, Debian and Arch packages) are installed with the package manager. Stage 6 (GitHub sign-in, packaging, GNOME) and stage 7 (release) aren't built yet.

**Developed and tested mainly on Fedora KDE.** Git clones, AppImages and programs from release archives should work
on other distros, and packages install with dnf, zypper, apt or pacman (each tried in a container), but other
distros (and GNOME) still need testing on real computers.
If you try it elsewhere, please say how it went in a GitHub issue, whether it worked or not.

## Installing it as a package

```sh
devtools/build_rpm.sh                                # builds dist/colliecourier-<version>.noarch.rpm from the last commit
sudo dnf install dist/colliecourier-*.noarch.rpm     # then it's in the menu, and `colliecourier` runs it
devtools/build_arch.sh                               # Arch's package (packaging/arch/PKGBUILD), built and tried in a container
```

Installed, it uses the system's menu entry and icon. Running it from this folder still works alongside.

## Running it

```sh
~/claudework/colliecourier/run.sh
```

Needs only what Fedora KDE already has: Python 3, PySide6 (`python3-pyside6`) and Kirigami. Your tracked repos are
saved in `~/.config/colliecourier/repos.toml`.

On other distros, install these first (names checked 2026-10-11 on Ubuntu 26.04, Arch and openSUSE Tumbleweed;
Python 3.13 or newer):

| Needed for | Fedora | Ubuntu / Debian | Arch | openSUSE |
| --- | --- | --- | --- | --- |
| The window | `python3-pyside6` | `python3-pyside6.qtquick python3-pyside6.qtwidgets python3-pyside6.qtdbus python3-pyside6.qtnetwork python3-pyside6.qtsvg` | `pyside6` | `python313-pyside6` |
| KDE's window parts | `kf6-kirigami` | `qml6-module-org-kde-kirigami qml6-module-qtquick-controls qml6-module-qtquick-dialogs qml6-module-qtquick-layouts` | `kirigami` | `kf6-kirigami-imports` |
| KDE's look (optional) | `kf6-qqc2-desktop-style` | `qml6-module-org-kde-desktop` | `qqc2-desktop-style` | `kf6-qqc2-desktop-style` |
| Icons | `breeze-icon-theme` | `kf6-breeze-icon-theme` | `breeze-icons` | `kf6-breeze-icons` |
| Notifications | `libnotify` | `libnotify-bin` | `libnotify` | `libnotify-tools` |
| Clones | `git-core` | `git` | `git` | `git-core` |
| Updates that ask for your password | `polkit` | `pkexec` | `polkit` | `polkit` |
| Keeping the GitHub sign-in | `libsecret` | `libsecret-tools` | `libsecret` | `secret-tool` |

Other ways to run it:

```sh
~/claudework/colliecourier/run.sh --check   # check every repo for updates now, without the window
```

**What it adds outside this folder** (all removable):

- `~/.local/share/applications/colliecourier.desktop`: the menu entry (written when the app starts).
- `~/.config/systemd/user/colliecourier-check.{timer,service}`: background checks, only while automatic checks are on
  (Settings). Turning them off removes the timer. To remove it by hand:
  `systemctl --user disable --now colliecourier-check.timer`.
- `~/.local/state/colliecourier/checks.json`: the last check's results. `~/.cache/colliecourier/icons/`: repo icons.
  `~/.cache/colliecourier/github/`: GitHub release lists, to ask "has it changed?" instead of downloading them again.
- Only if you sign in to GitHub with a code: the login, in your desktop's password store (KDE Wallet on Plasma,
  GNOME Keyring on GNOME, …), as
  "colliecourier: GitHub sign-in".
- Only when you install or update something: AppImages in `~/Applications` (or beside the one you had), with a menu
  entry `~/.local/share/applications/colliecourier-<repo>.desktop`; programs unpacked in
  `~/.local/share/colliecourier/programs/`, with a link in `~/.local/bin`; packages through the package manager (downloaded first to
  `~/.cache/colliecourier/downloads/`, then deleted); projects you install by cloning, in `~/src`.

To start over as if newly installed (the welcome screen shows again), run it with `--reset`. Your settings file is
renamed to a dated backup next to it, not deleted:

```sh
~/claudework/colliecourier/run.sh --reset
```

## Tests

```sh
cd ~/claudework/colliecourier && python3 -m unittest discover -s tests -t .
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
python3 -I devtools/check_look.py [dark]     # a tour of every screen and state, to look over (made-up projects)
python3 -I devtools/check_appimage.py        # installs then updates LocalSend's AppImage, in temporary folders
python3 -I devtools/check_program.py         # installs then updates ripgrep from its .tar.gz, in temporary folders
python3 -I devtools/check_rpm.py             # bottom's real .rpm up to dnf, which is a stand-in: nothing is installed
devtools/check_distros.sh [fedora opensuse ubuntu arch]  # packages installed for real, in each distro's container
python3 -I devtools/check_flatpak.py         # a Flatpak bundle installed and updated for real, in a temporary folder
```

## Code layout

| File                       | What it does                                                                   |
| -------------------------- | ------------------------------------------------------------------------------ |
| `colliecourier/config.py`    | The settings file: global settings and tracked repos                           |
| `colliecourier/sources.py`   | Talking to GitHub and GitLab: addresses, releases, branches                    |
| `colliecourier/assets.py`    | Build files: which kind, whether it suits this PC, remembering your pick       |
| `colliecourier/scan.py`      | Scanning: finding clones, RPMs and AppImages; matching them to tracked repos     |
| `colliecourier/icons.py`     | Repo icons: from this computer, the project's site, or the default (D13)          |
| `colliecourier/checker.py`   | Checking every repo for updates; results kept apart from settings                 |
| `colliecourier/integration.py` | Menu entry, notifications, taskbar badge, background timer, one copy at a time |
| `colliecourier/updater.py`   | Updating: pulling and cloning, downloads checked and put in place, packages     |
| `colliecourier/packages.py`  | Packages per distro: which tool installs each kind, reading names and versions  |
| `colliecourier/flatpaks.py`  | Flatpak bundles: which app a bundle holds, installing it for you, finding them  |
| `colliecourier/backend.py`   | Connects the window to the above; runs network work in the background          |
| `colliecourier/updating.py`  | The backend's Update and Install buttons and install scripts (part of it)      |
| `colliecourier/github_login.py` | Signing in to GitHub: the code sign-in, and keeping it in the password store |
| `colliecourier/account.py`   | The backend's sign-in buttons, for Settings and the welcome screen (part of it) |
| `colliecourier/qml/`         | The window: list page, repo page, Add dialog                                   |

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
