"""After Updating, for real: a clone running as containers (podman-compose), its step approved, an update pushed, and
Update clicked. Checks the step rebuilds and restarts the containers, that they then run the new version, and that a
change to the compose file stops the step until it's approved again.

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
    (other / "README.md").write_text("# Board\n\nTo update: pull, then rebuild the containers.\n")
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
    suggested = {s["label"]: s["command"] for s in d["stepChoices"]}
    check("the running containers are found, and rebuilding them offered",
          "Rebuild and restart its containers" in suggested, str(d["stepChoices"]))
    command = suggested.get("Rebuild and restart its containers", "")
    check("…with its own project, compose file and service", command.startswith("podman-compose -p board -f ")
          and command.endswith("docker-compose.yml up -d --build --force-recreate web"), command)
    check("reading it shows the compose file", "docker-compose.yml ----" in b.reviewStep(ID, command))

    # An update: version 2. The first Update asks what runs after it downloads; chosen, it pulls, then rebuilds and
    # restarts the containers.
    (other / "version").write_text("2\n")
    run("git", "commit", "-q", "-am", "version 2", cwd=other)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=other)
    asks = []
    b.askStep.connect(lambda repo_id, why: asks.append(why))
    b.updateRepo(ID)
    check("the first Update asks first", asks == ["update"] and serving(clone) == "1", str(asks))
    print("Update: pull, then rebuild…")
    b.updateWithStep(ID, command)
    d = b.details(ID)
    check("Update pulled", d["updateNote"] == "Pulled 1 new commit.", d["updateNote"])
    check("…then the step ran and applied it", d["stepResult"] == "applied", d["stepResult"] + d["stepOutput"][-500:])
    check("…its output shown", "web" in d["stepOutput"], d["stepOutput"][-300:])
    check("the containers now run version 2", serving(clone) == "2", serving(clone))

    # An update that changes the compose file: not run until approved again.
    (other / "docker-compose.yml").write_text('services:\n  web:\n    build: .\n    command: ["sleep", "7200"]\n')
    (other / "version").write_text("3\n")
    run("git", "commit", "-q", "-am", "version 3, new compose file", cwd=other)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=other)
    b.updateRepo(ID)
    d = b.details(ID)
    # (The last run's "Applied" was for version 2: it goes with the new update.)
    check("a changed compose file stops the step", d["stepChanged"] and d["stepResult"] == ""
          and serving(clone) == "2", f"{d['stepChanged']} {d['stepResult']} {serving(clone)}")
    check("…and the page is asked to show it again", asks == ["update", "changed"], str(asks))
    b.approveStep(ID, d["step"])  # looked at again
    b.runStep(ID)
    check("approved again, it runs: version 3", b.details(ID)["stepResult"] == "applied" and serving(clone) == "3",
          serving(clone))
    b.shutdown()
finally:
    subprocess.run(["podman-compose", "down"], cwd=work / "board", capture_output=True, env=ENV)
    subprocess.run(["podman", "unshare", "rm", "-rf", str(storage)], capture_output=True)
    shutil.rmtree(work, ignore_errors=True)

print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
