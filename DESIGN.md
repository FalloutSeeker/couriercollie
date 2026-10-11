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

| Kind                         | Where it looks                                       | How it finds the source                          |
| ---------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| Git clones                   | Your home folder (skips caches, `node_modules`)      | The clone's own remote URL (`git remote`)        |
| RPMs installed from a file   | dnf's record of packages not from any repo           | The package's homepage URL, if it's a Git host   |
| AppImages                    | `~/Applications`, `~/Downloads`, `~/.local/bin`, `/opt` | Info embedded in the AppImage, else ask you   |
| Loose programs               | `~/.local/bin`, `/usr/local/bin`, `/opt`             | Can't be detected reliably; you link them by hand |

Anything already looked after by dnf or Flatpak is left out, since those update themselves.

> On this machine today, a scan would find 11 git clones (10 AeroThemePlasma repos and `ultrakanban`) and no
> AppImages or GitHub RPMs.

### 2. Add a repo by hand

**Add** asks for:

- **Name**: what to call it in the list.
- **URL**: the project page, e.g. `https://github.com/owner/project`.

The app then fetches the project's releases and shows them, so you can pick which build file to follow (see 3).

### 3. Repo detail page

Clicking a tracked repo shows:

- **Your version** and a status line ("Up to date" / "Newer version available: …"). Your version is a release, a
  commit (when following a branch), or "Not installed". When a repo is added it starts at the newest version; change
  it if you're on an older one.
- **Releases list**: every version, newest first, with its date and release notes. Pre-releases are hidden unless
  you turn them on for that repo.
- **Your build file**: one project often publishes several files for the same version (an `.rpm`, an AppImage, ARM
  and Intel builds, etc.). You pick the one you use in one place, from the newest release's files, and the app
  follows that same file in future releases (it matches by pattern, so `app-1.2-x86_64.rpm` → `app-1.3-x86_64.rpm`
  still matches). The releases list is for reading, with a ✓ on your file in each release.
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

**Old versions** (DECISIONS.md, D11): the previous version is kept so an update can be undone. Deleting old versions
after a set time is **off by default** (kept forever). It's a global setting, offered on first launch and in
Settings. Only files in your own folders are deleted. Anything that would need admin rights is skipped, never prompted
for.

### 6. First launch

A short setup screen asks three things and says all of them can be changed later in Settings:

1. **Check for updates automatically?** If yes, pick how often. If no, checks only happen when you click Check now.
2. **Scan this computer for repos?** Off by default. If turned on, a scan runs when you click Done, and the scan
   results let you tick specific repos or **Select all**.
3. **Delete old versions automatically?** Off by default. If turned on, pick after how long: 7 / 30 / 90 days.

Toasts are on by default whenever automatic checks are on, and can be turned off in Settings.

### 7. Settings

All global; there are no per-repo settings.

- **Automatic checks**: on/off, and the interval.
- **Toast notifications**: on/off. Off leaves only the taskbar badge and the ⬆ icons in the app.
- **Scanning**: on/off. On shows the Scan button in the main window.
- **Delete old versions**: on/off, and after how long (7 / 30 / 90 days).
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
│  [ ] Delete old versions after [ 30 days ▾ ]                  │
│      Kept versions let you undo an update.                    │
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
- **Downloads** are kept in `~/.cache/repoproject` so a failed update can roll back to the previous file, and are
  cleaned up after the "delete old versions" period.

Tools (DECISIONS.md, D1): Python, with Qt and KDE's Kirigami for the window so it looks native on KDE. Both are
already installed on this machine.
