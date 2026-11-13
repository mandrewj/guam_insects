"""Hand curation of the taxonomy, kept in git as CSV files under curation/.

curation/taxa.csv: one row per taxon a curator touched. A row whose `taxon_id` is a GBIF key
overrides that taxon's fields (blank = keep GBIF's value); a row with a blank or curated
`taxon_id` adds a taxon (morphospecies, a genus GBIF lacks, the synthetic Hexapoda root).
New rows get an id on the next `resolve`, written back into the file, so links to them are
stable. Either the admin page or a spreadsheet can edit the file; both go through here.

curation/evidence.csv: what supports a curated taxon (or adds to a GBIF one): iNaturalist
observations, GBIF occurrences, the curator's own photo files, or a photo URL.

`resolve` derives the `taxa` table from GBIF + these files. Nothing here writes to the
pipeline tables, and nothing in the pipeline writes to these files.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import config, db

TAXA_CSV = config.CURATION_DIR / "taxa.csv"
EVIDENCE_CSV = config.CURATION_DIR / "evidence.csv"

TAXA_COLUMNS = ["taxon_id", "rank", "name", "authorship", "parent_id", "parent_name", "status",
                "accepted_id", "common_name", "establishment", "hidden", "note", "editor",
                "edited", "reason", "citation"]
# Columns that override a taxon's value; the rest are bookkeeping.
OVERRIDE_FIELDS = ["rank", "name", "authorship", "parent_id", "status", "accepted_id",
                   "common_name", "establishment", "hidden", "note"]
EVIDENCE_COLUMNS = ["taxon_id", "kind", "ref", "license", "credit", "note", "editor", "edited"]

STATUSES = {"accepted", "synonym", "doubtful", "morphospecies"}
ESTABLISHMENT = {"native", "endemic", "introduced", "invasive", "unknown"}
EVIDENCE_KINDS = {"inat_observation", "gbif_occurrence", "photo_file", "photo_url"}
# Photo licences the site may show (CLAUDE.md rule 3); a curator's own photo needs one too.
LICENSES = {"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"}
RANKS = ["Subphylum", "Class", "Subclass", "Superorder", "Order", "Suborder", "Infraorder",
         "Superfamily", "Family", "Subfamily", "Tribe", "Subtribe", "Genus", "Subgenus",
         "Species", "Subspecies"]


class CurationError(ValueError):
    pass


@dataclass
class Curation:
    rows: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    assigned: int = 0           # new ids handed out by this load


def _read(path: Path, columns: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:   # -sig: Excel adds a BOM
        reader = csv.DictReader(f)
        missing = set(columns) - set(reader.fieldnames or [])
        if missing:
            raise CurationError(f"{path.name}: missing column(s) {', '.join(sorted(missing))}")
        return [{c: (r.get(c) or "").strip() for c in columns} for r in reader
                if any((v or "").strip() for v in r.values())]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load(taxa_csv: Path = TAXA_CSV, evidence_csv: Path = EVIDENCE_CSV,
         assign_ids: bool = True) -> Curation:
    """Read and check both files; give new taxa ids (and save them) when `assign_ids`."""
    rows = _read(taxa_csv, TAXA_COLUMNS)
    errors = []
    seen: set[int] = set()
    next_id = max([config.HEXAPODA_ID] + [int(r["taxon_id"]) for r in rows
                                          if r["taxon_id"].isdigit()]) + 1
    assigned = 0
    for i, r in enumerate(rows, start=2):           # line 1 is the header
        where = f"taxa.csv line {i}"
        if not r["taxon_id"]:
            if not (r["name"] and r["rank"]):
                errors.append(f"{where}: a new taxon needs at least a name and a rank")
                continue
            if assign_ids:
                r["taxon_id"] = str(next_id)
                next_id += 1
                assigned += 1
            else:
                continue
        if not r["taxon_id"].isdigit():
            errors.append(f"{where}: taxon_id {r['taxon_id']!r} is not a number")
            continue
        tid = int(r["taxon_id"])
        if tid in seen:
            errors.append(f"{where}: taxon_id {tid} appears twice; merge the rows")
        seen.add(tid)
        if tid >= config.CURATED_ID_BASE and not (r["name"] and r["rank"]):
            errors.append(f"{where}: curated taxon {tid} needs a name and a rank")
        if r["rank"] and r["rank"] not in RANKS:
            errors.append(f"{where}: rank {r['rank']!r} is not one of {', '.join(RANKS)}")
        if r["status"] and r["status"] not in STATUSES:
            errors.append(f"{where}: status {r['status']!r} is not one of {sorted(STATUSES)}")
        if r["status"] == "synonym" and not r["accepted_id"]:
            errors.append(f"{where}: a synonym needs accepted_id")
        if r["establishment"] and r["establishment"] not in ESTABLISHMENT:
            errors.append(f"{where}: establishment {r['establishment']!r} is not one of "
                          f"{sorted(ESTABLISHMENT)}")
        if r["hidden"] and r["hidden"] not in ("0", "1"):
            errors.append(f"{where}: hidden must be 0 or 1")
        for col in ("parent_id", "accepted_id"):
            if r[col] and not r[col].isdigit():
                errors.append(f"{where}: {col} {r[col]!r} is not a number")
    evidence = _read(evidence_csv, EVIDENCE_COLUMNS)
    for i, e in enumerate(evidence, start=2):
        where = f"evidence.csv line {i}"
        if not e["taxon_id"].isdigit():
            errors.append(f"{where}: taxon_id {e['taxon_id']!r} is not a number")
        if e["kind"] not in EVIDENCE_KINDS:
            errors.append(f"{where}: kind {e['kind']!r} is not one of {sorted(EVIDENCE_KINDS)}")
        if not e["ref"]:
            errors.append(f"{where}: ref is empty")
        if e["kind"] in ("photo_file", "photo_url") and e["license"] not in LICENSES:
            errors.append(f"{where}: a photo needs a licence, one of {sorted(LICENSES)}")
        if e["kind"] == "photo_file" and e["ref"] and not (config.CURATED_PHOTOS_DIR /
                                                           e["ref"]).exists():
            errors.append(f"{where}: no file data/curated_photos/{e['ref']}")
    if errors:
        raise CurationError("\n".join(errors))
    if assigned:
        write_csv(taxa_csv, TAXA_COLUMNS, rows)
    return Curation(rows=rows, evidence=evidence, assigned=assigned)


GBIF_RANK = {"KINGDOM": "Kingdom", "PHYLUM": "Phylum", "CLASS": "Class", "ORDER": "Order",
             "FAMILY": "Family", "GENUS": "Genus", "SPECIES": "Species",
             "SUBSPECIES": "Subspecies", "VARIETY": "Variety", "FORM": "Form"}
GBIF_STATUS = {"ACCEPTED": "accepted", "DOUBTFUL": "doubtful"}   # anything else: synonym


def resolve(conn, cur: Curation) -> dict[str, int]:
    """Rebuild `taxa`: every hexapod GBIF taxon with presence, its ancestors, plus curation.

    Ancestors above class (Arthropoda, Animalia) are dropped: the four classes hang from the
    curated Hexapoda root (config.HEXAPODA_ID, its own row in taxa.csv). Raises
    CurationError on a broken tree, listing every problem at once.
    """
    gbif = {r["gbif_key"]: dict(r) for r in conn.execute("SELECT * FROM gbif_taxa")}
    present = {r[0] for r in conn.execute("SELECT DISTINCT taxon_id FROM taxon_presence")}
    curated = {int(r["taxon_id"]): r for r in cur.rows if r["taxon_id"]}
    evidence_ids = {int(e["taxon_id"]) for e in cur.evidence}

    # Which GBIF keys belong in the tree: present (or curated, or evidenced), hexapod,
    # accepted; then all their ancestors below Arthropoda.
    wanted = {k for k in present | set(curated) | evidence_ids if k in gbif}
    include: set[int] = set()
    for k in wanted:
        t = gbif[k]
        if t["class_key"] not in config.HEXAPOD_CLASSES:
            continue
        if GBIF_STATUS.get(t["taxonomic_status"]) is None and t["accepted_key"] in gbif:
            k = t["accepted_key"]               # a synonym's presence counts for its name
        while k and k in gbif and k not in include and k != config.ARTHROPODA_KEY:
            include.add(k)
            k = gbif[k]["parent_key"]

    taxa: dict[int, dict] = {}
    for k in include:
        t = gbif[k]
        taxa[k] = {
            "taxon_id": k, "gbif_key": k,
            "parent_id": config.HEXAPODA_ID if k in config.HEXAPOD_CLASSES else t["parent_key"],
            "rank": GBIF_RANK.get(t["rank"] or "", (t["rank"] or "").title()),
            "name": t["canonical_name"], "authorship": t["authorship"],
            "status": GBIF_STATUS.get(t["taxonomic_status"], "synonym"),
            "accepted_id": t["accepted_key"], "origin": "gbif",
            "common_name": t["vernacular_name"], "establishment": None, "hidden": 0,
            "hidden_reason": None, "note": None, "curated_fields": None,
        }

    # Curated rows: new taxa first (so parent_name can point at them), then overrides.
    by_name: dict[str, list[int]] = {}
    for tid, r in curated.items():
        if tid >= config.CURATED_ID_BASE:
            taxa[tid] = {"taxon_id": tid, "gbif_key": None, "parent_id": None, "rank": r["rank"],
                         "name": r["name"], "authorship": None, "status": "accepted",
                         "accepted_id": None, "origin": "curated", "common_name": None,
                         "establishment": None, "hidden": 0, "hidden_reason": None,
                         "note": None, "curated_fields": None}
    for t in taxa.values():
        by_name.setdefault(t["name"], []).append(t["taxon_id"])
    errors = []
    for tid, r in curated.items():
        t = taxa.get(tid)
        if t is None:
            errors.append(f"taxa.csv: taxon_id {tid} ({r['name'] or 'no name'}) is not a GBIF key "
                          "we hold; run `guaminsects taxa` to fetch it, or fix the id")
            continue
        changed = []
        for f in OVERRIDE_FIELDS:
            v = r[f]
            if v == "":
                continue
            t[f] = int(v) if f in ("parent_id", "accepted_id", "hidden") else v
            changed.append(f)
        if r["parent_name"] and not r["parent_id"]:
            hits = by_name.get(r["parent_name"], [])
            if len(hits) != 1:
                errors.append(f"taxa.csv: parent_name {r['parent_name']!r} for {t['name']} matches "
                              f"{len(hits)} taxa; give parent_id instead")
            else:
                t["parent_id"] = hits[0]
                changed.append("parent_id")
        if t["hidden"]:
            t["hidden_reason"] = r["reason"] or "curated"
        t["curated_fields"] = ",".join(changed) or None

    for t in taxa.values():
        p = t["parent_id"]
        if p is not None and p not in taxa:
            errors.append(f"{t['name']} ({t['taxon_id']}): parent {p} is not in the tree")
        if t["status"] == "synonym" and t["accepted_id"] not in taxa:
            errors.append(f"{t['name']} ({t['taxon_id']}): accepted taxon {t['accepted_id']} "
                          "is not in the tree")
    lineage = db.lineages({tid: t["parent_id"] for tid, t in taxa.items()})
    roots = [t for t in taxa.values() if t["parent_id"] is None]
    if len(roots) > 1:
        errors.append("more than one root: " + ", ".join(f"{t['name']} ({t['taxon_id']})"
                                                         for t in roots[:10]))
    # A cycle: walk up from each lineage top whose parent is in the tree until a node
    # repeats; report each cycle once, by its members, not every taxon hanging below it.
    reported: set[int] = set()
    for tid in taxa:
        top = int(lineage[tid].strip("/").split("/")[0])
        if taxa[top]["parent_id"] is None or taxa[top]["parent_id"] not in taxa or \
                top in reported:
            continue
        path, node = [], top
        while node not in path:
            path.append(node)
            node = taxa[node]["parent_id"]
        loop = path[path.index(node):]
        if not reported & set(loop):
            errors.append("these would sit under their own descendants (a cycle): " +
                          " > ".join(f"{taxa[x]['name']} ({x})" for x in loop))
        reported |= set(path)
    for e in cur.evidence:
        if int(e["taxon_id"]) not in taxa:
            errors.append(f"evidence.csv: taxon_id {e['taxon_id']} is not in the tree")
    if errors:
        raise CurationError("\n".join(errors))

    # Hidden propagates down: anything under a hidden taxon is hidden too.
    hidden_ids = {tid for tid, t in taxa.items() if t["hidden"]}
    for tid, t in taxa.items():
        if not t["hidden"] and any(f"/{h}/" in lineage[tid] for h in hidden_ids):
            t["hidden"], t["hidden_reason"] = 1, "under a hidden taxon"

    cols = ["taxon_id", "gbif_key", "parent_id", "rank", "name", "authorship", "status",
            "accepted_id", "origin", "common_name", "establishment", "hidden", "hidden_reason",
            "note", "curated_fields", "lineage", "depth", "resolved_at"]
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM taxa")
        conn.executemany(
            f"INSERT INTO taxa ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [[*(t[c] for c in cols[:15]), lineage[tid], lineage[tid].count("/") - 2, stamp]
             for tid, t in taxa.items()])
        conn.execute("DELETE FROM taxon_evidence")
        conn.executemany(
            "INSERT OR REPLACE INTO taxon_evidence (taxon_id, kind, ref, license, credit, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(int(e["taxon_id"]), e["kind"], e["ref"], e["license"] or None,
              e["credit"] or None, e["note"] or None) for e in cur.evidence])
    return {"taxa": len(taxa), "gbif": sum(t["origin"] == "gbif" for t in taxa.values()),
            "curated": sum(t["origin"] == "curated" for t in taxa.values()),
            "overridden": sum(bool(t["curated_fields"]) and t["origin"] == "gbif"
                              for t in taxa.values()),
            "hidden": sum(t["hidden"] for t in taxa.values())}


# ---------------------------------------------------------------- editing (admin page, import)

def _apply(conn, rows: list[dict], evidence: list[dict]) -> dict[str, int]:
    """Validate a whole new state of both files, resolve it, and only then save it.

    The files are written to temporary copies first; `load` and `resolve` raise before
    anything is replaced, so a bad edit never reaches curation/*.csv or the tree.
    """
    taxa_csv, evidence_csv = TAXA_CSV, EVIDENCE_CSV     # read at call time (tests patch them)
    tmp_taxa = taxa_csv.with_suffix(".pending.csv")
    tmp_ev = evidence_csv.with_suffix(".pending.csv")
    write_csv(tmp_taxa, TAXA_COLUMNS, rows)
    write_csv(tmp_ev, EVIDENCE_COLUMNS, evidence)
    try:
        cur = load(tmp_taxa, tmp_ev)
        stats = resolve(conn, cur)
    except CurationError:
        tmp_taxa.unlink(missing_ok=True)
        tmp_ev.unlink(missing_ok=True)
        resolve(conn, load(taxa_csv, evidence_csv))     # put the tree back as it was
        raise
    tmp_taxa.replace(taxa_csv)
    tmp_ev.replace(evidence_csv)
    stats["assigned"] = cur.assigned
    return stats


def upsert(conn, row: dict, editor: str, reason: str = "") -> dict[str, int]:
    """Add or change one taxa.csv row (blank taxon_id = a new taxon). Fields not given keep
    their current curated value; an empty string clears it back to GBIF's."""
    cur = load(TAXA_CSV, EVIDENCE_CSV, assign_ids=False)
    rows = [dict(r) for r in cur.rows]
    tid = str(row.get("taxon_id") or "").strip()
    target = next((r for r in rows if tid and r["taxon_id"] == tid), None)
    if target is None:
        target = {c: "" for c in TAXA_COLUMNS}
        rows.append(target)
    for c in TAXA_COLUMNS:
        if c in row and c not in ("editor", "edited"):
            target[c] = "" if row[c] is None else str(row[c]).strip()
    target["editor"], target["edited"] = editor, db.now()[:10]
    if reason:
        target["reason"] = reason
    if not any(target[c] for c in OVERRIDE_FIELDS + ["parent_name"]) and \
            target["taxon_id"] and int(target["taxon_id"]) < config.CURATED_ID_BASE:
        rows.remove(target)          # nothing left to override: drop the row
    return _apply(conn, rows, cur.evidence)


def remove(conn, taxon_id: int) -> dict[str, int]:
    """Drop a curated row. A hand-added taxon with children or evidence cannot go."""
    cur = load(TAXA_CSV, EVIDENCE_CSV, assign_ids=False)
    rows = [r for r in cur.rows if r["taxon_id"] != str(taxon_id)]
    return _apply(conn, rows, cur.evidence)


def add_evidence(conn, e: dict, editor: str) -> dict[str, int]:
    cur = load(TAXA_CSV, EVIDENCE_CSV, assign_ids=False)
    e = {c: str(e.get(c) or "").strip() for c in EVIDENCE_COLUMNS}
    e["editor"], e["edited"] = editor, db.now()[:10]
    ev = [x for x in cur.evidence if not (x["taxon_id"] == e["taxon_id"] and x["kind"] == e["kind"]
                                         and x["ref"] == e["ref"])] + [e]
    return _apply(conn, cur.rows, ev)


def remove_evidence(conn, taxon_id: int, kind: str, ref: str) -> dict[str, int]:
    cur = load(TAXA_CSV, EVIDENCE_CSV, assign_ids=False)
    ev = [x for x in cur.evidence if not (x["taxon_id"] == str(taxon_id) and x["kind"] == kind
                                         and x["ref"] == ref)]
    return _apply(conn, cur.rows, ev)


IMPORT_FIELDS = ["rank", "name", "authorship", "parent_id", "status", "accepted_id",
                 "common_name", "establishment", "hidden", "note"]


def import_checklist(conn, path: Path, editor: str) -> dict[str, int]:
    """Turn an edited copy of the exported checklist (guaminsects export) into curation rows:
    a changed cell becomes an override, a row with no taxon_id a new taxon. Unchanged rows
    are ignored, so the whole checklist can be opened, edited anywhere, and saved back."""
    current = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    cur = load(TAXA_CSV, EVIDENCE_CSV, assign_ids=False)
    rows = {r["taxon_id"]: dict(r) for r in cur.rows if r["taxon_id"]}
    new_rows = [dict(r) for r in cur.rows if not r["taxon_id"]]
    stats = {"changed": 0, "new": 0}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k: (v or "").strip() for k, v in r.items() if k}
            tid = r.get("taxon_id", "")
            if not tid:
                if r.get("name") and r.get("rank"):
                    row = {c: r.get(c, "") for c in TAXA_COLUMNS}
                    row.update(editor=editor, edited=db.now()[:10])
                    new_rows.append(row)
                    stats["new"] += 1
                continue
            t = current.get(int(tid)) if tid.isdigit() else None
            if t is None:
                continue
            diffs = {f: r[f] for f in IMPORT_FIELDS if f in r and
                     r[f] != ("" if t.get(f) is None else str(t[f]))}
            if not diffs:
                continue
            row = rows.setdefault(tid, {c: "" for c in TAXA_COLUMNS} | {"taxon_id": tid})
            row.update(diffs, editor=editor, edited=db.now()[:10])
            stats["changed"] += 1
    _apply(conn, list(rows.values()) + new_rows, cur.evidence)
    return stats
