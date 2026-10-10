# RepoProject

**Working name.** Something like Obtainium, but for Fedora KDE: a desktop app that keeps track of software you got
straight from GitHub or GitLab (git clones, release downloads, AppImages, loose programs), checks for new versions on a
schedule, and lets you update with a click.

## Status

**Stages 1 and 2 of PLAN.md are built.** You can add GitHub/GitLab repos, browse their releases, build files and
branches, and pick what to follow. The first-launch questions and the Settings page work and save your answers, but
scanning, update checks and cleanup aren't built yet, so those settings have no effect for now.

## Running it

```sh
~/claudework/RepoProject/run.sh
```

Needs only what Fedora KDE already has: Python 3, PySide6 (`python3-pyside6`) and Kirigami. Your tracked repos are
saved in `~/.config/repoproject/repos.toml`.

## Tests

```sh
cd ~/claudework/RepoProject && python3 -m unittest discover -s tests -t .
```

They don't use the network: GitHub and GitLab answers are saved in `tests/fixtures/`.

## Code layout

| File                       | What it does                                                                   |
| -------------------------- | ------------------------------------------------------------------------------ |
| `repoproject/config.py`    | The settings file: global settings and tracked repos                           |
| `repoproject/sources.py`   | Talking to GitHub and GitLab: addresses, releases, branches                    |
| `repoproject/assets.py`    | Build files: which kind, whether it suits this PC, remembering your pick       |
| `repoproject/backend.py`   | Connects the window to the above; runs network work in the background          |
| `repoproject/qml/`         | The window: list page, repo page, Add dialog                                   |

## Files

| File                         | What's in it                                                      |
| ---------------------------- | ----------------------------------------------------------------- |
| [DESIGN.md](DESIGN.md)       | What the app does: features, screens, and how it works underneath |
| [DECISIONS.md](DECISIONS.md) | The choices made, and why                                         |
| [PLAN.md](PLAN.md)           | The build order, in stages                                        |
| [LOG.md](LOG.md)             | Dated notes on what we decided and did, newest first              |

## Background

- Started 2026-10-10 from a conversation about tracking GitHub updates on Fedora.
- First idea was a "custom dnf": a local package repo filled from GitHub releases, so plain `dnf upgrade` sees them.
  That idea still lives on as one way to install RPM updates (see DECISIONS.md, D4), but the main product is now a GUI.
