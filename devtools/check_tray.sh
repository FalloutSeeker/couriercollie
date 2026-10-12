#!/bin/sh
# The tray icon and notifications, for real, in a Fedora container: devtools/tray_inner.py, on a virtual screen with a
# window manager and a tray, and with stand-ins for KDE Plasma's tray host and the notification server on its own
# session bus. Asks GitHub for four projects' releases. Screenshots go to .uicheck/tray-*. Nothing on this computer is
# touched; the container is removed.
#
#     devtools/check_tray.sh
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as it is here, committed or not
tar -rf "$work/app.tar" devtools/tray_inner.py devtools/desktop_host.py devtools/check_tray.sh 2>/dev/null || true
mkdir -p .uicheck "$work/out"
chmod -R a+rwX "$work"
podman run --rm -v "$work:/work:z" -v "$work/out:/out:z" registry.fedoraproject.org/fedora:44 sh -c '
    set -e
    dnf install -y -q python3-pyside6 kf6-kirigami git xorg-x11-server-Xvfb openbox stalonetray xdotool wmctrl \
        ImageMagick xwininfo xdpyinfo xsetroot python3-dbus python3-gobject libnotify dbus-daemon procps-ng openssl \
        >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
    mkdir -p /app && tar -xf /work/app.tar -C /app
    dbus-run-session -- python3 /app/devtools/tray_inner.py' || failed=1
cp "$work"/out/*.png .uicheck/ 2>/dev/null || true
cp "$work/out/app.log" .uicheck/tray-app.log 2>/dev/null || true
tail -30 "$work/out/app.log" 2>/dev/null | grep -iE "error|warning|traceback" | head -10 || true
exit ${failed:-0}
