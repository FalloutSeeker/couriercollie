# Build plan

The app gets built in stages. Each stage ends with something you can open and try on this machine (with your
AeroThemePlasma and ultrakanban repos), and nothing in a stage can change your system until stage 5.

| Stage | What you can do at the end                                            | Changes your system? |
| ----- | --------------------------------------------------------------------- | -------------------- |
| 1     | Open the app and see an empty window                                  | No                   |
| 2     | Add a repo by URL; browse its releases, build files and branches      | No                   |
| 3     | Scan the machine and track what it finds                              | No                   |
| 4     | Check for updates by hand or on a schedule; get toasts and the badge  | No                   |
| 5     | Click ⬆ to update                                                     | Yes, on your click   |
| 6     | Old-version cleanup, GitHub sign-in, app icon, installable package    | No                   |
| 7     | The app tracks its own updates, added on first launch                 | No                   |

**Progress:** stages 1–4 done (2026-10-10), stage 5 done (2026-10-11). The menu entry was pulled forward from stage 6 (notifications and the badge need it).

## Stage 1: Skeleton (done)

- Project layout, a Kirigami window that opens from a terminal command.
- Reading and writing the settings file (`~/.config/colliecourier/repos.toml`).
- Automated tests set up, so later stages can be checked without clicking through everything.

## Stage 2: Tracking repos by hand (done)

- **Add** dialog: name + URL. Works for GitHub and GitLab (including gitgud.io).
- Main list with the All / GitHub / GitLab filter.
- Repo page: releases (newest first, pre-releases hidden by default), build files under each release with "the one
  you use" picker, and a branch picker for repos without releases.
- Remove a repo from tracking.

## Stage 3: Scan (done)

- Finds git clones in your home folder, RPMs installed from a downloaded file whose homepage is on GitHub/GitLab, and
  AppImages in the usual folders.
- Scan results dialog with checkboxes; "Track selected" adds them to the list.
- Uses `scan.merge` (already built and tested): repos already on the list are updated in place and marked as
  scanned, never added twice. In the results, those show as "already tracked" rather than as new.
- For git clones, records the commit you're on as the installed version.

## Stage 4: Checking for updates (done)

- **Check now** button, using the light-touch methods from D7 (`git ls-remote` for clones, one request per release
  repo, "has anything changed?" requests, backing off when told to).
- ⬆ icons and the update count in the main window.
- **First-launch screen**: automatic checks on (with interval) or off.
- **Background checker** on a systemd user timer, toasts (clicking one opens the main window), and the taskbar badge.
- "GitHub's hourly limit was reached" bar.
- Settings page: automatic checks, interval, toasts on/off.

## Stage 5: Updating (done)

Built kind by kind, simplest first:

1. **Git clones** (done): pull the new commits. Separate "Run install script…" button that shows the script before
   running it.
2. **AppImages** (done): download, verify the checksum if one is published, swap in, keep the old one, add a menu
   entry. Install, for one you don't have yet, into `~/Applications`.
3. **Programs** (done): download, unpack into its own folder, link the program from `~/.local/bin`, keep the old
   version.
4. **RPMs** (done): download, verify, install through dnf, which asks for your password.

Each update removes the version it replaced once the new one is in place (no Undo; D11).

## Stage 6: Finishing

- Done (2026-10-11): **Sign in to GitHub** (DESIGN.md §8), optional, on the welcome screen and in Settings: with a
  code (device flow, kept in the desktop's password store; not the GitHub CLI's login, D7). Release lists are asked for with their ETag; an
  unchanged one (304) costs nothing signed in (tried), and no download signed out.
- Done (2026-10-11): an app icon (`data/colliecourier.svg`), the menu entry, and the app's own RPM
  (`packaging/colliecourier.spec`, built by `devtools/build_rpm.sh`; tested unpacked, not yet installed with dnf).
- **GNOME support** (checked 2026-10-11 by running the window with GNOME settings; the list, dragging and menus work):
  - Done: KDE's control style only if it's installed (`kf6-qqc2-desktop-style`), else Qt's Fusion (the window
    works in it, tested).
  - Done: Breeze fills in icons the current theme lacks (Adwaita has no `handle-sort`, `overflow-menu`,
    `update-low`, `emblem-mounted`, `application-x-rpm`, …), so none show blank; with no theme at all, Breeze is it
    (breeze-dark in dark mode).
  - Done: the RPM requires `kf6-kirigami`, `breeze-icon-theme`, `libnotify` and the rest, and recommends
    `kf6-qqc2-desktop-style` (the window works without it). Installed with dnf on a fresh Fedora 44 (a container):
    dependencies resolve, and the app starts.
  - Follow GNOME's dark mode: KDE's style takes colors from KDE settings, so on GNOME it likely stays light. Needs a
    real GNOME session to confirm.
  - Known and fine: no taskbar badge on GNOME's dock (Dash to Dock shows it); it looks like a KDE app.
- **Other distros** (asked for 2026-10-11). Fedora KDE stays the main target; these make the app safe and useful
  elsewhere:
  - Done: which package files suit this computer depends on what it has. `.rpm` only where dnf is; `.deb` and Arch
    packages (`.pkg.tar.zst`) are never offered. Each says why: "not supported on your distro", or "not supported
    yet" where apt, pacman or zypper is. Flatpak files say to use your software center. Arch packages are no longer
    mistaken for a program archive (or for macOS's `.pkg`).
  - Done: installing them: `.deb` with apt, Arch packages with pacman, RPMs with zypper on openSUSE (each through
    pkexec, like dnf), and the scan finding packages installed from downloaded files (zypper, apt; not pacman, which
    can't tell them from AUR builds). Tested for real in containers (`devtools/check_distros.sh`).
  - Single-file `.flatpak` bundles in releases: installed from a file they usually never update, like an RPM from a
    downloaded file, so the app could install and update them. (Installed Flatpaks stay Flatpak's to update.)
  - Done: an Arch package (`packaging/arch/PKGBUILD`, for the AUR at release): built with makepkg, installed with
    pacman and started in an Arch container (`devtools/build_arch.sh`). Maybe a `.deb` later.
  - Not a Flatpak of the app itself: its sandbox blocks scanning folders, running git, dnf and pkexec,
    `~/.local/bin` and the systemd timer.
  - Done: the libraries' package names per distro, in the README (looked up in Ubuntu 26.04, Arch and openSUSE
    Tumbleweed containers). The tests pass on openSUSE's Python 3.13.

## Stage 7: Release (once the app is complete)

- **Before it:** the project published as a public repo with releases that carry the RPM
  from stage 6.
- **The app's own repo is added on first launch**, in Uncategorized, so you're told about new versions of the app
  like anything else you track. Your version is the version that's running, so it starts as Up to date.
- Added **once**: if you stop tracking it, it doesn't come back on a later start. If it's already tracked (added by
  hand or found by a scan), it isn't added twice.
- **Send Feedback…** at the very bottom of the Settings window (not in the toolbar). It opens a pre-filled "New
  issue" page on GitHub in the browser; nothing is posted by the app, so there's no server and no token.
  - First a small dialog shows what's included, editable: app version, Fedora version, desktop (KDE/GNOME), Qt and
    Kirigami versions. Your tracked-repo list only if you tick it (off by default). Then **Open in Browser**.
  - The repo gets one issue template (`.github/ISSUE_TEMPLATE/feedback.yml`) that labels these `feedback`.
  - Sending needs a GitHub account, in the browser. The app's own GitHub sign-in (stage 6) stays read-only.
- **Start at login** (Settings, and offered on the welcome screen; off by default): opens the app when you log in, for
  those who want its window there. Not needed for automatic checks, which run without the app open (a systemd timer
  starts a short check and it exits), so the app never runs constantly unless you choose this. Done with an autostart
  entry (`~/.config/autostart/`), removed when turned off. Starts in the tray if the tray icon (below) is on;
  otherwise it opens the window. Asked for 2026-10-11.
- **Tray icon** (asked for 2026-10-11): shows while the app is running, with the number of updates, and a menu
  (Open, Check Now, Quit). Closing the window still quits unless "Keep running in the tray when closed" is on (off by
  default), so the app only stays running if you choose it. Not needed for automatic checks either way: those run
  from the systemd timer whether the app is open or not. Goes with Start at login (it can start in the tray). On
  GNOME a tray needs the AppIndicator extension; without it, no tray icon and closing quits as before.
- **Restore to Defaults** in the Settings window: every setting back to how it was on a fresh start (automatic
  checks, notifications, scanning and its folders). Tracked repos and categories are kept.
  Asks first.
- **User documentation** (a short guide in the README, or Help in the app). Say up front that it was developed and
  tested mainly on Fedora KDE; other distros (and GNOME) still need thorough testing, and reports from them are
  welcome, through Send Feedback or a GitHub issue. Open with what the app is for:
  **everything in one place, in a simple window**, instead of several separate tools. Each of these covers one piece
  (check each is still accurate when writing):
  - *Topgrade* runs every updater you have (dnf, Flatpak, …) from a terminal, but doesn't know about software you
    got straight from GitHub or GitLab.
  - *Gear Lever* and *AppImageLauncher* manage AppImages, and only AppImages.
  - *eget* and similar download a release's program from GitHub, in a terminal, one at a time.
  - *nvchecker* tells you a new version is out, from a terminal, but doesn't update anything.
  - *Discover* updates packages and Flatpaks, not what you downloaded or cloned yourself.
  - *Obtainium* is the same idea as this app, for Android.
  colliecourier brings these together for software from GitHub and GitLab: clones, AppImages, programs from release
  archives and RPMs, found by a scan or added by hand, checked on a schedule, and updated with a click. The pitch is
  one app to install and learn, not a handful of tools and their commands.
  Explain signing in to GitHub with this line: "colliecourier uses its registered app identity to ask GitHub for a
  read-only, public-data token on behalf of whoever signs in." (The token belongs to the person signing in, counts
  against their own 5,000-an-hour allowance, can't read anything private or change anything, and is revoked from
  GitHub's Settings → Applications. The app registration isn't tied to any repository.)
  Also include how the scan decides an RPM is one dnf won't update, in plain words:
  1. *Where it was installed from.* dnf records this for every package. Packages from Fedora, RPM Fusion or a COPR
     show that repository's name; one installed from a downloaded `.rpm` shows as `@commandline`. Only the second
     kind is considered, and only if its homepage is a GitHub or GitLab project.
  2. *Whether any repository you have enabled offers it.* Some RPMs add their own repository when you install them,
     so dnf does update them later (e.g. `rpmfusion-free-release`: installed from a file, but RPM Fusion keeps it
     updated). The first check alone would let a GitHub-hosted package like that through.

  If dnf can't answer, no RPMs are listed. (Details in DESIGN.md §1.)
  Also why these folders are scanned by default (D12), in plain words: your home folder is where you clone and
  download things; `/opt` and `/usr/local` are the standard places for software installed by hand outside the package
  manager; `/srv` holds things a computer serves (often cloned projects). The rest of the system (`/usr` and so on)
  belongs to the package manager, so it's slow to look through and has nothing to find. Folders can be added or
  removed in Settings.
- Added (2026-10-11) at your request.

## Later, not planned yet

- **Any git host, by git alone** (sourcehut, Bitbucket, kernel.org, self-hosted): new commits, versions from tags and
  Update for clones, without the site's API (no description, icon, release notes or commit list).

- Codeberg/Gitea sites.
- Tracking private repos.
- The "custom dnf" local package repo, so `dnf upgrade` and Discover see these updates.
