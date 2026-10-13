# Roadmap

## Before the first release

- **Publish:** a public repository and a release with the four packages and their `SHA256SUMS`
  (`devtools/build_package.sh`). Later, the AUR.

## Later

- A `collie` command: check and update from the terminal, with the same list.
- Any git host by git alone (sourcehut, Bitbucket, self-hosted): new commits and tags, without a site's API.
- Codeberg and other Gitea sites.
- Private repositories.

## Ideas to review

- **Picking among several Linux builds for you.** When a release has several files that run here (glibc and musl,
  an AppImage and a package), you're asked to choose. couriercollie could pick by a fixed order instead: your
  distro's package, then an AppImage, then an archive.
