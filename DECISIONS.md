# Decisions to settle

Each one has a recommendation. **Status** is `open` until you pick, then `decided` with the date.

---

## D1. What to build it with

**Recommendation:** Python + PySide6 (Qt) + Kirigami (KDE's interface toolkit).

- Looks and behaves like other KDE apps (Discover, System Settings).
- Python is the easiest of the options to read and change later.
- Both `python3-pyside6` and `kf6-kirigami` are already installed here.

Alternative: C++ with Qt. More native, much harder to work on. Not worth it here.

**Status:** open

## D2. Which sites to support

**Recommendation:** GitHub and GitLab (which includes gitgud.io) in the first version. Codeberg/Gitea later.

Your AeroThemePlasma repos are on gitgud.io, so GitHub alone would miss most of what you'd actually track.

**Status:** decided 2026-10-10. GitHub + GitLab, **plus a filter in the main list** to show All / GitHub / GitLab.

## D3. What "multiple versions" in a repo means

Your note: *"If the repo has multiple repositories (i.e. different build versions), list them when clicking into the
repo."* This could mean any of:

- **a) Build files**: one release ships several files (RPM, AppImage, ARM, Intel…). You pick one to follow.
- **b) Branches**: e.g. AeroThemePlasma has `Plasma/6.7` and `master`. You pick which to follow.
- **c) Related repos**: one project made of several repos (AeroThemePlasma + its 8 `repos/` sub-projects), shown
  together as a group.

**Recommendation:** a) and b) in the first version (both are in DESIGN.md). c) as a later "group" feature.

**Status:** decided 2026-10-10. **a) build files and b) branches.** c) isn't planned.

## D4. How updates get installed

**Recommendation for the first version:**

- **Notify, and update when you click.** Nothing installs on its own.
- RPMs install with `dnf install ./file.rpm`, which asks for your password.
- Git clones only pull. Re-running a project's install script (AeroThemePlasma has one) is a separate button, and the
  app shows you what it will run first.

Later option: the "custom dnf" idea, a local package repo the app fills, so `dnf upgrade` / Discover pick these up too.
More moving parts (signing keys, repo metadata), so not first.

**Status:** decided 2026-10-10. There are three **update modes**, chosen by the user:

| Mode                  | What happens when a new version is found                          |
| --------------------- | ----------------------------------------------------------------- |
| **Auto-update**       | Downloads and installs it                                         |
| **Notify + click**    | Sends a notification; installs when you click Update              |
| **Notify only**       | Sends a notification and links the page; you update by hand       |

- **Global setting**, asked on first launch, then changeable in Settings. The first-launch screen says so.
- **Per-repo override**: each repo can use the global setting (the default) or its own mode.
- The rest of the recommendation still applies in every mode: RPM installs ask for your password (so auto-update of an
  RPM shows a password prompt when it's ready, rather than installing silently). Git clones only pull, and a
  project's install script never runs automatically.

## D5. Background checking

**Recommendation:** a systemd user timer runs the checker, so checks happen with the window closed, plus a KDE
notification when something's new. Optional tray icon later.

**Status:** open

## D6. Safety rules

**Recommendation (these become fixed rules):**

- Never run anything as root without you clicking and entering your password.
- Verify downloads against the checksum file when the project publishes one; warn when it doesn't.
- Keep the previous version until the new one is installed, so an update can be undone.
- Never run a project's own install script automatically.

**Status:** open

## D7. GitHub request limit

GitHub allows 60 checks an hour without logging in. Tracking 20 repos every hour would hit that.

**Recommendation:** reuse the GitHub login that's already on this machine (`gh`, logged in as FalloutSeeker), which
raises the limit to 5,000 an hour. Fall back to the low limit if it's not available.

**Status:** open

## D8. Where downloaded apps go

**Recommendation:** AppImages in `~/Applications`, loose programs in `~/.local/bin`, with a menu entry created for
AppImages so they show up in the KDE launcher. Nothing in system folders except via dnf.

**Status:** open

## D9. Keeping this project in git

**Recommendation:** make `RepoProject` a git repo now (and later push it to a private GitHub repo), so every design
change and code change is saved and can be undone.

**Status:** decided 2026-10-10. Local git repo only, no GitHub for now.

## D10. Name

"RepoProject" is the working name. Pick a real one whenever. It only matters once it has an app icon and menu entry.

**Status:** open
