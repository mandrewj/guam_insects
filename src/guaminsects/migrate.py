"""`guaminsects migrate`: the pipeline database -> the dataset tables (refactor Phase 1).

One time, deleted in Phase 7 with the old pipeline. It reads the resolved database
(`data.nosync/guam.sqlite`), curation/*.csv and sources/*.csv, and writes `dataset/`.
Derived fields (the common name shown, links, English names) come from `site.build_records`,
so the dataset starts from exactly what the site shows today. No PDF text is carried
(snippet columns are not read).
"""

import csv
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path

from . import config, curation, dataset, db, geo, ids, library, names as namesreg, schema, site
from .dataset import join
from .enrich.photos import THUMB_DIR, thumb_name

PDF_PRESENCE = ("plazi", "pdf", "checklist")
CROP_DOC = "crop-pests-micronesia"
CROP_URL = "https://aubreymoore.github.io/crop-pest-list/"
NATIVITY_OF = {"native": "native", "endemic": "native", "introduced": "introduced",
               "invasive": "introduced"}
DOC_KIND = {"monograph": "monograph", "paper": "paper", "fact sheet": "fact sheet",
            "checklist": "checklist"}


def day(stamp: str | None) -> str:
    return (stamp or "")[:10]


def slug(text: str, limit: int = 56) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:limit].strip("-")


def ext(i: int) -> str:
    return ids.to_ext(i)


def migrate(conn, out: Path | None = None, copy_media: bool = True) -> dict:
    out = out or dataset.DATASET_DIR
    ds = dataset.Dataset(root=out)
    report: dict[str, object] = {}
    keys = db.keymap(conn)
    records = site.build_records(conn)                    # what the site shows today
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    cur = curation.load(curation.TAXA_CSV, curation.EVIDENCE_CSV, assign_ids=False)
    curated = {ids.to_int(r["taxon_id"]): r for r in cur.rows if r["taxon_id"]}

    # --- documents ------------------------------------------------------------------------
    doc_of_file: dict[str, str] = {}
    docs: list[dict] = []
    used: set[str] = set()
    for r in (library.rows() if library.LIBRARY.exists() else []):
        base = slug(Path(r["file"]).stem) or "document"
        doc_id, n = base, 2
        while doc_id in used:
            doc_id, n = f"{base}-{n}", n + 1
        used.add(doc_id)
        doc_of_file[r["file"]] = doc_id
        docs.append({"doc_id": doc_id, "file": r["file"], "title": r["title"] or Path(r["file"]).stem,
                     "authors": r["authors"], "year": r["year"], "container": r["series"],
                     "pages": r["pages"], "url": r["url"] if r["url"].startswith("http") else "",
                     "kind": r["kind"] if r["kind"] in schema.DOC_KINDS else "other",
                     "region": "yes" if r["scope"] in ("Guam", "Micronesia", "Marianas") else "",
                     "citation": library.citation(r), "added_by": "migrate",
                     "added": ""})
    checklists = {}
    for r in conn.execute("SELECT * FROM checklist_sources"):
        if r["source"] == "croppests":
            doc_id = CROP_DOC
            url = CROP_URL
        else:
            doc_id = "plazi-" + r["dataset_key"][:8]
            url = f"https://www.gbif.org/dataset/{r['dataset_key']}"
        checklists[r["dataset_key"]] = (doc_id, (r["areas"] or "").split(",") if r["areas"] else [])
        docs.append({"doc_id": doc_id, "title": r["title"], "url": url,
                     "licence": r["license"] or "", "doi": r["doi"] or "", "kind": "checklist",
                     "region": "yes", "citation": r["citation"] or r["title"],
                     "added_by": "migrate", "added": day(r["fetched_at"])})
    ds["documents"] = docs

    # --- taxa ------------------------------------------------------------------------------
    stmts: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM establishment ORDER BY taxon_id, area, year"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            stmts[tid].append(dict(r))
    nativity_counts: dict[str, int] = defaultdict(int)
    conflicts = []
    rows = []
    for tid, t in taxa.items():
        rec = records[tid]
        c = curated.get(tid, {})
        extra = json.loads(t["extra"] or "{}")
        nat, src, review, note = "unknown", "", "", t["note"] or ""
        if t["establishment"] in NATIVITY_OF:                  # a curator's value comes first
            nat, src, review = NATIVITY_OF[t["establishment"]], "editor", "editor"
            if t["establishment"] in ("endemic", "invasive"):
                note = (note + " " if note else "") + f"(curated as {t['establishment']})"
            nativity_counts["curated"] += 1
        elif stmts.get(tid):
            ordered = sorted(stmts[tid], key=lambda s: (s["area"] != "GU", s["area"]))
            values = {NATIVITY_OF.get(s["status"], "unknown") for s in ordered} - {"unknown"}
            if len(values) == 1:
                first = ordered[0]
                nat, review = values.pop(), "machine"
                src = (doc_of_file.get(first["source"]) or
                       ("gbif" if str(first["source"]).startswith("gbif") else ""))
                nativity_counts["machine statement"] += 1
            else:
                conflicts.append(ext(tid))
                nativity_counts["conflict -> unknown"] += 1
        nativity_counts[nat] += 1
        mine = bool(t["verified"])
        rows.append({
            "id": rec["ext"], "parent_id": ext(t["parent_id"]) if t["parent_id"] else "",
            "rank": t["rank"], "name": t["name"], "authorship": t["authorship"] or "",
            "status": t["status"], "common_name": rec["common"] or "",
            "other_common_names": join(n for n in rec["alt_common"] if n != rec["common"]),
            "nativity": nat, "nativity_source": src, "nativity_review": review,
            "iucn": (rec["conservation"] or {}).get("iucn") or "",
            "superfamily": extra.get("superfamily", ""), "subfamily": extra.get("subfamily", ""),
            "tribe": extra.get("tribe", ""),
            "in_col": "yes" if t["in_col"] else "no",
            "gbif_key": str(t["gbif_key"]) if t["gbif_key"] else "",
            "name_match": "Catalogue of Life" if t["in_col"] else "not in Catalogue of Life",
            "match_note": t["match_note"] or "",
            "hidden": "yes" if t["hidden"] else "", "hidden_reason": t["hidden_reason"] or "",
            "verified": "yes" if mine else "",
            "verified_by": c.get("editor", "") if mine else "",
            "verified_date": c.get("edited", "") if mine else "",
            "verification_source": c.get("citation", "") if mine else "",
            "note": note,
            "added_by": c.get("editor", "") if t["origin"] == "curated" else "",
            "added": c.get("edited", "") if t["origin"] == "curated" else "",
            "modified_by": c.get("editor", ""), "modified": c.get("edited", "")})
    for r in conn.execute("SELECT * FROM taxon_names"):
        if r["taxon_id"] not in taxa:
            continue
        acc = taxa[r["taxon_id"]]
        rows.append({"id": ext(r["name_id"]), "accepted_id": ext(r["taxon_id"]),
                     "rank": acc["rank"], "name": r["name"], "authorship": r["authorship"] or "",
                     "status": "synonym", "in_col": "yes" if r["kind"] == "COL synonym" else "no",
                     "name_match": r["kind"] or "", "match_note": r["note"] or "",
                     "name_sources": r["sources"] or ""})
    ds["taxa"] = rows
    ids_known = {r["id"] for r in rows}
    report["taxa"] = sum(r["status"] != "synonym" for r in rows)
    report["synonym_rows"] = sum(r["status"] == "synonym" for r in rows)
    report["nativity"] = dict(nativity_counts)
    report["nativity_conflicts"] = conflicts

    # --- keys ------------------------------------------------------------------------------
    nm = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM name_matches")}
    name_origin = {}
    with namesreg.REGISTRY.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name_origin[ids.NAME_BASE + int(r["id"])] = r["origin"].split("|")[0]
    seen_keys: set[tuple] = set()
    krows = []
    for r in conn.execute("SELECT key, taxon_id, how FROM taxon_keys"):
        if r["taxon_id"] not in taxa:
            continue
        k = r["key"]
        m = nm.get(k, {})
        if k < ids.COL_BASE:
            source, key = "gbif", str(k)
        elif k < ids.NAME_BASE:
            source, key = "col", ids.col_of(k)
        else:
            source = name_origin.get(k) or m.get("origin") or "literature"
            source = source if source in schema.KEY_SOURCES else "literature"
            key = m.get("name") or ext(k)
        if (source, key) in seen_keys:
            continue
        seen_keys.add((source, key))
        name = m.get("name") or (taxa[k]["name"] if k in taxa else "")
        krows.append({"source": source, "key": key, "name": name, "taxon_id": ext(r["taxon_id"]),
                      "how": "" if r["how"] == "self" else r["how"] or ""})
    ds["keys"] = krows

    # --- names (search and the page) -------------------------------------------------------
    names: dict[tuple, dict] = {}
    for r in conn.execute("SELECT taxon_id, synonym, source FROM taxon_synonyms WHERE synonym != ''"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa and r["synonym"] != taxa[tid]["name"]:
            names.setdefault((ext(tid), r["synonym"], "gbif synonym"),
                             {"taxon_id": ext(tid), "name": r["synonym"], "kind": "gbif synonym",
                              "source": r["source"]})
    for r in conn.execute("SELECT taxon_id, vernacular, synonyms FROM col_info"):
        tid = r["taxon_id"]
        if tid not in taxa:
            continue
        for n in json.loads(r["synonyms"] or "[]"):
            if n != taxa[tid]["name"]:
                names.setdefault((ext(tid), n, "col synonym"),
                                 {"taxon_id": ext(tid), "name": n, "kind": "col synonym",
                                  "source": "catalogue of life"})
    ds["names"] = list(names.values())

    # --- records ----------------------------------------------------------------------------
    cells: dict[tuple, dict] = {}
    for r in conn.execute("SELECT * FROM taxon_presence WHERE source IN ('gbif', 'gbif_backbone', 'inat')"):
        tid = keys.get(r["taxon_id"])
        if tid not in taxa:
            continue
        src = r["source"]
        if src == "gbif_backbone":
            if taxa[tid]["in_col"]:
                continue
            src = "gbif"
        c = cells.setdefault((tid, r["area"], src), {"n": 0, "keys": [], "at": ""})
        c["n"] += r["records"] or 0
        c["keys"].append(str(ids.col_of(r["taxon_id"]) or r["taxon_id"]))
        c["at"] = max(c["at"], day(r["fetched_at"]))
    spec_own: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT * FROM taxon_specimens"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa and (tid == r["taxon_id"] or not spec_own.get((tid, r["area"]))):
            c = cells.setdefault((tid, r["area"], "gbif_specimens"), {"n": 0, "keys": [], "at": ""})
            c["n"] += r["records"] or 0
            c["keys"].append(str(ids.col_of(r["taxon_id"]) or r["taxon_id"]))
            c["at"] = max(c["at"], day(r["fetched_at"]))
            spec_own[(tid, r["area"])] += r["records"] or 0
    ds["records"] = [{"taxon_id": ext(tid), "area": area, "source": src, "records": str(c["n"]),
                      "query_key": join(dict.fromkeys(c["keys"])), "refreshed": c["at"]}
                     for (tid, area, src), c in cells.items()]

    # --- literature, islands, hosts ---------------------------------------------------------
    lit: dict[tuple, dict] = {}

    def lit_row(tid: int, doc_id: str, kind: str) -> dict:
        return lit.setdefault((tid, doc_id, kind), {
            "taxon_id": ext(tid), "doc_id": doc_id, "kind": kind, "pages": [], "name_printed": "",
            "areas": set(), "islands": set(), "status": "", "status_area": set(),
            "first_record_year": "", "status_page": "", "method": "", "review": "", "added_by": "migrate",
            "added": ""})

    isl_area = {isl: a for a, d in geo.ISLAND_COORDS.items() for isl in d}
    from .literature import ISLANDS

    isl_area.update({isl: a for a, d in ISLANDS.items() for isl in d.values()})
    isl_rows: dict[tuple, dict] = {}
    mentions = conn.execute(
        "SELECT taxon_id, file, page, name_found, method, kind, areas, islands, decision, "
        "created_at FROM pdf_mentions WHERE decision != 'rejected' UNION ALL "
        "SELECT gbif_key, file, page, name, 'text', 'heading', areas, islands, decision, "
        "created_at FROM pdf_candidates WHERE gbif_key IS NOT NULL AND decision != 'rejected' "
        "ORDER BY 2, 3").fetchall()
    for r in mentions:
        tid = keys.get(r["taxon_id"])
        doc_id = doc_of_file.get(r["file"])
        if tid not in taxa or not doc_id:
            continue
        row = lit_row(tid, doc_id, "account" if r["kind"] == "heading" else "mention")
        if r["page"] not in row["pages"]:
            row["pages"].append(r["page"])
        row["name_printed"] = row["name_printed"] or r["name_found"]
        row["areas"] |= set((r["areas"] or "").split(",")) - {""}
        row["islands"] |= set((r["islands"] or "").split(",")) - {""}
        row["method"] = row["method"] or ("ocr" if r["method"] == "ocr" else "text")
        row["review"] = "editor" if r["decision"] == "accepted" else "machine"
        row["added"] = row["added"] or day(r["created_at"])
        if r["kind"] == "heading":
            for isl in (r["islands"] or "").split(","):
                if isl in isl_area:
                    isl_rows[(tid, isl_area[isl], isl, "literature", doc_id)] = {
                        "taxon_id": ext(tid), "area": isl_area[isl], "island": isl,
                        "source": "literature", "records": "", "doc_id": doc_id}
    for r in conn.execute("SELECT * FROM establishment"):
        tid = keys.get(r["taxon_id"])
        doc_id = doc_of_file.get(r["source"])
        if tid not in taxa or not doc_id:
            continue
        row = lit_row(tid, doc_id, "account")
        row["status"] = row["status"] or r["status"]
        row["status_area"].add(r["area"])
        if r["year"]:
            row["first_record_year"] = str(min(int(row["first_record_year"] or 9999), r["year"]))
        if r["page"]:
            row["status_page"] = row.get("status_page") or r["page"]
            if r["page"] not in row["pages"]:
                row["pages"].append(r["page"])
        row["method"] = row["method"] or "text"
        row["review"] = row["review"] or "machine"
    # Checklists: Plazi's digitised papers and the crop pest list.
    pres_areas: dict[tuple[int, str], set[str]] = defaultdict(set)
    for r in conn.execute("SELECT taxon_id, area FROM taxon_presence WHERE source = 'checklist'"):
        pres_areas[(keys.get(r["taxon_id"]), CROP_DOC)].add(r["area"])
    for r in conn.execute("SELECT DISTINCT nub_key, dataset_key FROM checklist_names"):
        tid = keys.get(r["nub_key"])
        if tid not in taxa:
            continue
        doc_id, areas = checklists[r["dataset_key"]]
        row = lit_row(tid, doc_id, "checklist")
        row["areas"] |= set(areas) if doc_id != CROP_DOC else pres_areas.get((tid, doc_id), set())
        row["method"] = "checklist" if doc_id == CROP_DOC else "plazi"
        row["added"] = ""
    for r in conn.execute("SELECT taxon_id, area, island FROM taxon_islands WHERE source = 'croppests'"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            lit_row(tid, CROP_DOC, "checklist")["islands"].add(r["island"])
            isl_rows[(tid, r["area"], r["island"], "literature", CROP_DOC)] = {
                "taxon_id": ext(tid), "area": r["area"], "island": r["island"],
                "source": "literature", "records": "1", "doc_id": CROP_DOC}
    out_lit = []
    for row in lit.values():
        order = {a: i for i, a in enumerate(config.AREA_CODES)}
        out_lit.append({**row, "pages": join(str(p) for p in sorted(row["pages"])),
                        "areas": join(sorted(row["areas"], key=order.get)),
                        "islands": join(sorted(row["islands"])),
                        "status_area": join(sorted(row["status_area"], key=order.get))})
    ds["literature"] = out_lit
    for r in conn.execute("SELECT taxon_id, area, island, records FROM taxon_islands WHERE source = 'gbif'"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            isl_rows[(tid, r["area"], r["island"], "gbif", "")] = {
                "taxon_id": ext(tid), "area": r["area"], "island": r["island"], "source": "gbif",
                "records": str(r["records"] or ""), "doc_id": ""}
    ds["islands"] = list(isl_rows.values())
    hosts: dict[tuple, dict] = {}
    for r in conn.execute("SELECT taxon_id, host FROM taxon_hosts"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            hosts.setdefault((tid, r["host"]), {"taxon_id": ext(tid), "host": r["host"],
                                                "doc_id": CROP_DOC, "review": ""})
    ds["hosts"] = list(hosts.values())

    # --- photos -----------------------------------------------------------------------------
    prow = []
    thumbs = set()
    for r in conn.execute(
            "SELECT tp.taxon_id, tp.position, tp.role, tp.from_taxon_id, p.* FROM taxon_photos tp "
            "JOIN photos p ON p.photo_id = tp.photo_id WHERE p.status = 'ok'"):
        if r["taxon_id"] not in taxa:
            continue
        base = {"taxon_id": ext(r["taxon_id"]), "position": str(r["position"]),
                "photo_id": r["photo_id"], "role": r["role"]}
        if r["role"] == "inherited":
            prow.append(base | {"from_id": ext(r["from_taxon_id"])})
            continue
        name = thumb_name(r["photo_id"])
        have = (THUMB_DIR / name).exists()
        if have:
            thumbs.add(name)
        prow.append(base | {
            "source": r["source"], "page_url": r["page_url"] or "", "display_url": r["display_url"] or "",
            "thumb": name if have else "", "thumb_url": r["thumb_url"] or "",
            "width": str(r["width"] or ""), "height": str(r["height"] or ""),
            "licence": r["license_code"] or "", "licence_url": r["license_url"] or "",
            "attribution": r["attribution"] or "", "retrieved": day(r["fetched_at"])})
    ds["photos"] = prow

    # --- links, distribution, vouchers -----------------------------------------------------
    link_rows = []
    for tid, rec in records.items():
        for lk in rec["links"]:
            sysname = lk["system"]
            if sysname not in schema.LINK_SYSTEMS:
                continue
            value = lk["url"]
            if sysname == "inaturalist":
                value = value.rsplit("/", 1)[1]
            elif sysname == "bugguide":
                value = value.rsplit("/", 1)[1]
            elif sysname == "wikidata":
                value = value.rsplit("/", 1)[1]
            link_rows.append({"taxon_id": ext(tid), "system": sysname, "value": value,
                              "label": lk["label"] if sysname == "editor" else "",
                              "confidence": lk.get("confidence") or "", "note": lk.get("note") or ""})
        nm_inat = rec["inat"]
        if nm_inat:             # iNaturalist's name-matched taxon (its English name is the label)
            same = next((x for x in link_rows[-8:] if x["taxon_id"] == ext(tid)
                         and x["system"] == "inaturalist" and x["value"] == str(nm_inat["id"])), None)
            if same:
                same["label"] = nm_inat["common"] or ""
                if "matched by name" not in same["note"]:
                    same["note"] = (same["note"] + "; " if same["note"] else "") + "matched by name"
            else:
                link_rows.append({"taxon_id": ext(tid), "system": "inaturalist",
                                  "value": str(nm_inat["id"]), "label": nm_inat["common"] or "",
                                  "confidence": "medium", "note": "matched by name"})
    ds["links"] = link_rows
    ds["distribution"] = [{"taxon_id": ext(r["taxon_id"]), "place": r["value"],
                           "status": r["status"] or "present", "source": r["source"] or "",
                           "added_by": r["added_by"], "added": r["added"]}
                          for r in conn.execute("SELECT * FROM taxon_annotations WHERE kind = 'distribution'")
                          if r["taxon_id"] in taxa]
    ds["vouchers"] = [{"taxon_id": ext(r["taxon_id"]), "kind": r["kind"], "ref": r["ref"],
                       "note": r["note"] or "", "licence": r["license"] or "",
                       "credit": r["credit"] or "", "added_by": r["editor"] or "",
                       "added": r["edited"] or ""}
                      for r in conn.execute("SELECT * FROM taxon_evidence") if r["taxon_id"] in taxa]

    # --- Wikipedia ---------------------------------------------------------------------------
    wiki = {}
    for r in conn.execute("SELECT * FROM wikipedia_articles"):
        tid = keys.get(r["taxon_id"], r["taxon_id"])
        if tid in taxa:
            wiki[tid] = {"taxon_id": ext(tid), "title": r["title"], "url": r["url"],
                         "revid": r["revid"], "rev_timestamp": r["rev_timestamp"],
                         "retrieved": day(r["fetched_at"]), "lead_only": bool(r["lead_only"]),
                         "html": r["html"]}
    ds.wikipedia = list(wiki.values())

    # --- names COL and the matcher could not place -------------------------------------------
    un = []
    counts: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT taxon_id, SUM(records) n FROM taxon_presence GROUP BY taxon_id"):
        counts[r["taxon_id"]] = r["n"] or 0
    for k, m in nm.items():
        if k in keys or ids.to_ext(k) in ids_known:
            continue
        un.append({"name": m["name"] or "", "rank": (m["rank"] or "").title(),
                   "source": m["origin"] if m["origin"] in schema.UNPLACED_SOURCES else "other",
                   "key": str(k), "records": str(counts.get(k, "")),
                   "note": m["note"] or ""})
    for r in conn.execute("SELECT name, file, COUNT(*) n FROM pdf_candidates WHERE gbif_key IS NULL "
                          "GROUP BY name, file"):
        un.append({"name": r["name"], "rank": "", "source": "literature",
                   "key": doc_of_file.get(r["file"], ""), "records": str(r["n"]),
                   "note": "a species-account heading the name finder could not place"})
    seen_un: set = set()
    ds["unplaced"] = [u for u in un if not ((u["name"], u["source"], u["key"]) in seen_un
                                            or seen_un.add((u["name"], u["source"], u["key"])))]

    ds["notes"] = []
    for t in schema.TABLES:           # one-line cells: no stray whitespace or newlines
        ds[t.name] = [{c: re.sub(r"\s+", " ", "" if v is None else str(v)).strip()
                       for c, v in r.items()} for r in ds[t.name]]
    dataset.write(ds, out)
    if copy_media:
        dest = config.ROOT / "media" / "thumbs"
        dest.mkdir(parents=True, exist_ok=True)
        for name in sorted(thumbs):
            if not (dest / name).exists():
                shutil.copy2(THUMB_DIR / name, dest / name)
        report["thumbnails"] = len(thumbs)
    report["rows"] = {t.name: len(ds[t.name]) for t in schema.TABLES} | {"wikipedia": len(ds.wikipedia)}
    return report
