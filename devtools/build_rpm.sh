#!/bin/sh
# Build colliecourier's RPM from the last commit (not uncommitted changes), into dist/. Builds in a temporary folder;
# nothing is installed. Install the result with: sudo dnf install dist/colliecourier-*.noarch.rpm
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import colliecourier; print(colliecourier.__version__)')
top=$(mktemp -d)
trap 'rm -rf "$top"' EXIT
mkdir -p "$top/SOURCES" dist
git archive --format=tar.gz --prefix="colliecourier-$version/" -o "$top/SOURCES/colliecourier-$version.tar.gz" HEAD
rpmbuild -bb --quiet --define "_topdir $top" --define "app_version $version" packaging/colliecourier.spec
cp "$top"/RPMS/noarch/*.rpm dist/
ls dist/colliecourier-"$version"-*.noarch.rpm
