"""`taxonomy.csv`: the taxonomy as a Darwin Core-style table, for the site's download buttons.

One row per taxon, depth first, children by name; each taxon's other names (synonym rows)
follow it. Built from the dataset and the records; it is a product, not tracked in git
(`dataset/taxa.csv` is the table to edit).

verificationStatus is the best evidence for the taxon or anything under it, highest first:
editor confirmed (taxa.verified), literature records (a checklist or species account places it
in Micronesia), specimen records (a preserved specimen or material sample on GBIF),
unconfirmed (observations only).
"""

import csv
import io
import json
from collections import defaultdict

from .. import ids
from ..dataset import Dataset, join
from ..model import Model

COLUMNS = ["taxonID", "parentNameUsageID", "parentNameUsage", "acceptedNameUsageID",
           "acceptedNameUsage", "scientificName", "scientificNameAuthorship", "taxonRank",
           "taxonomicStatus", "vernacularName", "kingdom", "phylum", "class", "order",
           "superfamily", "family", "subfamily", "tribe", "genus", "establishmentMeans",
           "recordedIn", "islands", "distributionTags", "inCatalogueOfLife", "nameMatch",
           "matchRemarks", "nameSources", "verificationStatus", "verificationRemarks",
           "verifiedBy", "verifiedDate", "verificationSource", "literatureRecords",
           "literatureSources", "specimenRecords", "gbifRecords", "inatObservations",
           "nameAccordingTo", "references", "associatedOccurrences", "associatedReferences",
           "taxonRemarks", "notes", "hidden", "modifiedBy", "modified"]
COL_TAXON = "https://www.catalogueoflife.org/data/taxon/"
GBIF_SPECIES = "https://www.gbif.org/species/"
INAT_OBS = "https://www.inaturalist.org/observations/"
GBIF_OCC = "https://www.gbif.org/occurrence/"
LEVELS = ["unconfirmed", "specimen records", "literature records", "editor confirmed"]
LOW_RANKS = {"Genus", "Subgenus", "Species", "Subspecies", "Variety", "Form"}
MACHINE = " [machine-read]"


def short_cite(d: dict) -> str:
    """'Kulzer 1957' from a document row."""
    first = (d["authors"].split(",")[0].split(";")[0] if d["authors"] else d["title"][:30]).strip()
    return f"{first} {d['year']}".strip()


def format_tag(r: dict, docs: dict | None = None) -> str:
    src = r["source"] or (short_cite(docs[r["doc_id"]]) if docs and r.get("doc_id") in docs else "")
    return f"{r['place']}: {r['status'] or 'present'}" + (f" ({src})" if src else "")


def format_link(r: dict) -> str:
    return f"{r['label']} <{r['value']}>" if r["label"] else r["value"]


def occurrence_url(r: dict) -> str | None:
    return (INAT_OBS + r["ref"] if r["kind"] == "inat_observation" else
            GBIF_OCC + r["ref"] if r["kind"] == "gbif_occurrence" else None)


def cite(e: dict) -> str:
    text = (e.get("citation") or e.get("title") or "").strip().rstrip(".")
    pages = e.get("pages") or []
    return (text + (f", p. {', '.join(str(p) for p in pages)}" if pages else "") +
            (MACHINE if e.get("machine_read") else ""))


def rows(ds: Dataset, records: dict[int, dict]) -> list[dict]:
    m = Model(ds)
    specimens: dict[int, int] = defaultdict(int)
    for r in ds["records"]:
        t = m.at(r["taxon_id"])
        if t is not None and r["source"] == "gbif_specimens":
            specimens[t] += int(r["records"] or 0)
    doc_rows = {d["doc_id"]: d for d in ds["documents"]}
    lists: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in ds["distribution"]:
        if (t := m.at(r["taxon_id"])) is not None:
            lists[t]["distributionTags"].append(format_tag(r, doc_rows))
    for r in ds["vouchers"]:
        if (t := m.at(r["taxon_id"])) is not None and (u := occurrence_url(r)):
            lists[t]["associatedOccurrences"].append(u)
    for r in ds["links"]:
        if r["system"] == "editor" and (t := m.at(r["taxon_id"])) is not None:
            lists[t]["associatedReferences"].append(format_link(r))

    def lit_kind(rec: dict) -> tuple[bool, bool]:
        checked = any(e["source"] != "pdf" or (e.get("areas") and not e.get("machine_read"))
                      for e in rec["literature"])
        checked |= any(p["literature"] and p["area"] not in rec.get("machine_lit", ())
                       for p in rec["presence"])
        machine = bool(rec.get("machine_lit")) or any(
            e["source"] == "pdf" and e.get("areas") and e.get("machine_read")
            for e in rec["literature"])
        return checked, machine

    totals: dict[int, int] = {}

    def specimens_of(tid: int) -> int:
        if tid not in totals:
            totals[tid] = specimens.get(tid) or sum(specimens_of(c["id"])
                                                    for c in records[tid]["children"])
        return totals[tid]

    def own_level(tid: int) -> int:
        if m.rows[tid]["verified"]:
            return 3
        checked, machine = lit_kind(records[tid])
        if checked or machine:
            return 2
        return 1 if specimens_of(tid) else 0

    level: dict[int, int] = defaultdict(int)
    for tid in records:
        n = own_level(tid)
        for a in [*m.ancestors(tid), tid]:
            level[a] = max(level[a], n)

    out = []
    stack = [m.root]
    while stack:
        tid = stack.pop()
        r, t = records[tid], m.rows[tid]
        stack.extend(reversed([c["id"] for c in r["children"]]))
        chain = r["lineage"] + [{"rank": r["rank"], "name": r["name"]}]
        by_rank = {a["rank"]: a["name"] for a in chain}
        parent = r["lineage"][-1] if r["lineage"] else None
        mine = bool(t["verified"])
        checked, machine = lit_kind(r)
        remark = ""
        if level[tid] == 2 and own_level(tid) == 2 and machine and not checked:
            remark = "literature records machine-read only"
        elif level[tid] > own_level(tid):
            remark = "from taxa under it"
        classification = {
            "kingdom": "Animalia", "phylum": "Arthropoda", "class": by_rank.get("Class", ""),
            "order": by_rank.get("Order", ""), "superfamily": t["superfamily"],
            "family": by_rank.get("Family", ""), "subfamily": t["subfamily"],
            "tribe": t["tribe"], "genus": by_rank.get("Genus", "")}
        col_id = ids.col_of(tid) if r["in_col"] else None
        out.append({
            "taxonID": r["ext"], "parentNameUsageID": ids.to_ext(parent["id"]) if parent else "",
            "parentNameUsage": parent["name"] if parent else "",
            "acceptedNameUsageID": "", "acceptedNameUsage": "",
            "scientificName": r["name"], "scientificNameAuthorship": r["authority"] or "",
            "taxonRank": r["rank"], "taxonomicStatus": r["status"],
            "vernacularName": r["common"] or "", **classification,
            "establishmentMeans": "" if r["nativity"] == "unknown" else r["nativity"],
            "recordedIn": join(k.upper() for k in r["regions"] or []),
            "islands": join(i for g in r["islands"] for i in g["islands"])
            if r["rank"] in LOW_RANKS else "",
            "inCatalogueOfLife": "yes" if r["in_col"] else "no",
            "nameMatch": "Catalogue of Life" if r["in_col"] else "not in Catalogue of Life",
            "matchRemarks": r["match_note"] or "", "nameSources": "",
            "verificationStatus": LEVELS[level[tid]], "verificationRemarks": remark,
            "verifiedBy": t["verified_by"] if mine else "",
            "verifiedDate": t["verified_date"] if mine else "",
            "verificationSource": t["verification_source"] if mine else "",
            "literatureRecords": len(r["literature"]),
            "literatureSources": join(cite(e) for e in r["literature"]),
            "specimenRecords": specimens_of(tid),
            "gbifRecords": sum(p["gbif"] for p in r["presence"]),
            "inatObservations": sum(p["inat"] for p in r["presence"]),
            "nameAccordingTo": "Catalogue of Life" if r["in_col"] else (
                "GBIF Backbone Taxonomy" if r["origin"] == "gbif" else
                "Insects of Guam curator" if r["origin"] == "curated" else "source name"),
            "references": COL_TAXON + col_id if col_id else (
                GBIF_SPECIES + str(tid) if r["origin"] == "gbif" else ""),
            "associatedOccurrences": join(lists[tid]["associatedOccurrences"]),
            "associatedReferences": join(lists[tid]["associatedReferences"]),
            "distributionTags": join(lists[tid]["distributionTags"]),
            "taxonRemarks": r["note"] or "", "notes": "", "hidden": int(r["hidden"]),
            "modifiedBy": t["modified_by"], "modified": t["modified"],
        })
        for nm in r["names"]:
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


def to_csv(table: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(table)
    return buf.getvalue()


def site_script(table: list[dict], js_global: str = "guaminsects") -> str:
    """data/taxonomy.js for the site's download buttons: visible taxa only, as arrays."""
    body = {"columns": COLUMNS, "rows": [[r[c] for c in COLUMNS] for r in table if not r["hidden"]]}
    return f"{js_global}.taxonomy({json.dumps(body, ensure_ascii=False, separators=(',', ':'))});\n"
