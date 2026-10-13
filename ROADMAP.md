# Roadmap

## Before the first release

- **Publish:** a public repository, with a release carrying the four packages and their `SHA256SUMS`
  (`devtools/build_package.sh` builds and tries them), and the Arch package on the AUR. Needs a release tag, and the
  AUR's checksum for it.

## Later

- A `collie` command: check and update from the terminal, with the same list.

- Any git host by git alone (sourcehut, Bitbucket, self-hosted): new commits and tags, without a site's API.
- Codeberg and other Gitea sites.
- Private repositories.

## Ideas to review

- **Choosing among several Linux builds for you.** Many releases offer more than one file that runs here (glibc and
  musl builds, `.tar.gz` and `.zip`, an AppImage beside a `.deb` or `.rpm`), so you're asked to choose. couriercollie
  could pick one by a fixed order: your distro's package, then an AppImage, then an archive (glibc over musl). Seen
  with delta, eza, LocalSend and glab.
