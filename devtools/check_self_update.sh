#!/bin/sh
# couriercollie updating itself, before a release exists, on each distro, in containers side by side: its packages
# are built three times (as they are, OLD, and as the next two versions, MID and NEW, from copies of the project with
# the version raised), OLD is installed with the distro's package manager, and it updates itself from a stand-in for
# GitHub (devtools/github_standin.py) serving the real packages (devtools/self_update_inner.py), then restarts. Then
# what can go wrong, and another project's real packages (skate's) updated alongside
# (devtools/self_update_scenarios.py). Nothing is installed on this computer; the containers are removed.
#
#     devtools/check_self_update.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
old=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
bump() { echo "$old" | awk -F. -v n="$1" '{print $1"."$2"."$3+n}'; }
mid=$(bump 1)
new=$(bump 2)
distros=${*:-fedora opensuse ubuntu debian arch}
builds=$(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u)
me="$work/releases/FalloutSeeker__couriercollie"

echo "building $old, $mid and $new"
devtools/build_package.sh $builds >/dev/null
mkdir -p "$me/v$old"
cp dist/*"$old"* dist/SHA256SUMS "$me/v$old/"
for version in "$mid" "$new"; do  # a copy of the project as committed here, its version raised
    git clone -q . "$work/$version"
    sed -i "s/^__version__ = .*/__version__ = \"$version\"/" "$work/$version/couriercollie/__init__.py"
    git -C "$work/$version" -c user.name=t -c user.email=t@t commit -qam "$version"
    "$work/$version/devtools/build_package.sh" $builds >/dev/null
    mkdir -p "$me/v$version"
    cp "$work/$version/dist/"*"$version"* "$work/$version/dist/SHA256SUMS" "$me/v$version/"
done
# Another project's real packages, from GitHub: skate, which none of the distros offers.
for tag in v1.0.1 v1.1.0; do
    mkdir -p "$work/releases/charmbracelet__skate/$tag"
    gh release download -R charmbracelet/skate "$tag" -D "$work/releases/charmbracelet__skate/$tag" \
        -p '*x86_64.rpm' -p '*amd64.deb'
done
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # for devtools/ inside (the app itself is the installed package)
chmod -R a+rX "$work"

run() {  # distro, image, install command for the OLD package
    podman run --rm -v "$work:/work:z" -e GITHUB_RELAY=http://127.0.0.1:18771 "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /app /tmp/releases && tar -xf /work/app.tar -C /app && cp -r /work/releases/. /tmp/releases/
        export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null
        mkdir -p /tmp/rt && chmod 700 /tmp/rt
        python3 /app/devtools/github_standin.py /tmp/releases 18771 >/tmp/standin.log 2>&1 &
        sleep 1
        cd /root
        python3 /app/devtools/self_update_inner.py $1 $old $new
        python3 /app/devtools/self_update_scenarios.py $1 $old $mid $new" > "$work/$1.log" 2>&1 \
        || echo "exit $?" >> "$work/$1.log"
}
# Side by side: shared (:z) rather than private (:Z) labels on /work, or each container would lock the others out.

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/releases/FalloutSeeker__couriercollie/v$old/couriercollie-$old-1.fc*.noarch.rpm" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/releases/FalloutSeeker__couriercollie/v$old/couriercollie-$old-1.noarch.rpm" & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 "$apt /work/releases/FalloutSeeker__couriercollie/v${old}/couriercollie_${old}_all.deb" & ;;
        debian) run debian docker.io/library/debian:13 "$apt /work/releases/FalloutSeeker__couriercollie/v${old}/couriercollie_${old}_all.deb" & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/releases/FalloutSeeker__couriercollie/v$old/couriercollie-$old-1-any.pkg.tar.zst" & ;;
    esac
    pids="${pids:-} $!"
done
wait $pids
for distro in $distros; do
    echo "=== $distro"
    cat "$work/$distro.log"
done
