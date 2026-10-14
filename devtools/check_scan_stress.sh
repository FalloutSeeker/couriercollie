#!/bin/sh
# Scanning and adding, the hard way, through the real window (off-screen), in a container per distro, at most two at
# once: devtools/scan_stress_inner.py, as a normal user, in a messy home folder made of real clones of real projects,
# AppImages, a package installed from a downloaded file (Fedora, openSUSE, Debian, Ubuntu), symlink loops, a deep
# tree and an unreadable folder. Then the app is quit mid-scan and started again. GitHub is asked through
# devtools/github_relay.py (your gh login stays here; only the projects named in scan_stress_inner.py pass).
# The projects are cloned once (shallow) into .uicheck/scan-stress-cache. Nothing is installed on this computer.
#
#     devtools/check_scan_stress.sh [fedora|opensuse|ubuntu|debian|arch …]
#     PACKAGE=1 devtools/check_scan_stress.sh fedora ubuntu   (a short first scan, with the INSTALLED app)
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=${PORT:-18771}
cache=$PWD/.uicheck/scan-stress-cache
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
{ cat devtools/scan_stress_inner.py; python3 -I devtools/scan_stress_inner.py --clones; } \
    | grep -oE "github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" | sed 's/\.git$//' | sed 's|github.com/||' | sort -u \
    > "$work/allow"
curl -s "http://127.0.0.1:$port/rate_limit" >/dev/null 2>&1 || sleep 1

# The real projects and AppImages, fetched once.
mkdir -p "$cache/appimages"
python3 -I devtools/scan_stress_inner.py --clones | while read -r url name; do
    [ -d "$cache/$name" ] || nice -n 19 git clone -q --depth 1 "$url.git" "$cache/$name"
done
for f in neovim/neovim/releases/download/v0.11.0/nvim-linux-x86_64.appimage \
         AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
         AppImageCommunity/AppImageUpdate/releases/download/continuous/appimageupdatetool-x86_64.AppImage; do
    [ -s "$cache/appimages/${f##*/}" ] || curl -sfL -o "$cache/appimages/${f##*/}" "https://github.com/$f"
done
chmod -R a+rX "$cache"

git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here
distros=${*:-fedora opensuse ubuntu debian arch}
# PREBUILT=folder: packages built already.
if [ -n "${PREBUILT:-}" ]; then cp "$PREBUILT"/* "$work/"; else
    nice -n 19 devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
    cp dist/* "$work/"
fi
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')

# A tiny package, cc-test-tool, with a GitHub project as its homepage, installed from its file.
make_rpm='printf "Name: cc-test-tool\nVersion: 1.0\nRelease: 1\nSummary: t\nLicense: MIT\nURL: https://github.com/sharkdp/hyperfine\nBuildArch: noarch\n%%description\nt\n%%install\nmkdir -p %%{buildroot}/usr/share/doc/cc-test-tool && echo 1 > %%{buildroot}/usr/share/doc/cc-test-tool/V\n%%files\n/usr/share/doc/cc-test-tool/V\n" > /tmp/t.spec
rpmbuild -bb --quiet --define "_rpmdir /pkgs" --define "_build_name_fmt cc-test-tool.rpm" /tmp/t.spec'
make_deb='mkdir -p /tmp/p/DEBIAN /tmp/p/usr/share/doc/cc-test-tool && echo 1 > /tmp/p/usr/share/doc/cc-test-tool/V
printf "Package: cc-test-tool\nVersion: 1.0-1\nArchitecture: all\nMaintainer: t <t@example.org>\nHomepage: https://github.com/sharkdp/hyperfine\nDescription: t\n" > /tmp/p/DEBIAN/control
dpkg-deb --build /tmp/p /pkgs/cc-test-tool.deb'
# What a normal user can't change or open: a clone the system owns in /opt, a locked folder in the home folder.
as_root='useradd -m tester && mkdir -p /data && chown tester /data
cp -a /cache/mhinz_vim-startify /opt/startify && git -C /opt/startify remote set-url origin https://github.com/mhinz/vim-startify.git
mkdir -m 700 /home/tester/locked && cp -a /cache/junegunn_vim-easy-align /home/tester/locked/vim-easy-align
mkdir -p -m 700 /tmp/rt && chown tester /tmp/rt'

run() {  # distro, image, install command, package kind ("" for none), extras (fonts, icons, the KDE style: as on a desktop)
    out=.uicheck/scan-stress/$1${PACKAGE:+-package}
    rm -rf "$out" && mkdir -p "$out" && chmod 777 "$out"
    podman run --rm --network pasta:-T,$port -e GITHUB_RELAY=http://127.0.0.1:$port -v "$work:/work:z" \
        -v "$cache:/cache:ro,z" -v "$PWD/$out:/out:Z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        ($5) >/tmp/extras.log 2>&1 || echo '(some extras missing)'
        mkdir -p /pkgs /app && tar -xf /work/app.tar -C /app
        case '$4' in
            rpm) ($make_rpm) >/tmp/pkg.log 2>&1 && { dnf install -y -q /pkgs/cc-test-tool.rpm || zypper -q --non-interactive install --allow-unsigned-rpm /pkgs/cc-test-tool.rpm; } >>/tmp/pkg.log 2>&1 || tail /tmp/pkg.log ;;
            deb) ($make_deb) >/tmp/pkg.log 2>&1 && apt-get install -y -qq /pkgs/cc-test-tool.deb >>/tmp/pkg.log 2>&1 || tail /tmp/pkg.log ;;
        esac
        $as_root
        go() { runuser -u tester -- env HOME=/home/tester XDG_RUNTIME_DIR=/tmp/rt GIT_CONFIG_GLOBAL=/dev/null \
            QT_QUICK_BACKEND=software QSG_RHI_BACKEND= GITHUB_RELAY=\$GITHUB_RELAY TEST_PACKAGE=$4 \
            sh -c \"cd /home/tester && nice -n 19 python3 /app/devtools/scan_stress_inner.py \$1\"; }
        if [ -n '${PACKAGE:-}' ]; then go package; exit; fi
        go main; echo \"EXITED_AT \$(date +%s.%N | cut -c1-13)\"
        go restart" > "$work/$1.log" 2>&1 || echo "exit $?" >> "$work/$1.log"
}

apt="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq"
running=0
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm git curl rpm-build util-linux" rpm \
            "dnf install -y -q google-noto-sans-fonts breeze-icon-theme qqc2-desktop-style" & ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git curl rpm-build util-linux shadow" rpm \
            "for p in google-noto-sans-fonts kf6-breeze-icons kf6-qqc2-desktop-style; do zypper -q --non-interactive install \$p; done" & ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates python3-pyside6.qttest" deb \
            "$apt fonts-noto-core breeze-icon-theme qml6-module-org-kde-desktop" & ;;
        debian) run debian docker.io/library/debian:13 \
            "$apt /work/couriercollie_${version}_all.deb git curl ca-certificates python3-pyside6.qttest" deb \
            "$apt fonts-noto-core breeze-icon-theme qml6-module-org-kde-desktop" & ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed git curl" "" \
            "pacman -S --noconfirm --needed noto-fonts breeze-icons qqc2-desktop-style" & ;;
    esac
    pids="${pids:-} $!"
    running=$((running + 1))
    if [ $running -ge 2 ]; then wait $pids; pids=; running=0; fi  # two at a time
done
[ -z "${pids:-}" ] || wait $pids
for distro in $distros; do
    echo "=== $distro"
    cat "$work/$distro.log"
done
for distro in $distros; do cp "$work/$distro.log" .uicheck/scan-stress/$distro${PACKAGE:+-package}/run.log; done
echo "GitHub requests: $(grep -cE '^[0-9]{3} ' "$work/relay.log")"
grep -h "refused" "$work/relay.log" | sort | uniq -c || true
