# Log

Newest first.

## 2026-10-10

- Decided: D2 (GitHub + GitLab, with a filter in the list), D3 (build files and branches; no repo groups),
  D4 (three update modes: a global setting asked on first launch, plus per-repo overrides), D9 (local git repo).
- Project folder created. Wrote README, DESIGN and DECISIONS.
- Scanned the machine to ground the design: 11 git clones (10 AeroThemePlasma repos on gitgud.io, plus
  `ultrakanban` on GitHub). No AppImages, and no RPMs installed from GitHub downloads (the only file-installed RPMs
  are NVIDIA and RPM Fusion, which already update through dnf). Python 3.14, PySide6 and Kirigami are installed.
- Goal agreed: "Obtainium for Fedora KDE": scan for or hand-add repos, list releases and build files, check on an
  interval, update from a GUI.
