#!/bin/sh
# couriercollie's package on a desktop, on each distro, in containers side by side (devtools/desktop_inner.py): the
# package's files (menu entry, icons), then the installed command on a virtual screen with a window manager (and
# the fonts a desktop has), and
# stand-ins for KDE Plasma's tray host and the notification server: its window and icon, tray icon and menu, a
# notification, Quit. Screenshots go to .uicheck/desktop/. Nothing is installed on this computer.
#
#     devtools/check_desktop.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"
tar -rf "$work/app.tar" devtools/desktop_inner.py devtools/desktop_host.py 2>/dev/null || true
distros=${*:-fedora opensuse ubuntu debian arch}
# PREBUILT=folder: packages built already (say, from a clone, while another check builds here).
if [ -n "${PREBUILT:-}" ]; then cp "$PREBUILT"/* "$work/"; else
    devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
    cp dist/* "$work/"
fi
mkdir -p "$work/out" .uicheck/desktop
chmod -R a+rwX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
deb_desktop="xvfb openbox xdotool wmctrl imagemagick x11-utils x11-xserver-utils python3-dbus python3-gi dbus openssl desktop-file-utils fonts-noto-core"

run() {  # distro, image, install command
    podman run --rm -v "$work:/work:z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /app && tar -xf /work/app.tar -C /app && ln -s /work/out /out
        cd /root && dbus-run-session -- python3 /app/devtools/desktop_inner.py $1" > "$work/$1.log" 2>&1 \
        || echo "exit $?" >> "$work/$1.log"
}
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm xorg-x11-server-Xvfb openbox xdotool wmctrl ImageMagick xprop xdpyinfo xsetroot python3-dbus python3-gobject dbus-daemon openssl desktop-file-utils google-noto-sans-fonts" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm xorg-x11-server-Xvfb openbox xdotool wmctrl ImageMagick xprop xdpyinfo xsetroot python3-dbus-python python3-gobject dbus-1-daemon openssl desktop-file-utils google-noto-sans-fonts" & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 "$apt /work/couriercollie_${version}_all.deb $deb_desktop" & ;;
        debian) run debian docker.io/library/debian:13 "$apt /work/couriercollie_${version}_all.deb $deb_desktop" & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed xorg-server-xvfb openbox xdotool wmctrl imagemagick xorg-xprop xorg-xdpyinfo xorg-xsetroot python-dbus python-gobject dbus openssl desktop-file-utils noto-fonts" & ;;
    esac
    pids="${pids:-} $!"
done
wait $pids
cp "$work"/out/*.png "$work"/out/*.log .uicheck/desktop/ 2>/dev/null || true
for distro in $distros; do
    echo "=== $distro"
    cat "$work/$distro.log"
done
