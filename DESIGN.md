# Design

How couriercollie works, for anyone reading or changing the code. The *why* behind each choice is in
[DECISIONS.md](DECISIONS.md).

**The problem:** software you get straight from GitHub or GitLab (an AppImage, a program from a release archive, a
downloaded `.rpm` or `.deb`, a git clone you built) is invisible to your package manager. Nothing tells you when
there's a new version.

## 1. Scanning

Off until turned on (D12). When on, **Scan** lists what it finds; you tick what to track.

| Finds | Where | How it knows the project |
| --- | --- | --- |
| Git clones | The scan folders, 6 levels deep | The clone's remote address |
| AppImages | The scan folders, plus `~/.local/bin` | Update info built into the AppImage |
| Packages installed from a file | The package manager | The package's homepage |
| Flatpak bundles | Flatpak | The app's homepage |

- **Only what nothing else updates is listed:**
  - **RPMs (dnf):** the package came from a downloaded file (`@commandline`), *and* no enabled repository offers it.
    The second check catches packages that add their own repository when installed.
  - **openSUSE (zypper):** listed under "(System Packages)".
  - **Debian/Ubuntu (apt):** marked "local".
  - **Arch:** never listed, because pacman can't tell a downloaded package from an AUR build (which AUR helpers update).
  - **Flatpak bundles:** their origin has no address, so Flatpak can't update them.
- **Scan folders:** your home folder, `/opt`, `/usr/local` and `/srv` by default; change them in Settings. Hidden and
  build folders (`node_modules`, `build`, etc.) are skipped. A scan runs as you, so a folder you can't open is skipped,
  and Settings says so.
- **No duplicates:** a find matching a tracked repo, by address or an old address, updates that entry instead.

## 2. Adding a repo by hand

Paste a project's address (any GitHub or GitLab page of it). The app follows renames, fetches the releases, and
picks the file for this computer if there's exactly one. A project without releases follows its default branch.

## 3. The repo page

Top to bottom:

- **Header:** icon, name, description, address.
- **Status box:** a headline ("Update available", "Up to date", "New commits on main", "Not installed"), your version
  → the newest, the buttons, and new commits when following a branch.
- **Tracking:** what's followed (a file or a branch), pre-releases, and where it came from.
- **Your build file:** choose from the newest release's files that run here. The choice is kept as a pattern
  (`app-1.2-x86_64.AppImage` → `app-*-x86_64.AppImage`), so the same file is followed in later releases. If nothing
  runs here, it's tracked by version only.
- **Releases:** the newest 10, with notes. **Show Older Releases** loads up to 30. Pictures in notes become links, so
  opening notes downloads nothing.
- **Branches:** for following new commits.

Details:

- **Your version:**
  - A repo added by hand starts as "Not installed". Set it with Mark as Up to Date or Set as My Version.
  - For a repo found on this computer, it's read from disk.
- **Loading:** a page loads once per app start. After that, only on Refresh, or when a check found something newer.
  When a page learns something newer than the last check (a new commit, say), the list's result updates too.
- **Also updated elsewhere:** if the project is installed from a repository your package manager uses, or as a
  Flatpak from Flathub (matched by homepage), the page says so. Nothing is stopped; updating it here too is your
  call, but the two copies can mix.
- **Install script:** a clone's `install.sh` / `install` / `setup.sh` gets a button. The button reads "Show and Run"
  (never run from here), "Run Again" (run at this version) or "Install the Update" (run before the clone changed).
  The script is always shown first, then runs in a terminal.
- **A clone on another branch than the one followed:** the page explains it, and offers to follow the clone's branch
  instead of an Update that would refuse.

## 4. Checking for updates

- **Check Now**, or automatically: daily, weekly, every two weeks or monthly (D5).
- **Requests:**
  - **A repo following releases:** one, for the newest 5 releases.
  - **A branch:** none (`git ls-remote`), plus one or two to list new commits when you're behind.
  - **In parallel:** 4 repos at a time.
- **Limits and offline:**
  - **GitHub's hourly limit:** the remaining GitHub repos keep their last result, marked "not rechecked". A bar says
    when they can be checked again, and offers to sign in.
  - **No connection:** results are kept the same way. A check where no site answered doesn't count, so the next one
    isn't put off.
- **Background:** a systemd user timer wakes hourly and 3 minutes after login, and runs `couriercollie --check
  --if-due`.
  - It checks only if the interval has passed since the last check.
  - If the app is open, the check is handed to it.
  - Opening the app never checks on its own.
- **Telling you:** a notification for updates not announced before, only when the window isn't in front. The taskbar
  icon shows the number of updates.
- **Results** live in `~/.local/state/couriercollie/checks.json`, apart from the settings. That way the background
  check and the window never overwrite each other.

## 5. Updating

Only when you click Update, or Install for something you don't have yet (D4).

| Kind | What Update does | Password? |
| --- | --- | --- |
| AppImage | Downloads it beside the old one, swaps it in, keeps your menu entries pointing at it | No |
| Program (release archive) | Unpacks into its own folder, switches the `~/.local/bin` link in one step | No |
| Package (`.rpm`, `.deb`, Arch) | Installs with dnf, zypper, apt or pacman | Yes |
| Flatpak bundle | Installs it for you with flatpak | No |
| Git clone | Pulls the followed branch (fast-forward only), or moves to the newest release's tag | Only if the system owns it |
| Not installed, branch only | Install clones it into `~/src` | No |

**An AppImage or program added by hand** that you have: where your copy is isn't known, so the button reads
**Install**, and it puts a new copy in place (updated from then on). A scan finds your copy, so Update replaces that
instead. The list's one-click Update isn't offered for these. Packages don't have this problem: the package manager
finds the installed one.

Every download:

1. Goes to a hidden `.part` file, with progress shown.
2. Is checked against the project's published SHA-256 (GitHub's own, or a checksum file in the release). A mismatch
   is thrown away; no checksum at all gives a warning.
3. Must really be what it claims (an AppImage's header, a package's magic bytes, a bundle's app ID).

The old version is removed only once the new one works (D6, D11).

**Packages, as root:** the checked file is copied where only root can write, checked again, and installed by the
package manager, named by its full path. Nothing in between can swap the file. Cancelling the password prompt
changes nothing.

**Clones are never forced.** Update refuses, saying why, when:

- the clone is on another branch;
- it has commits of its own;
- your changed files would be overwritten;
- moving to a release would strand commits;
- or it belongs to someone else.

As root (a system clone), git is run by full path, with the clone's hooks off.

**Programs:**

- **Unpacking is fenced:** nothing may land outside the program's folder, and no device files or setuid.
- **The program to link:** the archive's Linux executable. With several, the one named like the project, else you
  choose.
- **Your own commands are safe:** a command in `~/.local/bin` that couriercollie didn't put there is never replaced.

**Flatpak bundles** installed for all users are tracked but not updated here. Flatpak would read the file as root
from a folder you can write to, with no way to check it again.

## 6. First launch

One screen, everything changeable later in Settings:

1. Check for updates automatically? (Yes, daily, by default)
2. Scan this computer? (Off by default)
3. Sign in to GitHub (optional)

## 7. Settings

All global; nothing per repo.

- **Checking for Updates:** automatic checks and how often; notifications.
- **GitHub Account (optional):** sign in or out.
- **Finding Installed Repos:** scanning on/off and the scan folders.

## 8. Signing in to GitHub

Optional. Only needed if you track a lot of GitHub projects: GitHub answers 60 requests an hour without signing in,
5,000 with.

- **Sign In…** shows a code to enter at github.com/login/device (GitHub's device flow, through couriercollie's OAuth
  App). No client secret exists or is needed.
- **Read-only:** no access is asked for, so the login can only read public information.
- **Kept in the desktop's password store** (via `secret-tool`). The page names the one you have: KDE Wallet, GNOME
  Keyring, KeePassXC. With none, Sign In is unavailable and says why.
- **Sent only to api.github.com**, over https, never along a redirect, and only if it looks like a GitHub login. If
  GitHub turns it down, the app carries on without it and says so.
- **Unchanged release lists** are asked for with their ETag. A "not modified" answer has nothing to download, and
  costs nothing when signed in.

## 9. Categories

Your own headings for the list; see D14.

## Under the hood

- **The window** is QML (Kirigami). It talks to one Python `Backend` object (`backend.py`, with `updating.py` and
  `account.py` as parts of it).
- **No freezing:** anything that touches the network or disk runs on a worker thread. Results come back to the main
  thread through `_deliver`.
- **Page data** (releases, branches, comparisons) is kept in memory until the app closes; nothing is cached on disk
  except release lists (for ETags) and icons.
- **The settings file** is `~/.config/couriercollie/repos.toml`. It's written to a temporary file and renamed, so a
  crash can't leave it half-written. A file that can't be read is never overwritten.
- **One copy at a time:** a second launch, or the background check, talks to the open app through a local socket.
