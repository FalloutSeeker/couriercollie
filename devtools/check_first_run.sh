#!/bin/sh
# A brand-new user's first run, with couriercollie's package installed, in a container per distro, side by side: the
# welcome screen, the first scan (an AppImage renamed without its version, an old clone), adding and installing a
# project, Check Now and Settings, through the real window (off-screen). devtools/first_run_inner.py runs inside;
# screenshots go to .uicheck/first-run/<distro>. GitHub is asked through devtools/github_relay.py, with your gh
# login, which stays here. Nothing is installed on this computer; the containers are removed.
#
#     devtools/check_first_run.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18766
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
printf "jesseduffield/lazygit\nneovim/neovim\njunegunn/vim-plug\nFalloutSeeker/couriercollie\n" > "$work/allow"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
distros=${*:-fedora opensuse ubuntu debian arch}
devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
cp dist/* "$work/"
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')

run() {  # distro, image, install command, extras (fonts, icons, the KDE style: only for the screenshots' looks)
    out=.uicheck/first-run/$1
    rm -rf "$out" && mkdir -p "$out"
    podman run --rm --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port -v "$work:/work:z" \
        -v "$PWD/$out:/out:Z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        ($4) >/tmp/extras.log 2>&1 || echo '(some extras missing: screenshots may look plainer)'
        mkdir -p /app && tar -xf /work/app.tar -C /app
        # No GPU in a container: Qt draws in software.
        export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null QT_QUICK_BACKEND=software QSG_RHI_BACKEND=
        mkdir -p /tmp/rt && chmod 700 /tmp/rt
        cd /root && python3 /app/devtools/first_run_inner.py" > "$work/$1.log" 2>&1 || echo "exit $?" >> "$work/$1.log"
}
# Side by side: shared (:z) rather than private (:Z) labels on /work, or each container would lock the others out.

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm git curl" \
            "dnf install -y -q google-noto-sans-fonts breeze-icon-theme qqc2-desktop-style" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git curl" \
            "for p in google-noto-sans-fonts kf6-breeze-icons kf6-qqc2-desktop-style; do zypper -q --non-interactive install \$p; done" & ;;
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
    cat "$work/$distro.log"
done
cat "$work/relay.log"
