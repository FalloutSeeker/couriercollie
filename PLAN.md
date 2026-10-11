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

**Progress:** stages 1–4 done (2026-10-10). Stage 5: git clones, AppImages and programs done (2026-10-11). The menu entry was pulled forward from stage 6 (notifications and the badge need it).

## Stage 1: Skeleton (done)

- Project layout, a Kirigami window that opens from a terminal command.
- Reading and writing the settings file (`~/.config/repoproject/repos.toml`).
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

## Stage 5: Updating

Built kind by kind, simplest first:

1. **Git clones** (done): pull the new commits. Separate "Run install script…" button that shows the script before
   running it.
2. **AppImages** (done): download, verify the checksum if one is published, swap in, keep the old one, add a menu
   entry. Install, for one you don't have yet, into `~/Applications`.
3. **Programs** (done): download, unpack into its own folder, link the program from `~/.local/bin`, keep the old
   version.
4. **RPMs**: download, verify, install through dnf, which asks for your password.

Plus **Undo last update** for AppImages and programs while the old version is still kept.

## Stage 6: Finishing

- **Delete old versions after…** setting and the cleanup that runs with each check.
- **Sign in to GitHub** (DESIGN.md §8).
- App icon, KDE menu entry, and packaging the app itself as an RPM so it installs like anything else.
- **GNOME support** (checked 2026-10-11 by running the window with GNOME settings; the list, dragging and menus work):
  - Use KDE's control style only if it's installed (`kf6-qqc2-desktop-style`), else a standard Qt style. Without it
    the window doesn't open at all today.
  - Fall back to Breeze for icons the current theme lacks (Adwaita has no `handle-sort`, `overflow-menu`,
    `update-low`, `emblem-mounted`, `application-x-rpm`, …), so none show blank.
  - The RPM requires `kf6-kirigami`, `kf6-qqc2-desktop-style`, `breeze-icon-theme` and `libnotify` (notify-send).
  - Follow GNOME's dark mode: KDE's style takes colors from KDE settings, so on GNOME it likely stays light. Needs a
    real GNOME session to confirm.
  - Known and fine: no taskbar badge on GNOME's dock (Dash to Dock shows it); it looks like a KDE app.

## Stage 7: Release (once the app is complete)

- **Before it:** a real name (D10), and the project published as a public repo with releases that carry the RPM
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
- **Restore to Defaults** in the Settings window: every setting back to how it was on a fresh start (automatic
  checks, notifications, scanning and its folders, deleting old versions). Tracked repos and categories are kept.
  Asks first.
- **User documentation** (a short guide in the README, or Help in the app). Include how the scan decides an RPM is
  one dnf won't update, in plain words:
  1. *Where it was installed from.* dnf records this for every package. Packages from Fedora, RPM Fusion or a COPR
     show that repository's name; one installed from a downloaded `.rpm` shows as `@commandline`. Only the second
     kind is considered, and only if its homepage is a GitHub or GitLab project.
  2. *Whether any repository you have enabled offers it.* Some RPMs add their own repository when you install them,
     so dnf does update them later (e.g. `rpmfusion-free-release`: installed from a file, but RPM Fusion keeps it
     updated). The first check alone would let a GitHub-hosted package like that through.

  If dnf can't answer, no RPMs are listed. (Details in DESIGN.md §1.)
- Added (2026-10-11) at your request.

## Later, not planned yet

- **Any git host, by git alone** (sourcehut, Bitbucket, kernel.org, self-hosted): new commits, versions from tags and
  Update for clones, without the site's API (no description, icon, release notes or commit list).

- Codeberg/Gitea sites.
- Tracking private repos.
- The "custom dnf" local package repo, so `dnf upgrade` and Discover see these updates.
