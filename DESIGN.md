# Design

How couriercollie works, for anyone reading or changing the code. The *why* is in [DECISIONS.md](DECISIONS.md).

**The problem:** software you get straight from GitHub or GitLab (an AppImage, a release archive, a downloaded
`.rpm` or `.deb`, a git clone) is invisible to your package manager, so nothing tells you about new versions.

## 1. Scanning

Off until turned on (D12). **Scan** lists what it finds, new finds ticked; you choose what to track.

| Finds | Where | How it knows the project |
| --- | --- | --- |
| Git clones | Scan folders, 6 levels deep | The clone's remote address |
| AppImages | Scan folders, plus `~/.local/bin` | Update info built into the AppImage |
| Packages installed from a file | The package manager | The package's homepage |
| Flatpak bundles | Flatpak | The app's homepage |

- **Only what nothing else updates:** an RPM from a file that no enabled repository offers (dnf), "(System
  Packages)" (zypper), "local" (apt), a Flatpak bundle. Never Arch packages: pacman can't tell a downloaded one from an
  AUR build.
- **Scan folders:** home, `/opt`, `/usr/local` and `/srv` by default. Hidden and build folders are skipped, as are
  folders you can't open (Settings says which).
- **No duplicates:** a find matching a tracked repo (by address, or an old one) updates it instead.

## 2. Adding a repo

Paste any GitHub or GitLab page of the project. Renames are followed, and the file for this computer is picked if
there's exactly one. A project without releases follows its default branch.

**couriercollie itself** is added once, on the first start: its own package, or the clone's branch when run from
source. A scan shows it greyed out, "Added by default".

## 3. The repo page

- **Status:** a headline ("Update available", "Up to date", "New commits on main", "Not installed"), your version →
  the newest, and the buttons.
- **Tracking:** what's followed, pre-releases, what Update runs after downloading, and where it came from.
- **Your build file:** chosen from the newest release's files that run here, kept as a pattern
  (`app-1.2-x86_64.AppImage` → `app-*-x86_64.AppImage`). If nothing runs here, it's tracked by version only.
- **Releases** (newest 10, up to 30) and **branches**. Pictures in release notes become links.

Special cases:

- **Built only for other systems** (Android, Windows, other processors): version only, never installed. An info
  banner says what its builds are for; "Version not set" until you mark it.
- **Installed by your package manager** (or from Flathub): shown, never updated here; "Installed with Package
  Manager". Matched by homepage, never by name.
- **Your version:** "Not installed" for a repo added by hand until you set it; read from disk for one found here.
- **Loading:** once per app start; again on Refresh, or when a check found something newer.

### Update does the whole job (a clone)

Downloading only changes a clone's files, so Update also runs its step:

- **Asked once, the first time** (or once Install has cloned it): its install script, or a rebuild in its CMake or
  Meson build folder. The window shows what will run: Update, Only Download, or Cancel. Nothing is typed in.
  Change… (under Tracking) changes it.
- **Running containers** (from its compose files) are rebuilt and restarted without asking.
- **Asked again** if an update changes what was approved.
- **Runs inside the app,** output shown live. `sudo` asks in the desktop's own password window (`sudo -A`), so
  couriercollie never sees the password; without one, it stops and offers the command for a terminal.
- **Nothing to run:** Update only downloads.

Clones that aren't updated here: **part of another clone** (its install script names it), **another person's**, and
**on another branch** than the one followed (the page offers to follow that one).

## 4. Checking for updates

- **Check Now**, or automatically: daily, weekly, every two weeks or monthly (D5).
- **Requests:** one per repo following releases; none for a branch (`git ls-remote`), plus one or two to list new
  commits. Clones are compared locally when they have both commits. 4 repos at a time.
- **GitHub's hourly limit, or offline:** repos keep their last result, marked "not rechecked".
- **Background:** a systemd user timer wakes hourly (and after login) and runs `couriercollie --check --if-due`. If
  the app is open, it does the check. After an uninstall, the timer removes itself.
- **Telling you:** a notification for new updates when the window isn't in front; a count on the taskbar and tray
  icons.
- **Results** are kept apart from the settings (`~/.local/state/couriercollie/checks.json`), so the background check
  and the window never overwrite each other.

## 5. Updating

Only when you click Update or Install (D4).

| Kind | What Update does | Password? |
| --- | --- | --- |
| AppImage | Downloads it beside the old one, swaps it in, keeps menu entries pointing at it | No |
| Program (release archive) | Unpacks into its own folder, switches the `~/.local/bin` link | No |
| Package (`.rpm`, `.deb`, Arch) | Installs with dnf, zypper, apt or pacman, one at a time | Yes |
| Flatpak bundle | Installs it for you | No |
| Git clone | Pulls (fast-forward only) or moves to the newest release's tag, then runs its step | Only if the system owns it |
| Not installed yet (source only) | Clones it into `~/src` | No |

Every download goes to a hidden `.part` file, is checked against the project's SHA-256 (GitHub's own, or a
checksum file; none gives a warning) and must be what it claims. The old version goes only once the new one works.

- **Packages, as root:** copied where only root can write and checked again, so nothing can swap the file.
- **Clones are never forced:** Update refuses, saying why, if the clone has its own commits, changed files, another
  branch, or another owner. As root, git runs by full path with hooks off.
- **Programs:** unpacking can't land outside the program's folder. A command in `~/.local/bin` that couriercollie
  didn't put there is never replaced.
- **An AppImage or program added by hand:** its copy's place isn't known, so Install puts a new copy in place. A scan
  finds yours, so Update replaces that instead.
- **couriercollie itself:** after it updates itself, its page offers Restart.

## 6. First launch and Settings

The first launch asks three things, all changeable later: automatic checks (daily by default), scanning (off), and
GitHub sign-in (optional).

Settings, all global: checking and notifications; start at login and the tray; GitHub sign-in; scanning and its
folders; Send Feedback (a pre-filled GitHub issue, tracked repos only if ticked); Restore to Defaults.

## 7. Signing in to GitHub

Optional: GitHub allows 60 requests an hour without signing in, 5,000 with.

- **Device flow:** a code to enter at github.com/login/device. Read-only: no access is asked for.
- **Kept in the desktop's password store** (`secret-tool`): KDE Wallet, GNOME Keyring, KeePassXC.
- **Sent only to api.github.com**, over https, never along a redirect.

## Under the hood

- **The window** is QML (Kirigami), talking to one Python `Backend` (`backend.py`, with `updating.py` and
  `account.py`).
- **No freezing:** network and disk work runs on worker threads; results come back through `_deliver`.
- **Settings** (`~/.config/couriercollie/repos.toml`) are written to a temporary file and renamed. A file that can't
  be read is never overwritten.
- **One copy at a time:** a second launch, or the background check, talks to the open app through a local socket.
