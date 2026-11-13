"""The taxonomy as one Darwin Core-style CSV: `taxonomy.csv` at the top of the repository.

Every build rewrites it (so does `guaminsects taxonomy`) from the resolved tree and what
each source says. It is also a place to edit: change a cell in an editable column, or add a
row with a blank taxonID, and the next build turns the changes into curation/taxa.csv rows
before it rewrites the file. Changes are found by comparing with a snapshot of the file as
last written (data.nosync/taxonomy.last.csv), so a pipeline re-run in between is never
mistaken for an edit.

The site ships the same rows (data/taxonomy.js) for its download buttons: the whole
taxonomy, or the taxon being browsed with everything under it.

verificationStatus is the best evidence for the taxon or anything under it, highest first:
editor confirmed (verified=1 in curation/taxa.csv), literature records (a checklist or
species account places it in Micronesia), specimen records (a preserved specimen or
material sample on GBIF), unconfirmed (observations only).
"""

import csv
import io
import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from . import config, curation, db, ids

REPO_CSV = config.ROOT / "taxonomy.csv"
SNAPSHOT = config.ROOT / "data.nosync" / "taxonomy.last.csv"
COL_TAXON = "https://www.catalogueoflife.org/data/taxon/"
GBIF_SPECIES = "https://www.gbif.org/species/"

COLUMNS = ["taxonID", "parentNameUsageID", "parentNameUsage", "acceptedNameUsageID",
           "acceptedNameUsage", "scientificName", "scientificNameAuthorship", "taxonRank",
           "taxonomicStatus", "vernacularName", "kingdom", "phylum", "class", "order",
           "superfamily", "family", "subfamily", "tribe", "genus", "establishmentMeans",
           "recordedIn", "islands", "inCatalogueOfLife", "nameMatch", "matchRemarks",
           "nameSources", "verificationStatus", "verificationRemarks", "verifiedBy",
           "verifiedDate", "verificationSource", "literatureRecords", "literatureSources",
           "specimenRecords", "gbifRecords", "inatObservations", "nameAccordingTo", "references",
           "taxonRemarks", "hidden", "curatedFields"]
# Editable column -> curation/taxa.csv column. Everything else is computed and read-only.
EDITABLE = {"parentNameUsageID": "parent_id", "parentNameUsage": "parent_name",
            "acceptedNameUsageID": "accepted_id", "scientificName": "name",
            "scientificNameAuthorship": "authorship", "taxonRank": "rank",
            "taxonomicStatus": "status", "vernacularName": "common_name",
            "establishmentMeans": "establishment", "verificationStatus": "verified",
            "verificationSource": "citation", "taxonRemarks": "note", "hidden": "hidden"}
LEVELS = ["unconfirmed", "specimen records", "literature records", "editor confirmed"]
CONFIRMED = LEVELS[-1]
LOW_RANKS = {"Genus", "Subgenus", "Species", "Subspecies", "Variety", "Form"}   # island lists
SEP = " | "                      # Darwin Core's separator for lists in one cell
MACHINE = " [machine-read]"      # a citation the name finder made; no person has checked it


def rows(conn, records: dict[int, dict] | None = None) -> list[dict]:
    """One row per taxon, depth first, children by name (as the site lists them); each
    taxon's other names (synonyms, spelling variants, merged entries) follow it."""
    if records is None:
        from . import site

        records = site.build_records(conn, "public")
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute(
        "SELECT taxon_id, lineage, verified, extra FROM taxa")}
    keys = db.keymap(conn)
    specimens: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT taxon_id, SUM(records) n FROM taxon_specimens GROUP BY taxon_id"):
        t = keys.get(r["taxon_id"])
        if t is not None and (t == r["taxon_id"] or not specimens.get(t)):
            specimens[t] += r["n"]
    curated = {ids.to_int(r["taxon_id"]): r for r in
               curation.load(curation.TAXA_CSV, curation.EVIDENCE_CSV, assign_ids=False).rows
               if r["taxon_id"]}

    def lit_kind(rec: dict) -> tuple[bool, bool]:
        """(checked literature, machine-read literature) placing the taxon in Micronesia."""
        checked = any(e["source"] != "pdf" or (e.get("areas") and not e.get("machine_read"))
                      for e in rec["literature"])
        # Presence from checklists (Plazi, the crop pest list) is checked literature; the
        # PDF name finder's (machine_lit) is not.
        checked |= any(p["literature"] and p["area"] not in rec.get("machine_lit", ())
                       for p in rec["presence"])
        machine = bool(rec.get("machine_lit")) or any(
            e["source"] == "pdf" and e.get("areas") and e.get("machine_read")
            for e in rec["literature"])
        return checked, machine

    totals: dict[int, int] = {}

    def specimens_of(tid: int) -> int:
        # A taxon with no specimen count of its own totals its children's, which are
        # disjoint; GBIF's facet already counted everything else.
        if tid not in totals:
            totals[tid] = specimens.get(tid) or sum(specimens_of(c["id"])
                                                    for c in records[tid]["children"])
        return totals[tid]

    def own_level(tid: int) -> int:
        if taxa[tid]["verified"]:
            return 3
        checked, machine = lit_kind(records[tid])
        if checked or machine:
            return 2
        return 1 if specimens_of(tid) else 0

    level: dict[int, int] = defaultdict(int)
    for tid in records:              # a taxon is as well attested as anything under it
        n = own_level(tid)
        for a in taxa[tid]["lineage"].strip("/").split("/"):
            level[int(a)] = max(level[int(a)], n)

    out = []
    root = next(tid for tid, r in records.items() if not r["lineage"])
    stack = [root]
    while stack:
        tid = stack.pop()
        r = records[tid]
        stack.extend(reversed([c["id"] for c in r["children"]]))
        chain = r["lineage"] + [{"rank": r["rank"], "name": r["name"]}]
        by_rank = {a["rank"]: a["name"] for a in chain}
        extra = json.loads(taxa[tid]["extra"] or "{}")
        parent = r["lineage"][-1] if r["lineage"] else None
        cur = curated.get(tid, {})
        mine = bool(taxa[tid]["verified"])
        est = r["establishment"] or next((s["status"] for s in sorted(
            r["status_sources"], key=lambda s: s["area"] != "GU")), "")
        checked, machine = lit_kind(r)
        remark = ""
        if level[tid] == 2 and own_level(tid) == 2 and machine and not checked:
            remark = "literature records machine-read only"
        elif level[tid] > own_level(tid):
            remark = "from taxa under it"
        classification = {
            "kingdom": "Animalia", "phylum": "Arthropoda", "class": by_rank.get("Class", ""),
            "order": by_rank.get("Order", ""), "superfamily": extra.get("superfamily", ""),
            "family": by_rank.get("Family", ""), "subfamily": extra.get("subfamily", ""),
            "tribe": extra.get("tribe", ""), "genus": by_rank.get("Genus", "")}
        col_id = ids.col_of(tid) if r["in_col"] else None
        out.append({
            "taxonID": r["ext"], "parentNameUsageID": ids.to_ext(parent["id"]) if parent else "",
            "parentNameUsage": parent["name"] if parent else "",
            "acceptedNameUsageID": "", "acceptedNameUsage": "",
            "scientificName": r["name"], "scientificNameAuthorship": r["authority"] or "",
            "taxonRank": r["rank"], "taxonomicStatus": r["status"],
            "vernacularName": r["common"] or "", **classification,
            "establishmentMeans": est,
            "recordedIn": SEP.join(k.upper() for k in r["regions"] or []),
            "islands": SEP.join(i for g in r["islands"] for i in g["islands"])
            if r["rank"] in LOW_RANKS else "",
            "inCatalogueOfLife": "yes" if r["in_col"] else "no",
            "nameMatch": "Catalogue of Life" if r["in_col"] else "not in Catalogue of Life",
            "matchRemarks": r["match_note"] or "",
            "nameSources": "",
            "verificationStatus": LEVELS[level[tid]], "verificationRemarks": remark,
            "verifiedBy": cur.get("editor", "") if mine else "",
            "verifiedDate": cur.get("edited", "") if mine else "",
            "verificationSource": cur.get("citation", "") if mine else "",
            "literatureRecords": len(r["literature"]),
            "literatureSources": SEP.join(_cite(e) for e in r["literature"]),
            "specimenRecords": specimens_of(tid),
            "gbifRecords": sum(p["gbif"] for p in r["presence"]),
            "inatObservations": sum(p["inat"] for p in r["presence"]),
            "nameAccordingTo": "Catalogue of Life" if r["in_col"] else (
                "GBIF Backbone Taxonomy" if r["origin"] == "gbif" else
                "Insects of Guam curator" if r["origin"] == "curated" else "source name"),
            "references": COL_TAXON + col_id if col_id else (
                GBIF_SPECIES + str(tid) if r["origin"] == "gbif" else ""),
            "taxonRemarks": r["note"] or "", "hidden": int(r["hidden"]),
            "curatedFields": ",".join(r["curated"]),
        })
        for nm in r["names"]:            # the names shown as this taxon
            out.append({c: "" for c in COLUMNS} | classification | {
                "taxonID": ids.to_ext(nm["id"]), "acceptedNameUsageID": r["ext"],
                "acceptedNameUsage": r["name"], "scientificName": nm["name"],
                "scientificNameAuthorship": nm["authority"] or "", "taxonRank": r["rank"],
                "taxonomicStatus": "synonym",
                "inCatalogueOfLife": "yes" if nm["kind"] == "COL synonym" else "no",
                "nameMatch": nm["kind"], "matchRemarks": nm["note"] or "",
                "nameSources": nm["sources"] or "",
                "nameAccordingTo": "GBIF Backbone Taxonomy" if nm["id"] < ids.COL_BASE
                else "source name",
                "references": GBIF_SPECIES + str(nm["id"]) if nm["id"] < ids.COL_BASE else "",
                "hidden": int(r["hidden"])})
    return out


def _cite(e: dict) -> str:
    text = (e.get("citation") or e.get("title") or "").strip().rstrip(".")
    pages = e.get("pages") or []
    return (text + (f", p. {', '.join(str(p) for p in pages)}" if pages else "") +
            (MACHINE if e.get("machine_read") else ""))


def subtree(table: list[dict], taxon_id: str) -> list[dict]:
    """The rows of `taxon_id` (an external id) and everything under it, with their other
    names (rows are depth first)."""
    parent = {r["taxonID"]: r["parentNameUsageID"] or r["acceptedNameUsageID"] for r in table}
    inside: dict = {taxon_id: True}

    def under(tid) -> bool:
        path = []
        while tid not in inside:
            path.append(tid)
            tid = parent.get(tid) or None
            if tid is None:
                break
        ok = inside.get(tid, False) if tid is not None else False
        for p in path:
            inside[p] = ok
        return ok

    return [r for r in table if under(r["taxonID"])]


def to_csv(table: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(table)
    return buf.getvalue()


def write(table: list[dict], path: Path | None = None, snapshot: bool = True) -> bool:
    """Write the CSV (with a BOM, so Excel reads accents); keep a snapshot for `sync`.
    Returns whether the file changed."""
    path = path or REPO_CSV                  # read at call time (tests patch it)
    text = "﻿" + to_csv(table)
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    if snapshot:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, SNAPSHOT)
    return changed


def site_script(table: list[dict]) -> str:
    """data/taxonomy.js for the site's download buttons: visible taxa only, as arrays."""
    from .search import JS_GLOBAL

    body = {"columns": COLUMNS,
            "rows": [[r[c] for c in COLUMNS] for r in table if not r["hidden"]]}
    return f"{JS_GLOBAL}.taxonomy({json.dumps(body, ensure_ascii=False, separators=(',', ':'))});\n"


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k}
                for r in csv.DictReader(f)]


def default_editor() -> str:
    name = os.environ.get("GUAMINSECTS_EDITOR")
    if not name:
        try:
            name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True,
                                  cwd=config.ROOT, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            name = ""
    return name or "taxonomy.csv"


def import_edits(conn, path: Path, editor: str, baseline: dict[str, dict] | None = None,
                 dry_run: bool = False) -> dict:
    """Turn changed editable cells (against `baseline`, by default the current tree) and
    rows with a blank taxonID into curation/taxa.csv rows, checked as a whole by
    curation._apply. Changes to computed columns are counted and left alone."""
    if baseline is None:
        baseline = {str(r["taxonID"]): {k: str(v) for k, v in r.items()} for r in rows(conn)}
    cur = curation.load(curation.TAXA_CSV, curation.EVIDENCE_CSV, assign_ids=False)
    by_id = {r["taxon_id"]: dict(r) for r in cur.rows if r["taxon_id"]}
    new_rows = [dict(r) for r in cur.rows if not r["taxon_id"]]
    stamp = db.now()[:10]
    stats = {"changed": 0, "new": 0, "ignored": 0, "unknown": 0}
    changes: list[str] = []
    errors: list[str] = []
    for line, r in enumerate(read(path), start=2):
        tid = r.get("taxonID", "")
        if not tid:
            if not (r.get("scientificName") and r.get("taxonRank")):
                continue
            row = {c: "" for c in curation.TAXA_COLUMNS}
            for col, field in EDITABLE.items():
                row[field] = r.get(col, "")
            row["verified"] = "1" if r.get("verificationStatus") == CONFIRMED else ""
            row.update(editor=editor, edited=stamp, reason="added in " + path.name)
            new_rows.append(row)
            stats["new"] += 1
            changes.append(f"new {row['rank']} {row['name']}")
            continue
        base = baseline.get(tid)
        if base is None:
            stats["unknown"] += 1
            continue
        diffs: dict[str, str] = {}
        for col, value in r.items():
            if col not in base or value == base[col]:
                continue
            if col not in EDITABLE:
                stats["ignored"] += 1
                continue
            if col == "verificationStatus":
                if value not in LEVELS:
                    errors.append(f"{path.name} line {line}: verificationStatus {value!r} is "
                                  f"not one of {', '.join(LEVELS)}")
                elif value == CONFIRMED:
                    diffs["verified"] = "1"
                elif base[col] == CONFIRMED:
                    diffs["verified"] = ""
                else:                   # the other levels follow from the sources
                    stats["ignored"] += 1
                continue
            diffs[EDITABLE[col]] = value
        if "parent_name" in diffs:
            if "parent_id" in diffs:            # both changed: the id wins
                del diffs["parent_name"]
            else:
                diffs["parent_id"] = ""
        # Merging and splitting: an accepted taxon given an acceptedNameUsageID becomes a
        # synonym of it (shown as one taxon); a synonym row made accepted is its own taxon
        # again, under its accepted taxon's parent unless a parent is given.
        if diffs.get("accepted_id") and "status" not in diffs:
            diffs["status"] = "synonym"
        if diffs.get("status") == "synonym" and not (diffs.get("accepted_id") or
                                                     base["acceptedNameUsageID"]):
            errors.append(f"{path.name} line {line}: {base['scientificName']} made a synonym "
                          "needs acceptedNameUsageID (the taxon it is the same as)")
        if base["taxonomicStatus"] == "synonym" and diffs.get("status") in (
                "accepted", "doubtful", "morphospecies"):
            diffs["accepted_id"] = ""
            if not diffs.get("parent_id") and not diffs.get("parent_name"):
                acc = baseline.get(base["acceptedNameUsageID"]) or {}
                diffs["parent_id"] = acc.get("parentNameUsageID", "")
        if not diffs:
            continue
        row = by_id.setdefault(tid, {c: "" for c in curation.TAXA_COLUMNS} | {"taxon_id": tid})
        row.update(diffs, editor=editor, edited=stamp)
        row["reason"] = row["reason"] or "edited in " + path.name
        stats["changed"] += 1
        changes.append(f"{base['scientificName']} ({tid}): " +
                       ", ".join(f"{k} {v!r}" for k, v in diffs.items()))
    if errors:
        raise curation.CurationError("\n".join(errors))
    # A GBIF taxon's row with nothing left to override goes (as the admin page does).
    kept = [r for r in by_id.values() if ids.kind(ids.to_int(r["taxon_id"])) == "curated" or
            any(r[c] for c in curation.OVERRIDE_FIELDS + ["parent_name"])]
    if (stats["changed"] or stats["new"]) and not dry_run:
        curation._apply(conn, kept + new_rows, cur.evidence)
    return {**stats, "changes": changes}


def sync(conn, editor: str | None = None) -> dict | None:
    """Apply edits made to taxonomy.csv since it was last written; None when there are none.
    Raises curation.CurationError (and changes nothing) when an edit does not fit the tree."""
    if not REPO_CSV.exists():
        return None
    if not SNAPSHOT.exists():
        # No record of what was written (a fresh clone): keep a copy rather than guess.
        keep = config.DATA_DIR / "exports" / f"taxonomy.unsynced-{db.now()[:10]}.csv"
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_CSV, keep)
        print(f"taxonomy.csv has no snapshot to compare with; copied it to {keep} before "
              "rewriting. Re-apply any edits from there with `guaminsects import`.")
        return None
    if REPO_CSV.read_bytes() == SNAPSHOT.read_bytes():
        return None
    baseline = {r["taxonID"]: r for r in read(SNAPSHOT)}
    return import_edits(conn, REPO_CSV, editor or default_editor(), baseline)
