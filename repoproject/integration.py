"""How the app fits into the desktop: its menu entry, notifications, the taskbar badge, background checks on a
timer, and only one copy running at a time.

These change things outside the app (files in your home folder, a systemd user timer), so each is small, does one
thing, and is easy to undo: delete the menu entry, or turn automatic checks off.
"""

import os
import shutil
import socket
import subprocess
from pathlib import Path

APP_ID = "repoproject"
PROJECT = Path(__file__).resolve().parent.parent
LAUNCHER = PROJECT / "run.sh"
ICON = "system-software-update"
TIMER = "repoproject-check"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


# ---------------------------------------------------------------------------------------------------------------------
# Menu entry


def menu_entry_path() -> Path:
    return _data_home() / "applications" / f"{APP_ID}.desktop"


def menu_entry_text() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=RepoProject\n"
        "GenericName=Update Tracker\n"
        "Comment=Keep track of software from GitHub and GitLab, and hear about updates\n"
        f"Exec={LAUNCHER}\n"
        f"Icon={ICON}\n"
        "Terminal=false\n"
        "Categories=System;Utility;\n"
    )


def install_menu_entry() -> bool:
    """Write the menu entry if it's missing or out of date (e.g. the project folder moved). Returns True if written.
    Notifications and the taskbar badge use it to know which app they belong to."""
    path, text = menu_entry_path(), menu_entry_text()
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------------------------------------------------
# Notifications


def notify_command(title: str, body: str) -> list[str] | None:
    """A notify-send command with an "Open" action. When the notification is clicked, it prints "default" and exits.
    None if notify-send isn't installed."""
    tool = shutil.which("notify-send")
    if not tool:
        return None
    return [tool, "--app-name=RepoProject", f"--icon={ICON}", f"--hint=string:desktop-entry:{APP_ID}",
            "--action=default=Open", title, body]


def notify_and_open_on_click(title: str, body: str) -> bool:
    """For the background checker (the window isn't open): show a notification, and open the app if it's clicked.
    Runs on its own, so the checker can finish without waiting for a click."""
    command = notify_command(title, body)
    if not command:
        return False
    script = 'out=$("$@"); [ "$out" = default ] && exec "$REPOPROJECT_LAUNCHER"'
    subprocess.Popen(["sh", "-c", script, "sh", *command], start_new_session=True,
                     env={**os.environ, "REPOPROJECT_LAUNCHER": str(LAUNCHER)},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def updates_message(names: list[str]) -> tuple[str, str]:
    """("2 updates available", "AeroThemePlasma and SMOD")."""
    title = "1 update available" if len(names) == 1 else f"{len(names)} updates available"
    if len(names) <= 2:
        body = " and ".join(names)
    elif len(names) <= 4:
        body = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        body = ", ".join(names[:3]) + f", and {len(names) - 3} more"
    return title, body


# ---------------------------------------------------------------------------------------------------------------------
# Only one copy: the running app listens here; a second launch, or the background checker, talks to it


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP_ID}-{os.getuid()}"
    return Path(runtime) / f"{APP_ID}.socket"


def tell_running_app(message: str) -> bool:
    """Send "show" or "check" to the running app. False if it isn't running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(str(socket_path()))
            s.sendall(message.encode() + b"\n")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------------------------------------------------
# Background checks: a systemd user timer


def _unit_dir() -> Path:
    return _config_home() / "systemd" / "user"


def unit_texts() -> dict[str, str]:
    """The timer wakes up hourly, after a missed hour (the computer was off), and a few minutes after login. The
    checker then only checks if the chosen interval has passed since the last check (checker.due), so the interval
    is counted from the last check, and a missed check happens soon after the next login."""
    return {
        f"{TIMER}.service": (
            "[Unit]\n"
            "Description=RepoProject: check tracked repos for updates\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={LAUNCHER} --check --if-due\n"
            # When the check finishes, stop only the checker: the notification it showed keeps a small helper
            # waiting for a click (to open the app), which systemd would otherwise stop too.
            "KillMode=process\n"
        ),
        f"{TIMER}.timer": (
            "[Unit]\n"
            "Description=RepoProject: check for updates when due\n\n"
            "[Timer]\n"
            "OnStartupSec=3min\n"
            "OnCalendar=hourly\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        ),
    }


def _systemctl(*args: str) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def set_background_checks(on: bool, systemctl=_systemctl) -> bool:
    """Turn the timer on (writing its files) or off (removing them). Returns True if systemd accepted it."""
    folder = _unit_dir()
    if on:
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in unit_texts().items():
            path = folder / name
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
        return systemctl("daemon-reload") and systemctl("enable", "--now", f"{TIMER}.timer")
    stopped = systemctl("disable", "--now", f"{TIMER}.timer")
    for name in unit_texts():
        (folder / name).unlink(missing_ok=True)
    systemctl("daemon-reload")
    return stopped
