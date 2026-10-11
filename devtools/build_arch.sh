#!/bin/sh
# Build colliecourier's Arch package from the last commit, in an Arch container: makepkg with packaging/arch/PKGBUILD,
# then install it with pacman and start the app (off-screen) to see that it runs. The package goes to dist/.
# Nothing is installed on this computer.
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import colliecourier; print(colliecourier.__version__)')
work=$(mktemp -d)
# Files made in the container belong to its users: removed from inside podman's user namespace.
trap 'podman unshare rm -rf "$work"' EXIT
cp packaging/arch/PKGBUILD "$work/"
# Where makepkg would download the release from: the same snapshot, already here.
git archive --format=tar.gz --prefix="colliecourier-$version/" -o "$work/colliecourier-$version.tar.gz" HEAD
mkdir -p dist
podman run --rm -v "$work:/build:Z" -v "$PWD/dist:/dist:Z" docker.io/library/archlinux:latest bash -c '
set -e
pacman -Sy --noconfirm --needed base-devel >/dev/null 2>&1
useradd -m builder && chown -R builder /build
su builder -c "cd /build && makepkg --nodeps --noconfirm" >/build/makepkg.log 2>&1 || { tail -20 /build/makepkg.log; exit 1; }
cp /build/*.pkg.tar.zst /dist/
pacman -U --noconfirm /build/*.pkg.tar.zst >/build/pacman.log 2>&1 || { tail -20 /build/pacman.log; exit 1; }
echo "installed: $(pacman -Q colliecourier)"
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/rt QT_FORCE_STDERR_LOGGING=1
mkdir -p -m 700 /tmp/rt
code=0; timeout 8 colliecourier >/tmp/app.log 2>&1 || code=$?
echo "app: $( [ $code = 124 ] && echo "started, still running when stopped" || echo "exited with $code")"
grep -v "^$" /tmp/app.log | head -10
'
ls dist/colliecourier-"$version"-*.pkg.tar.zst
