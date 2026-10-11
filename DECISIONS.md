# Decisions

Each one has a recommendation. **Status** is `open` until you pick, then `decided` with the date. LOG.md records how
decisions changed along the way.

---

## D1. What to build it with

Python + PySide6 (Qt) + Kirigami (KDE's interface toolkit).

- Looks and behaves like other KDE apps (Discover, System Settings).
- Python is the easiest of the options to read and change later.
- Both `python3-pyside6` and `kf6-kirigami` are already installed here.

**Status:** decided 2026-10-10.

## D2. Which sites to support

GitHub and GitLab (which includes gitgud.io, where the AeroThemePlasma repos are). Codeberg/Gitea maybe later.

**Status:** decided 2026-10-10. GitHub + GitLab, **plus a filter in the main list** to show All / GitHub / GitLab.

## D3. What "multiple versions" in a repo means

- **a) Build files**: one release ships several files (RPM, AppImage, ARM, Intel…). You pick one to follow.
- **b) Branches**: for repos without releases, e.g. AeroThemePlasma's `Plasma/6.7` and `master`. You pick one.

**Status:** decided 2026-10-10. Both a) and b). Grouping related repos together isn't planned (since
2026-10-11, repos can be sorted into categories of your own: D14).

## D4. How updates get installed

- **Nothing installs on its own.** You click the ⬆ icon next to a repo (or Update on its page). So the app never pops
  up a password prompt you didn't ask for.
- RPMs install with `dnf install ./file.rpm`, which asks for your password after you click.
- Git clones only pull. Re-running a project's install script (AeroThemePlasma has one) is a separate button, and the
  app shows you what it will run first.

Later option: the "custom dnf" idea, a local package repo the app fills, so `dnf upgrade` / Discover pick these up too.

**Status:** decided 2026-10-10.

## D5. Checking and notifications

- **One global setting**, asked on first launch, changeable in Settings: automatic checks **on** with an interval
  (daily / every 7 days / every 14 days / monthly, where monthly = every 4 weeks; daily is the default), or **off** (only the Check now button).
- **No per-repo intervals.** Simpler, and one pass over all repos uses less of the system than many separate timers.
- Automatic checks run from a systemd user timer: the checker starts, checks everything, and exits. Nothing stays
  running in between.
- **When updates are found:** a toast (on by default). Clicking it opens the main window, where each repo with an
  update has a ⬆ icon. The app's taskbar icon shows a badge with the number of updates.
- **Toasts can be turned off**, leaving just the badge and the ⬆ icons.
- **Only from the background** (KDE HIG, status changes): a toast is sent only when the main window isn't open or
  in front. With the window in front, new updates show in the window itself.
- **As built (stage 4):** the timer wakes hourly (and after login) and the checker decides if the interval has passed,
  so the interval counts from the last check. Each update is announced once. The badge only shows while the app is
  open: Plasma clears a badge when the app that set it closes.

**Status:** decided 2026-10-10.

## D6. Safety rules

- Never run anything as root without you clicking and entering your password.
- Verify downloads against the checksum file when the project publishes one; warn when it doesn't.
- Keep the previous version until the new one is in place, so a failed update leaves a working copy.
- Never run a project's own install script automatically.

**Status:** decided 2026-10-10.

## D7. How the app talks to GitHub and GitLab

**The limits.** GitHub's API allows **60 requests an hour per IP address** without logging in, and 5,000 an hour
with a login. GitLab.com's limits are much looser, and self-hosted GitLab sites like gitgud.io set their own. These
limits apply **per user**: every copy of the app runs on its own machine and sends its own requests, so users don't
share a limit and there's no server of ours to run or pay for.

**How the app stays well under them, without needing a login:**

1. **Git clones use `git ls-remote`**, not the API. It asks the server which commit a branch is on, a few hundred
   bytes per repo, and isn't counted against the API limit at all. Most of what you'd track today is git clones.
2. **One request per repo per check** for release-tracked repos (just "what's the latest release?"). The full release
   list is fetched only when you open a repo's page.
3. **"Has anything changed?" requests.** The app remembers each answer's fingerprint (an ETag) and asks "only send
   it if it changed". When nothing changed, GitHub answers "not modified", and for logged-in requests those don't
   count against the limit.
4. **Back off when told to.** If a site says "slow down", the app waits until the time it gives and tries again next
   round instead of retrying in a loop.

**Rough math:** 30 release-tracked repos checked every 6 hours is 30 requests per check, well under 60 an hour,
with no login. You'd only hit the limit with something like 60+ release repos checked hourly.

**Optional login, for heavy use:** Settings → "Sign in to GitHub", which raises the limit to 5,000 an hour.
- If the `gh` command is already logged in (it is on this machine), the app offers to reuse that login.
- Otherwise it uses GitHub's sign-in code page (the same "enter this code at github.com/login/device" flow the
  ultrakanban Setup page uses).
- The login token is stored in KDE Wallet, never in the plain settings file.
- The app **never ships with a built-in token**. Anyone could pull it out of the app and use it, and GitHub would
  revoke it.

**Status:** decided 2026-10-10 ("works for now"): the four points above, working without a login by default, with
optional sign-in as designed in DESIGN.md §8.

## D8. Where downloaded apps go

AppImages in `~/Applications`, loose programs in `~/.local/bin`, with a menu entry created for AppImages so they show
up in the KDE launcher. Nothing in system folders except through dnf. Projects Install clones (ones you don't have,
followed by branch or source only) go in `~/src`, a common place for source code, and inside the default scan
folders.

**Status:** decided 2026-10-10.

## D9. Keeping this project in git

**Status:** decided 2026-10-10. Local git repo only, no GitHub for now.

## D10. Name

"RepoProject" stays as the working name until there's an app icon and menu entry to put a real name on.

**Status:** decided 2026-10-10 (keep the working name for now).

## D11. Old versions

Not kept. An update removes the version it replaced, once the new one is in place (D6). There's no Undo, and so no
setting to delete old versions after a while: nothing piles up. RPMs: dnf replaces the old version itself. Git clones:
the old versions are the repo's own history, which isn't touched.

**Status:** decided 2026-10-10; changed 2026-10-11: Undo and the "delete old versions after…" setting were dropped as
unnecessary, so old versions are removed straight away.

## D12. Scanning the computer

**Where:** the home folder, `/opt`, `/usr/local` and `/srv` by default (marked "Default" in Settings, which can add
or remove folders). Home alone missed `/opt` and `/usr/local`, the standard places for software installed by hand.
The rest of the system (`/usr`, …) isn't scanned: it's slow and doesn't hold hand-installed software. Decided
2026-10-10.

Global setting, **off by default**, because it looks through your files. Offered on first launch and in Settings.
While it's off, the Scan button is hidden and tracking is manual: you add repos yourself and set which version
you have, or mark it as up to date. Both places that offer the setting say so. With scanning
on, repos can still be added by hand.

**Manual and scanned entries are never duplicated.** Each repo is marked as added by hand or found on this computer.
When a scan finds a repo that's already on the list (added by hand, installed from the app, or installed some other
way), it updates that entry: it becomes a scanned one, with the folder it was found in and the version on disk.
Matching uses the repo's address and any older addresses it's known by, ignoring upper/lower case. If nothing
matches, the site is asked whether the address moved, and the old address is remembered for next time. Scan results start with nothing ticked. You pick specific repos or click
**Select all**.

**Status:** decided 2026-10-10.

## D13. Repo icons

Each repo gets an icon, looked up **once**, when it first appears in the list (on first load, when added by hand, or
when a scan adds it). The result is saved, including "none found", so it's never looked up again; only a site that
couldn't be reached is retried, on the next load. In order, the first that turns something up:

1. **On this computer:** a scanned RPM's menu entry; a scanned AppImage's own icon (read with 7z, never run); an icon
   file in a scanned clone; an installed app whose menu entry matches the repo's name (names under 4 letters skipped).
2. **The project's picture on its site:** a GitLab project's icon, else its group's picture; on GitHub, the owner's
   picture only if the owner is an organization. A person's profile picture wouldn't represent the project. Taken
   from the project info already fetched when adding (no extra request), downloaded once (max 1 MB, must be a
   picture) into `~/.cache/repoproject/icons`, and deleted when the repo is removed.
3. **The default icon** for the kind of repo.

Scanned repos also get a corner mark (`emblem-mounted`: found on this computer).

**Status:** decided 2026-10-10.

## D14. Categories

Your own categories for sorting the list, e.g. "Themes" and "Tools".

- **New Category…** (right of the filters) adds one at the bottom. Names are unique, ignoring upper/lower case.
- **Drag** a repo by its handle onto a category's heading (to the top of it) or above/below another repo. Drag a
  category by its handle to move it, with its repos. The row itself follows the pointer (its place stays faded),
  and a line shows where it will land.
- **⋮ on each heading** (or right-click it) has **Rename** and **Delete Category…**. Rename turns the name into a text
  box in place (Enter saves, Esc cancels); double-clicking the name does the same. A name that's taken says so and
  stays open. Delete sits in the menu rather than alone on the heading, so it isn't one stray click away.
- **Delete** never removes repos: they move to the end of Uncategorized, and stay tracked. A category with repos asks
  first; an empty one goes straight away.
- A repo is in one category at most. Repos in none are under **Uncategorized**, which is always first and can't be
  moved or deleted. Until there's a category, there are no headings and the list looks as before.
- The order is yours: it's the order in the settings file. Files from before categories keep their order by name; new
  repos go to the end of Uncategorized.
- The All / GitHub / GitLab filter still applies; headings stay, with the number shown.

**Status:** decided 2026-10-11.
