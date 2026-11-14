"""The record each taxon page renders (docs/APP_SPEC.md "The record"), from the dataset.

A field-for-field port of the old `site.build_records`, which read the database; this one
reads `dataset/` through `model.Model` and needs nothing else. Phase 2 of the refactor proved
the two equal (ops/compare_records.py) apart from the changes listed in docs/REFACTOR.md.
"""

import html as htmllib
import re
from collections import defaultdict
from pathlib import Path

from .. import config, geo, ids
from ..dataset import Dataset, split
from ..model import Model

SPECIES_RANKS = {"Species"}
# Rank codes in the checklist (app.js CL_RANK reads them back).
RANK_CODES = {"Subphylum": "P", "Class": "C", "Order": "O", "Family": "F", "Genus": "G",
              "Species": "S", "Subspecies": "s", "Variety": "v", "Form": "f"}
AREA_KEYS = {a["code"]: a["code"].lower() for a in config.AREAS}
AREA_SHORT = {"GU": "Guam", "MP": "CNMI", "PW": "Palau", "FM": "FSM", "MH": "Marshalls"}
PHOTO_SOURCES = {"inaturalist": "iNaturalist", "commons": "Wikimedia Commons", "gbif": "GBIF"}
GBIF_SPECIES = "https://www.gbif.org/species/"
COL_TAXON = "https://www.catalogueoflife.org/data/taxon/"
GBIF_RECORDS = ("https://www.gbif.org/occurrence/search?checklist_key="
                "7ddf754f-d193-4cc9-b351-99906754a03b&" +
                "&".join(f"country={a['gbif']}" for a in config.AREAS) + "&taxon_key=")
INAT_TAXA = "https://www.inaturalist.org/taxa/"
THUMBS = config.ROOT / "media" / "thumbs"
TAG = re.compile(r"<[^>]+>")
PDF_METHODS = {"text", "ocr", "manual"}


def preview(text: str, length: int = 150) -> str:
    """First ~`length` characters, extended to the end of the word, with an ellipsis."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= length:
        return text
    cut = text.find(" ", length)
    return (text if cut < 0 else text[:cut]).rstrip(",;:—-") + "…"


def license_label(code: str | None) -> str:
    """'cc-by-nc-sa' -> 'CC BY-NC-SA'; 'cc0' -> 'CC0'."""
    if not code:
        return ""
    return "CC0" if code == "cc0" else "CC " + code[3:].upper()


def card_thumb(photos: list[dict], look: int = 4, ratio: float = 1.2) -> str | None:
    """Card and identify-tile thumbnail: the first landscape photo among the first few (tiles
    are wider than tall), only among photos of the same standing as the first."""
    if not photos:
        return None
    first = photos[0]
    for ph in photos[:look]:
        if (ph.get("of_id") is None) != (first.get("of_id") is None):
            continue
        if ph.get("w") and ph.get("h") and ph["w"] >= ratio * ph["h"]:
            return ph["thumb"]
    return first["thumb"]


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return host.removeprefix("www.") or url


def _int(v: str) -> int | None:
    return int(v) if v else None


def origin_of(ext: str, in_col: bool) -> str:
    return ("curated" if ext.startswith("IOG-") else "col" if in_col else
            "name" if ext.startswith("name-") else "gbif")


def build_records(ds: Dataset, thumbs: Path = THUMBS) -> dict[int, dict]:
    m = Model(ds)
    taxa = m.rows
    at = m.at
    children, order = m.children, m.order

    # --- presence: what each source says per area ---------------------------------------------
    own: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for r in ds["records"]:
        tid = at(r["taxon_id"])
        if tid is None or r["source"] not in ("gbif", "inat"):
            continue
        cell = own[tid][r["area"]]
        cell[r["source"]] = cell.get(r["source"], 0) + int(r["records"] or 0)
    docs = {d["doc_id"]: d for d in ds["documents"]}
    lit_docs: dict[tuple[int, str], set[str]] = defaultdict(set)
    machine_lit: dict[int, set[str]] = defaultdict(set)
    for r in ds["literature"]:
        tid = at(r["taxon_id"])
        if tid is None or r["kind"] == "mention":
            continue
        for a in split(r["areas"]):
            lit_docs[(tid, a)].add(r["doc_id"])
            if r["method"] in PDF_METHODS and r["review"] == "machine":
                machine_lit[tid].add(a)
    for (tid, a), d in lit_docs.items():
        own[tid][a]["literature"] = len(d)

    # Editors' tags: "present" is a record of its own; "absent" and "doubtful" count for nothing.
    tags: dict[int, list[dict]] = defaultdict(list)
    tagged_isles: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in sorted(ds["distribution"], key=lambda r: (ids.to_int(r["taxon_id"]), r["place"])):
        tid = at(r["taxon_id"])
        area = geo.place_area(r["place"])
        if tid is None or area is None:
            continue
        tags[tid].append({"place": r["place"], "area": area, "status": r["status"] or "present",
                          "source": r["source"], "added_by": r["added_by"], "added": r["added"]})
        if (r["status"] or "present") == "present":
            own[tid][area]["editor"] = 1
            if r["place"] not in geo.GROUPS:
                tagged_isles[tid][area].add(r["place"])
    for t in tags.values():
        t.sort(key=lambda x: (config.AREA_CODES.index(x["area"]), x["place"] not in geo.GROUPS,
                              x["place"]))

    # --- roll-ups, leaves first ---------------------------------------------------------------
    species_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    inat_sum: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    lit_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    n_species: dict[int, int] = {}
    gbif_n: dict[int, dict[str, int]] = defaultdict(dict)
    for tid in order:
        for area in config.AREA_CODES:
            mine = own[tid].get(area, {}).get("gbif")
            gbif_n[tid][area] = mine if mine else sum(gbif_n[c].get(area, 0) for c in children[tid])
    for tid in order:
        t = taxa[tid]
        n = int(t["rank"] in SPECIES_RANKS and not t["hidden"])
        for area, srcs in own[tid].items():
            if t["rank"] in SPECIES_RANKS or t["rank"] == "Subspecies":
                species_in[tid][area].add(tid if t["rank"] == "Species" else m.parent(tid))
            inat_sum[tid][area] += srcs.get("inat", 0)
            if "literature" in srcs:
                lit_in[tid][area].add(tid)
        for c in children[tid]:
            n += n_species[c]
            for area, s in species_in[c].items():
                species_in[tid][area] |= s
            for area, v in inat_sum[c].items():
                inat_sum[tid][area] += v
            for area, s in lit_in[c].items():
                lit_in[tid][area] |= s
        n_species[tid] = n

    def presence_of(tid: int) -> list[dict]:
        t = taxa[tid]
        rows = []
        for area in config.AREA_CODES:
            srcs = own[tid].get(area, {})
            row = {"area": area, "label": AREA_SHORT[area],
                   "gbif": gbif_n[tid].get(area, 0),
                   "inat": inat_sum[tid].get(area, 0),
                   "literature": len(lit_in[tid].get(area, ())) if t["rank"] not in
                   SPECIES_RANKS else srcs.get("literature", 0),
                   "species": len(species_in[tid].get(area, ())) if t["rank"] not in
                   SPECIES_RANKS else None,
                   "editor": next((s for s in ("present", "doubtful", "absent")
                                   if any(x["area"] == area and x["status"] == s
                                          for x in tags.get(tid, []))), None)}
            if row["gbif"] or row["inat"] or row["literature"] or row["species"] or row["editor"]:
                rows.append(row)
        return rows

    def regions_of(tid: int) -> list[str] | None:
        areas = {a for a, s in own[tid].items() if any(s.values())}
        areas |= {a for a, s in species_in[tid].items() if s}
        return [AREA_KEYS[a] for a in config.AREA_CODES if a in areas] or None

    # --- the checklist under each taxon above species -----------------------------------------
    node: dict[int, list] = {}
    for tid in order:
        t = taxa[tid]
        if t["hidden"]:
            continue
        kids = [node[c] for c in sorted(children[tid], key=lambda c: taxa[c]["name"].casefold())
                if c in node]
        node[tid] = [tid, t["name"], RANK_CODES.get(t["rank"], "?")] + ([kids] if kids else [])

    # --- links and iNaturalist ------------------------------------------------------------------
    by_tid: dict[str, dict[int, list[dict]]] = {s: defaultdict(list) for s in
                                                 ("inaturalist", "wikidata", "wikispecies",
                                                  "bugguide", "editor")}
    for r in ds["links"]:
        tid = at(r["taxon_id"])
        if tid is not None and r["system"] in by_tid:
            by_tid[r["system"]][tid].append(r)
    wiki = {}
    for w in ds.wikipedia:
        tid = at(w["taxon_id"])
        if tid is not None:
            wiki[tid] = {"title": w["title"], "url": w["url"], "revid": w["revid"],
                         "rev_timestamp": w["rev_timestamp"], "retrieved": w["retrieved"],
                         "preview": preview(htmllib.unescape(TAG.sub(" ", w["html"] or ""))),
                         "lead_only": bool(w["lead_only"]), "html": w["html"]}

    # --- literature -----------------------------------------------------------------------------
    by_doc: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in ds["literature"]:
        tid = at(r["taxon_id"])
        if tid is not None and r["doc_id"] in docs:
            by_doc[(tid, r["doc_id"])].append(r)
    lit: dict[int, list[dict]] = defaultdict(list)
    for (tid, doc_id), rows in by_doc.items():
        d = docs[doc_id]
        kinds = {r["kind"] for r in rows}
        areas = {a for r in rows for a in split(r["areas"])}
        pages = sorted({int(p) for r in rows for p in split(r["pages"]) if p.isdigit()})
        if "checklist" in kinds:
            lit[tid].append({
                "dataset": doc_id, "title": d["title"], "citation": d["citation"],
                "areas": sorted(areas), "url": d["url"] or None, "doi": d["doi"] or None,
                "source": "croppests" if rows[0]["method"] == "checklist" else "plazi",
                "_sort": (d["title"], 0, "")})
        else:
            lit[tid].append({
                "title": d["title"], "citation": d["citation"],
                "areas": [a for a in config.AREA_CODES if a in areas],
                "url": d["url"] or None, "doi": None, "source": "pdf",
                "pages": pages[:12], "treated": "account" in kinds, "year": d["year"],
                "machine_read": not any(r["review"] == "editor" for r in rows),
                "kind": d["kind"], "_sort": (d["file"], pages[0] if pages else 0, "")})
    for entries in lit.values():
        pdfs = sorted((e for e in entries if e["source"] == "pdf"), key=lambda e: e["_sort"])
        lists = sorted((e for e in entries if e["source"] != "pdf"), key=lambda e: e["_sort"])
        entries[:] = lists + pdfs
        entries.sort(key=lambda w: (not w.get("treated"), w.get("year") or "9999"))
        for e in entries:
            del e["_sort"]

    # --- islands ----------------------------------------------------------------------------------
    islands: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in ds["islands"]:
        tid = at(r["taxon_id"])
        if tid is not None:
            islands[tid][r["area"]].add(r["island"])
    for tid, by_area in tagged_isles.items():
        for a, isl in by_area.items():
            islands[tid][a] |= isl
    for tid in order:                    # leaves first: a genus takes its species' islands
        for c in children[tid]:
            for a, isl in islands.get(c, {}).items():
                islands[tid][a] |= isl

    # --- nativity statements, names, hosts, vouchers -----------------------------------------------
    est: dict[int, list[dict]] = defaultdict(list)
    for (tid, _doc), rows in by_doc.items():
        for r in rows:
            if not r["status"]:
                continue
            for a in split(r["status_area"]) or [""]:
                est[tid].append({"area": a, "status": r["status"],
                                 "year": _int(r["first_record_year"]),
                                 "citation": docs[r["doc_id"]]["citation"],
                                 "page": _int(r["status_page"]),
                                 "auto": r["review"] == "machine"})
    for rows in est.values():
        rows.sort(key=lambda x: (x["area"], x["year"] is not None, x["year"] or 0))
    synonyms: dict[int, list[str]] = defaultdict(list)
    other_names: dict[int, list[dict]] = defaultdict(list)
    for tid, rows in m.syn_rows.items():
        for r in sorted(rows, key=lambda r: r["name"]):
            other_names[tid].append({
                "id": ids.to_int(r["id"]), "name": r["name"], "authority": r["authorship"] or None,
                "kind": r["name_match"] or None, "note": r["match_note"] or None,
                "sources": r["name_sources"]})
            if r["name"] not in synonyms[tid]:
                synonyms[tid].append(r["name"])
    for kind in ("gbif synonym", "col synonym"):
        for r in sorted((r for r in ds["names"] if r["kind"] == kind), key=lambda r: r["name"]):
            tid = at(r["taxon_id"])
            if tid is not None and r["name"] not in synonyms[tid]:
                synonyms[tid].append(r["name"])
    hosts: dict[int, list[str]] = defaultdict(list)
    for r in sorted(ds["hosts"], key=lambda r: r["host"]):
        tid = at(r["taxon_id"])
        if tid is not None and r["host"] not in hosts[tid]:
            hosts[tid].append(r["host"])
    evidence: dict[int, list[dict]] = defaultdict(list)
    for r in sorted(ds["vouchers"], key=lambda r: (ids.to_int(r["taxon_id"]), r["kind"], r["ref"])):
        tid = at(r["taxon_id"])
        if tid is not None:
            evidence[tid].append({"kind": r["kind"], "ref": r["ref"], "license": r["licence"],
                                  "credit": r["credit"], "note": r["note"],
                                  "added_by": r["added_by"], "added": r["added"]})

    # --- photos -------------------------------------------------------------------------------------
    meta = {}
    for r in ds["photos"]:
        if r["role"] == "own":
            meta.setdefault(r["photo_id"], r)
    photos: dict[int, list[dict]] = defaultdict(list)
    for r in sorted(ds["photos"], key=lambda r: (ids.to_int(r["taxon_id"]), int(r["position"]))):
        tid = at(r["taxon_id"])
        if tid is None or r["photo_id"] not in meta:
            continue
        p = meta[r["photo_id"]]
        borrowed = taxa.get(at(r["from_id"])) if r["role"] == "inherited" and r["from_id"] else None
        thumb = f"media/thumbs/{p['thumb']}" if p["thumb"] and (thumbs / p["thumb"]).exists() \
            else p["thumb_url"]
        photos[tid].append({
            "of": borrowed["name"] if borrowed else None,
            "of_id": at(r["from_id"]) if borrowed else None,
            "of_rank": borrowed["rank"] if borrowed else None,
            "display": p["display_url"], "thumb": thumb,
            "w": _int(p["width"]), "h": _int(p["height"]),
            "source": PHOTO_SOURCES[p["source"]],
            "page": p["page_url"], "license": license_label(p["licence"]),
            "license_url": p["licence_url"], "attribution": p["attribution"],
            "retrieved": p["retrieved"]})

    def common_of(t: dict) -> str | None:
        return t["common_name"] or None

    def brief(tid: int) -> dict:
        t = taxa[tid]
        return {"id": tid, "rank": t["rank"], "name": t["name"], "common": common_of(t)}

    def nativity_tag(tid: int) -> str | None:
        n = taxa[tid]["nativity"]
        return n if n in ("native", "introduced") else None

    records = {}
    for tid, t in taxa.items():
        kids = sorted((taxa[c] for c in children[tid]), key=lambda k: k["name"].casefold())
        ext = t["id"]
        in_col = t["in_col"] == "yes"
        # iNaturalist: Wikidata's id (high) beats a name match; the name match carries the
        # English name iNaturalist uses here.
        inat_rows = by_tid["inaturalist"].get(tid, [])
        by_name = next((x for x in inat_rows if "matched by name" in x["note"]), None)
        inat_link = next((x for x in inat_rows if x["confidence"] == "high"), by_name)
        inat_obs = sum(v.get("inat", 0) for v in own[tid].values())
        links = []
        col_id = ids.col_of(tid)
        if col_id and in_col:
            links.append({"system": "col", "label": "Catalogue of Life", "url": COL_TAXON + col_id,
                          "confidence": "high"})
            links.append({"system": "gbif", "label": "GBIF records in Micronesia",
                          "url": GBIF_RECORDS + col_id, "confidence": "high"})
        elif t["gbif_key"]:
            links.append({"system": "gbif", "label": "GBIF", "url": GBIF_SPECIES + t["gbif_key"],
                          "confidence": "high"})
        if inat_link:
            links.append({"system": "inaturalist", "label": "iNaturalist",
                          "url": INAT_TAXA + inat_link["value"], "confidence": inat_link["confidence"],
                          "note": inat_link["note"].replace("; matched by name", "")
                          if inat_link["confidence"] == "high" else inat_link["note"]})
        bg = by_tid["bugguide"].get(tid)
        if bg:
            links.append({"system": "bugguide", "label": "BugGuide",
                          "url": f"https://bugguide.net/node/view/{bg[0]['value']}",
                          "confidence": "high", "note": "North American guide"})
        if tid in wiki:
            links.append({"system": "wikipedia", "label": "Wikipedia", "url": wiki[tid]["url"],
                          "confidence": "high"})
        ws = by_tid["wikispecies"].get(tid)
        if ws:
            links.append({"system": "wikispecies", "label": "Wikispecies", "url": ws[0]["value"],
                          "confidence": ws[0]["confidence"]})
        wd = by_tid["wikidata"].get(tid)
        if wd:
            links.append({"system": "wikidata", "label": "Wikidata",
                          "url": f"https://www.wikidata.org/wiki/{wd[0]['value']}",
                          "confidence": wd[0]["confidence"], "note": wd[0]["note"] or None})
        for x in by_tid["editor"].get(tid, []):
            links.append({"system": "editor", "label": x["label"] or _host(x["value"]),
                          "url": x["value"], "confidence": "high",
                          "note": f"added by {x['added_by']}"})
        records[tid] = {
            "id": tid, "ext": ext, "in_col": in_col,
            "match_note": t["match_note"] or None, "names": other_names.get(tid, []),
            "machine_lit": [a for a in config.AREA_CODES if a in machine_lit.get(tid, ())],
            "rank": t["rank"], "name": t["name"], "authority": t["authorship"] or None,
            "common": common_of(t), "status": t["status"], "origin": origin_of(ext, in_col),
            "accepted_id": None,
            "nativity": t["nativity"] or "unknown", "nativity_source": t["nativity_source"] or None,
            "nativity_review": t["nativity_review"] or None,
            "hidden": bool(t["hidden"]), "hidden_reason": t["hidden_reason"] or None,
            "note": t["note"] or None, "curated": [],
            "species_count": n_species[tid],
            "lineage": [brief(a) for a in m.ancestors(tid)],
            "children": [{**brief(ids.to_int(k["id"])), "hidden": bool(k["hidden"]),
                          "status": k["status"],
                          "species_count": n_species[ids.to_int(k["id"])],
                          "kids": len(children[ids.to_int(k["id"])]), "map": None,
                          "regions": regions_of(ids.to_int(k["id"])),
                          "est": nativity_tag(ids.to_int(k["id"])),
                          "isles": sorted({i for a in islands.get(ids.to_int(k["id"]), {}).values()
                                           for i in a}) or None,
                          "thumb": card_thumb(photos.get(ids.to_int(k["id"])) or [])}
                         for k in kids],
            "checklist": node[tid][3] if t["rank"] not in SPECIES_RANKS and tid in node
            and len(node[tid]) > 3 else [],
            "presence": presence_of(tid),
            "islands": [{"area": a, "label": AREA_SHORT[a],
                         "islands": sorted(i for i in islands[tid][a]
                                           if i not in (AREA_SHORT[a], "Palau", "Marshall Is."))}
                        for a in config.AREA_CODES if a in islands.get(tid, {})],
            "regions": regions_of(tid),
            "literature": lit.get(tid, []),
            "evidence": evidence.get(tid, []),
            "distribution": tags.get(tid, []),
            "hosts": hosts.get(tid, []),
            "synonyms": [n for n in synonyms.get(tid, []) if n != t["name"]][:40],
            "alt_common": sorted(split(t["other_common_names"])),
            "status_sources": est.get(tid, []),
            "photos": photos.get(tid, []), "wikipedia": wiki.get(tid), "map": None,
            "sections": [],
            "conservation": {"iucn": t["iucn"], "qid": wd[0]["value"]} if t["iucn"] and wd else None,
            "links": links,
            "inat": {"id": int(by_name["value"]), "common": by_name["label"] or None,
                     "observations": inat_obs} if by_name else None,
            "sources": {"col": {"id": col_id if in_col else None, "fetched_at": None},
                        "gbif": {"key": _int(t["gbif_key"]), "fetched_at": None,
                                 "presence_fetched_at": None}},
        }
    return records
