"""Export the database into the static web app (site.nosync/public).

The app is one page (index.html) that renders any taxon from a small data file:
data/t/<id // 1000>/<id>.js, which calls guaminsects.load(<record>). Browsers allow
<script src> from file://, unlike fetch(), so the site works by double-clicking index.html
and equally from a web server or Vercel.

`build_records` defines the record the app renders; `docs/APP_SPEC.md` describes it. Records
are rewritten only when their content changes (a hash per file), so a rebuild after a small
curation edit touches a handful of files.

There is one build: the site opened on this computer (file:// or `guaminsects serve`) is the
one deployed, so it holds openly licensed content only. PDF snippets and links to files in
literature/ never go in it.
"""

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from . import config, db, geo, ids

WEBAPP_DIR = config.ROOT / "webapp"
JS_GLOBAL = "guaminsects"          # webapp/assets/app.js defines window.guaminsects
PUBLIC_BUDGET_MB = 90              # Vercel Hobby takes 100 MB per CLI deploy
AREA_KEYS = {a["code"]: a["code"].lower() for a in config.AREAS}   # URL-friendly region keys
AREA_SHORT = {"GU": "Guam", "MP": "CNMI", "PW": "Palau", "FM": "FSM", "MH": "Marshalls"}
SPECIES_RANKS = {"Species"}
# Rank codes in the checklist (app.js CL_RANK reads them back).
RANK_CODES = {"Subphylum": "P", "Class": "C", "Order": "O", "Family": "F", "Genus": "G",
              "Species": "S", "Subspecies": "s", "Variety": "v", "Form": "f"}
GBIF_SPECIES = "https://www.gbif.org/species/"
COL_TAXON = "https://www.catalogueoflife.org/data/taxon/"
GBIF_RECORDS = ("https://www.gbif.org/occurrence/search?checklist_key="
                "7ddf754f-d193-4cc9-b351-99906754a03b&" +
                "&".join(f"country={a['gbif']}" for a in config.AREAS) + "&taxon_key=")
INAT_TAXA = "https://www.inaturalist.org/taxa/"


def _ancestors(tid: int, taxa: dict[int, dict]) -> list[int]:
    chain, seen = [], {tid}
    pid = taxa[tid]["parent_id"]
    while pid is not None and pid in taxa and pid not in seen:
        chain.append(pid)
        seen.add(pid)
        pid = taxa[pid]["parent_id"]
    return chain[::-1]


def clean_common(common: str | None, scientific: str | None) -> str | None:
    """A common name as a reader should see it: not the scientific name again, trimmed."""
    if not common:
        return None
    # GBIF's vernacularName can be a comma-joined list ("Coconut rhinoceros beetle, Asiatic
    # rhinoceros beetle, Black beetle, ..."): the first is the preferred one.
    c = re.sub(r"\s+", " ", common.split(",")[0]).strip()
    if not c or c.lower() == (scientific or "").strip().lower():
        return None
    return c


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


PHOTO_SOURCES = {"inaturalist": "iNaturalist", "commons": "Wikimedia Commons", "gbif": "GBIF"}


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
    """A link's label when the editor gave none: its site, without www."""
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return host.removeprefix("www.") or url


def _postorder(children: dict[int, list[int]], roots: list[int]) -> list[int]:
    order, seen, stack = [], set(), [(r, False) for r in roots]
    while stack:
        node, done = stack.pop()
        if done:
            order.append(node)
            continue
        if node in seen:
            continue
        seen.add(node)
        stack.append((node, True))
        stack.extend((c, False) for c in children.get(node, ()))
    return order


def build_records(conn) -> dict[int, dict]:
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    # Source rows carry the key the source used (a COL id, a GBIF Backbone key, a name- id);
    # taxon_keys says which displayed taxon each belongs to (several names can be one taxon).
    keys = db.keymap(conn)
    children: dict[int, list[int]] = defaultdict(list)
    for t in taxa.values():
        if t["parent_id"] is not None and t["parent_id"] in taxa:
            children[t["parent_id"]].append(t["taxon_id"])
    roots = [tid for tid, t in taxa.items() if t["parent_id"] is None]
    order = _postorder(children, roots)          # leaves first, for every roll-up below

    # Presence: what each source says per area, keyed by taxon.
    own: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    machine_lit: dict[int, set[str]] = defaultdict(set)    # areas with machine-read records
    for r in conn.execute("SELECT taxon_id, area, source, records FROM taxon_presence"):
        tid = keys.get(r["taxon_id"])
        if tid is None or tid not in taxa:
            continue
        src = r["source"]
        if src == "gbif_backbone":
            # GBIF records under a Backbone name count only for a taxon COL lacks; for one in
            # COL, GBIF's count under the COL key already includes them.
            if taxa[tid]["in_col"]:
                continue
            src = "gbif"
        # The literature sources (Plazi's checklists, the PDF library, other checklists) count
        # as "literature": the number is how many documents record the taxon there.
        src = "literature" if src in ("plazi", "pdf", "checklist") else src
        cell = own[tid][r["area"]]
        cell[src] = cell.get(src, 0) + (r["records"] or 0)
        if r["source"] == "pdf":
            machine_lit[tid].add(r["area"])
    # Curated evidence (an iNat observation, a GBIF record) puts a taxon on the list even
    # with no area yet; the curator gives the area in the note until evidence is fetched.
    # An editor's distribution tag "present" is a record of its own ("editor" source);
    # "absent" and "doubtful" tags are shown on the page but count for nothing.
    tags: dict[int, list[dict]] = defaultdict(list)
    extra_links: dict[int, list[dict]] = defaultdict(list)
    tagged_isles: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in conn.execute("SELECT * FROM taxon_annotations ORDER BY taxon_id, kind, value"):
        tid = r["taxon_id"]
        if tid not in taxa:
            continue
        if r["kind"] == "link":
            extra_links[tid].append({"system": "editor", "label": r["note"] or _host(r["value"]),
                                     "url": r["value"], "confidence": "high",
                                     "note": f"added by {r['added_by']}"})
            continue
        area = geo.place_area(r["value"])
        if area is None:
            continue
        tags[tid].append({"place": r["value"], "area": area, "status": r["status"] or "present",
                          "source": r["source"], "added_by": r["added_by"], "added": r["added"]})
        if (r["status"] or "present") == "present":
            own[tid][area]["editor"] = 1
            if r["value"] not in geo.GROUPS:
                tagged_isles[tid][area].add(r["value"])
    for t in tags.values():
        t.sort(key=lambda x: (config.AREA_CODES.index(x["area"]), x["place"] not in geo.GROUPS,
                              x["place"]))

    # Roll-ups, leaves first: species per area (a species counts in an area when any source
    # records it there), iNat observations summed (iNat counts are per leaf taxon), visible
    # species overall. GBIF counts are not summed: the facet already counted every record
    # under a genus, family or order key.
    species_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    inat_sum: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    lit_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    n_species: dict[int, int] = {}
    # GBIF: a taxon's own facet count already covers everything under it. One with no count
    # of its own (the curated Hexapoda root, a hand-added genus) totals its children, which
    # are disjoint.
    gbif_n: dict[int, dict[str, int]] = defaultdict(dict)
    for tid in order:
        for area in config.AREA_CODES:
            mine = own[tid].get(area, {}).get("gbif")
            gbif_n[tid][area] = mine if mine else sum(gbif_n[c].get(area, 0) for c in children[tid])
    for tid in order:
        t = taxa[tid]
        n = int(t["rank"] in SPECIES_RANKS and not t["hidden"] and t["status"] != "synonym")
        for area, srcs in own[tid].items():
            if t["rank"] in SPECIES_RANKS or t["rank"] == "Subspecies":
                species_in[tid][area].add(tid if t["rank"] == "Species" else t["parent_id"])
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
                   # The editors' word on this area for this taxon itself: present wins.
                   "editor": next((s for s in ("present", "doubtful", "absent")
                                   if any(x["area"] == area and x["status"] == s
                                          for x in tags.get(tid, []))), None)}
            if row["gbif"] or row["inat"] or row["literature"] or row["species"] or \
                    row["editor"]:
                rows.append(row)
        return rows

    def regions_of(tid: int) -> list[str] | None:
        areas = {a for a, s in own[tid].items() if any(s.values())}
        areas |= {a for a, s in species_in[tid].items() if s}
        return [AREA_KEYS[a] for a in config.AREA_CODES if a in areas] or None

    # The checklist under each taxon above species: everything below it as nested
    # [id, name, rank code, children], children by name, hidden taxa left out. Built leaves
    # first, so each node is made once and shared by every ancestor's list.
    node: dict[int, list] = {}
    for tid in order:
        t = taxa[tid]
        if t["hidden"]:
            continue
        kids = [node[c] for c in sorted(children[tid], key=lambda c: taxa[c]["name"].casefold())
                if c in node]
        node[tid] = [tid, t["name"], RANK_CODES.get(t["rank"], "?")] + ([kids] if kids else [])

    # iNaturalist: the taxa iNat has observations of here, matched by name (rank agreeing).
    from .names import Registry

    reg = Registry()
    inat_by_taxon: dict[int, dict] = {}
    for r in conn.execute("SELECT inat_id, name, rank, common_name, SUM(observations) n "
                          "FROM inat_place_counts GROUP BY inat_id ORDER BY n DESC"):
        n = reg.by_name.get((r["name"], (r["rank"] or "").upper()))
        tid = keys.get(ids.NAME_BASE + n) if n else None
        if tid is not None and tid not in inat_by_taxon:
            inat_by_taxon[tid] = {"id": r["inat_id"], "common": r["common_name"],
                                  "observations": r["n"], "name": r["name"]}

    # Literature: digitized checklists naming the taxon (Plazi on GBIF).
    lit: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
            "SELECT DISTINCT n.nub_key, s.dataset_key, s.source, s.title, s.citation, s.areas, s.doi "
            "FROM checklist_names n JOIN checklist_sources s ON s.dataset_key = n.dataset_key "
            "ORDER BY s.title"):
        tid = keys.get(r["nub_key"])
        if tid in taxa and not any(e.get("dataset") == r["dataset_key"] for e in lit[tid]):
            lit[tid].append({"dataset": r["dataset_key"],
                "title": r["title"], "citation": r["citation"],
                "areas": (r["areas"] or "").split(",") if r["areas"] else [],
                "url": "https://aubreymoore.github.io/crop-pest-list/" if r["source"] == "croppests"
                else f"https://www.gbif.org/dataset/{r['dataset_key']}",
                "doi": r["doi"], "source": r["source"]})
    # The PDF library: one entry per (taxon, document) with the pages. The site cites (title,
    # pages, the publisher's URL), never a snippet or the file (CLAUDE.md rule 4).
    from . import library as librarylib

    lib_rows = {r["file"]: r for r in librarylib.rows()} if librarylib.LIBRARY.exists() else {}
    pdf_hits: dict[tuple[int, str], dict] = {}
    mentions = conn.execute(
        "SELECT taxon_id, file, page, kind, areas, decision FROM pdf_mentions "
        "WHERE decision != 'rejected' UNION ALL "
        # headings of names the tree did not have yet (now under their name- keys)
        "SELECT gbif_key, file, page, 'heading', areas, decision FROM pdf_candidates "
        "WHERE gbif_key IS NOT NULL AND decision != 'rejected' ORDER BY 2, 3").fetchall()
    for r in mentions:
        tid = keys.get(r["taxon_id"])
        if tid not in taxa or r["file"] not in lib_rows:
            continue
        e = pdf_hits.setdefault((tid, r["file"]), {
            "pages": [], "areas": set(), "treated": False, "reviewed": False})
        if r["page"] not in e["pages"]:
            e["pages"].append(r["page"])
        e["areas"] |= set((r["areas"] or "").split(",")) - {""}
        e["treated"] |= r["kind"] == "heading"
        e["reviewed"] |= r["decision"] == "accepted"
    for (tid, fname), e in pdf_hits.items():
        doc = lib_rows[fname]
        lit[tid].append({
            "title": doc["title"], "citation": librarylib.citation(doc),
            "areas": [a for a in config.AREA_CODES if a in e["areas"]],
            "url": doc["url"] or None, "doi": None, "source": "pdf",
            "pages": e["pages"][:12], "treated": e["treated"], "year": doc["year"],
            # Found by the name finder in the PDF text; a person has not checked it yet.
            "machine_read": not e["reviewed"],
            "kind": doc["kind"]})
    for entries in lit.values():
        entries.sort(key=lambda w: (not w.get("treated"), w.get("year") or "9999"))
    # Islands named in species accounts (literature headings), and later GBIF's level-1
    # areas: {area: {island: [sources]}} shown as "Recorded on" under the presence table.
    from .literature import ISLANDS

    island_area = {isl: a for a, d in ISLANDS.items() for isl in d.values()}
    islands: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in conn.execute("SELECT taxon_id, islands FROM pdf_mentions WHERE kind = 'heading' "
                          "AND islands IS NOT NULL AND decision != 'rejected' UNION ALL "
                          "SELECT gbif_key, islands FROM pdf_candidates WHERE gbif_key IS NOT "
                          "NULL AND islands IS NOT NULL AND decision != 'rejected'"):
        tid = keys.get(r["taxon_id"])
        for isl in r["islands"].split(","):
            if isl in island_area and tid in taxa:
                islands[tid][island_area[isl]].add(isl)
    for r in conn.execute("SELECT taxon_id, area, island FROM taxon_islands"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            islands[tid][r["area"]].add(r["island"])
    for tid, by_area in tagged_isles.items():
        for a, isl in by_area.items():
            islands[tid][a] |= isl
    for tid in order:                    # leaves first: a genus takes its species' islands
        for c in children[tid]:
            for a, isl in islands.get(c, {}).items():
                islands[tid][a] |= isl
    est: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM establishment ORDER BY taxon_id, area, year"):
        tid = keys.get(r["taxon_id"])
        if tid in taxa:
            est[tid].append({"area": r["area"], "status": r["status"], "year": r["year"],
                                       "citation": r["citation"], "page": r["page"],
                                       "auto": bool(r["auto"])})
    synonyms: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT taxon_id, synonym FROM taxon_synonyms WHERE synonym != '' "
                          "ORDER BY synonym"):
        tid = keys.get(r["taxon_id"])
        if tid is not None and r["synonym"] not in synonyms[tid]:
            synonyms[tid].append(r["synonym"])
    # Other names shown as this taxon (COL synonyms, spelling variants, merged entries).
    other_names: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM taxon_names ORDER BY name"):
        other_names[r["taxon_id"]].append({
            "id": r["name_id"], "name": r["name"], "authority": r["authorship"],
            "kind": r["kind"], "note": r["note"], "sources": r["sources"]})
        if r["name"] and r["name"] not in synonyms[r["taxon_id"]]:
            synonyms[r["taxon_id"]].insert(0, r["name"])
    hosts: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT taxon_id, host FROM taxon_hosts ORDER BY host"):
        tid = keys.get(r["taxon_id"])
        if tid is not None and r["host"] not in hosts[tid]:
            hosts[tid].append(r["host"])
    evidence: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM taxon_evidence ORDER BY taxon_id, kind, ref"):
        evidence[r["taxon_id"]].append({"kind": r["kind"], "ref": r["ref"], "license": r["license"],
                                        "credit": r["credit"], "note": r["note"],
                                        "added_by": r["editor"], "added": r["edited"]})
    wd = {r["taxon_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM taxon_wikidata WHERE qid IS NOT NULL")}
    bugguide: dict[int, int] = {}
    for r in conn.execute("SELECT gbif_key, bugguide_id, name FROM bugguide_links"):
        tid = keys.get(r["gbif_key"])
        if tid in taxa and (tid not in bugguide or r["name"] == taxa[tid]["name"]):
            bugguide[tid] = r["bugguide_id"]
    for k, v in wd.items():          # Wikidata's BugGuide id where entobase has none
        if v["bugguide_id"] and v["confidence"] == "high" and str(v["bugguide_id"]).isdigit():
            bugguide.setdefault(k, int(v["bugguide_id"]))
    wiki = {keys.get(r["taxon_id"], r["taxon_id"]): {
        "title": r["title"], "url": r["url"], "revid": r["revid"],
        "rev_timestamp": r["rev_timestamp"], "retrieved": r["fetched_at"],
        "preview": preview(r["text"]), "lead_only": bool(r["lead_only"]), "html": r["html"]}
        for r in conn.execute("SELECT * FROM wikipedia_articles")}
    from .enrich.photos import THUMB_DIR, thumb_name

    photos: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
            "SELECT tp.taxon_id, tp.role, tp.from_taxon_id, p.* FROM taxon_photos tp JOIN photos p "
            "ON p.photo_id = tp.photo_id WHERE p.status = 'ok' ORDER BY tp.taxon_id, tp.position"):
        if r["taxon_id"] not in taxa:
            continue
        borrowed = taxa.get(r["from_taxon_id"]) if r["role"] == "inherited" else None
        local = THUMB_DIR / thumb_name(r["photo_id"])
        photos[r["taxon_id"]].append({
            # A borrowed photo shows a taxon below this one; the page has to say which.
            "of": borrowed["name"] if borrowed else None,
            "of_id": r["from_taxon_id"] if borrowed else None,
            "of_rank": borrowed["rank"] if borrowed else None,
            "display": r["display_url"],
            "thumb": f"media/thumbs/{local.name}" if local.exists() else r["thumb_url"],
            "w": r["width"], "h": r["height"],
            "source": PHOTO_SOURCES[r["source"]],
            "page": r["page_url"], "license": license_label(r["license_code"]),
            "license_url": r["license_url"], "attribution": r["attribution"],
            "retrieved": r["fetched_at"]})
    fetched = dict(conn.execute("SELECT taxon_id, fetched_at FROM col_taxa"))
    fetched_bb = dict(conn.execute("SELECT gbif_key, fetched_at FROM gbif_taxa"))
    presence_fetched = conn.execute(
        "SELECT MAX(fetched_at) FROM taxon_presence WHERE source = 'gbif'").fetchone()[0]

    # The Catalogue of Life's English names and synonyms (ChecklistBank, `colinfo`).
    col_info = {r["taxon_id"]: (json.loads(r["vernacular"] or "[]"), json.loads(r["synonyms"] or "[]"))
                for r in conn.execute("SELECT * FROM col_info")}
    for tid, (_, syns) in col_info.items():
        for n in syns:
            if tid in taxa and n != taxa[tid]["name"] and n not in synonyms[tid]:
                synonyms[tid].append(n)

    def common_of(t: dict) -> str | None:
        """Curated, then iNaturalist's (as used locally), then Wikidata's English, then the
        Catalogue of Life's, then GBIF's."""
        inat = inat_by_taxon.get(t["taxon_id"])
        if "common_name" in (t["curated_fields"] or ""):
            return clean_common(t["common_name"], t["name"])
        w = wd.get(t["taxon_id"]) or {}
        wcommon = json.loads(w["commons"])[0] if w.get("commons") and \
            w.get("confidence") == "high" else None
        ccommon = (col_info.get(t["taxon_id"]) or ([], []))[0]
        return clean_common((inat or {}).get("common") or wcommon or
                            (ccommon[0] if ccommon else None) or t["common_name"], t["name"])

    def brief(t: dict) -> dict:
        return {"id": t["taxon_id"], "rank": t["rank"], "name": t["name"], "common": common_of(t)}

    records = {}
    for tid, t in taxa.items():
        kids = sorted((taxa[c] for c in children[tid]),
                      key=lambda k: (k["status"] == "synonym", k["name"].casefold()))
        inat = inat_by_taxon.get(tid)
        w = wd.get(tid) or {}
        links = []
        col_id = ids.col_of(tid)
        if col_id and t["in_col"]:
            links.append({"system": "col", "label": "Catalogue of Life", "url": COL_TAXON + col_id,
                          "confidence": "high"})
            links.append({"system": "gbif", "label": "GBIF records in Micronesia",
                          "url": GBIF_RECORDS + col_id, "confidence": "high"})
        elif t["gbif_key"]:
            links.append({"system": "gbif", "label": "GBIF", "url": GBIF_SPECIES +
                          str(t["gbif_key"]), "confidence": "high"})
        # iNaturalist: Wikidata's id (keyed on the GBIF key, name checked) beats a name match.
        inat_id = w.get("inat_id") if w.get("confidence") == "high" else None
        if inat_id:
            links.append({"system": "inaturalist", "label": "iNaturalist",
                          "url": INAT_TAXA + str(inat_id), "confidence": "high",
                          "note": "via Wikidata"})
        elif inat:
            links.append({"system": "inaturalist", "label": "iNaturalist",
                          "url": INAT_TAXA + str(inat["id"]), "confidence": "medium",
                          "note": "matched by name"})
        if tid in bugguide:
            links.append({"system": "bugguide", "label": "BugGuide",
                          "url": f"https://bugguide.net/node/view/{bugguide[tid]}",
                          "confidence": "high", "note": "North American guide"})
        if tid in wiki:
            links.append({"system": "wikipedia", "label": "Wikipedia", "url": wiki[tid]["url"],
                          "confidence": "high"})
        if w.get("wikispecies"):
            links.append({"system": "wikispecies", "label": "Wikispecies", "url": w["wikispecies"],
                          "confidence": w["confidence"]})
        if w.get("qid"):
            links.append({"system": "wikidata", "label": "Wikidata",
                          "url": f"https://www.wikidata.org/wiki/{w['qid']}",
                          "confidence": w["confidence"],
                          "note": None if w["confidence"] == "high" else
                          f"Wikidata names it {w['name']}"})
        links.extend(extra_links.get(tid, []))
        records[tid] = {
            "id": tid, "ext": t["ext_id"] or ids.to_ext(tid), "in_col": bool(t["in_col"]),
            "match_note": t["match_note"], "names": other_names.get(tid, []),
            "machine_lit": [a for a in config.AREA_CODES if a in machine_lit.get(tid, ())],
            "rank": t["rank"], "name": t["name"], "authority": t["authorship"],
            "common": common_of(t), "status": t["status"], "origin": t["origin"],
            "accepted_id": t["accepted_id"], "establishment": t["establishment"],
            "hidden": bool(t["hidden"]), "hidden_reason": t["hidden_reason"],
            "note": t["note"], "curated": (t["curated_fields"] or "").split(",")
            if t["curated_fields"] else [],
            "species_count": n_species[tid],
            "lineage": [brief(taxa[a]) for a in _ancestors(tid, taxa)],
            "children": [{**brief(k), "hidden": bool(k["hidden"]), "status": k["status"],
                          "species_count": n_species[k["taxon_id"]],
                          "kids": len(children[k["taxon_id"]]), "map": None,
                          "regions": regions_of(k["taxon_id"]),
                          "est": k["establishment"] or next(
                              (x["status"] for x in est.get(k["taxon_id"], [])
                               if x["area"] == "GU"), None),
                          "isles": sorted({i for a in islands.get(k["taxon_id"], {}).values()
                                           for i in a}) or None,
                          "thumb": card_thumb(photos.get(k["taxon_id"]) or [])}
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
            # Other English names (Wikidata), for search: "globe skimmer" finds Pantala
            # whose page leads with iNaturalist's "Wandering Glider".
            "alt_common": sorted(set((json.loads(w["commons"]) if w.get("commons") and
                                      w.get("confidence") == "high" else []) +
                                     (col_info.get(tid) or ([], []))[0])),
            "status_sources": est.get(tid, []),
            "photos": photos.get(tid, []), "wikipedia": wiki.get(tid), "map": None,
            "sections": [],
            "conservation": {"iucn": w["iucn"], "qid": w["qid"]}
            if w.get("iucn") and w.get("confidence") == "high" else None,
            "links": links,
            "inat": inat and {"id": inat["id"], "common": inat["common"],
                              "observations": inat["observations"]},
            "sources": {"col": {"id": col_id if t["in_col"] else None,
                                "fetched_at": fetched.get(tid)},
                        "gbif": {"key": t["gbif_key"],
                                 "fetched_at": fetched_bb.get(t["gbif_key"]),
                                 "presence_fetched_at": presence_fetched}},
        }
    return records


def _record_path(site: Path, tid: int) -> Path:
    # Ids are spread over 10^12 (ids.py), so bucket by the last three digits.
    return site / "data" / "t" / str(tid % 1000) / f"{tid}.js"


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def home_cards(records: dict[int, dict], root: int) -> list[dict]:
    """The home page lists the orders (and the non-insect classes) as cards: Hexapoda's own
    children are just four classes, one of which holds nearly everything."""
    out = []
    for c in records[root]["children"]:
        if c["name"] == "Insecta":
            out += [k for k in records[c["id"]]["children"]]
        else:
            out.append(c)
    return sorted(out, key=lambda c: (c["hidden"], -c["species_count"], c["name"]))


def build(conn, site: Path | None = None) -> dict[str, int]:
    """Copy the app shell and write every changed record, the search index and meta.js;
    also taxonomy.csv at the top of the repository, after taking in any edits made to it."""
    from . import search, taxonomy

    synced = taxonomy.sync(conn)        # before the tree is read: edits there become curation
    if synced:
        print("taxonomy.csv: " + ", ".join(f"{k} {v}" for k, v in synced.items()
                                           if k != "changes"))
        for c in synced["changes"]:
            print("  " + c)
    site = site or config.SITE_DIR / "public"
    site.mkdir(parents=True, exist_ok=True)
    for src in WEBAPP_DIR.rglob("*"):
        if src.is_file() and src.name != ".DS_Store":
            dest = site / src.relative_to(WEBAPP_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Thumbnails ship with the site (the one kind of image we host); photos are hotlinked.
    from .enrich.photos import THUMB_DIR

    if THUMB_DIR.exists():
        dest = site / "media" / "thumbs"
        dest.mkdir(parents=True, exist_ok=True)
        have = {p.name for p in dest.glob("*.webp")}
        for src in THUMB_DIR.glob("*.webp"):
            if src.name not in have:
                shutil.copy2(src, dest / src.name)
    records = build_records(conn)
    built_at = db.now()
    written = 0
    for tid, rec in records.items():
        body = json.dumps(rec, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        # built_at stays out of the hashed body, so an unchanged record is not rewritten.
        digest = hashlib.sha1(body.encode()).hexdigest()[:12]
        content = (f"{JS_GLOBAL}.load({body[:-1]},\"built_at\":\"{built_at}\","
                   f"\"hash\":\"{digest}\"}});\n")
        path = _record_path(site, tid)
        if path.exists() and f'"hash":"{digest}"' in path.read_text(encoding="utf-8"):
            continue
        _write_if_changed(path, content)
        written += 1
    keep = {_record_path(site, tid) for tid in records}
    removed = 0
    for stale in (site / "data" / "t").rglob("*.js"):
        if stale not in keep:
            stale.unlink()
            removed += 1

    table = taxonomy.rows(conn, records)
    taxonomy.write(table)
    (site / "data").mkdir(exist_ok=True)
    _write_if_changed(site / "data" / "taxonomy.js", taxonomy.site_script(table))

    idx = search.build(conn, records, site)
    root = next((tid for tid, r in records.items() if not r["lineage"]), None)
    species = [r for r in records.values() if r["rank"] == "Species" and not r["hidden"]
               and r["status"] != "synonym"]
    meta = {
        "built_at": built_at, "root": root,
        "title": config.SITE_TITLE, "subtitle": config.SITE_SUBTITLE,
        "home": home_cards(records, root) if root else [],
        "regions": [{"key": AREA_KEYS[a["code"]], "code": a["code"], "label": AREA_SHORT[a["code"]],
                     "name": a["name"]} for a in config.AREAS],
        "geo": geo.for_meta(),
        "search": {"docs": idx["docs"], "shards": idx["shards"], "stopwords": idx["stopwords"]},
        "counts": {
            "taxa": len(records), "species": len(species),
            "guam": sum("gu" in (r["regions"] or []) for r in species),
            "morphospecies": sum(r["status"] == "morphospecies" for r in records.values()),
            "not_in_col": sum(not r["in_col"] and r["origin"] != "curated" for r in species),
            "photos": sum(bool(r["photos"]) for r in records.values()),
            "literature": sum(bool(r["literature"]) for r in species),
        },
    }
    (site / "data").mkdir(exist_ok=True)
    _write_if_changed(site / "data" / "meta.js",
                      f"{JS_GLOBAL}.meta({json.dumps(meta, separators=(',', ':'))});\n")
    shipped = [p for p in site.rglob("*") if p.is_file() and ".vercel" not in p.parts]
    total = sum(p.stat().st_size for p in shipped)
    files = len(shipped)
    return {"records": len(records), "written": written, "removed": removed,
            "search_docs": idx["docs"], "files": files, "megabytes": round(total / 1e6, 1)}
