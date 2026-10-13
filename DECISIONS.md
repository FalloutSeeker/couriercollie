# Decisions

The choices behind couriercollie, and why. Numbered so the code can point to them (e.g. `DECISIONS.md, D6`).

## D1. Built with Python, PySide6 and Kirigami

- Looks and behaves like other KDE apps (Discover, System Settings).
- Python is easy to read and change; on Fedora KDE everything it needs is already installed.

## D2. GitHub and GitLab

- GitHub, plus any GitLab site, including self-hosted ones (e.g. gitgud.io).
- Other hosts (Codeberg, sourcehut, etc.) are told apart and refused with a clear message, not a confusing error.

## D3. A release's file, or a branch

- **Releases:** a release often ships several files (AppImage, `.rpm`, ARM and Intel builds). You pick one; the same
  file is followed in every later release.
- **Branches:** for projects without releases, you pick a branch and follow its new commits.

## D4. Nothing installs on its own

- Updates only happen when you click Update, so no password prompt appears that you didn't ask for.
- After a clone is pulled, only what you approved runs (its install script, or a rebuild), never typed in. If it
  changes, it waits until you've read it again. Running containers are rebuilt without asking.

## D5. One check schedule, quiet notifications

- One global setting: automatic checks (daily, weekly, every two weeks or monthly) or none.
  - **Why:** one pass over everything is simpler and lighter than a timer per repo.
- A systemd user timer starts a short check and exits. Nothing stays running in between.
- A notification only for updates not announced before, and only when the window isn't in front (KDE HIG).

## D6. Safety

- Nothing runs as root without your click and your password.
- Downloads are checked against the project's published checksum; you're told when there isn't one.
- The old version stays until the new one is in place, so a failed update leaves a working copy.
- What runs as root is named by full path, works on a copy only root can change, and never runs a clone's hooks.
- What your package manager or Flatpak installed is never updated here, only shown: two updaters would fight over
  the same files.

## D7. Staying within GitHub's limits

GitHub allows 60 requests an hour without signing in, 5,000 with. There's no server: each copy has its own allowance.

- **Branches via `git ls-remote`:** not counted at all.
- **One small request per release repo per check** (the newest 5 releases).
- **ETags:** an unchanged release list costs nothing when signed in.
- **Stop when told:** after "limit reached", the remaining GitHub repos wait for the next check.
- **Optional, read-only sign-in,** kept in the desktop's password store. Not the GitHub CLI's login (it can usually
  change your repositories), and no built-in token (anyone could pull it out of the app).

## D8. Where installed things go

| What | Where |
| --- | --- |
| AppImages | `~/Applications`, with a menu entry |
| Programs from release archives | `~/.local/share/couriercollie/programs`, with a link in `~/.local/bin` |
| Packages (`.rpm`, `.deb`, Arch) | The package manager |
| Flatpak bundles | Flatpak, for you only |
| Projects cloned by Install | `~/src` |

Nothing goes into system folders except through the package manager.

## D9. Hosted on GitHub

github.com/FalloutSeeker/couriercollie.

## D10. Name

**couriercollie**, all lowercase everywhere: window, menu, command, package, repository and folders. Environment
variables are upper case as usual (`COURIERCOLLIE_CONFIG`, etc.).

## D11. Old versions aren't kept

An update removes the version it replaced once the new one is in place (D6). Nothing piles up, so there's no cleanup
setting. A clone's history is its own and isn't touched.

## D12. Scanning is off until you turn it on

- **Why off:** it looks through your files.
- **Default folders:** home, `/opt`, `/usr/local` and `/srv`, where software installed by hand lives. The rest of the
  system belongs to the package manager.
- **No duplicates:** a find matching a tracked repo (by address, or an old one) updates it instead.
- **New finds start ticked:** tracking them is one click. Finds that look like a tracked repo are left unticked.

## D13. Repo icons

Each repo shows its own picture, or its first letter on a colour of its own.

- **Only pictures that are certainly the project's:** the installed app's icon, a GitLab project's icon, or a GitHub
  organization's picture (never a person's). Guesses sometimes picked the wrong picture.
- **Looked up once and saved.** PNG, JPEG or WebP, at most 1 MB; SVG only from an app on this computer.

## D14. Categories

- Your own headings for the list (e.g. "Themes", "Tools"). Drag repos and categories by their handles.
- Rename or delete from a heading's ⋮ menu. Deleting a category moves its repos to Uncategorized.

## D15. License: GPL-3.0-or-later

- Free software: anyone may use, study, change and share it, and shared changes stay open. The norm for KDE apps.
- Its parts allow it: PySide6, Qt and Kirigami are LGPL; the bundled Breeze icons are LGPL-3.0-or-later.
