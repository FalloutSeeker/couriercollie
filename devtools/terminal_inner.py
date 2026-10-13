"""When couriercollie hands over to a terminal, and how it carries on after: in a container (devtools/check_terminal.sh),
as an ordinary user ("tester", password "pw", with sudo), with real clones of real projects (one each: clones of the
same project would be one tracked repo).
What the app says to run in a terminal is run in one (a pseudo-terminal, the password typed as a person would), then
the app is used as it would be next: Refresh, Update again.

- A step after updating that asks for a password: typed in the password window, or (cancelled) run in a terminal.
- A clone that belongs to another user: pulled as that user, in a terminal; then Refresh.
- A clone with commits of its own: combined by hand (git pull --rebase); then Refresh.
- Files you changed that the update changes too: stashed in a terminal; then Update again.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/devtools")
import relay_client  # noqa: E402,F401  (GitHub's API through the relay)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from couriercollie.backend import Backend  # noqa: E402

HOME = Path.home()
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)


def pump(cond, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def in_terminal(line: str, password: bool = False) -> str:
    """Run a line as you would in a terminal: in a pseudo-terminal, typing the password once it's asked for (sudo
    throws away anything typed before its prompt)."""
    import pty
    import select

    print(f"  $ {line}", flush=True)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("sh", ["sh", "-c", line])
    out, typed, end = b"", False, time.monotonic() + 120
    while time.monotonic() < end:
        if select.select([fd], [], [], 0.2)[0]:
            try:
                chunk = os.read(fd, 4096)
            except OSError:  # it finished
                break
            if not chunk:
                break
            out += chunk
        if password and not typed and b"password" in out.lower():
            os.write(fd, b"pw\n")
            typed = True
    os.waitpid(pid, 0)
    text = out.decode(errors="replace").replace("\r", "").strip()
    print("    " + "\n    ".join(text.splitlines()[-3:]), flush=True)
    return text


SETTINGS = HOME / ".config/couriercollie/repos.toml"
b = Backend(SETTINGS)
b.updateSettings({"firstLaunchDone": True, "scanning": True})
b.addScanFolder("/srv")
b.startScan()
pump(lambda: b.scanState == "done", 300)
b.trackFound([i["key"] for i in b.scanItems if i["status"] == "new"])
pump(lambda: not b.checking, 300)
by_path = {r.local_path: r.id for r in b._config.repos}
print("tracked:", sorted(by_path), flush=True)


def repo_at(path):
    rid = by_path.get(str(path))
    if not rid:
        check(f"the scan found {path}", False, sorted(by_path))
    return rid


def update(rid):
    b.updateRepo(rid)
    pump(lambda: not b.details(rid)["updating"] and not b.details(rid).get("stepRunning"), 300)
    return b.details(rid)


def refresh(rid):
    b.loadDetails(rid, True)
    pump(lambda: b.details(rid)["state"] == "ready" and not b.details(rid).get("comparing"))
    return b.details(rid)


# ---- 1. A step after updating that asks for a password --------------------------------------------------------------
print("=== a step after updating that asks for a password", flush=True)
mine = HOME / "src/tpm"
rid = repo_at(mine)
if rid:
    from couriercollie import integration

    # The password window, answered as a person would: here by a stand-in for it (no one to click in a container).
    answers = HOME / "answer"
    helper = HOME / "fake-couriercollie"
    helper.write_text(f'#!/bin/sh\n[ "$1" = --askpass ] || exit 2\necho "$COURIERCOLLIE_STEP" > {HOME}/asked-for\n'
                      f'[ -s {answers} ] && cat {answers} || exit 1\n')
    helper.chmod(0o755)
    integration.LAUNCHER = helper
    answers.write_text("pw\n")
    from couriercollie import applying

    # A step approved before that uses sudo (as an earlier version let one be typed, or a project's script would).
    repo = b._config.find(rid)
    repo.apply_command = "sudo sh -c 'date +%s%N > /srv/applied'"
    repo.apply_approved = applying.fingerprint(repo.local_path, repo.apply_command)
    d = update(rid)
    print(f"  update: {d['updateNote']} / step: {d['stepResult']}", flush=True)
    check("the step ran after the update, and sudo asked in the password window",
          (HOME / "asked-for").read_text().strip() == b._config.find(rid).name, (HOME / "asked-for").exists())
    check("…typed there, the step did its work", d["stepResult"] == "applied" and Path("/srv/applied").exists(),
          (d["stepResult"], d["stepOutput"][-200:]))
    # Cancelled: the window gives no password, the step stops, and the terminal is there instead.
    answers.write_text("")
    subprocess.run(["sudo", "-k"])  # (sudo forgets the password it just had)
    b.runStep(rid)
    pump(lambda: not b.details(rid).get("stepRunning"))
    d = b.details(rid)
    check("cancelled, the step stops, and says to run it again or in a terminal", d["stepResult"] == "password",
          (d["stepResult"], d["stepOutput"][-200:]))
    before = Path("/srv/applied").read_text()
    in_terminal(d["stepTerminalLine"], password=True)
    check("…and its command can be run in a terminal instead", Path("/srv/applied").read_text() != before)

# ---- 2. A clone that belongs to another user -------------------------------------------------------------------------
print("=== a clone that belongs to another user", flush=True)
theirs = Path("/srv/zsh-autosuggestions")
rid = repo_at(theirs)
if rid:
    d = refresh(rid)
    print(f"  before: {d['headline']} / {b.repo(rid)['checkText']}", flush=True)
    check("it says whose it is, and offers no Update", d["theirs"] == "other" and not d["canUpdate"]
          and not b.repo(rid)["canUpdate"], (d["theirs"], d["canUpdate"]))
    # They update it themselves (here: in a terminal, through sudo, as them).
    in_terminal(f"sudo -u other sh -c 'cd {theirs} && git pull --ff-only'", password=True)
    d = refresh(rid)
    check("after they pull, Refresh says it's up to date", d["statusKind"] == "current", (d["headline"], d["status"]))
    b.checkNow()
    pump(lambda: not b.checking)
    check("…and so does the list", b.repo(rid)["checkText"] == "Up to date", b.repo(rid)["checkText"])

# ---- 3. A clone with commits of its own ------------------------------------------------------------------------------
print("=== a clone with commits of its own", flush=True)
diverged = HOME / "src/vim-fugitive"
rid = repo_at(diverged)
if rid:
    d = update(rid)
    print(f"  update: {d['updateNote']}", flush=True)
    check("Update leaves it, and says to combine them by hand", "commits of its own" in d["updateNote"],
          d["updateNote"])
    in_terminal(f"cd {diverged} && git pull --rebase")
    d = refresh(rid)
    print(f"  after combining: {d['headline']} / {d['status']} / list: {b.repo(rid)['checkText']}", flush=True)
    check("after combining them, Refresh says it has everything (and its own commit on top)",
          d["statusKind"] in ("current", "ahead") and not d["updateAvailable"], (d["headline"], d["status"]))

# ---- 4. Files you changed that the update changes too ----------------------------------------------------------------
print("=== files you changed that the update changes too", flush=True)
changed = HOME / "src/vim-plug"
rid = repo_at(changed)
if rid:
    d = update(rid)
    print(f"  update: {d['updateNote']}", flush=True)
    check("Update leaves it, and says to commit or stash them", "Commit or stash" in d["updateNote"], d["updateNote"])
    in_terminal(f"cd {changed} && git stash")
    d = update(rid)
    print(f"  update again: {d['updateNote']}", flush=True)
    note = d["updateNote"]
    d = refresh(rid)
    check("stashed, Update again works", d["statusKind"] == "current" and "Pulled" in note, (note, d["headline"]))

b.shutdown()
print(f"=== {len(failures)} failures", flush=True)
sys.exit(1 if failures else 0)
