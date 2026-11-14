"""`guaminsects serve`: the built site (site.nosync/public) on http://localhost.

The site is static (it also works from file://) and is the same one deployed; this is only
a local web server for it, bound to 127.0.0.1. The taxonomy editor has its own
(`guaminsects edit`, editor.py).
"""

import functools
import http.server
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(root: Path, port: int = 8765) -> int:
    if not (root / "index.html").exists():
        print(f"no site at {root}: run `uv run guaminsects build` first")
        return 1
    handler = functools.partial(Handler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"site at http://localhost:{port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
