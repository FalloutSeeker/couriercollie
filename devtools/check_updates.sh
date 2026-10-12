#!/bin/sh
# Updating real projects from a previous version, on each distro, in containers: devtools/updates_inner.py runs in
# each, with couriercollie's own package installed there (which brings in what it needs), as root. Programs,
# AppImages, packages (dnf, zypper, apt), git clones (a branch, release tags, the step after updating), what the
# distro's package manager installed, and a project for other systems. Downloads from GitHub, about 150 MB a distro.
# Nothing is installed on this computer; the containers are removed.
#
#     devtools/check_updates.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'podman unshare rm -rf "$work"' EXIT
git ls-files -z | xargs -0 tar -cf "$work/app.tar"  # the app as committed and staged here

# The projects' release lists, fetched once here (with your GitHub login, if gh has one) so the containers don't
# spend GitHub's hourly limit.
mkdir -p "$work/releases"
for project in BurntSushi/ripgrep sharkdp/fd junegunn/fzf neovim/neovim cli/cli ClementTsang/bottom sharkdp/bat \
        ImranR98/Obtainium; do
    gh api "repos/$project/releases?per_page=10" > "$work/releases/$(echo "$project" | sed 's|/|__|').json"
done

# couriercollie's packages, built for each distro (devtools/build_package.sh), for what they bring in.
# Ubuntu and Debian share one.
devtools/build_package.sh $(echo "${*:-fedora opensuse debian arch}" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) \
    >/dev/null
cp dist/* "$work/"
chmod -R a+rX "$work"

run() {  # distro, image, install command
    echo "=== $1 ($2)"
    podman run --rm -v "$work:/work:Z" "$2" sh -c "
        set -e
        $3 >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        mkdir -p /app && tar -xf /work/app.tar -C /app
        python3 /app/devtools/updates_inner.py $1" || failed="$failed $1"
}

failed=""
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')
for distro in ${*:-fedora opensuse ubuntu debian arch}; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y /work/couriercollie-$version-1.fc*.noarch.rpm git" ;;
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git" ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y /work/couriercollie_${version}_all.deb git ca-certificates" ;;
        debian) run debian docker.io/library/debian:13 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y /work/couriercollie_${version}_all.deb git ca-certificates" ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed git" ;;
    esac
done
echo "distros with failures:${failed:- none}"
[ -z "$failed" ]
