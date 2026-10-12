#!/bin/sh
# A brand-new user's first run, on Fedora with couriercollie's RPM installed, in a container: the welcome screen, the
# first scan (an AppImage renamed without its version, an old clone), adding and installing a project, Check Now and
# Settings, through the real window (off-screen). devtools/first_run_inner.py runs inside; screenshots go to
# .uicheck/first-run. Nothing is installed on this computer; the container is removed.
#
#     devtools/check_first_run.sh
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
devtools/build_package.sh fedora >/dev/null
cp dist/couriercollie-*.fc*.noarch.rpm "$work/"
out=.uicheck/first-run
rm -rf "$out" && mkdir -p "$out"
chmod -R a+rX "$work"
podman run --rm -v "$work:/work:Z" -v "$PWD/$out:/out:Z" registry.fedoraproject.org/fedora:44 sh -c '
    dnf install -y -q /work/couriercollie-*.noarch.rpm git curl google-noto-sans-fonts breeze-icon-theme \
        qqc2-desktop-style >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
    mkdir -p /app && tar -xf /work/app.tar -C /app
    # No GPU in a container: Qt draws in software.
    export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null QT_QUICK_BACKEND=software QSG_RHI_BACKEND=
    mkdir -p /tmp/rt && chmod 700 /tmp/rt
    cd /root && python3 /app/devtools/first_run_inner.py'
