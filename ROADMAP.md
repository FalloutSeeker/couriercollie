# Roadmap

## Before the first release

- **Publish:** a public repository, with a release carrying the four packages (`devtools/build_package.sh` builds
  and tries them), and the Arch package on the AUR. Needs a release tag, the AUR's checksum for it, and a license.
- **Choose a license.**
- **Track couriercollie itself** from the first launch, once. If you stop tracking it, it doesn't come back.
- **Send Feedback…** at the bottom of Settings: opens a pre-filled GitHub issue in the browser. It includes app
  version, distro, desktop and Qt/Kirigami versions, and your tracked list only if you tick it. Nothing is sent by
  the app itself.
- **Start at login** (off by default). Not needed for automatic checks, which run without the app open.
- **Tray icon** with the number of updates, and Open / Check Now / Quit. Closing the window still quits unless "Keep
  running in the tray" is on. On GNOME it needs the AppIndicator extension.
- **Restore to Defaults** in Settings: settings back to a fresh start; tracked repos and categories kept. Asks first.

## Still to check by hand

- **GNOME:** does the window follow GNOME's dark mode? Needs a real GNOME session.
- **The RPM on a real desktop:** install it once and see it in the app menu. Tested so far only in a container.

## Later

- Any git host by git alone (sourcehut, Bitbucket, self-hosted): new commits and tags, without a site's API.
- Codeberg and other Gitea sites.
- Private repositories.
- A `.deb` of couriercollie itself.
