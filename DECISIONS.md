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

- Updates only happen when you click Update. So the app never shows a password prompt you didn't ask for.
- A clone is pulled. After that, only a step you approved runs (rebuilding its containers, its install script, or a
  command of yours), and only as approved: if what it runs changes, it waits. A README's steps are quoted, never
  followed.

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

GitHub allows 60 requests an hour without signing in, 5,000 with. Each person's copy has its own allowance; there's
no server.

- **Branches via `git ls-remote`:** not counted against the limit at all.
- **One small request per release repo per check** (the newest 5 releases, not all of them).
- **"Has it changed?" requests (ETags):** an unchanged answer has nothing to download, and costs nothing when signed
  in.
- **Stop when told:** after a "limit reached" answer, the remaining GitHub repos wait for the next check.
- **Optional sign-in** with a code at github.com/login/device. It asks for no access, so it can only read public
  information. Kept in the desktop's password store, never in the settings file.
  - **Not the GitHub CLI's login:** `gh` logins can usually change your repositories, more than a read-only app
    should hold.
  - **No built-in token:** anyone could pull it out of the app.

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
- **Default folders:** your home folder, `/opt`, `/usr/local` and `/srv`. These are where software installed by hand
  lives. The rest of the system belongs to the package manager, so it's slow to search and has nothing to find.
- **No duplicates:** a find that matches a tracked repo (by address, or an old address it was renamed from) updates
  that entry instead of adding another.
- New finds start ticked, so tracking them is one click; untick what you don't want. Finds that look like a repo you
  already track are left unticked.

## D13. Repo icons

Every repo shows either its own picture or a monogram: its first letter on a colour of its own, the same every time.

- **Only pictures that are certainly the project's:** the installed app's own icon (its package's menu entry, its
  AppImage's icon, its Flatpak's), or the project's picture on its site (a GitLab project's icon or group picture; a
  GitHub organization's picture, never a person's).
  - **Why:** guesses (an installed app with a similar name, a logo found in a clone) sometimes picked the wrong
    picture, and icons by kind of repo looked different on every icon theme.
- **Looked up once and saved.** Downloads: PNG, JPEG or WebP only, at most 1 MB. SVG only from an app on this
  computer, never from a site.

## D14. Categories

- Your own headings for the list (e.g. "Themes", "Tools"). Drag repos and categories by their handles, or choose a
  repo's category on its page (from the keyboard too).
- Rename or delete from a heading's ⋮ menu. Deleting a category never removes its repos; they move to Uncategorized.

## D15. License: GPL-3.0-or-later

- couriercollie is free software: anyone may use, study, change and share it, and changed versions they share stay
  open, under the same license. The norm for KDE apps.
- Its parts allow it: PySide6, Qt and Kirigami are LGPL; the Breeze icons it brings along are LGPL-3.0-or-later
  (`couriercollie/icons/COPYING-ICONS`).
