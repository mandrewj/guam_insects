"""Downloaded documents (fact sheets, bulletins, open-access papers): sources/documents.csv.

The manifest is in git; the files are not (literature/ is git-ignored: the documents are
copyrighted, CLAUDE.md rule 4). Each row names a file under literature/ that people can
recognise ("ADAP 2000-4 - Coconut rhinoceros beetle (Oryctes rhinoceros).pdf") and the URL
it came from, which is what the public site links to. `fetch` downloads whatever is missing.
"""

import csv
import sys
import time

import httpx

from . import config

MANIFEST = config.SOURCES_DIR / "documents.csv"
COLUMNS = ["file", "url", "title", "authors", "year", "publisher", "series", "status", "note"]


def rows() -> list[dict]:
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch(delay: float = 1.0) -> dict[str, int]:
    stats = {"present": 0, "downloaded": 0, "failed": 0, "link only": 0}
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120,
                      follow_redirects=True) as http:
        for r in rows():
            if not r["file"]:
                stats["link only"] += 1
                continue
            path = config.LITERATURE_DIR / r["file"]
            if path.exists():
                stats["present"] += 1
                continue
            resp = http.get(r["url"])
            time.sleep(delay)
            if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
                print(f"  {resp.status_code} {r['url']}", file=sys.stderr)
                stats["failed"] += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            stats["downloaded"] += 1
    return stats
