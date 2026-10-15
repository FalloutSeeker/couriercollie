# Changelog

## 0.6.2 (beta), 2026-10-15

- **Dragging** a repo or category past the top or bottom of the list now scrolls the list and keeps the row under
  your pointer. Before, the row could get lost.
- **Fedora and openSUSE packages** now refuse to install on a release with a different Python, instead of installing
  an app that doesn't start. The README lists the oldest release each install works on.

## 0.6.0 (beta), 2026-10-14

The first version.

- **Track** software from GitHub and GitLab: add a project by its address, or scan your computer for clones,
  AppImages, packages installed from a file and Flatpak bundles.
- **Check** for new releases or commits, by hand or on a schedule, with notifications and a count on the taskbar and
  tray.
- **Update with one click:** AppImages and programs are swapped in, packages go through your package manager, git
  clones are pulled and their install script (shown to you first) runs.
- **Safe by default:** downloads are checked against published checksums, and anything your package manager or
  Flathub installed is only shown, never updated here.
- **Categories,** start at login, a tray icon, optional read-only GitHub sign-in, and Send Feedback.
- **Packages** for Fedora, openSUSE, Ubuntu/Debian and Arch. couriercollie keeps itself up to date too.
