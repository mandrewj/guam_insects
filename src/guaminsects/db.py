"""SQLite connection and small shared helpers."""

import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from . import config


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Columns added after the first release: (table, column, definition). schema.sql already
# has them for new databases; existing databases get them via ALTER TABLE.
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("taxa", "verified", "INTEGER NOT NULL DEFAULT 0"),
    ("taxa", "ext_id", "TEXT"),
    ("taxa", "in_col", "INTEGER NOT NULL DEFAULT 1"),
    ("taxa", "match_note", "TEXT"),
    ("taxa", "extra", "TEXT"),
]


def connect(path: Path = config.DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA journal_mode = WAL")
    for table, column, ddl in ADDED_COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.executescript(files("guaminsects").joinpath("schema.sql").read_text())
    return conn


def keymap(conn) -> dict[int, int]:
    """Any key a source row carries (a COL id, a GBIF Backbone key, a name- id) -> the
    displayed taxon it belongs to (`taxon_keys`, written by resolve)."""
    return dict(conn.execute("SELECT key, taxon_id FROM taxon_keys"))


def lineages(parents: dict[int, int | None]) -> dict[int, str]:
    """'/root/…/id/' for every id, walking `parents` up to a root (or a cycle, or a gap)."""
    lineage: dict[int, str] = {}
    for start in parents:
        if start in lineage:
            continue
        chain, seen, cur = [], set(), start
        while cur is not None and cur in parents and cur not in seen and cur not in lineage:
            seen.add(cur)
            chain.append(cur)
            cur = parents[cur]
        path = lineage.get(cur, "/") if cur is not None else "/"
        for tid in reversed(chain):
            path += f"{tid}/"
            lineage[tid] = path
    return lineage
