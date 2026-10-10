# RepoProject

**Working name.** Something like Obtainium, but for Fedora KDE: a desktop app that keeps track of software you got
straight from GitHub or GitLab (git clones, release downloads, AppImages, loose programs), checks for new versions on a
schedule, and lets you update with a click.

## Status

**Design phase.** No code yet. We're agreeing on what it does before building it.

## Files

| File                             | What's in it                                                          |
| -------------------------------- | --------------------------------------------------------------------- |
| [DESIGN.md](DESIGN.md)           | What the app does: features, screens, and how it works underneath     |
| [DECISIONS.md](DECISIONS.md)     | Choices to settle before building, each with a recommendation        |
| [LOG.md](LOG.md)                 | Dated notes on what we decided and did, newest first                  |

## Background

- Started 2026-10-10 from a conversation about tracking GitHub updates on Fedora.
- First idea was a "custom dnf": a local package repo filled from GitHub releases, so plain `dnf upgrade` sees them.
  That idea still lives on as one way to install RPM updates (see DECISIONS.md, D4), but the main product is now a GUI.
