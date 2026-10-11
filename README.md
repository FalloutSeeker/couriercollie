# couriercollie

Inspired by [Obtainium](https://github.com/ImranR98/Obtainium), keep the software you got from GitHub and GitLab up to date, in one simple window.

![couriercollie showing an update for LocalSend](docs/screenshot.png)

AppImages, programs from release archives, downloaded `.rpm` or `.deb` files and git clones never get updates from
your package manager. couriercollie keeps track of them, tells you when there's a new version, and updates them with
a click.

## Why another tool?

Each existing tool covers one piece:

| Tool | What it does | What it misses |
| --- | --- | --- |
| Topgrade | Runs your package managers | Software you got from GitHub |
| Gear Lever, AppImageLauncher | AppImages | Everything else |
| eget | Downloads a release's program | Runs in a terminal, one at a time |
| nvchecker | Tells you about new versions | Doesn't update anything |
| Discover | Packages and Flatpaks | What you downloaded yourself |

couriercollie does all of it in one app.

## Install

**Fedora KDE** already has everything it needs:

```sh
git clone https://github.com/FalloutSeeker/couriercollie
cd couriercollie
./run.sh
```

To put it in your app menu, build and install the package:

```sh
devtools/build_rpm.sh
sudo dnf install dist/couriercollie-*.noarch.rpm
```

**Other distros:** install the packages below first, then run the same three commands.

<details>
<summary>Packages to install</summary>

| For | Fedora | Ubuntu / Debian | Arch | openSUSE |
| --- | --- | --- | --- | --- |
| The window | `python3-pyside6` | `python3-pyside6.qtquick python3-pyside6.qtwidgets python3-pyside6.qtdbus python3-pyside6.qtnetwork python3-pyside6.qtsvg` | `pyside6` | `python313-pyside6` |
| KDE's toolkit | `kf6-kirigami` | `qml6-module-org-kde-kirigami qml6-module-qtquick-controls qml6-module-qtquick-dialogs qml6-module-qtquick-layouts` | `kirigami` | `kf6-kirigami-imports` |
| KDE's look (optional) | `kf6-qqc2-desktop-style` | `qml6-module-org-kde-desktop` | `qqc2-desktop-style` | `kf6-qqc2-desktop-style` |
| Icons | `breeze-icon-theme` | `kf6-breeze-icon-theme` | `breeze-icons` | `kf6-breeze-icons` |
| Notifications | `libnotify` | `libnotify-bin` | `libnotify` | `libnotify-tools` |
| Git | `git-core` | `git` | `git` | `git-core` |
| Password prompts | `polkit` | `pkexec` | `polkit` | `polkit` |
| GitHub sign-in | `libsecret` | `libsecret-tools` | `libsecret` | `secret-tool` |

Needs Python 3.13 or newer.

</details>

## Use it

1. **Add** a project by pasting its GitHub or GitLab address. Or turn on scanning in Settings, then click **Scan**
   to find what's already on your computer.
2. **Open it** and pick your file (the AppImage, archive or package you use), or a branch to follow.
3. **Update** when the list says there's a new version.

Settings has how often to check (or never), notifications, scan folders and GitHub sign-in.

## Good to know

**Is it safe?**

- Nothing updates until you click Update.
- Downloads are checked against the project's published checksum. You're warned when there isn't one.
- Your password is only asked for packages (through your package manager) and for clones owned by the system.
- A project's install script is shown to you before it runs.

**Does it run all the time?** No, but automatic checks don't need the window. With them on, a small background
timer runs a quick check now and then, and exits, even after you close the window. Turn automatic checks off in
Settings and nothing runs unless you open couriercollie.

**Do I need to sign in to GitHub?** Only if you track a lot of GitHub projects. GitHub allows 60 requests an hour
without signing in, and 5,000 with.

- couriercollie uses its registered app identity to ask GitHub for a read-only, public-data token on behalf of
  whoever signs in.
- That login can't see anything private or change anything.
- It's kept in your desktop's password store (KDE Wallet, GNOME Keyring, etc.).
- You can revoke it anytime in GitHub's Settings → Applications.

**What does a scan find?** Only what your package manager can't update:

- Git clones and AppImages in your scan folders.
- Packages installed from a downloaded file that no repository you have offers. On Fedora that's two checks: it
  came from a file (`@commandline`), and no enabled repository offers it (some packages add their own repository
  when installed).
- Flatpak bundles installed from a file.

The scan folders are your home folder, `/opt`, `/usr/local` and `/srv`, where software installed by hand lives. The
rest of the system belongs to your package manager. Change them in Settings.

**Which distros?** It's built and tested mainly on Fedora KDE. openSUSE, Ubuntu, Debian, Arch and GNOME are
supported, but need feedback. Tried it somewhere? Please
[open an issue](https://github.com/FalloutSeeker/couriercollie/issues), whether it worked or not.

**Start over:** `./run.sh --reset` brings the welcome screen back. Your old settings are kept as a dated backup.

<details>
<summary>Where it keeps things</summary>

| What | Where |
| --- | --- |
| Settings and your list | `~/.config/couriercollie/repos.toml` |
| Last check's results | `~/.local/state/couriercollie/checks.json` |
| Icons, release lists | `~/.cache/couriercollie/` |
| Background checks (only while on) | `~/.config/systemd/user/couriercollie-check.timer` |
| AppImages it installs | `~/Applications` |
| Programs it installs | `~/.local/share/couriercollie/programs`, linked from `~/.local/bin` |
| Projects it clones | `~/src` |
| GitHub sign-in (only if you sign in) | Your desktop's password store |

</details>
