"""A long session, sped up, to catch memory that keeps growing or CPU that never rests: real projects (GitHub through
devtools/github_relay.py if $GITHUB_RELAY is set), checked again and again, their pages opened and closed, filters
switched, Settings opened. Memory (resident size, Python objects, Qt objects) is measured each round; at the end,
how much CPU the app uses when left alone. Nothing is installed; settings and caches go to a temporary folder.

    python3 -I devtools/check_soak.py [ROUNDS]
"""

import gc
import os
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import relay_client  # noqa: E402,F401

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 40
PROJECTS = ["https://github.com/BurntSushi/ripgrep", "https://github.com/sharkdp/fd", "https://github.com/junegunn/fzf",
            "https://github.com/jesseduffield/lazygit", "https://github.com/neovim/neovim",
            "https://github.com/localsend/localsend", "https://gitlab.com/gitlab-org/cli",
            "https://github.com/tmux-plugins/tpm", "https://github.com/ImranR98/Obtainium",
            "https://github.com/zed-industries/zed"]

h = harness.start(settings={"scanning": True})
b, app, win = h.backend, h.app, h.win
win.resize(1150, 800)


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def settle():
    # Deleted QML objects go on the next turns of the event loop: let them, so they aren't counted as kept.
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(5):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    gc.collect()


def rss_mb():
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def qt_objects():
    # Counting makes a Python wrapper for each Qt object, which then stays: so it's done only twice, after the
    # Python objects are counted.
    from PySide6.QtCore import QObject
    return len(win.findChildren(QObject)) + len(b.findChildren(QObject))


for url in PROJECTS:
    n = len(b._config.repos)
    b.addRepo("", url)
    pump(lambda: not b.adding and len(b._config.repos) > n, 60)
print(f"tracking {len(b._config.repos)} real projects", flush=True)

samples = []
for i in range(ROUNDS):
    b.checkNow()
    pump(lambda: not b.checking, 120)
    for r in list(b._config.repos):
        win.openRepo(r.id)
        pump(lambda: b.details(r.id)["state"] in ("ready", "error"), 60)
        pump(seconds=0.05)
    win.closeRepo()
    for f in ("github", "gitlab", "all"):
        b.filter = f
        pump(seconds=0.02)
    win.openSettings()
    pump(seconds=0.1)
    if (w := h.window("Settings")) is not None:
        w.close()
    settle()
    samples.append((rss_mb(), len(gc.get_objects())))
    if i == ROUNDS // 4:
        qt_warm = qt_objects()
    print(f"round {i + 1:3}: {samples[-1][0]:6.1f} MB, {samples[-1][1]:7} Python objects", flush=True)

# Growth after warming up (the first rounds fill caches: icons, release lists, QML components).
warm, last = samples[ROUNDS // 4], samples[-1]
print(f"after warming up, over {ROUNDS - ROUNDS // 4 - 1} rounds: {last[0] - warm[0]:+.1f} MB, "
      f"{last[1] - warm[1]:+} Python objects, {qt_objects() - qt_warm:+} Qt objects", flush=True)

# Left alone, in Qt's own event loop (which sleeps until something happens): CPU used in 20 seconds.
from PySide6.QtCore import QTimer  # noqa: E402
before = resource.getrusage(resource.RUSAGE_SELF)
QTimer.singleShot(20_000, app.quit)
app.exec()
after = resource.getrusage(resource.RUSAGE_SELF)
busy = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
print(f"idle: {busy:.2f} s of CPU in 20 s ({busy / 20:.1%})", flush=True)
b.shutdown()
