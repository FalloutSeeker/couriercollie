# Log

Newest first.

## 2026-10-10

- Cleaned up terminal warnings:
  - "Could not register app ID: App info not found for 'repoproject'": the app told KDE its menu-entry name, but no
    menu entry exists yet (stage 6). The name is now only sent once the entry is installed.
  - "StackView has detected conflicting anchors": from Kirigami's layers, used to show Settings. Settings now opens in
    its own window, as in other KDE apps.
  - "Created graphical object was not placed in the graphics scene": from Kirigami creating pages. The app now
    creates pages itself and deletes them when closed. Closed repo pages weren't being deleted before.
  - Avoided two Kirigami errors this exposed: a TypeError if the Settings page is deleted along with its window, and
    one if a page is shown in a window twice. Each opening of Settings gets a fresh page owned by the main window.
- Check intervals narrowed to daily / every 7 days / every 14 days / monthly (4 weeks); daily is the default. Older
  saved values move to the next choice up (6 hours becomes daily).
- The welcome screen didn't get a fair chance: the app started at 19:55 and the settings file was written with the
  screen's starting answers in the same minute, so Done was likely hit by accident. Added `--reset` (renames the
  settings file to a dated backup) and reset the real settings; the old file is
  `~/.config/repoproject/repos.toml.backup-20261010-195941`.
- My radio-button fix had stopped KDE's style from highlighting the active list filter. The filter buttons are
  checkable again and re-tied to the saved filter after each click.
- Check intervals: added 3 days, 2 weeks and "month" (4 weeks), as a fixed list rather than a number + unit. The
  interval is counted from the last check; a check missed while the PC was off will run soon after the next login
  (to build in stage 4).
- Fixed radio buttons. On the welcome screen "Yes" and "No" were in different rows, so both stayed ticked and Done
  saved "Yes" even after picking "No". The list's filter buttons could un-highlight when clicked twice. Buttons that
  show a saved choice (filters, build files, branches) now only display it; a click asks the app, and the app's
  answer decides what's marked. Checked by simulating mouse clicks on the real window, which failed on the old
  screens and passes on the new ones.
- Built the first-launch screen and the Settings page early (they were planned for stage 4, but were expected now).
  The first start asks the three questions; answers are saved and the screen doesn't come back. Settings can change
  them anytime. The features behind them (scanning, background checks, cleanup) come in stages 3, 4 and 6.
- Built stages 1 and 2. Tested with 45 unit tests, and by driving the real window off-screen against live GitHub
  (LocalSend) and gitgud.io (AeroThemePlasma).
  - AeroThemePlasma moved from `wackyideas/aerothemeplasma` to `aeroshell/atp/aerothemeplasma`. The app follows the
    redirect and saves the new address, and it publishes no releases, so it's followed by branch (`Plasma/6.7`).
  - Found and fixed: the saved file pattern's `*` matched anything, so picking LocalSend's app tarball would also
    have matched its separate command-line tool. `*` now only matches version numbers.
  - Releases list only the files that suit this PC; the rest are behind "Show N files for other systems".
  - If exactly one file in the newest release suits this PC, it's picked automatically when the repo is added.
  - No extra packages needed: Python's own unittest, and a small TOML writer (tomli-w isn't installed by default).
  - Known: Qt prints "Created graphical object was not placed in the graphics scene" when a repo page opens. It's
    from how Kirigami creates pages; the page displays correctly.
- Added D12: scanning is off by default, offered on first launch and in Settings, results start unticked with Select
  all. Made D11 (delete old versions) off by default too, also offered on first launch and in Settings.
- Decided D7. All decisions are now settled. Wrote PLAN.md: six stages, and nothing changes the system before stage 5.
- Designed the optional GitHub sign-in (DESIGN §8): it explains the 60 vs 5,000 an hour limit, gives a live "do you
  need this?" estimate, shows a friendly bar when the limit is hit, and asks for read-only, public-data access.
- Simplified notifications: dropped update modes (Notify + click / Notify only) and per-repo overrides. Updates are
  always a click on the ⬆ icon. Dropped per-repo check intervals (one global schedule, lighter on the system).
  First launch now asks one question: automatic checks on (with interval) or off. Toasts on by default when checks
  are on, can be turned off, leaving the taskbar badge and in-app icons.
- Decided D1, D6, D8, D10 as recommended. Wrote up D7 (how the app talks to GitHub/GitLab within their limits).
- Revised D4: auto-update dropped, so the app never prompts for a password unasked. Two modes remain (Notify + click,
  Notify only), with an in-app notice always and an optional toast.
- Decided D5: global check interval asked on first launch, including "Never (manual only)".
- Added and decided D11: delete old versions after a set time, skipping anything that needs admin rights.
- Added a first-launch setup screen to DESIGN (update mode, interval, toasts, then offer a scan).
- Decided: D2 (GitHub + GitLab, with a filter in the list), D3 (build files and branches; no repo groups),
  D4 (three update modes: a global setting asked on first launch, plus per-repo overrides), D9 (local git repo).
- Project folder created. Wrote README, DESIGN and DECISIONS.
- Scanned the machine to ground the design: 11 git clones (10 AeroThemePlasma repos on gitgud.io, plus
  `ultrakanban` on GitHub). No AppImages, and no RPMs installed from GitHub downloads (the only file-installed RPMs
  are NVIDIA and RPM Fusion, which already update through dnf). Python 3.14, PySide6 and Kirigami are installed.
- Goal agreed: "Obtainium for Fedora KDE": scan for or hand-add repos, list releases and build files, check on an
  interval, update from a GUI.
