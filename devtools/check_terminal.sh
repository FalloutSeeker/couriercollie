#!/bin/sh
# When couriercollie hands over to a terminal, and how it carries on after (devtools/terminal_inner.py), in a container
# per distro with couriercollie's package installed: as an ordinary user with sudo, with real clones of real projects,
# set up as each situation needs (a few commits behind; owned by another user; a commit of its own; a file changed).
# GitHub is asked through devtools/github_relay.py, with your gh login, which stays here.
#
#     devtools/check_terminal.sh [fedora|opensuse|ubuntu|debian|arch …]
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
port=18772
python3 -I devtools/github_relay.py "$work/allow" $port > "$work/relay.log" 2>&1 &
relay=$!
trap 'kill $relay; podman unshare rm -rf "$work"' EXIT
printf "tmux-plugins/tpm\nzsh-users/zsh-autosuggestions\ntpope/vim-fugitive\njunegunn/vim-plug\nFalloutSeeker/couriercollie\n" > "$work/allow"
git ls-files -z | xargs -0 tar -cf "$work/app.tar"
distros=${*:-fedora opensuse ubuntu debian arch}
# PREBUILT=folder: packages built already (say, from a clone, while another check builds here).
if [ -n "${PREBUILT:-}" ]; then cp "$PREBUILT"/* "$work/"; else
    devtools/build_package.sh $(echo "$distros" | tr ' ' '\n' | sed 's/^ubuntu$/debian/' | sort -u) >/dev/null
    cp dist/* "$work/"
fi
chmod -R a+rX "$work"
version=$(python3 -c 'import couriercollie; print(couriercollie.__version__)')

# As root: the users, and the clones as each situation needs them.
setup='
useradd -m -G $admins tester && echo "tester:pw" | chpasswd
useradd -m other
behind() { git clone -q "https://github.com/$1.git" "$2" && git -C "$2" reset -q --hard HEAD~3; }
export GIT_CONFIG_GLOBAL=/dev/null
su tester -c "mkdir -p ~/src"
behind tmux-plugins/tpm /home/tester/src/tpm
behind tpope/vim-fugitive /home/tester/src/vim-fugitive
git -C /home/tester/src/vim-fugitive -c user.name=t -c user.email=t@t commit -q --allow-empty -m "my own change"
git clone -q https://github.com/junegunn/vim-plug.git /home/tester/src/vim-plug
f=$(git -C /home/tester/src/vim-plug diff --name-only HEAD~3 HEAD | head -1)
git -C /home/tester/src/vim-plug reset -q --hard HEAD~3
echo "\" my edit" >> "/home/tester/src/vim-plug/$f"
chown -R tester: /home/tester/src
behind zsh-users/zsh-autosuggestions /srv/zsh-autosuggestions
chown -R other: /srv/zsh-autosuggestions && chmod -R a+rX /srv/zsh-autosuggestions
mkdir -p /app && tar -xf /work/app.tar -C /app'

run() {  # distro, image, install command, admin group
    echo "=== $1"
    podman run --rm --network pasta:-T,$port -v "$work:/work:z" "$2" sh -c "
        ($3) >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
        admins=$4; $setup
        su tester -c 'cd ~ && env GITHUB_RELAY=http://127.0.0.1:$port XDG_RUNTIME_DIR=/tmp/rt-tester \
            GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=tester@example.com GIT_AUTHOR_NAME=tester \
            GIT_AUTHOR_EMAIL=tester@example.com sh -c \"mkdir -p -m 700 /tmp/rt-tester; \
            python3 /app/devtools/terminal_inner.py\"'" || echo "=== $1: exit $?"
}

wheel="groupadd -f wheel && mkdir -p /etc/sudoers.d && printf '%%wheel ALL=(ALL:ALL) ALL\\nDefaults !targetpw\\n' > /etc/sudoers.d/wheel && chmod 440 /etc/sudoers.d/wheel"
for distro in $distros; do
    case $distro in
        fedora) run fedora registry.fedoraproject.org/fedora:44 \
            "dnf install -y -q /work/couriercollie-$version-1.fc*.noarch.rpm git sudo util-linux-script passwd" wheel ;;
        ubuntu) run ubuntu docker.io/library/ubuntu:26.04 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /work/couriercollie_${version}_all.deb git sudo ca-certificates" sudo ;;
        debian) run debian docker.io/library/debian:13 \
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /work/couriercollie_${version}_all.deb git sudo ca-certificates" sudo ;;
        # As their users set it up: Arch's sudoers ships with the wheel line commented out, and openSUSE's asks for
        # root's password (targetpw) rather than your own.
        opensuse) run opensuse registry.opensuse.org/opensuse/tumbleweed:latest \
            "zypper -q --non-interactive install --allow-unsigned-rpm /work/couriercollie-$version-1.noarch.rpm git sudo util-linux shadow && $wheel" wheel ;;
        arch) run arch docker.io/library/archlinux:latest \
            "pacman -Sy --noconfirm && pacman -U --noconfirm /work/couriercollie-$version-1-any.pkg.tar.zst && pacman -S --noconfirm --needed git sudo util-linux && $wheel" wheel ;;
    esac
done
grep -v "^200 \|^304 \|relay on" "$work/relay.log" || true
