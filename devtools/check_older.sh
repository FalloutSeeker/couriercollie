#!/bin/sh
# Older distro releases: can couriercollie's requirements be installed with the distro's own packages (the README's
# commands), do the unit tests pass, and does the app start (off-screen)? Run side by side, in containers; a log each.
# Nothing is installed on this computer; the containers are removed.
#
#     devtools/check_older.sh [ubuntu-24.04 debian-12 fedora-43 leap-16 leap-15 …]
set -u
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as it is here, committed or not
chmod -R a+rX "$work"

apt_deps="python3 python3-pyside6.qtquick python3-pyside6.qtwidgets python3-pyside6.qtdbus python3-pyside6.qtnetwork \
qml6-module-org-kde-kirigami qml6-module-qtquick-controls qml6-module-qtquick-dialogs qml6-module-qtquick-layouts git"

check='
python3 --version
python3 -c "import PySide6.QtCore as q; print(\"PySide6\", q.qVersion())" || { echo "RESULT: PySide6 missing"; exit 1; }
mkdir -p /app && tar -xf /work/app.tar -C /app && cd /app
export QT_QPA_PLATFORM=offscreen QT_FORCE_STDERR_LOGGING=1 HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null
mkdir -p /tmp/home /tmp/rt && chmod 700 /tmp/rt
python3 -m unittest -q >/tmp/tests.log 2>&1; tests=$?
grep -E "^(Ran|OK|FAILED)" /tmp/tests.log; [ $tests = 0 ] || grep -B2 -A12 -E "^(ERROR|FAIL):" /tmp/tests.log | grep -v ResourceWarning | head -40
code=0; timeout 10 python3 -m couriercollie >/tmp/app.log 2>&1 || code=$?
if [ $code = 124 ]; then echo "app: started"; else echo "app: exited with $code"; tail -5 /tmp/app.log; fi
grep -iE "qml.*(error|not installed|unavailable)|failed to load" /tmp/app.log | head -5
[ $tests = 0 ] && [ $code = 124 ] && echo "RESULT: works" || echo "RESULT: problems"'

run() {  # name, image, install
    # :z, shared: several containers read it at once (a private :Z label would lock the others out).
    podman run --rm -v "$work:/work:z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { echo 'RESULT: requirements not installable'; tail -6 /tmp/setup.log; exit 1; }
        $check" > "$work/$1.log" 2>&1
}

names=${*:-ubuntu-24.04 debian-12 fedora-43 leap-16 leap-15}
for name in $names; do
    case $name in
        ubuntu-24.04) run "$name" docker.io/library/ubuntu:24.04 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $apt_deps" & ;;
        debian-12) run "$name" docker.io/library/debian:12 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $apt_deps" & ;;
        fedora-43) run "$name" registry.fedoraproject.org/fedora:43 \
            "dnf install -y -q python3-pyside6 kf6-kirigami git" & ;;
        leap-16) run "$name" registry.opensuse.org/opensuse/leap:16.0 \
            "zypper -q --non-interactive install python3 python3-pyside6 kf6-kirigami-imports git" & ;;
        leap-15) run "$name" registry.opensuse.org/opensuse/leap:15.6 \
            "zypper -q --non-interactive install python3 python3-pyside6 kf6-kirigami-imports git" & ;;
    esac
done
wait
for name in $names; do
    echo "=== $name"
    cat "$work/$name.log"
done
