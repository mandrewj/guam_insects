"""Read, check and write the dataset tables (`dataset/`, schema.py).

Writing is deterministic (sorted rows, fixed column order, UTF-8 with a BOM, `\\n` line
endings, minimal quoting), so a table written twice is the same bytes and a git diff shows
only what changed. `check` reports every problem at once.
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, geo, ids, schema
from .schema import SEP, Problems

DATASET_DIR = config.ROOT / "dataset"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL = re.compile(r"https?://\S+")


@dataclass
class Dataset:
    tables: dict[str, list[dict]] = field(default_factory=dict)
    wikipedia: list[dict] = field(default_factory=list)
    root: Path = DATASET_DIR

    def __getitem__(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def __setitem__(self, name: str, rows: list[dict]) -> None:
        self.tables[name] = rows


# --- reading -------------------------------------------------------------------------------

def read_csv(path: Path, names: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in names if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {', '.join(missing)}")
        return [{c: (r.get(c) or "") for c in names} for r in reader]


def load(root: Path | None = None) -> Dataset:
    root = root or DATASET_DIR
    ds = Dataset(root=root)
    for t in schema.TABLES:
        ds[t.name] = read_csv(root / t.file, t.names)
    wp = root / schema.WIKIPEDIA_FILE
    if wp.exists():
        ds.wikipedia = [json.loads(line) for line in wp.read_text("utf-8").splitlines() if line]
    return ds


# --- ordering ------------------------------------------------------------------------------

def tid(ext: str) -> int:
    """Sort position of a taxon id; an invalid id sorts last (check reports it)."""
    try:
        return ids.to_int(ext)
    except ValueError:
        return 1 << 62


def sort_taxa(rows: list[dict]) -> list[dict]:
    """Depth first, children by name, each taxon's synonym rows right after it."""
    accepted = [r for r in rows if r["status"] != "synonym"]
    by_id = {r["id"]: r for r in accepted}
    kids: dict[str, list[dict]] = {}
    for r in accepted:
        kids.setdefault(r["parent_id"], []).append(r)
    names: dict[str, list[dict]] = {}
    for r in rows:
        if r["status"] == "synonym":
            names.setdefault(r["accepted_id"], []).append(r)
    out, seen = [], set()
    roots = [r for r in accepted if not r["parent_id"] or r["parent_id"] not in by_id]
    stack = sorted(roots, key=lambda r: (r["parent_id"] != "", r["name"].casefold(), tid(r["id"])),
                   reverse=True)
    while stack:
        r = stack.pop()
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
        out += sorted(names.get(r["id"], []), key=lambda n: (n["name"].casefold(), tid(n["id"])))
        stack += sorted(kids.get(r["id"], []), key=lambda k: (k["name"].casefold(), tid(k["id"])),
                        reverse=True)
    out += [r for r in rows if r["status"] == "synonym" and r["accepted_id"] not in by_id]
    out += [r for r in accepted if r["id"] not in seen]       # a cycle: check reports it
    return out


def sort_rows(t: schema.Table, rows: list[dict]) -> list[dict]:
    if t.name == "taxa":
        return sort_taxa(rows)
    taxon = "taxon_id" in t.names

    def key(r):
        parts = [tid(r["taxon_id"])] if taxon else []
        for c in (t.sort or t.key):
            if c == "taxon_id":
                continue
            v = r[c]
            parts.append((0, int(v), "") if v.isdigit() and c in ("position", "year") else
                         (1, 0, v.casefold(), v))
        return parts

    return sorted(rows, key=key)


# --- writing -------------------------------------------------------------------------------

def to_csv(t: schema.Table, rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(t.names)
    for r in sort_rows(t, rows):
        w.writerow([r.get(c, "") for c in t.names])
    return buf.getvalue()


def write_text(path: Path, text: str, bom: bool = True) -> bool:
    data = (("﻿" if bom else "") + text).encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def wikipedia_text(rows: list[dict]) -> str:
    return "".join(json.dumps({f: r.get(f) for f in schema.WIKIPEDIA_FIELDS}, ensure_ascii=False,
                              separators=(",", ":")) + "\n"
                   for r in sorted(rows, key=lambda r: tid(r["taxon_id"])))


def write(ds: Dataset, root: Path | None = None) -> dict[str, bool]:
    """Write every table; returns which files changed."""
    root = root or ds.root
    changed = {}
    for t in schema.TABLES:
        rows = ds[t.name] = [{c: "" if r.get(c) is None else str(r.get(c)) for c in t.names}
                             for r in ds[t.name]]
        if not rows and not (root / t.file).exists():
            continue
        changed[t.file] = write_text(root / t.file, to_csv(t, rows))
    changed[schema.WIKIPEDIA_FILE] = write_text(root / schema.WIKIPEDIA_FILE,
                                                wikipedia_text(ds.wikipedia), bom=False)
    return changed


# --- checking ------------------------------------------------------------------------------

def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def copies(note: str, text: str, n: int = 8) -> str | None:
    """The first run of n consecutive words a note shares with the document's text, if any."""
    w = words(note)
    if len(w) < n:
        return None
    haystack = " " + " ".join(words(text)) + " "
    for i in range(len(w) - n + 1):
        run = " ".join(w[i:i + n])
        if f" {run} " in haystack:
            return run
    return None


def check(ds: Dataset, text_of=None) -> Problems:
    """Every problem in the dataset. `text_of(doc_id)` returns a document's text (or None)
    for the note-copying check; without it the check is skipped."""
    p = Problems()
    keys: dict[str, set] = {}
    for t in schema.TABLES:
        rows = ds[t.name]
        seen: set = set()
        for i, r in enumerate(rows, start=2):
            where = f"{t.file}:{i}"
            for c in t.cols:
                v = r.get(c.name, "")
                if v != v.strip() or "\n" in v:
                    p.add(f"{where}: {c.name} has stray whitespace or a newline")
                if not v:
                    if c.required:
                        p.add(f"{where}: {c.name} is required")
                    continue
                if c.enum and c.kind == "list":
                    for item in split(v):
                        if item not in c.enum:
                            p.add(f"{where}: {c.name} item {item!r} is not one of "
                                  f"{', '.join(map(str, c.enum))[:80]}")
                elif c.enum and v not in c.enum:
                    p.add(f"{where}: {c.name} {v!r} is not one of {', '.join(map(str, c.enum))[:80]}")
                if c.kind == "int" and not re.fullmatch(r"-?\d+", v):
                    p.add(f"{where}: {c.name} {v!r} is not a whole number")
                elif c.kind == "date" and not DATE.fullmatch(v):
                    p.add(f"{where}: {c.name} {v!r} is not a date (YYYY-MM-DD)")
                elif c.kind == "url" and not URL.fullmatch(v):
                    p.add(f"{where}: {c.name} {v!r} is not a URL")
                elif c.kind == "bool" and v not in ("yes", "no"):
                    p.add(f"{where}: {c.name} {v!r} must be yes, no or empty")
                elif c.kind == "id" and not ids.valid(v):
                    p.add(f"{where}: {c.name} {v!r} is not a taxon id")
                if c.maxlen and len(v) > c.maxlen:
                    p.add(f"{where}: {c.name} is {len(v)} characters (at most {c.maxlen})")
            k = tuple(r.get(c, "") for c in t.key)
            if k in seen:
                p.add(f"{where}: duplicate key {k}")
            seen.add(k)
        keys[t.name] = {r[t.key[0]] for r in rows} if len(t.key) == 1 else set()

    taxa = {r["id"]: r for r in ds["taxa"]}
    docs = keys["documents"]
    for t in schema.TABLES:
        for c in t.cols:
            if not c.ref:
                continue
            target = taxa if c.ref == "taxa" else docs
            for i, r in enumerate(ds[t.name], start=2):
                v = r.get(c.name, "")
                if v and v not in target:
                    p.add(f"{t.file}:{i}: {c.name} {v!r} is not in {c.ref}")
    _check_tree(ds, taxa, p)
    for i, r in enumerate(ds["photos"], start=2):
        if r["role"] == "inherited" and not r["from_id"]:
            p.add(f"photos.csv:{i}: an inherited photo needs from_id")
        if r["role"] == "own" and not (r["licence"] and r["attribution"] is not None
                                       and r["display_url"]):
            p.add(f"photos.csv:{i}: an own photo needs a licence, an attribution and a URL")
    own = {r["photo_id"] for r in ds["photos"] if r["role"] == "own"}
    for i, r in enumerate(ds["photos"], start=2):
        if r["role"] == "inherited" and r["photo_id"] not in own:
            p.add(f"photos.csv:{i}: inherited photo {r['photo_id']} has no own row")
    for i, r in enumerate(ds["vouchers"], start=2):
        if r["kind"] in ("photo_file", "photo_url") and r["licence"] not in schema.LICENCES:
            p.add(f"vouchers.csv:{i}: a photo voucher needs a licence ({', '.join(schema.LICENCES)})")
    for i, r in enumerate(ds["distribution"], start=2):
        if r["place"] and geo.place_area(r["place"]) is None:
            p.add(f"distribution.csv:{i}: {r['place']!r} is not a place (geo.PLACES)")
    if text_of is not None:
        for i, r in enumerate(ds["notes"], start=2):
            text = text_of(r["doc_id"])
            run = copies(r["note"], text) if text else None
            if run:
                p.add(f"notes.csv:{i}: the note shares eight words with the document: {run!r}")
    return p


def _check_tree(ds: Dataset, taxa: dict[str, dict], p: Problems) -> None:
    roots = [r for r in ds["taxa"] if r["status"] != "synonym" and not r["parent_id"]]
    if len(roots) != 1:
        p.add(f"taxa.csv: expected one root (an accepted taxon with no parent), found {len(roots)}")
    for i, r in enumerate(ds["taxa"], start=2):
        where = f"taxa.csv:{i} ({r['id']} {r['name']})"
        if r["status"] == "synonym":
            a = taxa.get(r["accepted_id"])
            if not r["accepted_id"]:
                p.add(f"{where}: a synonym needs accepted_id")
            elif a and a["status"] == "synonym":
                p.add(f"{where}: accepted_id points at another synonym")
            if r["parent_id"]:
                p.add(f"{where}: a synonym has no parent_id")
            continue
        if r["accepted_id"]:
            p.add(f"{where}: only a synonym has accepted_id")
        par = taxa.get(r["parent_id"]) if r["parent_id"] else None
        if r["parent_id"] and par is None:
            continue                      # reported by the reference check
        if par is not None:
            if par["status"] == "synonym":
                p.add(f"{where}: its parent is a synonym")
            elif schema.RANK_ORDER.get(par["rank"], 99) >= schema.RANK_ORDER.get(r["rank"], 0):
                p.add(f"{where}: rank {r['rank']} does not descend from {par['rank']}")
        if not r["nativity"]:
            p.add(f"{where}: no nativity")
    # cycles
    for r in ds["taxa"]:
        if r["status"] == "synonym":
            continue
        cur, seen = r, set()
        while cur and cur["parent_id"]:
            if cur["id"] in seen:
                p.add(f"taxa.csv: a cycle through {r['id']} {r['name']}")
                break
            seen.add(cur["id"])
            cur = taxa.get(cur["parent_id"])


def split(value: str) -> list[str]:
    return [x for x in value.split(SEP) if x]


def join(items) -> str:
    return SEP.join(i for i in items if i)
