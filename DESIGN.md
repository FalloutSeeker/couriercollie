# Design

## The problem

Some software on a Fedora machine never gets updated, because it didn't come from Fedora's repos or Flathub:

- **Git clones** you built or installed from, e.g. AeroThemePlasma in `~/aero/aerothemeplasma` (from gitgud.io).
- **Release downloads** from a project's Releases page: an `.rpm`, an AppImage, or a `.tar.gz` with a program inside.

`dnf upgrade` and Discover don't know these exist. You only find out about new versions by visiting each page.

## What the app does

### 1. Find what's already installed

Scanning is **off by default** (DECISIONS.md, D12), because it means looking through your files. You can turn it on
during first launch (see 6) or later in Settings (see 7). While it's off, the Scan button is hidden.

When it's on, a **Scan** button looks through the machine for things that came from GitHub/GitLab and lists them.
Nothing is ticked to start with. You tick the ones to track, or use **Select all**.

**Where it looks.** Folders to scan, by default the home folder, `/opt`, `/usr/local` and `/srv`: where software
installed by hand usually lives. Each is marked "Default" in Settings, where folders can be added (e.g. a second
drive) or removed. Subfolders are included up to 6 levels deep, except hidden ones and dependency or build folders
(`node_modules`, `build`, …), so a scan stays fast.

| Kind                         | Where it looks                                          | How it finds the source                      |
| ---------------------------- | ------------------------------------------------------- | -------------------------------------------- |
| Git clones                   | The folders to scan                                     | The clone's own remote URL (`git remote`)    |
| AppImages                    | The folders to scan, plus `~/.local/bin` (hidden)       | Update info embedded in the AppImage         |
| RPMs installed from a file   | The whole system, through dnf's list of installed RPMs  | The package's homepage, if it's a Git host   |
| Loose programs               | Not scanned                                             | Can't be detected reliably; add them by hand |

Finds in folders that belong to the system (common in `/opt`) are tracked like any other. Updating them will ask
for the password, on the user's click.

Anything already looked after by dnf or Flatpak is left out, since those update themselves, and the scan says so.
For RPMs that takes two checks, both asked of dnf: the package was installed from a downloaded file (dnf records it
as `@commandline`, where Fedora's would say `fedora` or `updates`); and no repository you have enabled offers a
package of that name. The second catches RPMs that add their own repository when installed (like
`rpmfusion-free-release`): installed from a file, but dnf updates them. If dnf can't answer, no RPMs are listed.

> On this machine today, a scan would find 11 git clones (10 AeroThemePlasma repos and `ultrakanban`) and no
> AppImages or GitHub RPMs.

### 1b. Categories

The list can be sorted into categories of your own, by dragging (DECISIONS.md, D14). Repos in none are under
"Uncategorized". Deleting a category keeps its repos.

### 2. Add a repo by hand

**Add** asks for:

- **Name**: what to call it in the list.
- **URL**: the project page, e.g. `https://github.com/owner/project`.

The app then fetches the project's releases and shows them, so you can pick which build file to follow (see 3).

### 3. Repo detail page

Clicking a tracked repo shows, top to bottom (laid out for scanning, chosen 2026-10-11):

- **Header:** the repo's icon, name (large), description and address.
- **Status box:** a short headline ("Update available", "Up to date", "New commits on Plasma/6.7", "Not installed",
  "Couldn't compare") with **your version → newest** in large type, the buttons below them, and new commits when
  following a branch. Coloured by the theme: highlight for an update, green for up to date, orange for a problem.
- **Tracking:** lined-up labels on the left: Follow, Build file (or Branch), Pre-releases, Source (added by hand, or
  found on this computer with its path).
- Then the build file picker, and the releases or branches lists.

Details:

- **Your version** and a status line ("Up to date" / "Newer version available: …"). Your version is a release, a
  commit (when following a branch), or "Not installed". A repo added by hand starts as "Not installed" (adding it doesn't mean you have it). To
  change it, open a release in the list and click "This is my version", or use "Mark as up to date" / "Mark as not
  installed".
  For repos found by a scan, your version is read from disk (a clone's commit, an AppImage's version, an RPM's
  version), so it follows a `git pull` or reinstall done outside the app, and isn't set by hand. Like everything on
  the page, it's read the first time the page opens after the app starts, then only on **Refresh** or when an update
  check finds something newer: opening a page again makes no requests. When following a branch you're behind on, the new commits are listed (up to 5, newest first).
- **Releases list**: every version, newest first, with its date and release notes. Pre-releases are hidden unless
  you turn them on for that repo.
- **Your build file**: one project often publishes several files for the same version (an `.rpm`, an AppImage, ARM
  and Intel builds, etc.). You pick the one you use in one place, from the newest release's files, and the app
  follows that same file in future releases (it matches by pattern, so `app-1.2-x86_64.rpm` → `app-1.3-x86_64.rpm`
  still matches). Only files that run on this computer can be chosen. The releases list is for reading.
- **Versions only**: if nothing in the newest release runs on this computer (e.g. an Android-only project), there's
  no file to choose. The repo is tracked by version only, as with scanning off: you hear about new releases and set
  your version yourself or mark it as up to date. Nothing is downloaded or installed. If a later release adds a file
  for this computer, the file picker comes back.
- **Branches**, for repos that don't publish releases (common for git clones): the app follows new commits on a
  branch instead, e.g. `Plasma/6.7`.
- **Update** and **Open project page** buttons.

There are no per-repo check settings. Checking is one global schedule (see 4), to keep things simple and light on the
system.

### 4. Checking for updates

One global setting, chosen on first launch (see 6) and changeable in Settings:

- **Automatic checks on**, with an interval: daily / every 7 days / every 14 days / monthly (every 4 weeks). The
  time is counted from the last check, not from a weekday. Checks run in the background
  even when the window is closed.
- **Automatic checks off**: nothing runs in the background. The **Check now** button in the main window still works.

When an automatic check finds updates:

- **Toast** (on by default): a KDE notification like "2 updates available: AeroThemePlasma, SomeApp". Clicking it
  opens the main window.
- **Badge**: the app's icon in the taskbar shows the number of updates. If toasts are turned off in Settings, the
  badge is the only signal.
- **In the main window**, each repo with an update has an **update icon** (⬆) next to it. Clicking the icon updates
  that repo.

### 5. Updating

**Nothing ever installs on its own**, so the app never shows a password prompt you didn't ask for. You update by
clicking the ⬆ icon in the list, or **Update** on the repo's page.

What "Update" does depends on the kind:

| Kind        | Update does                                                                     |
| ----------- | ------------------------------------------------------------------------------- |
| RPM         | Downloads the new `.rpm` and installs it through dnf (asks for your password)   |
| AppImage    | Downloads the new file and swaps it in, keeping the old one until it works      |
| Program     | Downloads, unpacks, and swaps in the new program file                           |
| Git clone   | Pulls the new commits. Re-running the project's install script is a separate, deliberate step |

**Git clones (built 2026-10-11).** For clones found by a scan, or made by Install. Update is on the repo page, and
the ⬆ in the list becomes a button.

- **Install, for a project you don't have** (added by hand, and following a branch, or releases with nothing to
  download for this computer): clones it into `~/src/<name>` (D8; `<name>-2` if that's taken), on the branch, or at
  the newest release's tag. It's cloned under a hidden name first, so a failed clone leaves nothing behind.
  Afterwards it's a clone like one a scan found: its version is read from disk, and Update pulls it.

- **Following a branch:** fetches the branch from the clone's remote for the project and fast-forwards to it.
- **Following releases:** the clone's version is the release tag it's at (else its commit). Update fetches the newest
  release's tag and moves the clone to it; the branch it was on is left as it was (`git switch <branch>` goes back).
  No build-file picker for a clone.
- **Refuses**, saying why and changing nothing, when: the clone is on another branch than the one followed; it has
  commits of its own; files you changed would be overwritten; moving to a release would strand commits that aren't
  on any branch; or the clone is someone else's (it shows the command to run as them).
- **Clones that belong to the system** (e.g. in `/opt`): Update asks for your password once (polkit, as Discover
  does) and runs the git commands as root. The page says so beforehand.
- Afterwards your version, the page and the list say Up to date, without asking the site. A failed update from the
  list opens the repo's page, where the reason is. Changing what a repo follows clears the old result until the next
  check.

**AppImages (built 2026-10-11).** For repos that follow an AppImage file. **Update** downloads the newest
release's file next to the one you have; **Install** (when you don't have it) puts it in `~/Applications` (D8).

- The download goes to a hidden `.part` file, with its progress shown, then is **checked**: against the SHA-256
  GitHub publishes for every release file (no extra request), or else a checksum file in the release
  (`<file>.sha256`, `SHA256SUMS`, `checksums.txt`, …). A mismatch throws the download away. With no published
  checksum it's still installed, and the page says so in a warning (D6). It must also really be an AppImage
  (the "AI" mark in its header), or it's thrown away.
- Then it's made runnable and swapped in under the release's own file name. The old file is removed only once the
  new one is in place (D6), so nothing piles up.
- **Menu entries:** yours that started the old file (e.g. from AppImageLauncher or Gear Lever) are pointed at the
  new one. If none starts it, the app adds one (`~/.local/share/applications/repoproject-<repo>.desktop`) with the
  AppImage's own icon.
- From then on the repo's version is read from the file, as for a scanned one ("Found on this computer").

**RPMs (built 2026-10-11).** For repos that follow an `.rpm` file. **Install…** / **Update…** (the dots: it asks for
your password, which the page says beforehand):

- Downloaded (with progress) into `~/.cache/repoproject/downloads`, checked against the published checksum (else a
  warning), and must really be an RPM. Its header is read with `rpm` (as you, nothing installed): if you have the
  package already, the file must be that same package (a renamed one stops, saying so), and it must be for this
  computer's processor or `noarch`.
- Then `dnf install -y <file>` runs as root through polkit: one password prompt per update. Cancelling it changes
  nothing. dnf's own error is shown if it fails (e.g. a missing dependency). The download is deleted either way.
- From then on the version is read from the installed package (`rpm -q`), like an RPM a scan found.

**Programs (built 2026-10-11).** For repos that follow a release archive (`.tar.gz`, `.tgz`, `.tar.xz`, `.tar.bz2`,
`.tar.zst`, `.zip`) with a ready-made program inside, e.g. ripgrep or LocalSend's tarball.

- Downloaded and checked like an AppImage (published checksum, else a warning), then **unpacked whole** into its own
  folder, `~/.local/share/repoproject/programs/<repo>/<version>/`, since some programs need the files next to them.
  Unpacking is safe: nothing may land outside that folder, no device files or setuid, at most 4 GB unpacked.
- **The program** is the archive's Linux executable (not libraries); if there are several, the one named like the
  project; otherwise the page lists them to choose from, and the choice is kept for later updates.
- A **link** in `~/.local/bin` (where Fedora's terminal looks for commands) starts it, e.g. `rg`. Updating unpacks
  the new version beside the old, switches the link in one step, then removes the old version's folder.
- A command in `~/.local/bin` that RepoProject didn't put there is **never replaced**: the update stops and says so.
- No menu entry: these are mostly command-line tools. The page shows the command under Tracking.

**Install scripts.** A clone's `install.sh`, `install` or `setup.sh` (never `uninstall.sh`) gets a "Show and Run…"
button under Tracking. The script is shown in full first; Run in Terminal opens Konsole in the clone's folder, as
you, kept open afterwards so its output can be read. The script asks for a password itself if it needs one. Update
never runs it.

**Old versions** aren't kept (D11): each update removes the version it replaced, once the new one is in place.

### 6. First launch

A short setup screen asks two things and says both can be changed later in Settings:

1. **Check for updates automatically?** If yes, pick how often. If no, checks only happen when you click Check now.
2. **Scan this computer for repos?** Off by default. If turned on, a scan runs when you click Done, and the scan
   results let you tick specific repos or **Select all**.

Toasts are on by default whenever automatic checks are on, and can be turned off in Settings.

### 7. Settings

All global; there are no per-repo settings.

- **Automatic checks**: on/off, and the interval.
- **Toast notifications**: on/off. Off leaves only the taskbar badge and the ⬆ icons in the app.
- **Scanning**: on/off. On shows the Scan button in the main window.
- **GitHub account** (optional): Sign in / Sign out, with the explanation below.

### 8. Signing in to GitHub (optional)

Signing in is never required. The Settings section explains why someone would do it:

```
┌ GitHub account ───────────────────────────────────────────────┐
│  Not signed in                               [Sign in…]       │
│                                                               │
│  GitHub limits how often apps can ask it about releases:      │
│  60 requests an hour without signing in, 5,000 an hour with.  │
│                                                               │
│  Each check uses about one request per repo that publishes    │
│  releases. Repos you cloned with git don't count.             │
│                                                               │
│  You're tracking 12 release repos, checked every 6 hours:     │
│  about 12 requests per check. You don't need to sign in.      │
│                                                               │
│  Sign in if you track a lot of repos or check often.          │
│  RepoProject only reads public release info with it. It       │
│  doesn't change anything on GitHub. The login is kept in      │
│  KDE Wallet, and you can sign out anytime.                    │
└───────────────────────────────────────────────────────────────┘
```

- **The "you're tracking…" lines are worked out live** from the number of release repos and the check interval, so
  the advice fits the user. When usage is close to the limit, they say "Signing in is recommended" instead.
- **When the limit is actually hit**, the main window shows a bar: "GitHub's hourly limit was reached, so 8 repos
  weren't checked. They'll be checked after 15:00. [Sign in to GitHub] [Dismiss]". Repos that weren't checked keep
  their last known status. Nothing is shown as an error.
- **Sign in…** offers to reuse the `gh` login if one exists ("Use your existing GitHub CLI login as FalloutSeeker?").
  Otherwise it shows a short code and opens github.com/login/device to enter it.
- **Signed in** shows the account name and how many requests are left this hour, with **Sign out**.
- **Permissions:** the sign-in asks for no extra access beyond reading public data, since checking releases only
  reads public information. (Tracking a *private* repo would need read access to it. That's a later decision.)

## Screens (rough sketches)

**First launch**

```
┌ Welcome to RepoProject ───────────────────────────────────────┐
│  Check for updates automatically?                             │
│    ◉ Yes, every [ 6 hours ▾ ]                                 │
│    ○ No, I'll click "Check now" myself                        │
│                                                               │
│  You'll get a notification when updates are found.            │
│                                                               │
│  [ ] Scan this computer for repos I've already installed      │
│      You'll choose which ones to track.                       │
│                                                               │
│  You can change all of this later in Settings.                │
│                                                       [Done]  │
└───────────────────────────────────────────────────────────────┘
```

**Main list** (the Scan button only shows when scanning is on)

```
┌ RepoProject ────────────────────────────────────── [Scan] [+ Add] [⚙] ┐
│  Show: (All) (GitHub) (GitLab)                       2 updates        │
│  Name                 Installed      Latest        Kind               │
│  AeroThemePlasma      a1b2c3d        f9e8d7c       git          [⬆]   │
│  smod                 4d5e6f7        4d5e6f7       git           ✓    │
│  SomeApp              1.4.0          1.5.2         AppImage     [⬆]   │
│  OtherTool            2.0.1          2.0.1         RPM           ✓    │
│                                                                       │
│  Last checked 14:02 · next check 20:02                [Check now]     │
└───────────────────────────────────────────────────────────────────────┘
```

**Repo detail**

```
┌ ← SomeApp ─────────────────────────── github.com/owner/someapp ┐
│  Installed 1.4.0 · Latest 1.5.2                     [Update]  │
│  Follow: [ Releases ▾ ]                                       │
│                                                               │
│  ▾ 1.5.2   2026-10-08   (latest)                              │
│      ◉ SomeApp-1.5.2-x86_64.AppImage     84 MB   ← you use    │
│      ○ SomeApp-1.5.2-aarch64.AppImage    80 MB                │
│      ○ someapp-1.5.2.x86_64.rpm          31 MB                │
│      Release notes…                                           │
│  ▸ 1.5.1   2026-09-21                                         │
│  ▸ 1.4.0   2026-08-02   (installed)                           │
└───────────────────────────────────────────────────────────────┘
```

**Scan results**

```
┌ Found 11 items ────────────────────── [Select all] [Select none] ┐
│  [ ] AeroThemePlasma   git   ~/aero/aerothemeplasma  gitgud.io │
│  [ ] smod              git   …/repos/smod            gitgud.io │
│  [ ] ultrakanban       git   ~/ultrakanban           github    │
│  …                                                             │
│                                  [Cancel] [Track selected (0)] │
└────────────────────────────────────────────────────────────────┘
```

### 9. Checking for updates (built in stage 4)

- **Check Now** in the list's toolbar checks every repo; the line under the filters shows "3 updates · checked 21:53 ·
  next check tomorrow 21:53" (or "automatic checks are off"). Each row shows its result on the right, with the update
  icon for an update.
- **Requests per check:** one per repo that follows releases; none for a branch (`git ls-remote`), plus one or two to
  compare when your commit isn't the branch's newest. Scanned repos read their version from disk. Four at a time.
- **Hourly limit:** once GitHub says it's reached, the other GitHub repos aren't asked; they keep their last result,
  marked "not rechecked", and a bar says when they can be checked again.
- **No connection** (or a site that doesn't answer): those repos also keep their last result, marked "(not
  rechecked)", rather than an error replacing it. The line under the filters says how many couldn't be checked. A
  repo that fails for a reason of its own (e.g. its branch is gone) says "Couldn't check", with why on hover.
- **Results** are kept in `~/.local/state/repoproject/checks.json`, apart from the settings file, so the background
  checker and the open window never overwrite each other's changes.
- **Background:** a systemd user timer (`repoproject-check.timer`) wakes hourly, after a missed hour, and 3 minutes
  after login, and runs `run.sh --check --if-due`. That only checks if automatic checks are on and the interval has
  passed since the last check. If the app is open, it hands the check to the app. Opening the app never checks on its
  own, and a computer that was off past the interval checks once, shortly after login. A check where no site answered
  (no connection yet) doesn't count, so it's tried again within the hour rather than a whole interval later.
- **Notifications** only for updates not announced before, and only when the window isn't in front; clicking one opens
  (or brings forward) the app. The **taskbar badge** shows the number of updates while the app is open (Plasma clears a
  badge when its app closes).
- **One copy at a time:** opening the app again brings the open window forward.

## How it works underneath (plain version)

- **One settings file** (`~/.config/repoproject/repos.toml`) lists what's tracked, which build file or branch to
  follow, and the global settings. It's plain text, so you can read or back it up.
- **A background checker** runs on a systemd user timer, only if automatic checks are on. It runs, checks every repo
  in one pass, records what's new for the window to show, sets the taskbar badge, sends a toast if those are on, and
  exits. Nothing stays running between checks. It never installs anything.
- **Taskbar badge** uses the same mechanism other KDE apps use for unread counts. It shows on the app's taskbar icon
  when the app is open or pinned to the taskbar. To check when building: whether the badge stays visible after the
  checker exits while the window is closed.
- **The window** is a separate program that reads the same settings file. Closing it doesn't stop checks.
- **Downloads** go to a hidden `.part` file beside where they'll end up (RPMs: `~/.cache/repoproject/downloads`),
  and are removed once installed or if anything goes wrong.

Tools (DECISIONS.md, D1): Python, with Qt and KDE's Kirigami for the window so it looks native on KDE. Both are
already installed on this machine.
