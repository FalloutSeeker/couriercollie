"""After Updating, for real: a clone running as containers (podman-compose), whose own install.sh rebuilds and
restarts them. Checks the first Update shows install.sh and runs it once approved, that the containers then run the
new version, that the next Update does it all in one click, and that a change to install.sh stops it until it's
approved again.

Podman uses a storage folder of its own here (CONTAINERS_STORAGE_CONF), so your images and containers are never
seen or touched; it's deleted at the end. Downloads busybox (about 2 MB) into it. No window.

    python3 -I devtools/check_after_update.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
work = Path(tempfile.mkdtemp())
storage = work / "storage"
(work / "storage.conf").write_text(f'[storage]\ndriver = "overlay"\ngraphroot = "{storage}/graph"\n'
                                   f'runroot = "{storage}/run"\n')
os.environ["CONTAINERS_STORAGE_CONF"] = str(work / "storage.conf")
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
failures = []


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def serving(clone):
    """What the running container says its version is."""
    names = run("podman", "ps", "--format", "{{.Names}}", "--filter", "label=com.docker.compose.service=web")
    return run("podman", "exec", names.splitlines()[0], "cat", "/version") if names else ""


try:
    # The project: a container that serves its version file. Published to a bare repo; you have a clone, running.
    upstream, other, clone = work / "upstream.git", work / "other", work / "board"
    run("git", "init", "-q", "--bare", "-b", "main", str(upstream))
    run("git", "clone", "-q", str(upstream), str(other))
    (other / "Dockerfile").write_text("FROM docker.io/library/busybox:latest\nCOPY version /version\n")
    (other / "version").write_text("1\n")
    (other / "docker-compose.yml").write_text('services:\n  web:\n    build: .\n    command: ["sleep", "3600"]\n')
    (other / "install.sh").write_text("#!/bin/sh\nset -e\npodman-compose up -d --build --force-recreate\n")
    (other / "README.md").write_text("# Board\n\nTo update: pull, then run install.sh.\n")
    run("git", "add", ".", cwd=other)
    run("git", "commit", "-q", "-m", "version 1", cwd=other)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=other)
    run("git", "clone", "-q", str(upstream), str(clone))
    print("starting the project's containers (in their own storage)…")
    run("podman-compose", "up", "-d", "--build", cwd=clone)
    check("running version 1", serving(clone) == "1")

    from couriercollie import config, sources
    from couriercollie.backend import Backend

    start = run("git", "rev-parse", "HEAD", cwd=clone)
    ID = "github.com/example/board"
    settings = work / "repos.toml"
    config.save(config.Config(repos=[config.TrackedRepo(
        id=ID, name="Board", url="", host="github", follow="branch", branch="main", kind="git", source="scanned",
        local_path=str(clone), installed=start)]), settings)
    sources.releases = lambda ref, host, **_: []
    sources.branches = lambda ref: ("main", [sources.Branch("main", run("git", "rev-parse", "HEAD", cwd=other))])
    sources.compare = lambda ref, host, yours, head: sources.Comparison(
        sources.SAME if yours == head else sources.BEHIND, 1, [])
    b = Backend(settings)

    def at_once(work_, done):
        try:
            result, error = work_(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)
    b._run = at_once  # one thing at a time, so each check follows the last step
    b.loadDetails(ID, True)
    d = b.details(ID)
    check("only install.sh is offered", [c["label"] for c in d["stepChoices"]] == ["Run install.sh"],
          str(d["stepChoices"]))
    command = d["stepChoices"][0]["command"] if d["stepChoices"] else ""
    check("reading it shows install.sh", "install.sh ----" in b.reviewStep(ID, command))

    def push(version, script=None):
        (other / "version").write_text(f"{version}\n")
        if script:
            (other / "install.sh").write_text(script)
        run("git", "commit", "-q", "-am", f"version {version}", cwd=other)
        run("git", "push", "-q", "origin", "HEAD:main", cwd=other)

    # Version 2. The first Update asks first, showing what will run; nothing is done yet.
    push(2)
    asks = []
    b.askStep.connect(lambda repo_id, why: asks.append(why))
    b.updateRepo(ID)
    check("the first Update asks, and waits", asks == ["update"] and b.details(ID)["updateNote"] == "",
          f"{asks} {b.details(ID)['updateNote']}")
    print("approved: pull, then install.sh…")
    b.updateWithStep(ID, command)  # (the window's Update)
    d = b.details(ID)
    check("Update pulled", d["updateNote"] == "Pulled 1 new commit.", d["updateNote"])
    check("…then the step ran and applied it", d["stepResult"] == "applied", d["stepResult"] + d["stepOutput"][-500:])
    check("…its output shown", "web" in d["stepOutput"], d["stepOutput"][-300:])
    check("the containers now run version 2", serving(clone) == "2", serving(clone))

    # Version 3: one click does it all.
    push(3)
    b.updateRepo(ID)
    check("the next Update doesn't ask: version 3", asks == ["update"] and b.details(ID)["stepResult"] == "applied"
          and serving(clone) == "3", f"{asks} {serving(clone)}")

    # Version 4 changes install.sh: not run until it's read and approved again.
    push(4, "#!/bin/sh\nset -e\necho rebuilding\npodman-compose up -d --build --force-recreate\n")
    b.updateRepo(ID)
    d = b.details(ID)
    # (The last run's "Applied" was for version 3: it goes with the new update.)
    check("a changed install.sh stops the step", d["stepChanged"] and d["stepResult"] == ""
          and serving(clone) == "3", f"{d['stepChanged']} {d['stepResult']} {serving(clone)}")
    check("…and the page is asked to show it again", asks == ["update", "changed"], str(asks))
    b.approveStep(ID, d["step"])  # looked at again
    b.runStep(ID)
    check("approved again, it runs: version 4", b.details(ID)["stepResult"] == "applied" and serving(clone) == "4",
          serving(clone))
    b.shutdown()
finally:
    subprocess.run(["podman-compose", "down"], cwd=work / "board", capture_output=True, env=ENV)
    subprocess.run(["podman", "unshare", "rm", "-rf", str(storage)], capture_output=True)
    shutil.rmtree(work, ignore_errors=True)

print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
