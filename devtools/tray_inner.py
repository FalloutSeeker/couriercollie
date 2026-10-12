"""Run inside a container by devtools/check_tray.sh: the tray icon, for real, both ways Qt shows one.

1. XEmbed: a virtual screen (Xvfb), a window manager (openbox) and a tray (stalonetray). Clicked with xdotool,
   screenshotted with ImageMagick.
2. StatusNotifierItem (KDE Plasma's way): a stand-in tray host on the session bus (sni_host.py) sees what the app
   offers, and the test clicks it and opens its menu over D-Bus, as Plasma would.

Plus what might break it: closing the window, fast clicks, a second launch, start at login, the tray turned off, no
tray at all, the tray going away while the window is closed, the count changing fast, Quit. Screenshots to /out.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUT = Path("/out")
APP = Path("/app")
SCREEN = (1280, 800)
failures = []


def check(label, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.2)
    return condition()


def shot(name, crop=None):
    path = OUT / f"tray-{name}.png"
    sh("magick", "import", "-window", "root", str(path), env=ENV)
    if crop:  # x, y, w, h: also a close-up, four times as big
        x, y, w, h = crop
        sh("magick", str(path), "-crop", f"{w}x{h}+{x}+{y}", "-filter", "point", "-resize", "400%",
           str(OUT / f"tray-{name}-closeup.png"))
    print(f"  screenshot: {path.name}", flush=True)


# ---- a home of its own, with three updates waiting -------------------------------------------------------------------

home = Path(tempfile.mkdtemp(prefix="home-"))
ENV = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
       "XDG_DATA_HOME": str(home / ".local/share"), "XDG_STATE_HOME": str(home / ".local/state"),
       "XDG_CACHE_HOME": str(home / ".cache"), "XDG_RUNTIME_DIR": str(home / "run"), "DISPLAY": ":99",
       "QT_QPA_PLATFORM": "xcb", "QT_FORCE_STDERR_LOGGING": "1"}
(home / "run").mkdir(parents=True, mode=0o700)
# Four projects on a stand-in GitLab site here (site(), below): you have v1, the newest is v2. No GitHub, so nothing
# here depends on its hourly limit.
SITE = "localhost:8443"
REPOS = [f"{SITE}/team/app{i}" for i in range(1, 5)]


def settings(keep_in_tray=True, start_at_login=False, toasts=True, auto_check=False):
    path = home / ".config/couriercollie/repos.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    repos = "".join(f'[[repos]]\nid = "{r}"\nname = "{r.rsplit("/", 1)[1]}"\nurl = "https://{r}"\nhost = "gitlab"\n'
                    f'follow = "releases"\ninstalled = "v1"\n\n' for r in REPOS)
    path.write_text(f'categories = []\n\n[settings]\nfirst_launch_done = true\n'
                    f'auto_check = {str(auto_check).lower()}\ntoasts = {str(toasts).lower()}\n'
                    f'keep_in_tray = {str(keep_in_tray).lower()}\nstart_at_login = {str(start_at_login).lower()}\n'
                    f'tracked_itself = true\n\n{repos}')


def updates(count):
    """What the background checker would write: `count` of the repos have an update."""
    path = home / ".local/state/couriercollie/checks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    results = {}
    for i in range(count):
        repo = REPOS[i] if i < len(REPOS) else f"{SITE}/team/extra{i}"
        results[repo] = {"status": "update", "text": "Update available: v2", "newest": "v2"}
    # Written as the checker does (a new file, renamed into place), which is what the window watches for.
    tmp = path.with_suffix(".tmp")
    # Checked long ago, so the timer's next check is due.
    tmp.write_text(json.dumps({"last_run": "2026-01-01T00:00:00+00:00", "results": results, "notified": {}}))
    os.replace(tmp, path)


def extra_repos(count):
    """Repos for a count above four, so each update is a tracked repo's."""
    path = home / ".config/couriercollie/repos.toml"
    text = path.read_text()
    for i in range(len(REPOS), count):
        r = f"{SITE}/team/extra{i}"
        text += f'[[repos]]\nid = "{r}"\nname = "extra{i}"\nurl = "https://{r}"\nhost = "gitlab"\ninstalled = "v1"\n\n'
    path.write_text(text)


def launch(*args):
    log = open(OUT / "app.log", "a")
    return subprocess.Popen([sys.executable, "-m", "couriercollie", *args], cwd=APP, env=ENV, stdout=log,
                            stderr=subprocess.STDOUT)


def window_shown():
    return sh("xdotool", "search", "--onlyvisible", "--name", "^couriercollie$", env=ENV).stdout.strip() != ""


def window_id():
    ids = sh("xdotool", "search", "--name", "^couriercollie$", env=ENV).stdout.split()
    return ids[0] if ids else ""


def close_window():
    sh("wmctrl", "-c", "couriercollie", env=ENV)


def gone(process, seconds=8.0):
    return wait_for(lambda: process.poll() is not None, seconds)


# ---- a stand-in GitLab site, over https, with a v2 of each project -----------------------------------------------------


def site():
    import http.server
    import ssl
    import threading

    cert = home / "site.pem"
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
       "-addext", "subjectAltName=DNS:localhost", "-keyout", str(cert), "-out", str(cert))

    class GitLab(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if "/releases" in self.path:
                body = json.dumps([{"tag_name": "v2", "name": "v2", "released_at": "2026-10-10T00:00:00Z",
                                    "description": "New", "assets": {"links": []}}])
                self.send_response(200)
            else:
                body = json.dumps({"message": "404 Not Found"})
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), GitLab)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ENV["SSL_CERT_FILE"] = str(cert)  # the app trusts it, as it would a real site's


site()

# ---- the screen, its window manager, and a tray at the top right ----------------------------------------------------

xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", f"{SCREEN[0]}x{SCREEN[1]}x24", "-nolisten", "tcp"])
wait_for(lambda: sh("xdpyinfo", env=ENV).returncode == 0)
subprocess.Popen(["openbox"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
TRAY_X, TRAY_Y, ICON = SCREEN[0] - 120, 0, 48


def start_tray():
    p = subprocess.Popen(["stalonetray", "--geometry", f"3x1+{TRAY_X}+{TRAY_Y}", "--icon-size", str(ICON),
                          "--background", "#31363b", "--window-type", "dock", "--kludges", "force_icons_size"],
                         env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: sh("xdotool", "search", "--class", "stalonetray", env=ENV).stdout.strip() != "")
    return p


def docked():
    """How many icons the tray holds: the windows inside it."""
    import re

    tray = sh("xdotool", "search", "--class", "stalonetray", env=ENV).stdout.split()
    if not tray:
        return 0
    m = re.search(r"^\s*(\d+) child", sh("xwininfo", "-children", "-id", tray[-1], env=ENV).stdout, re.M)
    return int(m.group(1)) if m else 0


EMPTY = [0]  # the tray's own windows, with no icon in it


def has_icon():
    return docked() > EMPTY[0]


def quit_from_menu(process):
    """Quit, the menu's last item, from the keyboard. If that didn't end it, it's ended anyway, so the next check
    starts clean. Returns whether the menu did it."""
    click_icon(3)
    time.sleep(1)
    sh("xdotool", "key", "Up", "Return", env=ENV)
    if gone(process, 10):
        return True
    process.terminate()
    gone(process, 5)
    return False


def click_icon(button=1):
    sh("xdotool", "mousemove", str(TRAY_X + ICON // 2), str(TRAY_Y + ICON // 2), "click", str(button), env=ENV)


TRAY_AREA = (TRAY_X - 8, TRAY_Y, 128, ICON + 8)
stalonetray = start_tray()
time.sleep(1)
EMPTY[0] = docked()
subprocess.Popen(["xsetroot", "-solid", "#4d5a66"], env=ENV)

print("=== XEmbed tray (stalonetray), with the window manager", flush=True)
settings(keep_in_tray=True)
extra_repos(12)  # twelve tracked, so the count can go past nine
updates(3)
app = launch()
check("the app starts, with its window", wait_for(window_shown, 20))
check("its icon is in the tray", wait_for(has_icon, 10), str(docked()))
time.sleep(1.5)
shot("1-window-and-tray", TRAY_AREA)

sh("xdotool", "mousemove", str(TRAY_X + ICON // 2), str(TRAY_Y + ICON // 2), env=ENV)
time.sleep(2.5)
shot("2-tooltip", (TRAY_X - 260, 0, 380, 110))

close_window()
check("closing the window leaves it running", wait_for(lambda: not window_shown(), 5) and app.poll() is None)
check("…with its icon still in the tray", has_icon())
time.sleep(0.5)
shot("3-window-closed", TRAY_AREA)

click_icon()
check("a click on the icon opens the window", wait_for(window_shown, 5))
time.sleep(1)
sh("xdotool", "windowactivate", "--sync", window_id(), env=ENV)
time.sleep(0.5)
click_icon()
check("another, with the window in front, puts it away", wait_for(lambda: not window_shown(), 5))
for _ in range(20):  # clicked quickly, over and over
    click_icon()
    time.sleep(0.05)
time.sleep(1)
check("twenty fast clicks: still running", app.poll() is None)

if window_shown():
    close_window()
    wait_for(lambda: not window_shown(), 5)
click_icon(3)
time.sleep(1.5)
shot("4-menu", (TRAY_X - 260, 0, 380, 200))
menu_open = sh("xdotool", "search", "--onlyvisible", "--class", "couriercollie", env=ENV).stdout.strip() != ""
check("a right-click opens its menu", menu_open)
state = home / ".local/state/couriercollie/checks.json"
before = state.stat().st_mtime
sh("xdotool", "key", "Down", "Down", "Return", env=ENV)  # Open couriercollie, Check Now
check("Check Now from the menu checks", wait_for(lambda: state.stat().st_mtime != before, 30))
check("…and the window stays closed", not window_shown())

updates(12)
time.sleep(0.2)
subprocess.run([sys.executable, "-c", "print()"])
# The window reads the list only at start; the count comes from the results, which it re-reads when they change.
check("still running after the results changed", wait_for(lambda: app.poll() is None, 2))
time.sleep(2)
shot("5-twelve-updates", TRAY_AREA)
for n in range(40):  # the count changing fast
    updates(n % 5)
    time.sleep(0.05)
updates(3)
time.sleep(2)
check("forty quick changes to the count: still running", app.poll() is None)

second = launch()
check("a second launch opens the window of the one running", wait_for(window_shown, 10))
check("…and doesn't start a second copy", gone(second, 10) and second.returncode == 0, str(second.returncode))
close_window()
wait_for(lambda: not window_shown(), 5)

# The tray goes away while the window is closed (the panel crashed, say): a launch still brings the window back.
stalonetray.kill()
stalonetray.wait()
time.sleep(1)
check("the tray gone: it keeps running", app.poll() is None)
again = launch()
check("…and a launch brings its window back", wait_for(window_shown, 10) and gone(again, 10))
close_window()
stalonetray = start_tray()
check("the tray back: its icon comes back to it", wait_for(has_icon, 10), str(docked()))

check("Quit from the menu ends it", quit_from_menu(app))
check("…and its icon leaves the tray", wait_for(lambda: not has_icon(), 5), str(docked()))
shot("6-quit", TRAY_AREA)

print("=== start at login", flush=True)
settings(keep_in_tray=True, start_at_login=True)
updates(1)
app = launch("--at-login")
check("with the tray: it starts in the tray, no window", wait_for(has_icon, 15) and not window_shown())
time.sleep(1)
shot("7-at-login", TRAY_AREA)
again = launch("--at-login")
check("…started again at login, it leaves the running one be", gone(again, 10) and not window_shown(),
      f"second: {again.returncode}, window: {window_shown()}")
check("…and Quit ends it", quit_from_menu(app))
settings(keep_in_tray=False, start_at_login=True)
app = launch("--at-login")
check("without the tray: at login it opens its window", wait_for(window_shown, 15))
close_window()
check("…and closing it quits", gone(app, 10))

print("=== the tray turned off", flush=True)
settings(keep_in_tray=False)
app = launch()
check("no tray icon", wait_for(window_shown, 15) and not has_icon(), str(docked()))
close_window()
check("closing the window quits", gone(app, 10))

print("=== no tray on the desktop", flush=True)
stalonetray.kill()
stalonetray.wait()
settings(keep_in_tray=True)
app = launch()
check("the tray asked for, but none: it opens its window", wait_for(window_shown, 15))
close_window()
check("…and closing it quits, so it can't run on unseen", gone(app, 10))

# ---- KDE Plasma's way: StatusNotifierItem, over D-Bus ----------------------------------------------------------------

print("=== StatusNotifierItem (KDE Plasma's way), over D-Bus", flush=True)
NOTES = home / "notifications.jsonl"
ENV["NOTIFICATIONS"] = str(NOTES)
host = subprocess.Popen([sys.executable, str(APP / "devtools/desktop_host.py")], env=ENV, stdout=subprocess.PIPE,
                        text=True)
check("a tray host is on the session bus", host.stdout.readline().strip() == "ready")
import dbus  # noqa: E402

bus = dbus.SessionBus()
watcher = bus.get_object("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")


def registered():
    return [str(s) for s in watcher.Get("org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems",
                                        dbus_interface="org.freedesktop.DBus.Properties")]


settings(keep_in_tray=True)
updates(3)
app = launch()
check("the app registers its icon with the host", wait_for(lambda: registered() != [], 20), str(registered()))
service = registered()[0] if registered() else ""
name, _, path = service.partition("/") if "/" in service else (service, "", "StatusNotifierItem")
item = bus.get_object(name, "/" + (path or "StatusNotifierItem"))


def prop(key):
    return item.Get("org.kde.StatusNotifierItem", key, dbus_interface="org.freedesktop.DBus.Properties")


tooltip = prop("ToolTip")
check("its tooltip says the count", str(tooltip[2]) == "couriercollie: 3 updates" or
      "3 updates" in str(tooltip[2]) + str(tooltip[3]), f"{tooltip[2]!r} {tooltip[3]!r}")
pixmaps = prop("IconPixmap")
check("its icon is drawn, at several sizes", len(pixmaps) >= 2, str(len(pixmaps)))
if pixmaps:
    from PySide6.QtGui import QImage  # noqa: E402

    w, h, data = max(pixmaps, key=lambda p: int(p[0]))
    # ARGB32, big-endian (network order), as the spec says.
    image = QImage(bytes(bytearray(data)), int(w), int(h), QImage.Format.Format_ARGB32).rgbSwapped()
    raw = bytearray(data)
    for i in range(0, len(raw), 4):  # big-endian ARGB to the little-endian layout QImage reads
        raw[i:i + 4] = raw[i:i + 4][::-1]
    QImage(bytes(raw), int(w), int(h), int(w) * 4, QImage.Format.Format_ARGB32).scaled(
        int(w) * 4, int(h) * 4).save(str(OUT / "tray-8-plasma-icon.png"))
    print("  screenshot: tray-8-plasma-icon.png (the icon as Plasma receives it, four times as big)", flush=True)
close_window()
wait_for(lambda: not window_shown(), 5)
item.Activate(0, 0, dbus_interface="org.kde.StatusNotifierItem")
check("Plasma's click on it opens the window", wait_for(window_shown, 5))
updates(1)
check("the count it shows follows the results", wait_for(lambda: str(prop("ToolTip")[2]) == "couriercollie: 1 update",
                                                          10), str(prop("ToolTip")[2]))
menu = bus.get_object(name, str(prop("Menu")))
_revision, layout = menu.GetLayout(0, -1, [], dbus_interface="com.canonical.dbusmenu")
labels = {str(child[1].get("label", "")).replace("&", ""): int(child[0]) for child in layout[2]}
check("its menu: Open, Check Now, Quit", {"Open couriercollie", "Check Now", "Quit"} <= set(labels), str(labels))

# ---- Notifications: on updates found while the window isn't in front -------------------------------------------------

print("=== notifications (four projects you have v1 of, on the stand-in site)", flush=True)
tester = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")


def notes():
    return [json.loads(line) for line in NOTES.read_text().splitlines()] if NOTES.exists() else []


def checked_since(moment):
    path = home / ".local/state/couriercollie/checks.json"
    return path.exists() and path.stat().st_mtime > moment


def background_check(*extra):
    """What the timer runs: handed to the app if it's open."""
    return sh(sys.executable, "-m", "couriercollie", "--check", *extra, cwd=APP, env=ENV, timeout=120)


def fresh_results():
    """Nothing announced yet, as on a first check."""
    updates(0)


close_window()
wait_for(lambda: not window_shown(), 5)
fresh_results()
NOTES.unlink(missing_ok=True)
said = background_check().stdout.strip()
check("the timer's check is handed to the open app", said == "couriercollie is open; it's checking.", said)
check("updates found with the window closed: a notification", wait_for(lambda: notes() != [], 60), str(notes()))
note = notes()[0] if notes() else {}
check(f"…saying how many, and which ({note.get('summary')}: {note.get('body')})",
      note.get("summary") == "4 updates available" and note.get("body") == "app1, app2, app3, and app4",
      str(note))
check("…as couriercollie's, with an Open action", note.get("app_name") == "couriercollie" and
      note.get("desktop_entry") == "couriercollie" and "default" in note.get("actions", []), str(note))
if note:
    tester.Click(note["id"], "default", dbus_interface="org.couriercollie.Test")
check("clicking it opens the window", wait_for(window_shown, 10))
time.sleep(1)
shot("9-from-notification")

moment = time.time()
time.sleep(1.1)
background_check()
wait_for(lambda: checked_since(moment), 60)
time.sleep(2)
check("the same updates aren't announced again", len(notes()) == 1, str(len(notes())))

sh("xdotool", "windowactivate", "--sync", window_id(), env=ENV)
fresh_results()
time.sleep(1)
moment = time.time()
time.sleep(1.1)
background_check()
wait_for(lambda: checked_since(moment), 60)
time.sleep(2)
check("with the window in front: no notification (the list shows them)", len(notes()) == 1, str(len(notes())))

if "Quit" in labels:
    menu.Event(labels["Quit"], "clicked", dbus.String("", variant_level=1), 0, dbus_interface="com.canonical.dbusmenu")
    check("Quit from Plasma's menu ends it", gone(app, 10))
    check("…and it leaves the tray", wait_for(lambda: registered() == [], 5), str(registered()))

settings(keep_in_tray=True, toasts=False)
app = launch()
wait_for(window_shown, 20)
close_window()
fresh_results()
moment = time.time()
time.sleep(1.1)
background_check()
wait_for(lambda: checked_since(moment), 60)
time.sleep(2)
check("notifications off in Settings: none", len(notes()) == 1, str(len(notes())))
app.terminate()
gone(app, 10)

# couriercollie closed: the timer's check notifies itself, and a click starts the app.
settings(keep_in_tray=False, auto_check=True)
fresh_results()
NOTES.unlink(missing_ok=True)
background_check("--if-due")
check("couriercollie closed: the timer's check notifies", wait_for(lambda: notes() != [], 30), str(notes()))
if notes():
    tester.Click(notes()[0]["id"], "default", dbus_interface="org.couriercollie.Test")
check("…and clicking it starts couriercollie", wait_for(window_shown, 20))
shot("10-started-from-notification")
sh("pkill", "-f", "python3 -m couriercollie")  # the app it started
close_window()
host.terminate()

for process in (xvfb,):
    process.terminate()
shutil.rmtree(home, ignore_errors=True)
print("FAILURES:", failures or "none", flush=True)
sys.exit(1 if failures else 0)
