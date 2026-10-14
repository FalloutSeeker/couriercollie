#!/bin/sh
# Rough handling (devtools/abuse_inner.py), in a container per distro with
# its package installed, through the real window (off-screen) and real projects: the settings file edited by hand,
# the results file broken, install folders deleted, Update clicked twice, Stop Tracking mid-update, a clone's .git
# deleted, a dangling program link, an AppImage in a folder with spaces. GitHub is asked through
# devtools/github_relay.py, with your gh login, which stays here.
#
#     devtools/check_abuse.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18774
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
printf "neovim/neovim\njesseduffield/lazygit\ncharmbracelet/skate\ntmux-plugins/tpm\nFalloutSeeker/couriercollie\nlocalsend/localsend\njunegunn/fzf\n" \
    > "$work/allow"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"
distros=${*:-fedora opensuse ubuntu debian arch}
# PREBUILT=folder: packages built already (say, from a clone, while another check builds here).
if [ -n "${PREBUILT:-}" ]; then cp "$PREBUILT"/* "$work/"; else
    devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
    cp dist/* "$work/"
fi
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')

run() {  # distro, image, install command, extras
    out=.uicheck/abuse/$1
    rm -rf "$out" && mkdir -p "$out"
    podman run --rm --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port -v "$work:/work:z" \
        -v "$PWD/$out:/out:Z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        ($4) >/tmp/extras.log 2>&1 || true
        mkdir -p /app && tar -xf /work/app.tar -C /app
        export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null QT_QUICK_BACKEND=software QSG_RHI_BACKEND=
        mkdir -p /tmp/rt && chmod 700 /tmp/rt
        cd /root && python3 /app/devtools/abuse_inner.py $1" > "$work/$1.log" 2>&1 || echo "exit $?" >> "$work/$1.log"
}
# Side by side: shared (:z) rather than private (:Z) labels on /work, or each container would lock the others out.

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q --setopt=install_weak_deps=False /work/couriercollie-$version-1.fc*.noarch.rpm git curl" \
            "dnf install -y -q google-noto-sans-fonts breeze-icon-theme qqc2-desktop-style" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git curl" \
            "for p in google-noto-sans-fonts kf6-breeze-icons kf6-qqc2-desktop-style; do zypper -q -n install \$p; done" & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates python3-pyside6.qttest" \
            "$apt fonts-noto-core breeze-icon-theme qml6-module-org-kde-desktop" & ;;
        debian) run debian docker.io/library/debian:13 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates python3-pyside6.qttest" \
            "$apt fonts-noto-core breeze-icon-theme qml6-module-org-kde-desktop" & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed git curl" \
            "pacman -S --noconfirm --needed noto-fonts breeze-icons qqc2-desktop-style" & ;;
    esac
    pids="${pids:-} $!"
done
wait $pids  # (not the relay)
for distro in $distros; do
    echo "=== $distro"
    grep -v "^PASS" "$work/$distro.log"
done
