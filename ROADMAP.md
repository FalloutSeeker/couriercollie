# Roadmap

## Before the first release

- **Publish:** a public repository, with a release carrying the four packages (`devtools/build_package.sh` builds
  and tries them), and the Arch package on the AUR. Needs a release tag, the AUR's checksum for it, and a license.
- **Choose a license.**
- **Send Feedback…** at the bottom of Settings: opens a pre-filled GitHub issue in the browser. It includes app
  version, distro, desktop and Qt/Kirigami versions, and your tracked list only if you tick it. Nothing is sent by
  the app itself.

## Still to check by hand

- **GNOME:** does the window follow GNOME's dark mode? Needs a real GNOME session.
- **The RPM on a real desktop:** install it once and see it in the app menu. Tested so far only in a container.

## Later

- Any git host by git alone (sourcehut, Bitbucket, self-hosted): new commits and tags, without a site's API.
- Codeberg and other Gitea sites.
- Private repositories.
