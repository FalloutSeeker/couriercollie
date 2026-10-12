#!/bin/sh
# Many real projects, installed at their previous release and updated to the newest, on each distro, in containers
# side by side (devtools/repos_inner.py, with couriercollie's package installed). Fedora and Ubuntu get the full set;
# the others a core set. GitHub is asked through devtools/github_relay.py, with your gh login, which stays here.
# Downloads about 400 MB a distro for the full set. Nothing is installed on this computer; the containers are removed.
#
#     devtools/check_repos.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18767
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
# The projects devtools/repos_inner.py asks GitHub about: the relay passes on nothing else.
grep -oE "github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" devtools/repos_inner.py | sed 's|github.com/||' | sort -u \
    > "$work/allow"
echo "vercel/hyper" >> "$work/allow"  # where zeit/hyper went
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
distros=${*:-fedora opensuse ubuntu debian arch}
devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
cp dist/* "$work/"
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')

run() {  # distro, image, install command, set
    podman run --rm --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port -v "$work:/work:z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /app && tar -xf /work/app.tar -C /app
        export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null
        mkdir -p /tmp/rt && chmod 700 /tmp/rt
        cd /root && python3 /app/devtools/repos_inner.py $1 $4" > "$work/$1.log" 2>&1 || echo "exit $?" >> "$work/$1.log"
}
# Side by side: shared (:z) rather than private (:Z) labels on /work, or each container would lock the others out.

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm git curl" all & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git curl" \
            core & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates" all & ;;
        debian) run debian docker.io/library/debian:13 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates" core & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed git curl" \
            core & ;;
    esac
    pids="${pids:-} $!"
done
wait $pids  # (not the relay)
for distro in $distros; do
    echo "=== $distro"
    grep -vE "^PASS" "$work/$distro.log"
    echo "($(grep -c "^PASS" "$work/$distro.log") passed)"
done
grep -h "refused" "$work/relay.log" || true
