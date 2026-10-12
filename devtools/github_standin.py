"""Stands in for GitHub's API for devtools/check_self_update.sh, for projects whose releases are folders of real
files here (a release before it exists, or one set up for a test): RELEASES/<owner>__<name>/<tag>/<files>. Releases
are listed newest first by version, each file with its SHA-256 as GitHub gives it, and the files are served from
here too. Anything else is "not found". The folders are read on every request, so a test can change them as it goes.

A release folder can also hold markers, to set up what can go wrong:
    .prerelease   the release is a pre-release (a test version)
    .nodigest     GitHub gives no checksum for its files (as for releases from before it did)
    .baddigest    the checksum GitHub gives doesn't match the file
    .truncate     a download stops halfway (the connection dropped)

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
BASE = f"http://127.0.0.1:{PORT}"


def project_folder(owner: str, name: str) -> Path | None:
    folder = RELEASES / f"{owner}__{name}"
    return folder if folder.is_dir() else None


def releases(owner: str, name: str) -> list[dict]:
    def key(folder):
        return [int(n) for n in re.findall(r"\d+", folder.name)]

    listed = []
    project = project_folder(owner, name)
    for folder in sorted((f for f in project.iterdir() if f.is_dir()), key=key, reverse=True):
        files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))

        def digest(p):
            if (folder / ".nodigest").exists():
                return None
            if (folder / ".baddigest").exists():
                return "sha256:" + "0" * 64
            return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()

        listed.append({
            "tag_name": folder.name, "name": folder.name, "draft": False,
            "prerelease": (folder / ".prerelease").exists(),
            "published_at": "2026-10-12T12:00:00Z", "body": f"{name} {folder.name}",
            "html_url": f"https://github.com/{owner}/{name}/releases/tag/{folder.name}",
            "assets": [{"name": p.name, "size": p.stat().st_size, "digest": digest(p),
                        "browser_download_url": f"{BASE}/download/{owner}__{name}/{folder.name}/{p.name}"}
                       for p in files],
        })
    return listed


class StandIn(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if m := re.fullmatch(r"/repos/([^/]+)/([^/]+)", path):
            if project_folder(*m.groups()):
                owner, name = m.groups()
                return self.answer({"full_name": f"{owner}/{name}", "name": name, "description": name,
                                    "default_branch": "main", "homepage": "",
                                    "html_url": f"https://github.com/{owner}/{name}",
                                    "owner": {"login": owner, "type": "User"}})
        if (m := re.fullmatch(r"/repos/([^/]+)/([^/]+)/releases", path)) and project_folder(*m.groups()):
            return self.answer(releases(*m.groups()))
        if path.startswith("/download/"):
            file = RELEASES / path.removeprefix("/download/")
            if file.is_file() and RELEASES.resolve() in file.resolve().parents:
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                cut = (file.parent / ".truncate").exists()
                self.wfile.write(body[: len(body) // 2] if cut else body)
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
