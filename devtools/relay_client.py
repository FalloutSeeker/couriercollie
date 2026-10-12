"""In a test container: send api.github.com's requests to devtools/github_relay.py (address in $GITHUB_RELAY), which
adds your login there. Everything else (downloads, git, GitLab) goes out as usual. Import before making requests."""

import os
import urllib.request

RELAY = os.environ.get("GITHUB_RELAY", "")


class _ToRelay(urllib.request.BaseHandler):
    handler_order = 100  # before the usual HTTPS handler

    def https_open(self, req):
        if req.host != "api.github.com":
            return None  # the usual way
        headers = dict(req.header_items())
        headers.pop("Authorization", None)
        return urllib.request.urlopen(urllib.request.Request(RELAY + req.selector, headers=headers), timeout=60)


if RELAY:
    urllib.request.install_opener(urllib.request.build_opener(_ToRelay))
