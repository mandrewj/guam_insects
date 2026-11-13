"""`guaminsects serve`: the built site on http://localhost, for local use and curation.

A plain static server (the site also works from file://). The admin endpoints that write
curation/*.csv are added here, bound to localhost only, so they never exist on Vercel.
"""

import functools
import http.server
from pathlib import Path


def serve(root: Path, port: int = 8765) -> int:
    if not (root / "index.html").exists():
        print(f"nothing built at {root}; run `uv run guaminsects build {root.name}` first")
        return 1
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root} at http://localhost:{port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
