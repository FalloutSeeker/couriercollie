"""Stands in for GitHub for couriercollie's own project, for devtools/check_self_update.sh: before a release exists,
it answers the API's questions about FalloutSeeker/couriercollie from a folder of real built packages, one folder per
release (RELEASES/v0.6.1/…), newest first by version, each file with its SHA-256 as GitHub gives it. Files are
served from here too. Anything else is "not found".

    python3 github_standin.py RELEASES PORT

The app reaches it through devtools/relay_client.py ($GITHUB_RELAY), as it would GitHub's API.
"""

import hashlib
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RELEASES, PORT = Path(sys.argv[1]), int(sys.argv[2])
PROJECT = "FalloutSeeker/couriercollie"
BASE = f"http://127.0.0.1:{PORT}"


def releases() -> list[dict]:
    def key(folder):
        return [int(n) for n in re.findall(r"\d+", folder.name)]

    listed = []
    for folder in sorted((f for f in RELEASES.iterdir() if f.is_dir()), key=key, reverse=True):
        files = sorted(p for p in folder.iterdir() if p.is_file())
        listed.append({
            "tag_name": folder.name, "name": folder.name, "draft": False, "prerelease": False,
            "published_at": "2026-10-12T12:00:00Z", "body": f"couriercollie {folder.name}",
            "html_url": f"https://github.com/{PROJECT}/releases/tag/{folder.name}",
            "assets": [{"name": p.name, "size": p.stat().st_size,
                        "browser_download_url": f"{BASE}/download/{folder.name}/{p.name}",
                        "digest": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
        })
    return listed


class StandIn(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == f"/repos/{PROJECT}":
            return self.answer({"full_name": PROJECT, "name": "couriercollie", "description": "couriercollie",
                                "default_branch": "main", "homepage": "", "html_url": f"https://github.com/{PROJECT}",
                                "owner": {"login": "FalloutSeeker", "type": "User"}})
        if path == f"/repos/{PROJECT}/releases":
            return self.answer(releases())
        if path.startswith("/download/"):
            file = RELEASES / path.removeprefix("/download/")
            if file.is_file() and RELEASES in file.resolve().parents:
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        self.answer({"message": "Not Found"}, 404)

    def answer(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


print("ready", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), StandIn).serve_forever()
