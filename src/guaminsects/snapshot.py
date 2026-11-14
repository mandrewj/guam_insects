"""The build's data as a public download, so a push can rebuild the site without the data
machine (CLAUDE.md round 6).

    uv run guaminsects snapshot [--upload]   # on the data machine, after a harvest
    uv run guaminsects restore [--force]      # CI, or a new machine

`snapshot` copies data.nosync/guam.sqlite with every passage of PDF text removed (CLAUDE.md
rule 4: PDFs are in copyright; their facts, citations and page numbers stay, their words go),
compacts it, and packs the card thumbnails. `--upload` puts both on the GitHub release
`data-snapshot` (public: the repository is). `restore` fetches them back into
data.nosync/guam.sqlite and data/media/thumbs.
"""

import gzip
import io
import json
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

from . import config, db

TAG = "data-snapshot"
DB_ASSET = "guam.sqlite.gz"
THUMBS_ASSET = "thumbs.tar"
INFO_ASSET = "snapshot.json"
OUT_DIR = config.LOCAL_DIR / "snapshot"
RELEASE_URL = "https://github.com/{repo}/releases/download/" + TAG + "/{asset}"
# Columns that hold text copied out of a PDF. Any column of these names, in any table, is
# emptied (a table added later with a snippet is caught too).
PDF_TEXT_COLUMNS = {"snippet", "context", "excerpt", "quote", "page_text"}


def strip(conn: sqlite3.Connection) -> dict[str, int]:
    """Empty every PDF-text column; returns {table.column: rows emptied}."""
    out = {}
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for t in tables:
        for col in [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]:
            if col.lower() in PDF_TEXT_COLUMNS:
                n = conn.execute(f"UPDATE {t} SET {col} = NULL WHERE {col} IS NOT NULL").rowcount
                out[f"{t}.{col}"] = n
    conn.commit()
    return out


def make(out_dir: Path = OUT_DIR) -> dict:
    if not config.DB_PATH.exists():
        raise SystemExit(f"no database at {config.DB_PATH}")
    from .enrich.photos import THUMB_DIR

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "guam.sqlite"
    tmp.unlink(missing_ok=True)
    src = db.connect()
    dst = sqlite3.connect(tmp)
    src.backup(dst)                      # a consistent copy, even with a writer running
    src.close()
    dst.execute("PRAGMA journal_mode = DELETE")
    emptied = strip(dst)
    leftover = [f"{t}.{c}" for t, c in _text_columns(dst)
                if dst.execute(f"SELECT 1 FROM {t} WHERE {c} IS NOT NULL LIMIT 1").fetchone()]
    if leftover:
        raise SystemExit(f"PDF text left in {leftover}; not making a snapshot")
    counts = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("taxa", "taxon_presence", "photos", "pdf_mentions")}
    dst.execute("VACUUM")
    dst.close()
    with tmp.open("rb") as f, gzip.open(out_dir / DB_ASSET, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    tmp.unlink()
    thumbs = sorted(THUMB_DIR.glob("*.webp")) if THUMB_DIR.exists() else []
    with tarfile.open(out_dir / THUMBS_ASSET, "w") as tar:   # webp: already compressed
        for p in thumbs:
            tar.add(p, arcname=p.name)
    info = {"made": db.now(), "emptied": emptied, "counts": counts, "thumbs": len(thumbs),
            "sizes_mb": {a: round((out_dir / a).stat().st_size / 1e6, 1)
                         for a in (DB_ASSET, THUMBS_ASSET)}}
    (out_dir / INFO_ASSET).write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def _text_columns(conn) -> list[tuple[str, str]]:
    return [(t, c) for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            for c in [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            if c.lower() in PDF_TEXT_COLUMNS]


def upload(out_dir: Path = OUT_DIR, repo: str | None = None) -> None:
    """Put the snapshot on the release (made once), replacing the previous files. Uses gh."""
    from .editor import REPO

    repo = repo or REPO
    files = [str(out_dir / a) for a in (DB_ASSET, THUMBS_ASSET, INFO_ASSET)]
    have = subprocess.run(["gh", "release", "view", TAG, "--repo", repo], capture_output=True)
    if have.returncode:
        subprocess.run(["gh", "release", "create", TAG, "--repo", repo, "--latest=false",
                        "--title", "Data snapshot (for rebuilds)", "--notes",
                        "The build's database (PDF text removed) and card thumbnails, "
                        "replaced after each harvest. Made by `guaminsects snapshot --upload`; "
                        "read by `guaminsects restore` and the rebuild workflow."],
                       check=True)
    subprocess.run(["gh", "release", "upload", TAG, "--repo", repo, "--clobber", *files],
                   check=True)


def restore(repo: str | None = None, force: bool = False) -> dict:
    """Download the snapshot into data.nosync/guam.sqlite and data/media/thumbs."""
    import httpx

    from .editor import REPO
    from .enrich.photos import THUMB_DIR

    repo = repo or REPO
    if config.DB_PATH.exists() and not force:
        raise SystemExit(f"{config.DB_PATH} exists; --force replaces it")

    def get(asset: str) -> bytes:
        url = RELEASE_URL.format(repo=repo, asset=asset)
        r = httpx.get(url, follow_redirects=True, timeout=600)
        r.raise_for_status()
        return r.content

    info = json.loads(get(INFO_ASSET))
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.DB_PATH.with_suffix(".restoring")
    tmp.write_bytes(gzip.decompress(get(DB_ASSET)))
    for suffix in ("-wal", "-shm"):
        Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
    tmp.replace(config.DB_PATH)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(get(THUMBS_ASSET))) as tar:
        for m in tar.getmembers():
            if m.isfile() and "/" not in m.name and m.name.endswith(".webp"):
                (THUMB_DIR / m.name).write_bytes(tar.extractfile(m).read())
                n += 1
    return {"made": info.get("made"), "thumbs": n, "db": str(config.DB_PATH)}
