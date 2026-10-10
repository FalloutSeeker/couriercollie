# Log

Newest first.

## 2026-10-10

- Designed the optional GitHub sign-in (DESIGN §8): it explains the 60 vs 5,000 an hour limit, gives a live "do you
  need this?" estimate, shows a friendly bar when the limit is hit, and asks for read-only, public-data access.
- Simplified notifications: dropped update modes (Notify + click / Notify only) and per-repo overrides. Updates are
  always a click on the ⬆ icon. Dropped per-repo check intervals (one global schedule, lighter on the system).
  First launch now asks one question: automatic checks on (with interval) or off. Toasts on by default when checks
  are on, can be turned off, leaving the taskbar badge and in-app icons.
- Decided D1, D6, D8, D10 as recommended. Wrote up D7 (how the app talks to GitHub/GitLab within their limits).
- Revised D4: auto-update dropped, so the app never prompts for a password unasked. Two modes remain (Notify + click,
  Notify only), with an in-app notice always and an optional toast.
- Decided D5: global check interval asked on first launch, including "Never (manual only)".
- Added and decided D11: delete old versions after a set time, skipping anything that needs admin rights.
- Added a first-launch setup screen to DESIGN (update mode, interval, toasts, then offer a scan).
- Decided: D2 (GitHub + GitLab, with a filter in the list), D3 (build files and branches; no repo groups),
  D4 (three update modes: a global setting asked on first launch, plus per-repo overrides), D9 (local git repo).
- Project folder created. Wrote README, DESIGN and DECISIONS.
- Scanned the machine to ground the design: 11 git clones (10 AeroThemePlasma repos on gitgud.io, plus
  `ultrakanban` on GitHub). No AppImages, and no RPMs installed from GitHub downloads (the only file-installed RPMs
  are NVIDIA and RPM Fusion, which already update through dnf). Python 3.14, PySide6 and Kirigami are installed.
- Goal agreed: "Obtainium for Fedora KDE": scan for or hand-add repos, list releases and build files, check on an
  interval, update from a GUI.
