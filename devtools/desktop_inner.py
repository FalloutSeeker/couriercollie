"""Run inside a container by devtools/check_desktop.sh, with couriercollie's package installed: the package on a
desktop, as a person gets it. Its files (menu entry, icons), then the installed `couriercollie` command on a virtual
screen (Xvfb, a window manager), with stand-ins for KDE Plasma's tray host and the notification server on its own
session bus (devtools/desktop_host.py): the window and its icon, the tray icon and its menu, a notification, Quit.
Prints PASS/FAIL; screenshots to /out.

    dbus-run-session -- python3 desktop_inner.py DISTRO
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DISTRO = sys.argv[1]
OUT = Path("/out")
APP = Path("/app")  # (only for desktop_host.py: the app itself is the installed package)
SCREEN = (1280, 800)
failures = []


def check(label, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)
    return ok


# Where the packages put the app (the couriercollie command loads it from there): for importing its parts here.
APP_DIR = "/usr/share/couriercollie"


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.2)
    return condition()


home = Path(tempfile.mkdtemp(prefix="home-"))
ENV = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
       "XDG_DATA_HOME": str(home / ".local/share"), "XDG_STATE_HOME": str(home / ".local/state"),
       "XDG_CACHE_HOME": str(home / ".cache"), "XDG_RUNTIME_DIR": str(home / "run"), "DISPLAY": ":99",
       "QT_QPA_PLATFORM": "xcb", "QT_FORCE_STDERR_LOGGING": "1"}
(home / "run").mkdir(parents=True, mode=0o700)


def shot(name, window="root"):
    """A screenshot (ImageMagick 7 is "magick import", 6 just "import")."""
    path = OUT / f"{DISTRO}-{name}.png"
    grab = ["magick", "import"] if shutil.which("magick") else ["import"]
    sh(*grab, "-window", window, str(path), env=ENV)
    if not path.exists():  # (an ImageMagick without X11, as openSUSE's: Qt grabs it instead)
        wid = "0" if window == "root" else str(int(window))
        sh(sys.executable, "-c", "import sys\nfrom PySide6.QtGui import QGuiApplication\n"
           f"app = QGuiApplication(sys.argv)\napp.primaryScreen().grabWindow({wid}).save({str(path)!r})", env=ENV)
    print(f"  screenshot: {path.name}", flush=True)
    return path


# ---- The package's files ----------------------------------------------------------------------------------------------

print(f"=== {DISTRO}: the package's files", flush=True)
command = shutil.which("couriercollie")
check("the couriercollie command is installed", bool(command), str(command))
entry = Path("/usr/share/applications/couriercollie.desktop")
check("its menu entry is installed", entry.is_file())
text = entry.read_text() if entry.is_file() else ""
check("…naming its icon", "Icon=couriercollie\n" in text, text)
if shutil.which("desktop-file-validate"):
    r = sh("desktop-file-validate", str(entry))
    check("…and valid, as the desktop reads it", r.returncode == 0 and not r.stdout.strip(), r.stdout + r.stderr)
sizes = [16, 22, 24, 32, 48, 64, 128, 256, 512]
missing = [s for s in sizes if not Path(f"/usr/share/icons/hicolor/{s}x{s}/apps/couriercollie.png").is_file()]
check("its icon, at every size", not missing, str(missing))
check("…and not the old drawing", not Path("/usr/share/icons/hicolor/scalable/apps/couriercollie.svg").exists())
# By name, as a desktop's icon theme finds it (every theme falls back to hicolor, where the package puts it).
found = sh(sys.executable, "-c", """
import sys
from PySide6.QtGui import QGuiApplication, QIcon
app = QGuiApplication(sys.argv)
QIcon.setThemeSearchPaths(["/usr/share/icons"])
QIcon.setThemeName("hicolor")
icon = QIcon.fromTheme("couriercollie")
print(not icon.isNull(), sorted(s.width() for s in icon.availableSizes()))
from couriercollie import tray
QIcon.setThemeName("")
mine = tray.app_icon()  # (without a theme: the app's own files)
print(sorted(s.width() for s in mine.availableSizes()))
""", env={**ENV, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": APP_DIR})
lines = found.stdout.splitlines() + ["", ""]
check("a desktop's icon theme finds it by name", lines[0].startswith("True"), found.stdout + found.stderr[-300:])
check("…and without one, the app has it at every size", lines[1] == str(sizes), lines[1])

# ---- A stand-in GitLab site: four projects you have v1 of; v2 is out ---------------------------------------------------

SITE = "localhost:8443"
REPOS = [f"{SITE}/team/app{i}" for i in range(1, 5)]


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
config = home / ".config/couriercollie/repos.toml"
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text('categories = []\n\n[settings]\nfirst_launch_done = true\nauto_check = false\ntoasts = true\n'
                  'keep_in_tray = true\ntracked_itself = true\n\n' + "".join(
                      f'[[repos]]\nid = "{r}"\nname = "{r.rsplit("/", 1)[1]}"\nurl = "https://{r}"\nhost = "gitlab"\n'
                      f'follow = "releases"\ninstalled = "v1"\n\n' for r in REPOS))

# ---- The screen, a window manager, and Plasma's tray host and notification server -------------------------------------

xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", f"{SCREEN[0]}x{SCREEN[1]}x24", "-nolisten", "tcp"])
wait_for(lambda: sh("xdpyinfo", env=ENV).returncode == 0)
subprocess.Popen(["openbox"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.Popen(["xsetroot", "-solid", "#4d5a66"], env=ENV)
NOTES = home / "notifications.jsonl"
ENV["NOTIFICATIONS"] = str(NOTES)
host = subprocess.Popen([sys.executable, str(APP / "devtools/desktop_host.py")], env=ENV, stdout=subprocess.PIPE,
                        text=True)
check("a tray host and a notification server are on the session bus", host.stdout.readline().strip() == "ready")

# ---- The installed app ------------------------------------------------------------------------------------------------

print(f"=== {DISTRO}: the installed couriercollie, on a desktop", flush=True)
log = open(OUT / f"{DISTRO}-app.log", "w")
app = subprocess.Popen([command or "couriercollie"], env=ENV, stdout=log, stderr=subprocess.STDOUT)


def window_id():
    ids = sh("xdotool", "search", "--onlyvisible", "--name", "^couriercollie$", env=ENV).stdout.split()
    return ids[0] if ids else ""


check("it starts, with its window", wait_for(lambda: window_id() != "", 30))
time.sleep(3)
win = window_id()
icon_prop = sh("xprop", "-id", win, "_NET_WM_ICON", env=ENV).stdout if win else ""
check("the window carries its icon (the title bar's, and the taskbar's on X11)",
      "_NET_WM_ICON(CARDINAL)" in icon_prop and len(icon_prop) > 1000, icon_prop[:120])
klass = sh("xprop", "-id", win, "WM_CLASS", env=ENV).stdout if win else ""
check("…and says which menu entry it is (the taskbar's icon on Wayland)", "couriercollie" in klass, klass)
shot("1-desktop")
if win:
    shot("2-window", win)

import dbus  # noqa: E402

bus = dbus.SessionBus()
watcher = bus.get_object("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")


def registered():
    return [str(s) for s in watcher.Get("org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems",
                                        dbus_interface="org.freedesktop.DBus.Properties")]


check("its tray icon is registered, as with Plasma's panel", wait_for(lambda: registered() != [], 20))
service = registered()[0] if registered() else ""
name, _, path = service.partition("/") if "/" in service else (service, "", "StatusNotifierItem")
item = bus.get_object(name, "/" + (path or "StatusNotifierItem")) if service else None


def prop(key):
    return item.Get("org.kde.StatusNotifierItem", key, dbus_interface="org.freedesktop.DBus.Properties")


if item:
    pixmaps = prop("IconPixmap")
    check("the tray icon is drawn, at several sizes", len(pixmaps) >= 2, str(len(pixmaps)))
    if pixmaps:
        w, h, data = max(pixmaps, key=lambda p: int(p[0]))
        raw = bytearray(data)  # ARGB32 in network order: to the little-endian layout an image reads
        for i in range(0, len(raw), 4):
            raw[i:i + 4] = raw[i:i + 4][::-1]
        opaque = [raw[i:i + 4] for i in range(0, len(raw), 4) if raw[i + 3] > 128]
        dark = sum(1 for p in opaque if max(p[:3]) < 80)
        light = sum(1 for p in opaque if min(p[:3]) > 200)
        # The collie in its white circle: plenty of black and of white (a blank or generic icon has not both).
        check("…and it's the collie: black on white", len(opaque) > 0 and dark / len(opaque) > 0.2
              and light / len(opaque) > 0.2, f"{len(opaque)} opaque, {dark} dark, {light} light")
        # The icon as the panel receives it, four times as big, to look at.
        (home / "icon.raw").write_bytes(bytes(raw))
        sh(sys.executable, "-c", f"""
from PySide6.QtGui import QImage
data = open("{home}/icon.raw", "rb").read()
QImage(data, {int(w)}, {int(h)}, {int(w) * 4}, QImage.Format.Format_ARGB32).scaled({int(w) * 4}, {int(h) * 4}).save(
    "{OUT}/{DISTRO}-3-tray-icon.png")
""", env={**ENV, "QT_QPA_PLATFORM": "offscreen"})
    menu = bus.get_object(name, str(prop("Menu")))
    _revision, layout = menu.GetLayout(0, -1, [], dbus_interface="com.canonical.dbusmenu")
    labels = {str(child[1].get("label", "")).replace("&", ""): int(child[0]) for child in layout[2]}
    check("its menu: Open, Check Now, Quit", {"Open couriercollie", "Check Now", "Quit"} <= set(labels), str(labels))

# ---- A notification, from the timer's check, with the window out of the way ----------------------------------------

print(f"=== {DISTRO}: a notification", flush=True)
sh("wmctrl", "-c", "couriercollie", env=ENV)
wait_for(lambda: window_id() == "", 5)
NOTES.unlink(missing_ok=True)
said = sh(command or "couriercollie", "--check", env=ENV, timeout=120).stdout.strip()
check("the timer's check is handed to the open app", "checking" in said, said)
check("a notification says what's new", wait_for(lambda: NOTES.exists() and NOTES.read_text().strip() != "", 30))
notes = [json.loads(line) for line in NOTES.read_text().splitlines()] if NOTES.exists() else []
if notes:
    n = notes[-1]
    print(f"  notification: {n.get('summary')!r} / {n.get('body')!r} / icon {n.get('icon')!r} "
          f"{n.get('image_path')!r}", flush=True)
    check("…with couriercollie's icon", "couriercollie" in n.get("icon", "") + n.get("image_path", "")
          + n.get("desktop_entry", ""), str(n)[:300])

# ---- Quit, from the tray icon's menu --------------------------------------------------------------------------------

if item:
    menu.Event(labels.get("Quit", 0), "clicked", dbus.String(""), 0, dbus_interface="com.canonical.dbusmenu")
    check("Quit, from the tray icon's menu, ends it", wait_for(lambda: app.poll() is not None, 15))
if app.poll() is None:
    app.terminate()

# ---- Opened and closed, every way a person does it ------------------------------------------------------------------

print(f"=== {DISTRO}: opened and closed, every way", flush=True)


def launch():
    return subprocess.Popen([command or "couriercollie"], env=ENV, stdout=log, stderr=subprocess.STDOUT)


def copies():
    """couriercollie's processes, from /proc (no pgrep in every image)."""
    found = []
    for d in Path("/proc").iterdir():
        try:
            words = (d / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if d.name.isdigit() and any(w.endswith(b"/couriercollie") or w == b"couriercollie" for w in words):
            found.append(d.name)
    return found


app = launch()
check("started again after Quit", wait_for(lambda: window_id() != "", 30))
sh("wmctrl", "-c", "couriercollie", env=ENV)
check("closing the window (tray on) leaves it running", wait_for(lambda: window_id() == "", 5) and app.poll() is None)
second = launch()
check("starting it again brings its window back…", wait_for(lambda: window_id() != "", 15))
check("…from the copy already running (the second start hands over and ends)",
      wait_for(lambda: second.poll() is not None, 15) and app.poll() is None, str(copies()))
for i in range(5):  # quit and start, quickly
    app.terminate()
    wait_for(lambda: app.poll() is not None, 15)
    app = launch()
    if not wait_for(lambda: window_id() != "", 30):
        break
check("quit and started five times in a row: it starts each time", window_id() != "" and app.poll() is None)
app.kill()  # killed outright: its socket is left behind
wait_for(lambda: app.poll() is not None, 10)
app = launch()
check("killed outright, it starts again (what it left behind doesn't stop it)", wait_for(lambda: window_id() != "", 30))
app.terminate()
wait_for(lambda: app.poll() is not None, 15)
good = config.read_text()
broken = good + "\n[[repos]\nbroken"
config.write_text(broken)
app = launch()
check("with its settings file broken, it still starts", wait_for(lambda: window_id() != "", 30))
time.sleep(3)
shot("4-broken-settings")
check("…and saves nothing over the broken file", config.read_text() == broken)
config.write_text(good)  # fixed by hand while it's open
time.sleep(3)
listed = sh(sys.executable, "-c", f"from couriercollie import config; from pathlib import Path; "
            f"print(sorted(r.id for r in config.load(Path({str(config)!r})).repos))",
            env={**ENV, "PYTHONPATH": APP_DIR}).stdout.strip()
check("…and, fixed by hand, the file still lists your repos", listed == str(sorted(REPOS)), listed)
app.terminate()
check("…and quits normally", wait_for(lambda: app.poll() is not None, 15))
log.close()
warnings = [ln for ln in (OUT / f"{DISTRO}-app.log").read_text().splitlines()
            if any(w in ln.lower() for w in ("warning", "error", "traceback")) and "propagateSizeHints" not in ln]
print(f"  app's warnings: {warnings[:6]}", flush=True)
print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
xvfb.terminate()
sys.exit(1 if failures else 0)
