#!/bin/sh
# Takes the README's screenshot (docs/screenshot.png) in a container, in Breeze Dark, from real projects really
# installed (devtools/readme_shot_inner.py). GitHub is asked through devtools/github_relay.py, with your gh login,
# which stays here. Needs Breeze Dark's colours here (/usr/share/color-schemes/BreezeDark.colors).
#
#     devtools/readme_shot.sh
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18769
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
printf "localsend/localsend\nneovim/neovim\nBurntSushi/ripgrep\njesseduffield/lazygit\nzed-industries/zed\ntmux-plugins/tpm\n" \
    > "$work/allow"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
devtools/build_package.sh fedora >/dev/null
cp dist/couriercollie-*.fc*.noarch.rpm "$work/"
# KDE's style reads its colours from kdeglobals.
{ cat /usr/share/color-schemes/BreezeDark.colors
  printf "\n[General]\nColorScheme=BreezeDark\n[Icons]\nTheme=breeze-dark\n[KDE]\nwidgetStyle=Breeze\n"; } > "$work/kdeglobals"
mkdir -p "$work/out"
chmod -R a+rwX "$work"
podman run --rm --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port -v "$work:/work:z" \
    registry.fedoraproject.org/fedora:44 sh -c '
    dnf install -y -q /work/couriercollie-*.noarch.rpm git curl google-noto-sans-fonts breeze-icon-theme \
        qqc2-desktop-style plasma-integration >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
    mkdir -p /app /root/.config && tar -xf /work/app.tar -C /app && cp /work/kdeglobals /root/.config/
    # No GPU in a container: Qt draws in software.
    # The KDE platform plugin, as on a Plasma desktop: it colours icons for the dark theme.
    export HOME=/root XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null QT_QUICK_BACKEND=software QSG_RHI_BACKEND= \
        QT_QPA_PLATFORMTHEME=kde
    mkdir -p /tmp/rt && chmod 700 /tmp/rt
    cd /root && python3 /app/devtools/readme_shot_inner.py'
cp "$work/out/screenshot.png" docs/screenshot.png
echo "docs/screenshot.png updated"
