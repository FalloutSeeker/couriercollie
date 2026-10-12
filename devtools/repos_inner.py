"""Many real projects on one distro, in a container (devtools/check_repos.sh), as a user adds them: by address, from
the real sites (GitHub through devtools/github_relay.py). Each is installed at its previous release (as if installed
a while ago), checked by running what was installed, then updated to the newest and checked again. Then edge cases:
a renamed project, one built for other systems, one with no releases, an archived one, and a site that isn't
supported. Prints PASS/FAIL lines.

    python3 repos_inner.py DISTRO [all|core]
"""

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/devtools")
import relay_client  # noqa: E402,F401  (GitHub's API through the relay, with your login)

print("GitHub through the relay:", relay_client.RELAY or "no", flush=True)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from couriercollie import assets, checker, config, packages, updater  # noqa: E402
from couriercollie.backend import Backend  # noqa: E402

DISTRO, SET = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "all")
HOME = Path(os.environ["HOME"])
PACKAGE = {"fedora": assets.KIND_RPM, "opensuse": assets.KIND_RPM, "ubuntu": assets.KIND_DEB,
           "debian": assets.KIND_DEB}.get(DISTRO, "")
updater.ROOT = []  # root in the container: packages install without a password prompt
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)
    return ok


def fresh_backend():
    path = HOME / ".config/couriercollie/repos.toml"
    path.unlink(missing_ok=True)
    b = Backend(path)

    def at_once(work, done):  # one thing at a time, as the steps follow each other
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)
    b._run = at_once
    return b


def add(b, url):
    failed = []
    b.addFailed.connect(failed.append)
    before = {r.id for r in b._config.repos}
    b.addRepo("", url)
    new = [r.id for r in b._config.repos if r.id not in before]
    return (new[0] if new else ""), (failed[0] if failed else "")


def version_in(text):
    m = re.search(r"\d+\.\d+(\.\d+)?", text or "")
    return m.group(0) if m else (text or "")[:80]


def run(*command):
    r = subprocess.run(command, capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()


def program(*args):
    return lambda repo: (version_in(run(repo.local_path, *args)) if repo.local_path and Path(repo.local_path).exists()
                         else "missing")


def appimage(*args):
    # No FUSE in a container: the AppImage runs itself unpacked.
    return lambda repo: version_in(run(repo.local_path, "--appimage-extract-and-run", *args))


def package(name):
    return lambda repo: packages.installed_version(PACKAGE, name)[0]


def prefer(*patterns):
    def choose(names):
        for p in patterns:
            for n in names:
                if re.search(p, n):
                    return n
        return ""
    return choose


def project(url, choose, version_of):
    """Add by address; pick the file (if the app didn't); install the previous release; update to the newest."""
    print(f"- {url}", flush=True)
    b = fresh_backend()
    rid, failed = add(b, url)
    check(f"{url}: added", bool(rid), failed)
    if not rid:
        b.shutdown()
        return
    repo, d = b._config.find(rid), b._details[rid]
    if repo.managed_by:  # e.g. Fedora's own bat: shown, never installed or updated here
        info = b.details(rid)
        check(f"{rid}: your package manager has it, so it's shown and not offered for install",
              info["headline"].startswith("Installed with") and not info["canUpdate"], info["headline"])
        print(f"  {info['headline']}: {info['versionText']}", flush=True)
        b.shutdown()
        return
    real = d.releases
    stable = [r for r in real if not r.prerelease]
    if not repo.asset_pattern:
        names = [f["name"] for f in b.details(rid).get("fileChoices", [])]
        name = choose(names)
        check(f"{rid}: a file to choose among {len(names)}", bool(name), names)
        if not name:
            b.shutdown()
            return
        b.pickAsset(rid, stable[0].tag, name)
    repo = b._config.find(rid)
    # The previous release that has the file (some releases skip a platform).
    # (Not a moving tag like Neovim's "stable", which is the newest under another name.)
    previous = next((r for r in stable[1:] if re.search(r"\d", r.tag)
                     and assets.pick(repo.asset_pattern, [a.name for a in r.assets])), None)
    if not check(f"{rid}: follows {repo.asset_pattern}; a previous release has it", previous is not None):
        b.shutdown()
        return
    newest = stable[0]
    print(f"  {previous.tag} -> {newest.tag}", flush=True)
    d.releases = [previous]  # as the release list was then
    b.updateRepo(rid)
    repo, info = b._config.find(rid), b.details(rid)
    check(f"{rid}: installs {previous.tag}", repo.installed == previous.tag and info["updateNoteKind"] != "error",
          info["updateNote"])
    have = version_of(repo)
    check(f"{rid}: …and that's what runs", assets.same_version(have, previous.tag), have)
    d.releases = real  # the newest is out
    b._checks.results[rid] = checker.releases_result([newest], repo.installed)
    check(f"{rid}: the update is offered", b.details(rid)["canUpdate"] and b.repo(rid)["updateAvailable"],
          b.details(rid).get("status"))
    b.updateRepo(rid)
    repo, info = b._config.find(rid), b.details(rid)
    check(f"{rid}: updates to {newest.tag}", repo.installed == newest.tag and info["updateNoteKind"] != "error",
          info["updateNote"])
    have = version_of(repo)
    check(f"{rid}: …and that's what runs", assets.same_version(have, newest.tag), have)
    check(f"{rid}: …and the page and list say up to date",
          info["statusKind"] == "current" and b.repo(rid)["checkText"] == "Up to date",
          f"{info['statusKind']} / {b.repo(rid)['checkText']}")
    print(f"  note: {info['updateNote']}", flush=True)
    b.shutdown()


def x86(*extra):
    return prefer(*extra, r"x86_64.*linux.*musl.*\.tar\.gz$", r"x86_64.*linux.*\.tar\.gz$", r"linux.*x86_64.*\.tar\.gz$",
                  r"(amd64|x86_64).*\.tar\.(gz|xz)$")


print(f"=== {DISTRO}: programs", flush=True)
programs = [
    ("https://github.com/BurntSushi/ripgrep", x86(), program("--version")),
    ("https://github.com/sharkdp/fd", x86(), program("--version")),
    ("https://github.com/junegunn/fzf", x86(r"linux_amd64\.tar\.gz$"), program("--version")),
    ("https://github.com/jesseduffield/lazygit", x86(r"linux_x86_64\.tar\.gz$"), program("--version")),
    ("https://gitlab.com/gitlab-org/cli", x86(r"Linux_x86_64\.tar\.gz$", r"linux_amd64\.tar\.gz$"),
     program("--version")),
]
more_programs = [
    ("https://github.com/sharkdp/bat", x86(), program("--version")),
    ("https://github.com/dandavison/delta", x86(), program("--version")),
    ("https://github.com/eza-community/eza", x86(r"x86_64-unknown-linux-musl\.tar\.gz$"), program("--version")),
    ("https://github.com/ajeetdsouza/zoxide", x86(), program("--version")),
    ("https://github.com/starship/starship", x86(), program("--version")),
    ("https://github.com/casey/just", x86(), program("--version")),
    ("https://github.com/charmbracelet/glow", x86(r"Linux_x86_64\.tar\.gz$"), program("--version")),
    ("https://github.com/ClementTsang/bottom", x86(r"x86_64-unknown-linux-musl\.tar\.gz$"), program("--version")),
    ("https://github.com/bootandy/dust", x86(), program("--version")),
    ("https://github.com/zellij-org/zellij", x86(r"zellij-x86_64-unknown-linux-musl\.tar\.gz$"), program("--version")),
    ("https://github.com/derailed/k9s", x86(r"k9s_Linux_amd64\.tar\.gz$"), program("version", "--short")),
    ("https://github.com/helix-editor/helix", x86(r"x86_64-linux\.tar\.xz$"), program("--version")),
    ("https://github.com/cli/cli", x86(r"linux_amd64\.tar\.gz$"), program("--version")),
]
for args in programs + (more_programs if SET == "all" else []):
    project(*args)

print(f"=== {DISTRO}: AppImages", flush=True)
project("https://github.com/neovim/neovim", prefer(r"x86_64\.appimage$"), appimage("--version"))

if PACKAGE:
    print(f"=== {DISTRO}: packages ({PACKAGE})", flush=True)
    ext = r"\.rpm$" if PACKAGE == assets.KIND_RPM else r"\.deb$"
    arch = r"(x86_64|amd64)"
    pkgs = [("https://github.com/charmbracelet/glow", prefer(arch + ".*" + ext), package("glow")),
            ("https://github.com/cli/cli", prefer(arch + ".*" + ext), package("gh"))]
    if SET == "all":
        pkgs += [("https://github.com/derailed/k9s", prefer(arch + ".*" + ext), package("k9s")),
                 ("https://github.com/ClementTsang/bottom", prefer(arch + ".*" + ext), package("bottom"))]
    for args in pkgs:
        project(*args)

print(f"=== {DISTRO}: edge cases", flush=True)
b = fresh_backend()
rid, failed = add(b, "https://github.com/zeit/hyper")
check("a renamed project (zeit/hyper) is added under its new address, the old one kept",
      rid == "github.com/vercel/hyper" and "github.com/zeit/hyper" in b._config.find(rid).aliases, (rid, failed))
rid2, failed = add(b, "https://github.com/vercel/hyper")
check("…and adding it again by its new address says it's tracked", not rid2 and "Already tracking" in failed, failed)

rid, failed = add(b, "https://github.com/ImranR98/Obtainium")
info = b.details(rid) if rid else {}
check("Obtainium (Android) is noted as for other systems, with no update or install offered",
      rid and b._config.find(rid).other_systems and not info.get("canUpdate"), (failed, info.get("headline")))

rid, failed = add(b, "https://github.com/tmux-plugins/tpm")
check("a project with no releases follows its branch", rid and b._config.find(rid).follow == config.FOLLOW_BRANCH,
      failed)
if rid:
    b.updateRepo(rid)
    repo = b._config.find(rid)
    check("…and Install clones it", repo.local_path and (Path(repo.local_path) / ".git").exists(),
          b.details(rid).get("updateNote"))

rid, failed = add(b, "https://github.com/ogham/exa")
check("an archived project with releases can still be added", bool(rid), failed)

rid, failed = add(b, "https://codeberg.org/forgejo/forgejo")
check("an unsupported site is turned down with a reason", not rid and failed, failed)
print(f"  codeberg: {failed}", flush=True)
b.shutdown()

print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
sys.exit(1 if failures else 0)
