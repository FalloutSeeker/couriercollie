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

**Progress:** stages 1–4 done (2026-10-10). The menu entry was pulled forward from stage 6 (notifications and the badge need it).

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

1. **Git clones**: pull the new commits. Separate "Run install script…" button that shows the script before running it.
2. **AppImages**: download, verify the checksum if one is published, swap in, keep the old one, add a menu entry.
3. **Programs**: download, unpack, swap the program file in `~/.local/bin`, keep the old one.
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
- Added (2026-10-11) at your request.

## Later, not planned yet

- Codeberg/Gitea sites.
- Tracking private repos.
- The "custom dnf" local package repo, so `dnf upgrade` and Discover see these updates.
