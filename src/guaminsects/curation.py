"""Hand curation of the taxonomy, kept in git as CSV files under curation/.

curation/taxa.csv: one row per taxon a curator touched. `taxon_id` is the taxon's id as the
site shows it (ids.py): a Catalogue of Life id (KVC9L), gbif:<key> or name-<n> for a name COL
lacks, IOG-<n> for one added here. A row for an existing taxon overrides its fields (blank =
keep the source's value); status synonym with accepted_id merges it into another taxon, and
status accepted on a merged name makes it its own taxon again. A row with a blank taxon_id
adds a taxon (a morphospecies, a genus no source has); it gets an IOG- id on the next
`resolve`, written back into the file, so links to it are stable.

curation/evidence.csv: what supports a curated taxon (or adds to a GBIF one): iNaturalist
observations, GBIF occurrences, the curator's own photo files, or a photo URL.

`resolve` derives the `taxa` table from COL + the name matches + these files (tree.py). Nothing here writes to the
pipeline tables, and nothing in the pipeline writes to these files.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import config, db, ids

TAXA_CSV = config.CURATION_DIR / "taxa.csv"
EVIDENCE_CSV = config.CURATION_DIR / "evidence.csv"

TAXA_COLUMNS = ["taxon_id", "rank", "name", "authorship", "parent_id", "parent_name", "status",
                "accepted_id", "common_name", "establishment", "hidden", "verified", "note",
                "editor", "edited", "reason", "citation"]
# Columns that override a taxon's value; the rest are bookkeeping.
OVERRIDE_FIELDS = ["rank", "name", "authorship", "parent_id", "status", "accepted_id",
                   "common_name", "establishment", "hidden", "verified", "note"]
# Columns added after files were first written: a file without them still reads (as blank).
OPTIONAL_COLUMNS = {"verified"}
EVIDENCE_COLUMNS = ["taxon_id", "kind", "ref", "license", "credit", "note", "editor", "edited"]

STATUSES = {"accepted", "synonym", "doubtful", "morphospecies"}
ESTABLISHMENT = {"native", "endemic", "introduced", "invasive", "unknown"}
EVIDENCE_KINDS = {"inat_observation", "gbif_occurrence", "photo_file", "photo_url"}
# Photo licences the site may show (CLAUDE.md rule 3); a curator's own photo needs one too.
LICENSES = {"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"}
RANKS = ["Subphylum", "Class", "Order", "Family", "Genus", "Species", "Subspecies"]


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
        missing = set(columns) - set(reader.fieldnames or []) - OPTIONAL_COLUMNS
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
    next_n = 1 + max([0] + [ids.to_int(r["taxon_id"]) - ids.LOCAL_BASE for r in rows
                            if ids.valid(r["taxon_id"]) and
                            ids.kind(ids.to_int(r["taxon_id"])) == "curated"])
    assigned = 0
    for i, r in enumerate(rows, start=2):           # line 1 is the header
        where = f"taxa.csv line {i}"
        if not r["taxon_id"]:
            if not (r["name"] and r["rank"]):
                errors.append(f"{where}: a new taxon needs at least a name and a rank")
                continue
            if assign_ids:
                r["taxon_id"] = f"IOG-{next_n}"
                next_n += 1
                assigned += 1
            else:
                continue
        if not ids.valid(r["taxon_id"]):
            errors.append(f"{where}: taxon_id {r['taxon_id']!r} is not an id (a Catalogue of "
                          "Life id like KVC9L, gbif:<key>, name-<n> or IOG-<n>)")
            continue
        tid = ids.to_int(r["taxon_id"])
        if tid in seen:
            errors.append(f"{where}: taxon_id {r['taxon_id']} appears twice; merge the rows")
        seen.add(tid)
        if ids.kind(tid) == "curated" and not (r["name"] and r["rank"]):
            errors.append(f"{where}: curated taxon {r['taxon_id']} needs a name and a rank")
        if r["rank"] and r["rank"] not in RANKS:
            errors.append(f"{where}: rank {r['rank']!r} is not one of {', '.join(RANKS)}")
        if r["status"] and r["status"] not in STATUSES:
            errors.append(f"{where}: status {r['status']!r} is not one of {sorted(STATUSES)}")
        if r["status"] == "synonym" and not r["accepted_id"]:
            errors.append(f"{where}: a synonym needs accepted_id")
        if r["establishment"] and r["establishment"] not in ESTABLISHMENT:
            errors.append(f"{where}: establishment {r['establishment']!r} is not one of "
                          f"{sorted(ESTABLISHMENT)}")
        for flag in ("hidden", "verified"):
            if r[flag] and r[flag] not in ("0", "1"):
                errors.append(f"{where}: {flag} must be 0 or 1")
        for col in ("parent_id", "accepted_id"):
            if r[col] and not ids.valid(r[col]):
                errors.append(f"{where}: {col} {r[col]!r} is not an id")
    evidence = _read(evidence_csv, EVIDENCE_COLUMNS)
    for i, e in enumerate(evidence, start=2):
        where = f"evidence.csv line {i}"
        if not ids.valid(e["taxon_id"]):
            errors.append(f"{where}: taxon_id {e['taxon_id']!r} is not an id")
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


def resolve(conn, cur: Curation) -> dict[str, int]:
    """Rebuild `taxa` (and taxon_keys, taxon_names) from COL, the name matches and `cur`.
    Raises CurationError on a broken tree, listing every problem at once."""
    from . import tree

    return tree.build(conn, cur)


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
            target["taxon_id"] and ids.kind(ids.to_int(target["taxon_id"])) != "curated":
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
