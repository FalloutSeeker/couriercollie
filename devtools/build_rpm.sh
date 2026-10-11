#!/bin/sh
# Build couriercollie's RPM from the last commit (not uncommitted changes), into dist/. Builds in a temporary folder;
# nothing is installed. Install the result with: sudo dnf install dist/couriercollie-*.noarch.rpm
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
top=$(mktemp -d)
trap 'rm -rf "$top"' EXIT
mkdir -p "$top/SOURCES" dist
git archive --format=tar.gz --prefix="couriercollie-$version/" -o "$top/SOURCES/couriercollie-$version.tar.gz" HEAD
rpmbuild -bb --quiet --define "_topdir $top" --define "app_version $version" packaging/couriercollie.spec
cp "$top"/RPMS/noarch/*.rpm dist/
ls dist/couriercollie-"$version"-*.noarch.rpm
