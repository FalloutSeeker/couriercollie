#!/bin/sh
# What's left after couriercollie is uninstalled, in a Fedora container running systemd, as a user with their own
# systemd manager. Two ways it can go:
#   1. Installed as a package, then `dnf remove couriercollie`.
#   2. Run from a project folder, then the folder is deleted.
# Each time, background checks are on. Afterwards the timer wakes, finds couriercollie gone, and should turn itself off
# and remove its files (and a project folder's menu entry), leaving no failed units. Settings, results and the cache
# are kept, as with any app. Nothing is installed on this computer; the container is removed at the end.
#
#     devtools/check_uninstall.sh       (builds the Fedora package first, with devtools/build_package.sh)
set -eu
cd "$(dirname "$0")/.."
devtools/build_package.sh fedora >/dev/null
rpm=$(ls dist/couriercollie-*.fc*.noarch.rpm | tail -1)
image=registry.fedoraproject.org/fedora:44
name=couriercollie-uninstall-$$
work=$(mktemp -d)
trap 'podman rm -f $name >/dev/null 2>&1; rm -rf "$work"' EXIT
git archive --format=tar --prefix=couriercollie/ -o "$work/source.tar" HEAD
cp "$rpm" "$work/"
chmod -R a+rX "$work"  # mktemp's folder is yours only; the container's user reads from it too

echo "=== starting a Fedora container with systemd (installs systemd first)"
podman run -d --name $name --systemd=always -v "$work:/work:Z" $image \
    sh -c 'dnf install -y -q systemd python3 procps-ng >/tmp/setup.log 2>&1 && exec /sbin/init' >/dev/null
until podman exec $name sh -c 'systemctl is-system-running 2>/dev/null | grep -qE "running|degraded"'; do sleep 2; done

in_box() { podman exec $name sh -c "$1"; }
# As the user, with their systemd manager and bus.
as_user() { podman exec -u tester -e XDG_RUNTIME_DIR=/run/user/1000 \
    -e DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus -w /home/tester $name sh -c "$1"; }

in_box 'useradd -u 1000 -m tester && loginctl enable-linger tester'
until in_box 'test -S /run/user/1000/bus'; do sleep 1; done

failures=0
expect() {  # label, shell test run as the user
    if as_user "$2" >/dev/null 2>&1; then echo "  ok:   $1"; else echo "  FAIL: $1"; failures=$((failures + 1)); fi
}
wake() {  # what the timer does when it fires
    as_user 'systemctl --user start couriercollie-check.service' 2>/dev/null || true
}
report() {
    echo "  units:  $(as_user 'ls ~/.config/systemd/user 2>/dev/null | tr "\n" " "')"
    echo "  failed: $(as_user 'systemctl --user --failed --no-legend | wc -l') unit(s)"
}

echo "=== 1. installed as a package"
in_box "dnf install -y -q /work/$(basename "$rpm") >/tmp/install.log 2>&1" || { in_box 'tail -20 /tmp/install.log'; exit 1; }
as_user 'mkdir -p ~/.config/couriercollie && printf "categories = []\n[settings]\nauto_check = true\n" > ~/.config/couriercollie/repos.toml'
as_user 'python3 -c "from couriercollie import integration; integration.set_background_checks(True)"'
expect "the timer is on" 'systemctl --user is-enabled couriercollie-check.timer'
wake
expect "a check runs while it's installed" 'test -f ~/.local/state/couriercollie/checks.json'
expect "nothing failed" 'test "$(systemctl --user --failed --no-legend | wc -l)" = 0'
in_box 'dnf remove -y -q couriercollie >/dev/null 2>&1'
wake
report
expect "the check was skipped, not failed" 'systemctl --user show -p Result couriercollie-check.service | grep -q "=success"'

expect "the timer turned itself off" '! systemctl --user is-enabled couriercollie-check.timer'
expect "its files are gone" '! ls ~/.config/systemd/user/couriercollie-check.* ~/.config/systemd/user/timers.target.wants/couriercollie-check.timer'
expect "no failed units" 'test "$(systemctl --user --failed --no-legend | wc -l)" = 0'
expect "settings are kept" 'test -f ~/.config/couriercollie/repos.toml'

echo "=== 2. run from a project folder, then the folder deleted"
as_user 'mkdir -p ~/src && tar -xf /work/source.tar -C ~/src'
as_user 'cd ~/src/couriercollie && python3 -c "from couriercollie import integration; integration.install_menu_entry(); integration.set_background_checks(True)"'
expect "the menu entry was written" 'test -f ~/.local/share/applications/couriercollie.desktop'
expect "the timer is on" 'systemctl --user is-enabled couriercollie-check.timer'
as_user 'rm -rf ~/src/couriercollie'
wake
report
expect "the timer turned itself off" '! systemctl --user is-enabled couriercollie-check.timer'
expect "its files are gone" '! ls ~/.config/systemd/user/couriercollie-check.*'
expect "the menu entry and icon are gone" '! ls ~/.local/share/applications/couriercollie.desktop ~/.local/share/icons/hicolor/512x512/apps/couriercollie.png'
expect "no failed units" 'test "$(systemctl --user --failed --no-legend | wc -l)" = 0'

echo "=== left in the home folder (kept on purpose: settings, results, cache)"
as_user 'cd ~ && find .config .local .cache -path "*couriercollie*" 2>/dev/null | sort' | sed 's/^/  /'
[ $failures = 0 ] && echo "FAILURES: none" || { echo "FAILURES: $failures"; exit 1; }
