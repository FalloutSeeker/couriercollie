# Design

## The problem

Some software on a Fedora machine never gets updated, because it didn't come from Fedora's repos or Flathub:

- **Git clones** you built or installed from, e.g. AeroThemePlasma in `~/aero/aerothemeplasma` (from gitgud.io).
- **Release downloads** from a project's Releases page: an `.rpm`, an AppImage, or a `.tar.gz` with a program inside.

`dnf upgrade` and Discover don't know these exist. You only find out about new versions by visiting each page.

## What the app does

### 1. Find what's already installed

A **Scan** button looks through the machine for things that came from GitHub/GitLab and lists them. You tick the ones
to track.

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

- **Installed version** and **latest version**, with when it was last checked.
- **Releases list**: every version, newest first, with its date and release notes. Pre-releases are hidden unless
  you turn them on for that repo.
- **Build files per release**: one project often publishes several files for the same version (an `.rpm`, an
  AppImage, ARM and Intel builds, etc.). They're listed under each release; you pick the one you use and the app
  remembers it for future updates (it matches by pattern, so `app-1.2-x86_64.rpm` → `app-1.3-x86_64.rpm` still matches).
- **Branches**, for repos that don't publish releases (common for git clones): the app follows new commits on a
  branch instead, e.g. `Plasma/6.7`.
- **Check interval** for this repo (overrides the default), and **Update** / **Open project page** buttons.

### 4. Checking on a schedule

- A global check interval, chosen on first launch (see 6): every hour / 6 hours / 12 hours / day / week, or
  **Never (manual only)**. Each repo can override it.
- With an interval set, checks run in the background even when the window is closed. With Never, the app only checks
  when you click **Check now**.
- New versions show up in the app (marked "new", with an update count), plus a KDE toast unless you turned toasts off.
  Clicking the toast opens that repo's page.

### 5. Updating

**Nothing ever installs on its own** (DECISIONS.md, D4), so the app never shows a password prompt you didn't ask for.
**Update mode**: each repo uses one of:

- **Notify + click**: notifies you, then installs when you click Update.
- **Notify only**: notifies you and links the project page.

The global mode is chosen on first launch (see 6). Each repo's detail page can override it ("Use global setting" is
the default).

What "Update" does depends on the kind:

| Kind        | Update does                                                                     |
| ----------- | ------------------------------------------------------------------------------- |
| RPM         | Downloads the new `.rpm` and installs it through dnf (asks for your password)   |
| AppImage    | Downloads the new file and swaps it in, keeping the old one until it works      |
| Program     | Downloads, unpacks, and swaps in the new program file                           |
| Git clone   | Pulls the new commits. Re-running the project's install script is a separate, deliberate step |

**Old versions** (DECISIONS.md, D11): the previous version is kept so an update can be undone, then deleted after a
set time (Settings: 7 / 30 / 90 days / Never; default 30). Only files in your own folders are deleted. Anything that
would need admin rights is skipped, never prompted for.

### 6. First launch

A short setup screen asks three things, and says all of them can be changed later in Settings:

1. **How should updates work?** Notify + click / Notify only.
2. **How often should it check?** Every hour / 6 hours / 12 hours / day / week / Never (I'll click Check now).
3. **Desktop notifications (toasts)?** On / Off. Not asked if the interval is Never, since then you're always in the
   app when a check happens.

Then it offers to run a **Scan** for things already installed.

## Screens (rough sketches)

**First launch**

```
┌ Welcome to RepoProject ───────────────────────────────────────┐
│  How should updates work?                                     │
│    ◉ Tell me, and I'll click Update                           │
│    ○ Just tell me (link to the project page)                  │
│                                                               │
│  How often should it check?   [ Every 6 hours ▾ ]             │
│    (Never = only when you click Check now)                    │
│                                                               │
│  Desktop notifications        [✓]                             │
│                                                               │
│  You can change all of this later in Settings.                │
│                                       [Scan my system] [Done] │
└───────────────────────────────────────────────────────────────┘
```

**Main list**

```
┌ RepoProject ────────────────────────────────────── [Scan] [+ Add] [⚙] ┐
│  Show: (All) (GitHub) (GitLab)                                        │
│  Name                 Installed      Latest        Kind       Status  │
│  AeroThemePlasma      a1b2c3d        f9e8d7c       git        ● new   │
│  smod                 4d5e6f7        4d5e6f7       git        ✓       │
│  SomeApp              1.4.0          1.5.2         AppImage   ● new   │
│  OtherTool            2.0.1          2.0.1         RPM        ✓       │
│                                                                       │
│  Last checked 14:02 · next check 20:02                [Check now]     │
└───────────────────────────────────────────────────────────────────────┘
```

**Repo detail**

```
┌ ← SomeApp ─────────────────────────── github.com/owner/someapp ┐
│  Installed 1.4.0 · Latest 1.5.2                     [Update]  │
│  Follow: [ Releases ▾ ]   Check every: [ 6 hours ▾ ]          │
│  Update mode: [ Use global setting (Notify + click) ▾ ]       │
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
┌ Found 11 items ───────────────────────────────────────────────┐
│  [✓] AeroThemePlasma   git   ~/aero/aerothemeplasma  gitgud.io │
│  [✓] smod              git   …/repos/smod            gitgud.io │
│  [ ] ultrakanban       git   ~/ultrakanban           github    │
│  …                                                             │
│                                       [Cancel] [Track selected]│
└───────────────────────────────────────────────────────────────┘
```

## How it works underneath (plain version)

- **One settings file** (`~/.config/repoproject/repos.toml`) lists what's tracked, which build file to follow, and
  intervals. It's plain text, so you can read or back it up.
- **A background checker** runs on a systemd user timer (only if an interval is set). It asks GitHub/GitLab for each
  repo's latest release or commit, compares it with what's installed, records what's new for the window to show, and
  sends a toast if those are on. It never installs anything.
- **The window** is a separate program that reads the same settings file. Closing it doesn't stop checks.
- **Downloads** are kept in `~/.cache/repoproject` so a failed update can roll back to the previous file, and are
  cleaned up after the "delete old versions" period.

Proposed tools (see DECISIONS.md, D1): Python, with Qt and KDE's Kirigami for the window so it looks native on KDE.
Both are already installed on this machine.
