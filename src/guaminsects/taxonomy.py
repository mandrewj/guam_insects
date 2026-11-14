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
           "recordedIn", "islands", "distributionTags", "inCatalogueOfLife", "nameMatch", "matchRemarks",
           "nameSources", "verificationStatus", "verificationRemarks", "verifiedBy",
           "verifiedDate", "verificationSource", "literatureRecords", "literatureSources",
           "specimenRecords", "gbifRecords", "inatObservations", "nameAccordingTo", "references",
           "associatedOccurrences", "associatedReferences", "taxonRemarks", "hidden",
           "curatedFields", "modifiedBy", "modified"]
# Editable column -> curation/taxa.csv column. Everything else is computed and read-only.
EDITABLE = {"parentNameUsageID": "parent_id", "parentNameUsage": "parent_name",
            "acceptedNameUsageID": "accepted_id", "scientificName": "name",
            "scientificNameAuthorship": "authorship", "taxonRank": "rank",
            "taxonomicStatus": "status", "vernacularName": "common_name",
            "establishmentMeans": "establishment", "verificationStatus": "verified",
            "verificationSource": "citation", "taxonRemarks": "note", "hidden": "hidden"}
# Editable lists, filed into curation/annotations.csv and evidence.csv (one item per row):
# distributionTags "Rota: present (Buden 2004) | Yap: doubtful"; associatedOccurrences
# iNaturalist observation and GBIF occurrence URLs (vouchers); associatedReferences other
# links, "Label <https://...>" or a bare URL. webapp/../editor/assets/model.js reads and
# writes the same formats.
LIST_COLUMNS = ["distributionTags", "associatedOccurrences", "associatedReferences"]
INAT_OBS = "https://www.inaturalist.org/observations/"
GBIF_OCC = "https://www.gbif.org/occurrence/"
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

        records = site.build_records(conn)
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute(
        "SELECT taxon_id, lineage, verified, extra FROM taxa")}
    keys = db.keymap(conn)
    specimens: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT taxon_id, SUM(records) n FROM taxon_specimens GROUP BY taxon_id"):
        t = keys.get(r["taxon_id"])
        if t is not None and (t == r["taxon_id"] or not specimens.get(t)):
            specimens[t] += r["n"]
    cur_all = curation.load(curation.TAXA_CSV, curation.EVIDENCE_CSV, assign_ids=False)
    curated = {ids.to_int(r["taxon_id"]): r for r in cur_all.rows if r["taxon_id"]}
    lists, touched = annotation_cells(cur_all, keys)

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
            **{c: SEP.join(lists[tid][c]) for c in LIST_COLUMNS},
            "modifiedBy": touched.get(tid, ("", ""))[1],
            "modified": touched.get(tid, ("", ""))[0],
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
                "hidden": int(r["hidden"]),
                "modifiedBy": touched.get(nm["id"], ("", ""))[1],
                "modified": touched.get(nm["id"], ("", ""))[0]})
    return out


def format_tag(a: dict) -> str:
    return f"{a['value']}: {a['status'] or 'present'}" + (f" ({a['source']})" if a["source"]
                                                          else "")


def parse_tag(text: str) -> dict:
    """'Rota: present (Buden 2004)' -> {value, status, source}; ValueError if malformed."""
    place, sep, rest = text.partition(":")
    status, _, source = rest.strip().partition(" ")
    source = source.strip()
    if not sep or status not in curation.DISTRIBUTION_STATUS or (
            source and not (source.startswith("(") and source.endswith(")"))):
        raise ValueError(f"{text!r} is not 'Place: present|absent|doubtful (source)'")
    return {"value": place.strip(), "status": status, "source": source[1:-1].strip()}


def occurrence_url(e: dict) -> str | None:
    return (INAT_OBS + e["ref"] if e["kind"] == "inat_observation" else
            GBIF_OCC + e["ref"] if e["kind"] == "gbif_occurrence" else None)


def parse_occurrence(text: str) -> tuple[str, str]:
    """An iNaturalist observation or GBIF occurrence URL -> (evidence kind, number)."""
    t = text.strip().split("?")[0].split("#")[0].rstrip("/")
    for prefix, kind in ((INAT_OBS, "inat_observation"), (GBIF_OCC, "gbif_occurrence")):
        for p in (prefix, prefix.replace("https://www.", "https://"),
                  prefix.replace("https://", "http://")):
            if t.startswith(p) and t[len(p):].isdigit():
                return kind, t[len(p):]
    raise ValueError(f"{text!r} is not an iNaturalist observation or GBIF occurrence URL")


def format_link(a: dict) -> str:
    return f"{a['note']} <{a['value']}>" if a["note"] else a["value"]


def parse_link(text: str) -> dict:
    t = text.strip()
    if t.endswith(">") and " <" in t:
        label, _, url = t[:-1].rpartition(" <")
        return {"value": url.strip(), "note": label.strip()}
    return {"value": t, "note": ""}


def annotation_cells(cur, keys: dict[int, int]) -> tuple[dict, dict]:
    """The list cells of each displayed taxon, and who last touched it: ({tid: {column:
    [items]}}, {tid or name id: (date, editor)})."""
    lists: dict[int, dict[str, list[str]]] = defaultdict(lambda: {c: [] for c in LIST_COLUMNS})
    touched: dict[int, tuple[str, str]] = {}

    def touch(ext: str, date: str, who: str) -> None:
        if not (who or date) or not ids.valid(ext):
            return
        for t in {ids.to_int(ext), keys.get(ids.to_int(ext), ids.to_int(ext))}:
            if (date, who) > touched.get(t, ("", "")):
                touched[t] = (date, who)

    for a in cur.annotations:
        tid = keys.get(ids.to_int(a["taxon_id"]), ids.to_int(a["taxon_id"]))
        col = "distributionTags" if a["kind"] == "distribution" else "associatedReferences"
        lists[tid][col].append(format_tag(a) if a["kind"] == "distribution" else format_link(a))
        touch(a["taxon_id"], a["added"], a["added_by"])
    for e in cur.evidence:
        tid = keys.get(ids.to_int(e["taxon_id"]), ids.to_int(e["taxon_id"]))
        if url := occurrence_url(e):
            lists[tid]["associatedOccurrences"].append(url)
        touch(e["taxon_id"], e["edited"], e["editor"])
    for r in cur.rows:
        touch(r["taxon_id"], r["edited"], r["editor"])
    return lists, touched


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
    keys = db.keymap(conn)
    annotations = [dict(a) for a in cur.annotations]
    evidence = [dict(e) for e in cur.evidence]
    lists_changed = False
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
            if col in LIST_COLUMNS:
                try:
                    n = _import_list(col, tid, base[col], value, annotations, evidence, keys,
                                     editor, stamp)
                except ValueError as e:
                    errors.append(f"{path.name} line {line}: {e}")
                    continue
                if n:
                    lists_changed = True
                    stats["changed"] += 1
                    changes.append(f"{base['scientificName']} ({tid}): {col} {value!r}")
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
        current = by_id.get(tid, {})
        diffs = {k: v for k, v in diffs.items() if current.get(k, "") != v or not current}
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
    # A GBIF taxon's row with nothing left to override goes (as the curation API does).
    kept = [r for r in by_id.values() if ids.kind(ids.to_int(r["taxon_id"])) == "curated" or
            any(r[c] for c in curation.OVERRIDE_FIELDS + ["parent_name"])]
    if (stats["changed"] or stats["new"]) and not dry_run:
        curation._apply(conn, kept + new_rows, evidence, annotations if lists_changed else None)
    return {**stats, "changes": changes}


def _import_list(col: str, tid: str, old: str, new: str, annotations: list[dict],
                 evidence: list[dict], keys: dict[int, int], editor: str, stamp: str) -> int:
    """Turn a changed list cell into added and removed annotation / evidence rows (in place).
    Returns how many rows changed; items already filed (or already gone) change nothing."""
    split = lambda v: [x.strip() for x in v.split("|") if x.strip()]  # noqa: E731
    before, after = split(old), split(new)
    shown = keys.get(ids.to_int(tid), ids.to_int(tid))

    def mine(row: dict) -> bool:
        return ids.valid(row["taxon_id"]) and keys.get(
            ids.to_int(row["taxon_id"]), ids.to_int(row["taxon_id"])) == shown

    n = 0
    if col == "associatedOccurrences":
        parse = parse_occurrence
        have = {(e["kind"], e["ref"]) for e in evidence if mine(e)}
        for item in set(after) - set(before):
            kind, ref = parse(item)
            if (kind, ref) not in have:
                evidence.append({c: "" for c in curation.EVIDENCE_COLUMNS} | {
                    "taxon_id": tid, "kind": kind, "ref": ref, "editor": editor,
                    "edited": stamp})
                n += 1
        gone = {parse(item) for item in set(before) - set(after)}
        keep = [e for e in evidence if not (mine(e) and (e["kind"], e["ref"]) in gone)]
        n += len(evidence) - len(keep)
        evidence[:] = keep
        return n
    kind = "distribution" if col == "distributionTags" else "link"
    parse = parse_tag if kind == "distribution" else parse_link
    old_items = {parse(x)["value"]: parse(x) for x in before}
    new_items = {parse(x)["value"]: parse(x) for x in after}
    for value, item in new_items.items():
        row = next((a for a in annotations if mine(a) and a["kind"] == kind and
                    a["value"] == value), None)
        fields = {k: item.get(k, "") for k in ("status", "source", "note") if k in item}
        if row is None:
            annotations.append({c: "" for c in curation.ANNOTATION_COLUMNS} | fields | {
                "taxon_id": tid, "kind": kind, "value": value, "added_by": editor,
                "added": stamp})
            n += 1
        elif any(row.get(k, "") != v for k, v in fields.items()):
            row.update(fields, added_by=editor, added=stamp)
            n += 1
    for value in set(old_items) - set(new_items):
        keep = [a for a in annotations if not (mine(a) and a["kind"] == kind and
                                              a["value"] == value)]
        n += len(annotations) - len(keep)
        annotations[:] = keep
    return n


def _as_committed(path: Path) -> bool:
    """True when `path` is tracked by git and unchanged since the last commit."""
    try:
        rel = path.resolve().relative_to(config.ROOT.resolve())
    except ValueError:
        return False
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(rel)],
                                 cwd=config.ROOT, capture_output=True, timeout=30)
        same = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(rel)],
                              cwd=config.ROOT, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return tracked.returncode == 0 and same.returncode == 0


def sync(conn, editor: str | None = None) -> dict | None:
    """Apply edits made to taxonomy.csv since it was last written and not yet committed;
    None when there are none.
    Raises curation.CurationError (and changes nothing) when an edit does not fit the tree."""
    if not REPO_CSV.exists():
        return None
    if _as_committed(REPO_CSV):
        # The file is what git has: it came from a commit (the editor's, which carries its
        # curation rows; CI's or another machine's regeneration), not from a hand edit here.
        # Only uncommitted edits are imported, so a pulled regeneration is never mistaken
        # for edits.
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
