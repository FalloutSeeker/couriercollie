# Log

Newest first.

## 2026-10-11

- Categories (D14): New Category…, drag repos into and around categories and drag categories by their handles,
  delete a category (its repos move to Uncategorized). The list order is now yours, kept in the settings file; an
  older file keeps its order by name. New click check: `devtools/check_categories.py`.
  - Found while testing: a New Category toolbar button pushed Check Now into the overflow menu, so it sits at the
    right of the filters instead.
- Renaming categories: ⋮ menu on each heading (also on right-click) with Rename and Delete Category…; Rename edits the
  name in place, as does double-clicking it. Checked under Breeze Light and Breeze Dark as well as Aero: nothing
  in the window uses fixed colors, and every icon it names exists in Breeze, which other icon themes fall back to.
- The update icon follows your version straight away (finishing the last request of 2026-10-10).

## 2026-10-10

- Built stage 4, checking for updates (DESIGN.md §9): Check Now, per-repo results with the update icon, a status line,
  the rate-limit bar; background checks through a systemd user timer that only checks when the interval has passed;
  notifications (only new updates, only when the window isn't in front, click opens the app); the taskbar badge while
  the app is open; one copy at a time. The menu entry came forward from stage 6.
  - Results live in their own file, so the background checker and the window can't overwrite each other.
  - Found while testing on this machine: systemd stopped the notification's click helper when the check finished, so
    clicking wouldn't have opened the app. Fixed with `KillMode=process` in the service.
  - Found while testing: my window-check harness wrote check results into the real `~/.local/state`; removed them
    and the harness now uses a temporary file.
  - Repos skipped because of the hourly limit keep their last result (marked "not rechecked") instead of losing it.
- Repo icons (D13): looked up once per repo, in order: on this computer (scanned RPM's menu entry, scanned AppImage's
  own icon read with 7z without running it, icon file in a scanned clone, matching installed app), then the
  project's picture on its site (GitLab project/group, GitHub organizations only), then the default. Scanned repos
  get a corner mark. Here: Aero and SMOD got the AeroShell logo; obt, Test and aerial (owned by people) keep the
  defaults. A site that can't be reached is retried next load; everything else, even "none found", is saved.
  `devtools/check_icons.py` checks it on a copy of your settings.
- Review and test pass across stages 1–3:
  - Bug: clicking two branches quickly could show "Couldn't compare…" when the first answer arrived late. Each
    comparison is now numbered; late answers to older ones are ignored.
  - Settings file: values of the wrong kind (hand-edited or damaged) now fall back to defaults instead of loading
    as-is; a file whose sections are the wrong shape is treated as unreadable (never overwritten). If settings can't
    be saved (e.g. read-only folder), the main window shows a warning instead of the save silently failing; it clears
    once a save works.
  - Sites: GitHub's secondary rate limit (403 with retry-after) is reported as "too many requests"; answers that
    aren't text are reported as not from a GitHub/GitLab site.
  - Faster: checking scan finds with their sites runs 4 at a time (10 finds here: 3.7 s → 1.8 s). Measured and left
    alone: finding things on disk (0.2 s) and preparing a repo page (under 1 ms for 245 files).
  - Cleanup: one helper for "the followed branch's newest commit" instead of four copies; values sent to the
    window that nothing used were removed.
  - Tests: 121 → 132, including offline behaviour (adding, a repo page then Try Again, scanning), HTTP errors, quick
    branch clicks, and bad settings files. A scan test was quietly reaching GitHub; all tests now pass with the
    network switched off (`unshare -rn`), where the two permission tests skip since they'd run as root.
- Repos added by hand now start as "Not installed" instead of assuming the newest version (the user added "aerial"
  to watch it and it claimed v1.2.1; the "Test" repo's "fake commit" had the same cause). "Set as My Version" or
  "Mark as Up to Date" records a version once you have it. Scanned repos still read theirs from disk.
- Files named like Windows installers or screensavers ("Aerial.Setup.1.2.1.zip", "….SCR.zip") no longer count as
  fitting this computer; Aerial ("Apple TV screen saver for Windows") is now versions-only.
- Fixed a leftover reference to the old "Which file you use" heading (now "Your Build File").
- Bug: on the hand-added "Test" repo (gitgud.io/atmk/app-store), choosing the "flatpak" branch said the user's commit
  wasn't on gitgud.io, as if it were fake. "flatpak" was started from scratch and shares no history with "master",
  so gitgud.io answers "Merge Base Not Found". That's now read as "split apart": "Not comparable with flatpak: your
  version (commit 405c894) isn't part of it." GitHub gives a 404 for the same case; the app then checks your
  commit exists before saying so. The "couldn't compare" message no longer blames the commit.
- Bug: every SMOD branch said "Newer commits", because any difference from a branch's newest commit counted as an
  update. Now the app asks the site how your commit relates to the branch's newest: behind (an update, with the
  new commits listed), ahead ("Your version is newer than master"), split apart ("Not comparable with
  hidpi-functionality: your clone is on Plasma/6.7."), or the same. GitHub's compare gives this in one request;
  GitLab needs a second (the common ancestor) only when the branch has commits you don't. If your commit isn't on
  the site, the page says it can't be compared. The branch checked out in a scanned clone is tagged "On this
  computer". Changing your version by hand now re-compares too. Tests no longer make network requests by accident.
- Bug: switching branch and back showed "Up to date" for SMOD while the clone was behind. Switching branch reset
  "your version" to the new branch's newest commit (a rule from earlier today). Now switching branch never changes
  your version: it only changes what it's compared with. Scanned repos re-read their version from disk, and the
  list of new commits is refreshed for the chosen branch.
- Found while checking that: a crash (in Qt's layout code) when the new-commits list changed inside the repo page's
  form after a branch click. The list is now one label instead of a row per commit. Page rebuilds after a change
  are also deferred until the click has been handled. Checked with three runs of every window check, plus
  repeatedly removing and restoring all scan folders in Settings (the other list inside a form).
- SMOD showed "Newer commits" while the user believed it was current. It was right: the clone last fetched at 16:13,
  and a commit was pushed at 21:52; `git status` can't show that without a fetch. But "Mark as Up to Date" had been
  clicked, so the app's saved version no longer matched the clone. Fixed by:
  - Scanned repos' versions are read from disk each time their page opens (clone commit, AppImage version, RPM
    version), with a note saying so, and a warning if the folder is gone.
  - "Mark as Up to Date" / "Mark as Not Installed" hidden for scanned repos.
  - What's new: the commits between your version and the branch's newest, by title (one request).
  - `devtools/check_scanned_repo.py` checks this against a real scanned clone.
- Scan locations: was the home folder only. Now the home folder, `/opt`, `/usr/local` and `/srv` by default, with git
  clones and AppImages looked for in all their subfolders (plus `~/.local/bin`). Settings has a "Folders to scan" list
  with defaults marked "Default", Add Folder…, remove buttons and Restore Defaults; the welcome screen and scan dialog
  name the folders. Finds in folders owned by the system get a note that updating will ask for the password. A scan
  of all four folders here still takes about 0.2 s.
- KDE HIG pass (app design, layout and navigation, displaying content, status changes, text and labels, icons),
  light compliance tweaks only:
  - Title case for buttons, actions, dialog titles and headings; sentence case kept for checkbox, radio and form
    labels. Ellipsis on actions that need more input ("Add…", "Scan…", "Stop Tracking…"). Dialog titles echo their
    button ("Add Repo"); "This is my version" became the imperative "Set as My Version". Curly apostrophes.
  - Every button has an icon; Close uses window-close instead of a red X (red is for destructive actions).
  - Status uses an update icon rather than green text alone. Confirmation buttons say what they do ("Stop Tracking"
    / "Cancel"), not OK.
  - Shortcuts: Ctrl+N add, Ctrl+R refresh, the standard Settings shortcut. No bare function keys.
  - Placeholder text only as an example (the Add dialog's Name hint moved under the fields); long explanations cut
    to two sentences and kept to a readable line width.
  - Stage 4 note: toasts only when the window isn't in front (D5).
  - Rebuilt the click checks as `devtools/check_pages.py`.
- Built stage 3, scanning. Finds git clones in the home folder (up to 6 folders deep, skipping hidden folders and
  dependency folders), RPMs installed from a downloaded file with a GitHub/GitLab homepage, and AppImages that carry
  their update source. Each project is listed once even if found in several places. Finds not already on the list
  are checked with their site (moved projects, private repos, unsupported sites); tracked ones need no request.
  Tracked repos are updated automatically; new finds are listed unticked with Select all / Select none.
  - On this computer: 10 projects in 0.2 s on disk, about 6 s checking with the sites.
  - Mirrors: the tracked "Aero" is a GitHub copy of the gitgud.io project the clone came from. Addresses can't tell,
    so a find with the same project name and description as a tracked repo is shown as "Looks like Aero…"; ticking
    it links the two instead of adding a second entry.
  - Versions found on disk ("1.18.2") are matched to release tags ("v1.18.2").
  - Fixed: the scan dialog showed nothing (all its content was hidden when it opened, so Kirigami sized it empty).
  - Fixed: Kirigami logged "Could not create delegate for ToolBarLayout" on every start with scanning off (the
    default), because the Scan button was listed but hidden. It's now left out of the toolbar instead.
  - Added `devtools/` (off-screen window checks, reusable) and `devtools/check_scan.py`.
- "Your version" is no longer a dropdown (it repeated the "your version" tag in the releases list). It's shown as
  text; you set it from the releases list ("This is my version" in an opened release) or with "Mark as up to date"
  and "Mark as not installed".
- Only files that run on this computer can be chosen. Projects with nothing for this computer (Obtainium: Android
  only) are tracked by version only: no picker, a "Tracking versions only" explanation, and "Versions only" in the
  list. A saved pick of a file for another system is dropped the next time the repo's releases load.
- Manual vs scanned entries. Each repo records how it got on the list, where it was found, and other addresses it's
  known by. `scan.merge` (for stage 3) updates existing entries instead of adding duplicates, including when the
  clone on disk uses an old address: the Aero clone here is `wackyideas/aerothemeplasma`, but the app saves the new
  `aeroshell/atp/aerothemeplasma`. Repo pages show "Tracking: Added by hand" or "Found on this computer: <folder>".
  With scanning on, the welcome screen and Settings say repos can still be added by hand.
- With scanning off, the welcome screen and Settings now say tracking is manual: you add repos yourself and set which
  version you have, or mark it as up to date. With scanning on, they say versions are read from the computer.
- Added a "Mark as up to date" button on the repo page, shown when your version isn't the newest.
- The welcome screen now opens after the window's first frame is drawn. Opening it earlier logged a Kirigami "binding
  loop" because the window had no size yet to centre it in.
- Added "Your version" to each repo page: a release, or a commit when following a branch, or "Not installed". It starts
  at the newest version when a repo is added (or first loaded, for repos added earlier), and resets when you switch
  between releases and a branch, or switch branch. A status line says "Up to date" or "Newer version available: …".
  This is what update checks (stage 4) will compare against.
- Cleaned up the releases list: the green ✓ and the "has your file" tag on every release were confusing. Release
  headers now only show "your version", "newest" and "pre-release". Opening a release shows one line ("Your file: …"
  or "Your file isn't in this release"), then "Show all N files" and the release notes.
- Repo page redesign, after testing with Obtainium: every release had its own radio buttons, and because the same
  file appears in each release, a button showed as picked in every release at once. Choosing a file now happens in
  one place, "Your build file", listing the newest release's files. The releases list is read-only, with a ✓ on
  your file. Warnings show when the newest release lacks your file, or has nothing for this computer.
- Classification fix: `app-x86_64-release.apk.idsig` (an Android signature file) counted as fitting this PC because
  of "x86_64". Files belonging to another system's package (`.apk.`, `.exe.`, …) and `.idsig` files are now excluded.
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
