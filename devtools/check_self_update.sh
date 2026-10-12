#!/bin/sh
# couriercollie updating itself, before a release exists: the packages are built twice, as they are (OLD) and as the
# next version (NEW, from a copy of the project with its version raised), and in a container per distro the OLD one
# is installed with the distro's package manager, then updates itself to NEW from a stand-in for GitHub
# (devtools/github_standin.py) serving the real NEW packages. devtools/self_update_inner.py runs inside. Nothing is
# asked of GitHub, nothing is installed on this computer, and the containers are removed.
#
#     devtools/check_self_update.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
old=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
new=$(echo "$old" | awk -F. '{print $1"."$2"."$3+1}')
distros=${*:-fedora opensuse ubuntu debian arch}
builds=$(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u)

echo "building $old and $new"
devtools/build_package.sh $builds >/dev/null
mkdir -p "$work/releases/v$old" "$work/releases/v$new"
cp dist/*"$old"* dist/SHA256SUMS "$work/releases/v$old/"
# The next version: a copy of the project as committed here, its version raised.
git clone -q . "$work/next"
sed -i "s/^__version__ = .*/__version__ = \"$new\"/" "$work/next/couriercollie/__init__.py"
git -C "$work/next" -c user.name=t -c user.email=t@t commit -qam "$new"
"$work/next/devtools/build_package.sh" $builds >/dev/null
cp "$work/next/dist/"*"$new"* "$work/next/dist/SHA256SUMS" "$work/releases/v$new/"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # for devtools/ inside (the app itself is the installed package)
chmod -R a+rX "$work"

run() {  # distro, image, install command for the OLD package
    podman run --rm -v "$work:/work:z" -e GITHUB_RELAY=http://127.0.0.1:18771 "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /app && tar -xf /work/app.tar -C /app
        export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null
        mkdir -p /tmp/rt && chmod 700 /tmp/rt
        python3 /app/devtools/github_standin.py /work/releases 18771 >/tmp/standin.log 2>&1 &
        sleep 1
        cd /root && python3 /app/devtools/self_update_inner.py $1 $old $new" > "$work/$1.log" 2>&1 \
        || echo "exit $?" >> "$work/$1.log"
}
# Side by side: shared (:z) rather than private (:Z) labels on /work, or each container would lock the others out.

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/releases/v$old/couriercollie-$old-1.fc*.noarch.rpm" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/releases/v$old/couriercollie-$old-1.noarch.rpm" & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 "$apt /work/releases/v${old}/couriercollie_${old}_all.deb" & ;;
        debian) run debian docker.io/library/debian:13 "$apt /work/releases/v${old}/couriercollie_${old}_all.deb" & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/releases/v$old/couriercollie-$old-1-any.pkg.tar.zst" & ;;
    esac
    pids="${pids:-} $!"
done
wait $pids
for distro in $distros; do
    echo "=== $distro"
    cat "$work/$distro.log"
done
