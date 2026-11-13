"""Small throttled JSON client for public APIs (GBIF, iNaturalist, Wikipedia, Wikidata).

Ported from entobase as is, plus `get_cached`: answers are kept under data/raw/ so a re-run
(or a rebuild of the database from scratch) does not repeat the network work.
"""

import hashlib
import json
import time
import urllib.parse
from pathlib import Path

import httpx

from .. import config

# Seconds to wait after a 429 or 5xx, multiplied by the attempt number. GBIF's transient
# 503s clear in seconds.
RETRY_WAIT = 5
THROTTLE_WAIT = 30     # per attempt, after a 429 with no Retry-After header


class ApiClient:
    def __init__(self, base: str, min_interval: float = 1.0):
        self.base = base
        self.min_interval = min_interval
        self._last = 0.0
        self.requests = 0
        self._http = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=60)

    def _fetch(self, path: str, params: dict | list | None, attempts: int = 4) -> httpx.Response:
        r = None
        for attempt in range(attempts):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            r = self._http.get(self.base + path, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < attempts - 1:
                    if r.status_code == 429:
                        # iNaturalist throttles per minute ("normal_throttling"), and 5-15 s
                        # never outlasts it: wait as long as the server says, else 30 s a try.
                        try:
                            wait = float(r.headers.get("Retry-After", ""))
                        except ValueError:
                            wait = THROTTLE_WAIT * (attempt + 1)
                        time.sleep(min(wait, 120))
                    else:
                        time.sleep(RETRY_WAIT * (attempt + 1))  # back off, then retry
                continue
            return r
        r.raise_for_status()
        raise RuntimeError(f"giving up on {self.base + path}: HTTP {r.status_code}")

    def get(self, path: str = "", params: dict | list | None = None) -> dict:
        r = self._fetch(path, params)
        r.raise_for_status()
        return r.json()

    def get_cached(self, path: str = "", params: dict | list | None = None,
                   refresh: bool = False) -> dict:
        """`get`, answered from data/raw/ when this exact request was made before."""
        cache = cache_path(self.base + path, params)
        if cache.exists() and not refresh:
            return json.loads(cache.read_text())
        data = self.get(path, params)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(cache)
        return data

    def get_bytes(self, path: str, params: dict | None = None,
                  attempts: int = 4) -> bytes | None:
        """Raw body, or None for 204/404 (e.g. an empty map tile)."""
        r = self._fetch(path, params, attempts)
        if r.status_code in (204, 404):
            return None
        r.raise_for_status()
        return r.content

    def close(self) -> None:
        self._http.close()


def cache_path(url: str, params: dict | list | None = None, root: Path | None = None) -> Path:
    """data/raw/<host>/<path>/<readable query or hash>.json for one GET request."""
    parts = urllib.parse.urlsplit(url)
    items = sorted(params.items() if isinstance(params, dict) else (params or []))
    query = urllib.parse.urlencode(items)
    stem = query if 0 < len(query) <= 120 and "/" not in query else ""
    if not stem:
        stem = hashlib.sha256(query.encode()).hexdigest()[:24] if query else "index"
    safe = "".join(c if c.isalnum() or c in "=&-_.,+%" else "_" for c in stem)
    return (root or config.RAW_DIR) / parts.netloc / parts.path.strip("/") / f"{safe}.json"
