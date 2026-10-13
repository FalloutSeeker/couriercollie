"""Run inside a distro's container by devtools/check_updates.sh, as root there: real projects are installed at a
previous release (or set back a few commits), then updated through the app's own Update (Backend.updateRepo), from
GitHub, and the result checked for real: the updated program is run, the package manager asked, git read. Also: a
clone's step after updating, what the distro's package manager installed (never updated), and a project built for
other systems (never installed). Nothing outside the container is touched.

The release lists come from /work/releases (fetched once, outside, so the containers don't spend GitHub's hourly
limit); the files themselves are downloaded from GitHub, checked against GitHub's checksums.

    python3 devtools/updates_inner.py <fedora|opensuse|ubuntu|debian|arch>
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DISTRO = sys.argv[1]
home = Path(tempfile.mkdtemp(prefix="home-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
                  XDG_STATE_HOME=str(home / ".local/state"), XDG_CACHE_HOME=str(home / ".cache"),
                  COURIERCOLLIE_CLONES=str(home / "src"), GIT_CONFIG_GLOBAL="/dev/null")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from couriercollie import applying, assets, checker, config, sources, updater  # noqa: E402
from couriercollie.backend import Backend, Details, _fit_files  # noqa: E402
from couriercollie.config import NOT_INSTALLED, TrackedRepo  # noqa: E402

updater.ROOT = []  # root already, in the container: no password to ask for
failures = []


def check(label, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(f"{DISTRO}: {label}")


def out(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


RELEASES = {}
for file in Path("/work/releases").glob("*.json"):
    owner, name = file.stem.split("__")
    RELEASES[f"github.com/{owner}/{name}"] = sources.parse_github_releases(json.loads(file.read_text()))
sources.releases = lambda ref, host, count=30, **_: RELEASES[ref.id][:count]
real_versions = {k: [r for r in v if not r.prerelease and re.match(r"v?\d", r.tag)] for k, v in RELEASES.items()}


def backend_with(*repos):
    path = home / ".config/couriercollie/repos.toml"
    config.save(config.Config(repos=list(repos)), path)
    b = Backend(path)

    def at_once(work, done):  # one thing at a time, so each check follows the last step
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)
    b._run = at_once
    return b


def note(b, repo_id):
    return b.details(repo_id)["updateNote"]


def release_update(repo_id, file_pattern, version_of_result, versions=None, checksum=True):
    """Install the previous release's file (as a release list from then would show it), then Update to the newest.
    `file_pattern`: a regex for the file, among the release's; `version_of_result(repo)`: the version it now has,
    asked of the installed thing itself. `versions`: the releases, newest first, if not the project's latest two;
    `checksum`: whether the newest's file has a published checksum (if not, it's installed with a warning)."""
    versions = versions or real_versions[repo_id]
    newest, previous = versions[0], versions[1]
    print(f"- {repo_id}: {previous.tag} -> {newest.tag}", flush=True)
    old = next((a for a in previous.assets if re.fullmatch(file_pattern, a.name)), None)
    if not old:
        check(f"{repo_id}: the previous release has the file", False, file_pattern)
        return
    info = assets.classify(old.name, old.url)
    check(f"{repo_id}: {old.name} suits this computer", info.suits, info.note)
    repo = TrackedRepo(id=repo_id, name=repo_id.rsplit("/", 1)[1], url=f"https://{repo_id}", host="github",
                       asset_pattern=assets.pattern_for(old.name, previous.tag), kind=info.kind,
                       installed=NOT_INSTALLED)
    b = backend_with(repo)
    b._details[repo_id] = Details(state="ready", releases=[previous])  # before the newest came out
    b.updateRepo(repo_id)
    repo = b._config.find(repo_id)
    check(f"{repo_id}: installs {previous.tag}", repo.installed == previous.tag and not
          b.details(repo_id)["updateNoteKind"] == "error", note(b, repo_id))
    have = version_of_result(repo)
    check(f"{repo_id}: …which is what's there", assets.same_version(have, previous.tag), have)
    b._details[repo_id] = Details(state="ready", releases=versions)  # the newest is out
    b._checks.results[repo_id] = checker.releases_result([newest], repo.installed)
    check(f"{repo_id}: the update is offered", b.details(repo_id)["canUpdate"] and b.repo(repo_id)["updateAvailable"])
    b.updateRepo(repo_id)
    repo = b._config.find(repo_id)
    d = b.details(repo_id)
    check(f"{repo_id}: updates to {newest.tag}", repo.installed == newest.tag and d["updateNoteKind"] != "error",
          d["updateNote"])
    if checksum:
        check(f"{repo_id}: …checked against GitHub's checksum", d["updateNoteKind"] == "done"
              and "Checked against the project\u2019s published checksum" in d["updateNote"], d["updateNote"])
    else:
        check(f"{repo_id}: …with a warning that there's no checksum to check it against",
              d["updateNoteKind"] == "warning" and "publishes no checksum" in d["updateNote"], d["updateNote"])
    have = version_of_result(repo)
    check(f"{repo_id}: …and it runs the new version", assets.same_version(have, newest.tag), have)
    check(f"{repo_id}: …which the list and page say", d["statusKind"] == "current" and
          b.repo(repo_id)["checkText"] == "Up to date", f"{d['statusKind']} / {b.repo(repo_id)['checkText']}")
    b.shutdown()
    return repo


def version_in(text):
    m = re.search(r"\d+\.\d+(\.\d+)?", text)
    return m.group(0) if m else text[:80]


def program_version(command):
    def ask(repo):
        link = Path(repo.local_path)
        if not link.exists():
            return f"no {link}"
        return version_in(out(str(link), *command))
    return ask


def package_version(name):
    kind = {"fedora": assets.KIND_RPM, "opensuse": assets.KIND_RPM}.get(DISTRO, assets.KIND_DEB)
    from couriercollie import packages
    return lambda repo: packages.installed_version(kind, name)[0]


def appimage_version(repo):
    # No FUSE in a container: the AppImage runs itself unpacked.
    path = Path(repo.local_path)
    return version_in(out(str(path), "--appimage-extract-and-run", "--version"))


print(f"=== {DISTRO}: release files", flush=True)
release_update("github.com/BurntSushi/ripgrep", r"ripgrep-[\d.]+-x86_64-unknown-linux-musl\.tar\.gz",
               program_version(["--version"]))
release_update("github.com/sharkdp/fd", r"fd-v[\d.]+-x86_64-unknown-linux-gnu\.tar\.gz", program_version(["--version"]))
release_update("github.com/junegunn/fzf", r"fzf-[\d.]+-linux_amd64\.tar\.gz", program_version(["--version"]))
release_update("github.com/neovim/neovim", r"nvim-linux-x86_64\.appimage", appimage_version)
if DISTRO in ("fedora", "opensuse"):
    release_update("github.com/cli/cli", r"gh_[\d.]+_linux_amd64\.rpm", package_version("gh"))
    release_update("github.com/ClementTsang/bottom", r"bottom-[\d.]+-1\.x86_64\.rpm", package_version("bottom"))
elif DISTRO in ("ubuntu", "debian"):
    release_update("github.com/cli/cli", r"gh_[\d.]+_linux_amd64\.deb", package_version("gh"))
    release_update("github.com/ClementTsang/bottom", r"bottom_[\d.]+-1_amd64\.deb", package_version("bottom"))
else:
    # Arch: no project here publishes Arch packages, and other distros' aren't offered.
    release_update("github.com/cli/cli", r"gh_[\d.]+_linux_amd64\.tar\.gz", program_version(["--version"]))
    for name in ("gh_2.102.0_linux_amd64.rpm", "gh_2.102.0_linux_amd64.deb"):
        check(f"{name} isn't offered on Arch", not assets.classify(name).suits, str(assets.classify(name)))

# An older release with no checksums published (bat 0.24 -> 0.25, before GitHub gave them).
BAT = "github.com/sharkdp/bat"
older = [r for r in real_versions[BAT] if r.tag in ("v0.25.0", "v0.24.0")]
if len(older) == 2:
    release_update(BAT, r"bat-v[\d.]+-x86_64-unknown-linux-musl\.tar\.gz", program_version(["--version"]), older,
                   checksum=False)
else:
    check("bat's v0.24.0 and v0.25.0 are in its release list", False, str([r.tag for r in real_versions[BAT]]))

# An AppImage a scan found: your own file name, and a menu entry of yours that must keep working.
print("- an AppImage found on this computer, with its own menu entry", flush=True)
import urllib.request  # noqa: E402

NVIM = "github.com/neovim/neovim"
newest, previous = real_versions[NVIM][0], real_versions[NVIM][1]
old_file = next(a for a in previous.assets if a.name == "nvim-linux-x86_64.appimage")
mine = home / "Applications" / "Neovim.AppImage"
mine.parent.mkdir(parents=True, exist_ok=True)
urllib.request.urlretrieve(old_file.url, mine)
mine.chmod(0o755)
entry = home / ".local/share/applications/my-neovim.desktop"
entry.parent.mkdir(parents=True, exist_ok=True)
entry.write_text(f"[Desktop Entry]\nType=Application\nName=My Neovim\nExec={mine} %F\nTryExec={mine}\nIcon=nvim\n")
repo = TrackedRepo(id=NVIM, name="Neovim", url="", host="github", asset_pattern="nvim-linux-x86_64.appimage",
                   kind="AppImage", source="scanned", local_path=str(mine), installed=previous.tag)
b = backend_with(repo)
b._details[NVIM] = Details(state="ready", releases=RELEASES[NVIM])
b.updateRepo(NVIM)
repo = b._config.find(NVIM)
new_file = Path(repo.local_path)
check(f"scanned AppImage: updated to {newest.tag}", repo.installed == newest.tag
      and appimage_version(repo) == version_in(newest.tag), note(b, NVIM))
check("…the old file is gone, the new one beside it", not mine.exists() and new_file.parent == mine.parent,
      f"{mine.exists()} {new_file}")
text = entry.read_text()
check("…and your menu entry runs the new one", f"Exec={new_file} %F" in text and f"TryExec={new_file}" in text, text)
b.shutdown()

print(f"=== {DISTRO}: git clones", flush=True)
src = home / "src"
src.mkdir(parents=True, exist_ok=True)
# Following a branch: set back a few commits, then Update pulls them.
plug = src / "vim-plug"
out("git", "clone", "-q", "https://github.com/junegunn/vim-plug.git", str(plug))
head = out("git", "rev-parse", "HEAD", cwd=plug)
changed = out("git", "diff", "--name-only", "HEAD~3", "HEAD", cwd=plug).splitlines()
out("git", "reset", "-q", "--hard", "HEAD~3", cwd=plug)
PLUG = "github.com/junegunn/vim-plug"
ref = sources.RepoRef.from_id(PLUG)
default, branches = sources.branches(ref)
repo = TrackedRepo(id=PLUG, name="vim-plug", url="", host="github", follow="branch", branch=default, kind="git",
                   source="scanned", local_path=str(plug), installed=out("git", "rev-parse", "HEAD", cwd=plug))
b = backend_with(repo)
b._details[PLUG] = Details(state="ready", default_branch=default, branches=branches)
def approved(b, repo_id, command):
    """A step approved before (as kept in the settings): any command, as earlier versions let one be typed."""
    repo = b._config.find(repo_id)
    repo.apply_command, repo.apply_approved = command, applying.fingerprint(repo.local_path, command)


# Its step after updating: names no file of the clone, so updates don't change it.
approved(b, PLUG, "git rev-parse HEAD > /tmp/applied-at")
b.updateRepo(PLUG)
d = b.details(PLUG)
check("branch: Update pulls the 3 commits", out("git", "rev-parse", "HEAD", cwd=plug) == head
      and d["updateNote"] == "Pulled 3 new commits.", d["updateNote"])
check("…then its step runs, in the clone", d["stepResult"] == "applied"
      and Path("/tmp/applied-at").read_text().strip() == head, d["stepResult"] + d["stepOutput"])
# A step naming a file the update changes: not run until approved again.
named = next((f for f in changed if (plug / f).is_file()), "")
out("git", "reset", "-q", "--hard", "HEAD~3", cwd=plug)
b._config.find(PLUG).installed = out("git", "rev-parse", "HEAD", cwd=plug)
approved(b, PLUG, f"cat {named} > /dev/null")
b.updateRepo(PLUG)
d = b.details(PLUG)
check(f"…a step naming a file the update changed ({named}) waits to be looked at again",
      d["stepChanged"] and d["stepResult"] == "", f"{d['stepChanged']} {d['stepResult']}")
b.shutdown()

# Following releases: a clone at the previous tag moves to the newest.
FZF = "github.com/junegunn/fzf"
fzf = src / "fzf"
newest, previous = real_versions[FZF][0], real_versions[FZF][1]
out("git", "clone", "-q", "https://github.com/junegunn/fzf.git", str(fzf))
out("git", "-c", "advice.detachedHead=false", "checkout", "-q", previous.tag, cwd=fzf)
repo = TrackedRepo(id=FZF, name="fzf", url="", host="github", follow="releases", kind="git", source="scanned",
                   local_path=str(fzf), installed=previous.tag)
b = backend_with(repo)
b._details[FZF] = Details(state="ready", releases=RELEASES[FZF])
b.updateRepo(FZF)
check(f"releases: the clone moves from {previous.tag} to {newest.tag}",
      out("git", "describe", "--tags", "--exact-match", cwd=fzf) == newest.tag, note(b, FZF))
b.shutdown()

print(f"=== {DISTRO}: what the package manager installed", flush=True)
install = {"fedora": ["dnf", "install", "-y", "-q"], "opensuse": ["zypper", "-q", "--non-interactive", "install"],
           "ubuntu": ["apt-get", "install", "-y", "-qq"], "debian": ["apt-get", "install", "-y", "-qq"],
           "arch": ["pacman", "-S", "--noconfirm", "--needed"]}[DISTRO]
subprocess.run([*install, "ripgrep"], capture_output=True, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
RG = "github.com/BurntSushi/ripgrep"
repo = TrackedRepo(id=RG, name="ripgrep", url="", host="github", asset_pattern="ripgrep-*-x86_64-unknown-linux-musl.tar.gz",
                   kind="Program", installed=NOT_INSTALLED)
found = checker.find_managed([repo])
check(f"the distro's ripgrep is found as its package manager's ({found.get(RG)})", RG in found, str(found))
b = backend_with(repo)
b._checks, _fresh = checker.check_all(b._config.repos)
b._details[RG] = Details(state="ready", releases=RELEASES[RG])
before = out("rg", "--version")
b._config.find(RG).managed_by = found.get(RG, "")
b.updateRepo(RG)
check("…never updated here", not b.details(RG)["canUpdate"] and not b.repo(RG)["canUpdate"]
      and out("rg", "--version") == before and b._config.find(RG).installed == NOT_INSTALLED)
check("…and the list says so", b._checks.results[RG].text == "Installed with Package Manager", b._checks.results[RG].text)
b.shutdown()

print(f"=== {DISTRO}: a project built for other systems", flush=True)
OBT = "github.com/ImranR98/Obtainium"
repo = TrackedRepo(id=OBT, name="Obtainium", url="", host="github", installed=NOT_INSTALLED)
b = backend_with(repo)
b._details[OBT] = Details(state="ready", releases=RELEASES[OBT])
_fit_files(b._config.find(OBT), b._details[OBT])
b.updateRepo(OBT)
check("Obtainium (Android) is never installed", b._config.find(OBT).other_systems and not b.details(OBT)["canUpdate"]
      and not any(src.glob("Obtainium*")), b.details(OBT).get("otherSystems", ""))
b.shutdown()

shutil.rmtree(home, ignore_errors=True)
print(f"FAILURES ({DISTRO}):", failures or "none", flush=True)
sys.exit(1 if failures else 0)
