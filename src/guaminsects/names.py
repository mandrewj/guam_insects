"""Every name a source used, put on the Catalogue of Life (`guaminsects match`).

Sources carry keys: GBIF Backbone keys (Plazi, the crop pest list, establishment statements,
BugGuide links, older rows), or name- ids for names GBIF does not have (iNaturalist names,
literature headings; numbered in sources/names.csv so they keep their ids). Each key is
matched once (enrich/col.py `match`) and the answer kept in `name_matches`:

    taxon > 0      the COL taxon it stands for (the same name, a COL synonym, a spelling
                   variant COL knows, or a near spelling within the same genus)
    taxon = 0      COL does not have it: `parent` is the key (or COL taxon) it goes under,
                   so `resolve` can add it to the tree flagged "not in the Catalogue of Life"

`resolve` (curation.py) turns this into the tree; nothing here decides what is shown.
"""

import csv
import json
import re
import sys

from . import config, db, ids
from .enrich import col
from .literature import GERMAN_ENGLISH, LATIN_STOP

REGISTRY = config.SOURCES_DIR / "names.csv"
REGISTRY_COLUMNS = ["id", "name", "rank", "origin", "hints"]
BACKBONE_RANKS = {"KINGDOM", "PHYLUM", "CLASS", "ORDER", "FAMILY", "GENUS", "SPECIES",
                  "SUBSPECIES", "VARIETY", "FORM"}
SPECIES_GROUP = {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}


class Registry:
    """sources/names.csv: name- ids for names no GBIF key stands for. Ids are never reused."""

    def __init__(self, path=None):
        self.path = path or REGISTRY
        self.rows: dict[int, dict] = {}
        self.by_name: dict[tuple[str, str], int] = {}
        if self.path.exists():
            with self.path.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    n = int(r["id"])
                    self.rows[n] = r
                    self.by_name[(r["name"], r["rank"])] = n
        self.dirty = False

    def key_for(self, name: str, rank: str, origin: str, hints: dict | None = None) -> int:
        rank = rank.upper()
        n = self.by_name.get((name, rank))
        if n is None:
            n = max(self.rows, default=0) + 1
            self.rows[n] = {"id": str(n), "name": name, "rank": rank, "origin": origin,
                            "hints": json.dumps(hints or {}, sort_keys=True)}
            self.by_name[(name, rank)] = n
            self.dirty = True
        elif origin not in self.rows[n]["origin"].split("|"):
            self.rows[n]["origin"] += "|" + origin
            self.dirty = True
        return ids.NAME_BASE + n

    def get(self, key: int) -> dict | None:
        return self.rows.get(key - ids.NAME_BASE)

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
            w.writeheader()
            w.writerows(self.rows[n] for n in sorted(self.rows))
        tmp.replace(self.path)
        self.dirty = False


# Tables whose rows carry a source key; the first set can put a taxon in the tree.
KEYED = [("taxon_presence", "taxon_id"), ("taxon_islands", "taxon_id"),
         ("taxon_hosts", "taxon_id"), ("establishment", "taxon_id"),
         ("pdf_mentions", "taxon_id"), ("pdf_candidates", "gbif_key"),
         ("checklist_names", "nub_key"), ("bugguide_links", "gbif_key"),
         ("taxon_synonyms", "taxon_id")]


def source_keys(conn) -> set[int]:
    keys: set[int] = set()
    for table, column in KEYED:
        keys |= {r[0] for r in conn.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND "
            f"({column} < ? OR ({column} >= ? AND {column} < ?))",
            (ids.COL_BASE, ids.NAME_BASE, ids.LOCAL_BASE))}
    return keys


def describe(conn, reg: Registry, key: int, backbone: dict[int, dict]) -> dict | None:
    """name, rank, authorship, hints and the key of the parent name, for one source key.
    Hints are the class and order (a family placement is what goes out of date)."""
    if ids.kind(key) == "gbif":
        t = backbone.get(key)
        if not t or t["class_key"] not in config.HEXAPOD_CLASSES:
            return None                    # a homonym outside the hexapods
        hints = {}
        for rank, col_key in (("class", "class_key"), ("order", "order_key")):
            h = backbone.get(t[col_key]) if t[col_key] else None
            if h:
                hints[rank] = h["canonical_name"]
        parent = t["parent_key"] if t["parent_key"] in backbone else None
        if t["rank"] == "CLASS":
            parent = None
        return {"name": t["canonical_name"], "rank": t["rank"], "authorship": t["authorship"],
                "hints": hints, "parent_key": parent, "origin": "gbif"}
    r = reg.get(key)
    if not r:
        return None
    words = r["name"].split()
    parent = None
    if r["rank"] == "SPECIES" and len(words) >= 2:
        parent = reg.key_for(words[0], "GENUS", r["origin"].split("|")[0])
    elif r["rank"] == "SUBSPECIES" and len(words) >= 3:
        parent = reg.key_for(" ".join(words[:2]), "SPECIES", r["origin"].split("|")[0])
    return {"name": r["name"], "rank": r["rank"], "authorship": None,
            "hints": json.loads(r["hints"] or "{}"), "parent_key": parent,
            "origin": r["origin"]}


def is_hexapod(d: dict) -> bool:
    keys = {c["key"] for c in d.get("classification") or []}
    return col.HEXAPODA in keys or (d.get("usage") or {}).get("key") == col.HEXAPODA


def _genus(name: str) -> str:
    return name.split()[0] if name else ""


# Words that end up in heading-shaped lines of the literature without being epithets.
NOT_EPITHETS = LATIN_STOP | GERMAN_ENGLISH | {
    "paratypes", "holotypes", "types", "dermatitis", "species", "group", "complex", "larvae",
    "nymphs", "adults", "records", "notes", "remarks", "distribution", "material", "examined",
    "key", "keys", "figures", "plates", "table", "tables", "described", "unknown", "undescribed",
    "spec", "indet", "sensu", "lato", "stricto", "auct", "nec", "non", "partim"}


def plausible(name: str, rank: str) -> bool:
    """A literature heading that looks like a real binomial (or trinomial)."""
    words = name.split()
    want = {"SPECIES": 2, "SUBSPECIES": 3}.get(rank)
    if want and len(words) != want:
        return False
    return all(re.fullmatch(r"[a-z]{3,}(-[a-z]+)?", w) and w not in NOT_EPITHETS
               for w in words[1:])


def decide(conn, desc: dict, d: dict) -> dict:
    """The name_matches row for one answer (and the COL taxa it points at, stored)."""
    mt = col.match_type(d)
    usage = d.get("usage") or {}
    acc = d.get("acceptedUsage") or {}
    name, rank = desc["name"], desc["rank"]
    row = {"match_type": mt, "taxon": 0, "parent": 0, "kind": "not in COL", "note": None}
    target = acc if d.get("synonym") and acc else usage
    hexapod = is_hexapod(d)
    same_rank = usage.get("rank") == rank or (usage.get("rank") in SPECIES_GROUP and
                                              rank in SPECIES_GROUP)
    if mt in ("EXACT", "VARIANT", "FUZZY") and hexapod and same_rank and target.get("key"):
        fuzzy_ok = mt != "FUZZY" or (rank in SPECIES_GROUP and
                                     _genus(usage.get("canonicalName")) == _genus(name))
        if fuzzy_ok:
            col.store_answer(conn, d)
            row["taxon"] = ids.from_col(target["key"])
            accepted = target.get("canonicalName") or target.get("name")
            if d.get("synonym"):
                row["kind"] = "COL synonym"
                row["note"] = f"Catalogue of Life: a synonym of {accepted}"
            elif mt == "VARIANT":
                row["kind"] = "spelling variant"
                row["note"] = f"spelling variant of {accepted} (Catalogue of Life)"
            elif mt == "FUZZY":
                row["kind"] = "spelling variant"
                row["note"] = f"matched by spelling: {name} → {accepted}"
            else:
                row["kind"] = "same"
            return row
        row["note"] = f"possibly {usage.get('canonicalName')} (spelling); held for review"
    # Not in COL: where does it go? The genus COL matched (for a species), else the
    # source's own parent name (matched in turn), else whatever COL matched above it.
    above = usage if mt == "HIGHERRANK" and hexapod and usage.get("key") else None
    direct = above and (rank == "SPECIES" and above.get("rank") == "GENUS" or
                        rank == "SUBSPECIES" and above.get("rank") == "SPECIES")
    if desc["origin"] == "literature" and not direct:
        # A literature-only heading COL lacks enters the tree only inside a genus (or for a
        # subspecies, a species) COL has, and only if it looks like a name: headings are
        # noisy (OCR splits, "Three paratypes").
        row["note"] = (row["note"] or "Not in the Catalogue of Life; its genus is not either") + \
            "; literature name held for review"
        return row
    if desc["origin"] == "literature" and not plausible(name, rank):
        row["note"] = "does not look like a name (a literature heading); held for review"
        return row
    if direct:
        col.store_answer(conn, d)
        row["parent"] = ids.from_col(above["key"])
    elif desc["parent_key"]:
        row["parent"] = desc["parent_key"]
    elif above:
        col.store_answer(conn, d)
        row["parent"] = ids.from_col(above["key"])
    if row["note"] is None:
        row["note"] = "Not in the Catalogue of Life"
    return row


def match_one(client, desc: dict) -> dict:
    """COL's answer for one name, with the source's class and order as hints (without them
    the matcher sends some common genera, Scymnus or Phoridae, up to Animalia). If that
    answer is not a hexapod, or stops above the order, ask again as an insect."""
    hints = {"phylum": "Arthropoda"} | {k: v for k, v in desc["hints"].items()
                                        if k in ("class", "order")}
    d = col.match(client, desc["name"], desc["rank"], desc["authorship"], hints=hints,
                  force_hints=True)
    usage = d.get("usage") or {}
    weak = not is_hexapod(d) or usage.get("rank") in ("SUBPHYLUM", "PHYLUM", "KINGDOM", "CLASS")
    if weak and "class" not in desc["hints"]:
        d2 = col.match(client, desc["name"], desc["rank"], desc["authorship"],
                       hints=hints | {"class": "Insecta"}, force_hints=True)
        if is_hexapod(d2) and col.match_type(d2) != "NONE":
            return d2
    return d


def match_keys(conn, client, keys: set[int]) -> dict:
    """Match these keys (again), and any parent names they need."""
    return match_all(conn, client, keys=keys)


def match_all(conn, client, refresh: bool = False, reg: Registry | None = None,
              keys: set[int] | None = None, shard: tuple[int, int] = (0, 1)) -> dict:
    """Match every source key not matched yet. Keys with records (which can add a taxon)
    go first, so the tree can be built before the rest (citations only) are done.
    `shard` (i, n) takes every n-th key, for two polite streams side by side."""
    reg = reg or Registry()
    backbone = {r["gbif_key"]: dict(r) for r in conn.execute("SELECT * FROM gbif_taxa")}
    done = set() if refresh else {r[0] for r in conn.execute("SELECT key FROM name_matches")}
    if keys is not None:
        todo = sorted(keys)
    else:
        with_records = {r[0] for r in conn.execute("SELECT DISTINCT taxon_id FROM taxon_presence")}
        todo = sorted((k for k in source_keys(conn) - done if k % shard[1] == shard[0]),
                      key=lambda k: (k in with_records, -k))     # popped from the end
    stats = {"asked": 0, "col": 0, "not_in_col": 0, "unplaced": 0, "skipped": 0}
    seen = set(done)
    while todo:
        key = todo.pop()
        seen.add(key)
        desc = describe(conn, reg, key, backbone)
        if not desc or desc["rank"] not in BACKBONE_RANKS or not desc["name"]:
            stats["skipped"] += 1
            continue
        d = match_one(client, desc)
        row = decide(conn, desc, d)
        stats["asked"] += 1
        stats["col" if row["taxon"] else "not_in_col"] += 1
        if not row["taxon"] and not row["parent"]:
            stats["unplaced"] += 1
        p = row["parent"]
        if p and ids.kind(p) in ("gbif", "name") and p not in seen:
            todo.append(p)
        conn.execute(
            "INSERT OR REPLACE INTO name_matches (key, name, rank, authorship, origin, "
            "match_type, taxon, parent, kind, note, hints, matched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, desc["name"], desc["rank"], desc["authorship"], desc["origin"],
             row["match_type"], row["taxon"], row["parent"], row["kind"], row["note"],
             json.dumps(desc["hints"], sort_keys=True), db.now()))
        conn.commit()                 # per name: never hold the lock across a request
        if stats["asked"] % 100 == 0:
            reg.save()
            print(f"  matched {stats['asked']}, {len(todo)} to go", file=sys.stderr)
    conn.commit()
    reg.save()
    return stats


ENDINGS = re.compile(r"(us|a|um|is|e|ii|i|ae|es)$")


def stem(epithet: str) -> str:
    """Latin epithet without its gender or genitive ending: 'marginatus' -> 'marginat'."""
    return ENDINGS.sub("", epithet.lower())


def near(a: str, b: str) -> bool:
    """Two names of the same rank under the same parent that are one spelling apart, or
    differ only in a gender ending ('Gonocephalum adpressiformis' / '-forme')."""
    wa, wb = a.lower().split(), b.lower().split()
    if len(wa) != len(wb) or wa[:-1] != wb[:-1] or a == b:
        return False
    x, y = wa[-1], wb[-1]
    if stem(x) == stem(y) and min(len(stem(x)), len(stem(y))) >= 4:
        return True
    return len(x) >= 6 and _distance(x, y) <= 1


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
