#!/bin/sh
# Installing, finding and updating a release's package with each distro's real package manager, in containers:
# dnf (Fedora), zypper (openSUSE), apt (Ubuntu) and pacman (Arch). A small test package is made in each, then
# devtools/distro_inner.py has the app install it. Nothing is installed on this computer.
#
#     devtools/check_distros.sh [fedora|opensuse|ubuntu|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here

# How each makes a v1.0 and a v2.0 of cc-test-tool, with a GitHub homepage, into /pkgs.
make_rpm='
for v in 1.0 2.0; do cat > /tmp/t.spec <<SPEC
Name: cc-test-tool
Version: $v
Release: 1
Summary: test
License: MIT
URL: https://github.com/example/tool
BuildArch: noarch
%description
test
%install
mkdir -p %{buildroot}/usr/share/doc/cc-test-tool && echo $v > %{buildroot}/usr/share/doc/cc-test-tool/VERSION
%files
/usr/share/doc/cc-test-tool/VERSION
SPEC
rpmbuild -bb --quiet --define "_rpmdir /pkgs" --define "_build_name_fmt %%{NAME}-%%{VERSION}.%%{ARCH}.rpm" /tmp/t.spec 2>/dev/null
done'
make_deb='
for v in 1.0 2.0; do rm -rf /tmp/p; mkdir -p /tmp/p/DEBIAN /tmp/p/usr/share/doc/cc-test-tool
echo $v > /tmp/p/usr/share/doc/cc-test-tool/VERSION
printf "Package: cc-test-tool\nVersion: $v-1\nArchitecture: all\nMaintainer: t <t@example.org>\nHomepage: https://github.com/example/tool\nDescription: test\n" > /tmp/p/DEBIAN/control
dpkg-deb --build /tmp/p /pkgs/cc-test-tool_$v-1_all.deb >/dev/null
done'
make_arch='
useradd -m builder; chown builder /pkgs
for v in 1.0 2.0; do mkdir -p /tmp/b$v; cat > /tmp/b$v/PKGBUILD <<PKG
pkgname=cc-test-tool
pkgver=$v
pkgrel=1
pkgdesc=test
arch=(any)
url=https://github.com/example/tool
license=(MIT)
package() { install -Dm644 /dev/null "\$pkgdir/usr/share/doc/cc-test-tool/VERSION"; }
PKG
chown -R builder /tmp/b$v; su builder -c "cd /tmp/b$v && PKGDEST=/pkgs makepkg --noconfirm >/dev/null 2>&1"
done'

run() {  # distro, image, setup, maker, kind
    echo "=== $1"
    podman run --rm -v "$work:/work:Z" "$2" sh -c "
        set -e
        $3 >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /pkgs /app && tar -xf /work/app.tar -C /app
        $4
        python3 /app/devtools/distro_inner.py $5 /pkgs"
}

for distro in ${*:-fedora opensuse ubuntu arch}; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 "dnf install -y -q rpm-build python3" "$make_rpm" rpm ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install rpm-build python3" "$make_rpm" rpm ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3" "$make_deb" deb ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm --needed base-devel python" "$make_arch" arch ;;
    esac
done
