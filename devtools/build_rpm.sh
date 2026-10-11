#!/bin/sh
# Build RepoProject's RPM from the last commit (not uncommitted changes), into dist/. Builds in a temporary folder;
# nothing is installed. Install the result with: sudo dnf install dist/repoproject-*.noarch.rpm
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import repoproject; print(repoproject.__version__)')
top=$(mktemp -d)
trap 'rm -rf "$top"' EXIT
mkdir -p "$top/SOURCES" dist
git archive --format=tar.gz --prefix="repoproject-$version/" -o "$top/SOURCES/repoproject-$version.tar.gz" HEAD
rpmbuild -bb --quiet --define "_topdir $top" --define "app_version $version" packaging/repoproject.spec
cp "$top"/RPMS/noarch/*.rpm dist/
ls dist/repoproject-"$version"-*.noarch.rpm
