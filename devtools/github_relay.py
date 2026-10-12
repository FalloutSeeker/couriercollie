"""Lets tests in containers ask GitHub's API with your login (5,000 requests an hour instead of 60), without the
login ever going into a container: this runs here, holds the token (from `gh auth token`) in memory, and passes on
only GET requests for the projects named in the allow-list file (one "owner/name" a line, read on every request).
Containers send api.github.com's requests here instead (devtools/relay_client.py).

    python3 -I devtools/github_relay.py ALLOW_FILE [PORT]

Listens on this computer only (127.0.0.1); podman containers reach it as host.containers.internal.
"""

import re
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOW = Path(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 18765
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


class Relay(BaseHTTPRequestHandler):
    def do_GET(self):
        if not allowed(self.path):
            self.send_error(403, "Not on the relay's allow-list")
            print("refused:", self.path, flush=True)
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
