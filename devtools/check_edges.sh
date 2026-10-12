#!/bin/sh
# Edge cases, for real, in a container with couriercollie's package installed (devtools/edges_inner.py): the network
# dropping partway through a download, a full disk, the app killed partway through an update, two copies started, a
# broken settings file. The container may cut its own network (NET_ADMIN), and its ~/Applications is a 40 MB disk.
# GitHub is asked through devtools/github_relay.py, with your gh login, which stays here.
#
#     devtools/check_edges.sh [fedora|ubuntu]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18768
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
echo "neovim/neovim" > "$work/allow"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
distro=${1:-fedora}
devtools/build_package.sh "$(echo "$distro" | sed 's/^ubuntu$/debian/')" >/dev/null
cp dist/* "$work/"
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
case $distro in
    fedora) image=registry.fedoraproject.org/fedora:44
            install="dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm iproute iproute-tc procps-ng" ;;
    ubuntu) image=docker.io/library/ubuntu:26.04
            install="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /work/couriercollie_${version}_all.deb iproute2 ca-certificates" ;;
esac
podman run --rm --cap-add NET_ADMIN --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port \
    --mount type=tmpfs,destination=/root/Applications,tmpfs-size=40m -v "$work:/work:Z" "$image" sh -c "
    ($install) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
    mkdir -p /app && tar -xf /work/app.tar -C /app
    export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null QT_QPA_PLATFORM=offscreen
    mkdir -p /tmp/rt && chmod 700 /tmp/rt
    cd /root && python3 /app/devtools/edges_inner.py"
