"""Lets tests in containers ask GitHub's API with your login (5,000 requests an hour instead of 60), without the
login ever going into a container: this runs here, holds the token (from `gh auth token`) in memory, and passes on
only GET requests for the projects named in the allow-list file (one "owner/name" a line, read on every request).
Containers send api.github.com's requests here instead (devtools/relay_client.py).

    python3 -I devtools/github_relay.py ALLOW_FILE [PORT] [CHAOS_FILE]

With CHAOS_FILE, GitHub misbehaves on purpose: the file holds a number from 0 to 1 (read on every request), the share
of answers turned into something that goes wrong (devtools/check_chaos.sh): an error, a rate limit, a long wait, a
broken or wrong-shaped answer, or the connection dropped partway. Each is printed as "chaos <what> <path>".

Listens on this computer only (127.0.0.1); podman containers reach it as host.containers.internal.
"""

import random
import re
import subprocess
import time
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOW = Path(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 18765
CHAOS = Path(sys.argv[3]) if len(sys.argv) > 3 else None
TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
REPO_PATH = re.compile(r"^/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(/[^?#]*)?(\?.*)?$")
PASSED_ON = ("Accept", "If-None-Match", "User-Agent")
SENT_BACK = ("Content-Type", "ETag", "Link", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining",
             "X-RateLimit-Reset")


def allowed(path: str) -> bool:
    if path == "/rate_limit":
        return True
    m = REPO_PATH.match(path)
    names = {line.strip().lower() for line in ALLOW.read_text().splitlines() if line.strip()}
    return bool(m) and f"{m.group(1)}/{m.group(2)}".lower() in names


def chaos_rate() -> float:
    try:
        return float(CHAOS.read_text().strip() or 0) if CHAOS else 0.0
    except (OSError, ValueError):
        return 0.0


# Answers that aren't what was asked for: JSON of the wrong shape, an HTML page (a captive portal), nothing at all.
WRONG = [b"{}", b'[1, "a", null, {"tag_name": 5, "assets": "x"}]', b'{"message": "chaos"}', b"null",
         b"<html><body>Please log in to the hotel Wi-Fi</body></html>", b"", b'[{"name": null, "commit": {}}]']


class Relay(BaseHTTPRequestHandler):
    def answer(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def chaos(self) -> bool:
        """Something goes wrong instead of the real answer, as often as the chaos file says. True if it did."""
        if random.random() >= chaos_rate():
            return False
        what = random.choice(["500", "502", "ratelimit", "secondary", "429", "slow", "wrong", "cut"])
        print("chaos", what, self.path, flush=True)
        soon = str(int(time.time()) + 5)
        if what in ("500", "502"):
            self.answer(int(what), b'{"message": "Server Error"}')
        elif what == "ratelimit":
            self.answer(403, b'{"message": "API rate limit exceeded"}',
                        [("X-RateLimit-Remaining", "0"), ("X-RateLimit-Reset", soon)])
        elif what == "secondary":
            self.answer(403, b'{"message": "secondary rate limit"}', [("Retry-After", "5")])
        elif what == "429":
            self.answer(429, b"", [("Retry-After", "5")])
        elif what == "slow":
            time.sleep(25)  # longer than the app waits
            self.answer(200, b"[]")
        elif what == "wrong":
            self.answer(200, random.choice(WRONG), [("Content-Type", "application/json")])
        else:  # the connection drops partway through the answer
            self.send_response(200)
            self.send_header("Content-Length", "5000")
            self.end_headers()
            self.wfile.write(b'[{"tag_name": "v1')
        return True

    def do_GET(self):
        if not allowed(self.path):
            self.send_error(403, "Not on the relay's allow-list")
            print("refused:", self.path, flush=True)
            return
        if self.chaos():
            return
        req = urllib.request.Request("https://api.github.com" + self.path,
                                     headers={h: v for h in PASSED_ON if (v := self.headers.get(h))})
        req.add_unredirected_header("Authorization", f"Bearer {TOKEN}")  # not sent on to wherever it redirects
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, headers, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, e.headers, e.read()
        except OSError as e:
            self.send_error(502, str(e))
            return
        print(status, self.path, flush=True)
        self.send_response(status)
        for name in SENT_BACK:
            if value := headers.get(name):
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_PATCH = do_DELETE = do_POST

    def log_message(self, *args):
        pass


print(f"relay on 127.0.0.1:{PORT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Relay).serve_forever()
