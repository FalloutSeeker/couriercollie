#!/bin/sh
# Build couriercollie's package for a distro from the last commit, in that distro's container, then install it there
# with its own package manager (which proves the dependencies are right) and start the app off-screen to see that it
# runs. The packages go to dist/. Nothing is installed on this computer.
#
#     devtools/build_package.sh [fedora|opensuse|debian|arch …]     (all four if none is named)
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
work=$(mktemp -d)
# Files made in a container belong to its users: removed from inside podman's user namespace.
trap 'podman unshare rm -rf "$work"' EXIT
git archive --format=tar.gz --prefix="couriercollie-$version/" -o "$work/couriercollie-$version.tar.gz" HEAD
cp packaging/couriercollie.spec packaging/arch/PKGBUILD packaging/debian/control "$work/"
# The Arch package's version is written in its PKGBUILD: kept in step with the app's, so a release can't forget it.
sed -i "s/^pkgver=.*/pkgver=$version/" "$work/PKGBUILD"
mkdir -p dist

# After installing: start the app off-screen for a few seconds, and show anything it complained about.
smoke_test='
export QT_QPA_PLATFORM=offscreen QT_FORCE_STDERR_LOGGING=1 XDG_RUNTIME_DIR=/tmp/rt
mkdir -p -m 700 /tmp/rt
code=0; timeout 8 couriercollie >/tmp/app.log 2>&1 || code=$?
if [ $code = 124 ]; then echo "app: started, still running when stopped"; else echo "app: exited with $code"; fi
grep -i -E "error|not installed|cannot|failed" /tmp/app.log | head -10 || true'

rpm_build='
rpmbuild -bb --quiet --define "_topdir /tmp/rpm" --define "_sourcedir /work" --define "app_version '"$version"'" \
    /work/couriercollie.spec >/tmp/build.log 2>&1 || { tail -20 /tmp/build.log; exit 1; }
cp /tmp/rpm/RPMS/noarch/*.rpm /dist/'

deb_build='
root=/tmp/deb/couriercollie
mkdir -p $root/DEBIAN $root/usr/lib/python3/dist-packages /tmp/src
tar -xzf /work/couriercollie-'"$version"'.tar.gz -C /tmp/src && cd /tmp/src/couriercollie-'"$version"'
cp -a couriercollie $root/usr/lib/python3/dist-packages/
install -Dm755 data/couriercollie $root/usr/bin/couriercollie
install -Dm644 data/couriercollie.desktop $root/usr/share/applications/couriercollie.desktop
install -Dm644 data/couriercollie.svg $root/usr/share/icons/hicolor/scalable/apps/couriercollie.svg
install -Dm644 README.md $root/usr/share/doc/couriercollie/README.md
# Debian keeps a package'\''s license in its doc folder, as "copyright".
{ printf "couriercollie: GPL-3.0-or-later. Its Breeze icons (couriercollie/icons): LGPL-3.0-or-later.\n\n"; cat LICENSE; } \
    > $root/usr/share/doc/couriercollie/copyright
sed "s/@VERSION@/'"$version"'/" /work/control > $root/DEBIAN/control
dpkg-deb --build --root-owner-group $root /dist/couriercollie_'"$version"'_all.deb >/dev/null'

arch_build='
useradd -m builder && cp /work/PKGBUILD /work/couriercollie-'"$version"'.tar.gz /home/builder/
chown -R builder /home/builder
su builder -c "cd ~ && makepkg --nodeps --noconfirm" >/tmp/build.log 2>&1 || { tail -20 /tmp/build.log; exit 1; }
cp /home/builder/*.pkg.tar.zst /dist/'

run() {  # name, image, prepare, build, install
    echo "=== $1"
    podman run --rm -v "$work:/work:Z" -v "$PWD/dist:/dist:Z" "$2" sh -c "
        set -e
        $3 >/tmp/prepare.log 2>&1 || { tail -20 /tmp/prepare.log; exit 1; }
        $4
        $5 >/tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }
        echo \"installed: \$(command -v couriercollie)\"
        $smoke_test"
}

for distro in ${*:-fedora opensuse debian arch}; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q rpm-build desktop-file-utils python3" "$rpm_build" \
            "dnf install -y /dist/couriercollie-$version-1.fc*.noarch.rpm" ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install rpm-build desktop-file-utils python3" "$rpm_build" \
            "zypper --non-interactive install --allow-unsigned-rpm /dist/couriercollie-$version-1.noarch.rpm" ;;
        debian) run debian docker.io/library/ubuntu:26.04 \
            "apt-get update -qq" "$deb_build" \
            "DEBIAN_FRONTEND=noninteractive apt-get install -y /dist/couriercollie_${version}_all.deb" ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm --needed base-devel" "$arch_build" \
            "pacman -U --noconfirm /dist/couriercollie-$version-1-any.pkg.tar.zst" ;;
    esac
done
# For the release page, for anyone who downloads a package by hand. (couriercollie itself checks its own updates
# against the checksum GitHub publishes for every release file.)
(cd dist && sha256sum couriercollie[-_]"$version"[-_]* > SHA256SUMS)
ls dist/
