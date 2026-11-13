"""Export the database into the static web app (site/public or site/local).

The app is one page (index.html) that renders any taxon from a small data file:
data/t/<id // 1000>/<id>.js, which calls guaminsects.load(<record>). Browsers allow
<script src> from file://, unlike fetch(), so the site works by double-clicking index.html
and equally from a web server or Vercel.

`build_records` defines the record the app renders; `docs/APP_SPEC.md` describes it. Records
are rewritten only when their content changes (a hash per file), so a rebuild after a small
curation edit touches a handful of files.

Two targets share this code. `public` is what gets deployed: openly licensed content only.
`local` may add what must not be published (PDF snippets, links to files in literature/);
until those sources exist the two are the same.
"""

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from . import config, db

WEBAPP_DIR = config.ROOT / "webapp"
JS_GLOBAL = "guaminsects"          # webapp/assets/app.js defines window.guaminsects
TARGETS = ("public", "local")
PUBLIC_BUDGET_MB = 90              # Vercel Hobby takes 100 MB per CLI deploy
AREA_KEYS = {a["code"]: a["code"].lower() for a in config.AREAS}   # URL-friendly region keys
AREA_SHORT = {"GU": "Guam", "MP": "CNMI", "PW": "Palau", "FM": "FSM", "MH": "Marshalls"}
ABOVE_FAMILY = {"Subphylum", "Class", "Subclass", "Superorder", "Order", "Suborder",
                "Infraorder", "Superfamily"}
SPECIES_RANKS = {"Species"}
GBIF_SPECIES = "https://www.gbif.org/species/"
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


def build_records(conn, target: str = "public") -> dict[int, dict]:
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    children: dict[int, list[int]] = defaultdict(list)
    for t in taxa.values():
        if t["parent_id"] is not None and t["parent_id"] in taxa:
            children[t["parent_id"]].append(t["taxon_id"])
    roots = [tid for tid, t in taxa.items() if t["parent_id"] is None]
    order = _postorder(children, roots)          # leaves first, for every roll-up below

    # Presence: what each source says per area, keyed by taxon.
    own: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for r in conn.execute("SELECT taxon_id, area, source, records FROM taxon_presence"):
        if r["taxon_id"] in taxa:
            # Both literature sources (Plazi's digitised checklists, the PDF library) count
            # as "literature": the number is how many documents record the taxon there.
            src = "literature" if r["source"] in ("plazi", "pdf") else r["source"]
            cell = own[r["taxon_id"]][r["area"]]
            cell[src] = cell.get(src, 0) + (r["records"] or 0)
    # Curated evidence (an iNat observation, a GBIF record) puts a taxon on the list even
    # with no area yet; the curator gives the area in the note until evidence is fetched.

    # Roll-ups, leaves first: species per area (a species counts in an area when any source
    # records it there), iNat observations summed (iNat counts are per leaf taxon), visible
    # species overall. GBIF counts are not summed: the facet already counted every record
    # under a genus, family or order key.
    species_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    inat_sum: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    lit_in: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    n_species: dict[int, int] = {}
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
                   "gbif": srcs.get("gbif") or 0,
                   "inat": inat_sum[tid].get(area, 0),
                   "literature": len(lit_in[tid].get(area, ())) if t["rank"] not in
                   SPECIES_RANKS else srcs.get("literature", 0),
                   "species": len(species_in[tid].get(area, ())) if t["rank"] not in
                   SPECIES_RANKS else None}
            if row["gbif"] or row["inat"] or row["literature"] or row["species"]:
                rows.append(row)
        return rows

    def regions_of(tid: int) -> list[str] | None:
        areas = {a for a, s in own[tid].items() if any(s.values())}
        areas |= {a for a, s in species_in[tid].items() if s}
        return [AREA_KEYS[a] for a in config.AREA_CODES if a in areas] or None

    # Families under each rank above family, so an order page reaches them in one step.
    families: dict[int, list[dict]] = {}
    for tid, t in taxa.items():
        if t["rank"] not in ABOVE_FAMILY:
            continue
        out, stack, seen = [], list(children[tid]), set()
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            k = taxa[c]
            if k["rank"] == "Family" and not k["hidden"] and n_species[c]:
                out.append({"id": c, "name": k["name"], "common": None, "n": n_species[c]})
            elif k["rank"] not in ("Genus", "Species", "Subspecies"):
                stack.extend(children[c])
        if len(out) > 1:
            families[tid] = sorted(out, key=lambda f: f["name"].casefold())

    # iNaturalist: the taxa iNat has observations of here, matched by name (rank agreeing).
    inat_by_name: dict[tuple[str, str], dict] = {}
    for r in conn.execute("SELECT inat_id, name, rank, common_name, SUM(observations) n "
                          "FROM inat_place_counts GROUP BY inat_id"):
        inat_by_name[(r["name"], r["rank"])] = {"id": r["inat_id"], "common": r["common_name"],
                                                "observations": r["n"]}

    # Literature: digitised checklists naming the taxon (Plazi on GBIF).
    lit: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
            "SELECT DISTINCT n.nub_key, s.dataset_key, s.title, s.citation, s.areas, s.doi "
            "FROM checklist_names n JOIN checklist_sources s ON s.dataset_key = n.dataset_key "
            "ORDER BY s.title"):
        if r["nub_key"] in taxa:
            lit[r["nub_key"]].append({
                "title": r["title"], "citation": r["citation"],
                "areas": (r["areas"] or "").split(",") if r["areas"] else [],
                "url": f"https://www.gbif.org/dataset/{r['dataset_key']}",
                "doi": r["doi"], "source": "plazi"})
    # The PDF library: one entry per (taxon, document) with the pages. The public build cites
    # (title, pages, the publisher's URL); only the local build carries a snippet and a link
    # to the file on this computer (CLAUDE.md rule 4).
    from . import library as librarylib

    lib_rows = {r["file"]: r for r in librarylib.rows()} if librarylib.LIBRARY.exists() else {}
    pdf_hits: dict[tuple[int, str], dict] = {}
    for r in conn.execute("SELECT taxon_id, file, page, kind, areas, snippet, decision FROM "
                          "pdf_mentions WHERE decision != 'rejected' ORDER BY file, page"):
        if r["taxon_id"] not in taxa or r["file"] not in lib_rows:
            continue
        e = pdf_hits.setdefault((r["taxon_id"], r["file"]), {
            "pages": [], "areas": set(), "treated": False, "snippet": None})
        if r["page"] not in e["pages"]:
            e["pages"].append(r["page"])
        e["areas"] |= set((r["areas"] or "").split(",")) - {""}
        e["treated"] |= r["kind"] == "heading"
        if target == "local" and not e["snippet"] and r["snippet"]:
            e["snippet"] = r["snippet"]
    for (tid, fname), e in pdf_hits.items():
        doc = lib_rows[fname]
        lit[tid].append({
            "title": doc["title"], "citation": librarylib.citation(doc),
            "areas": [a for a in config.AREA_CODES if a in e["areas"]],
            "url": doc["url"] or None, "doi": None, "source": "pdf",
            "pages": e["pages"][:12], "treated": e["treated"], "year": doc["year"],
            "kind": doc["kind"],
            **({"snippet": e["snippet"], "file": "literature/" + fname}
               if target == "local" else {})})
    for entries in lit.values():
        entries.sort(key=lambda w: (not w.get("treated"), w.get("year") or "9999"))
    # Islands named in species accounts (literature headings), and later GBIF's level-1
    # areas: {area: {island: [sources]}} shown as "Recorded on" under the presence table.
    from .literature import ISLANDS

    island_area = {isl: a for a, d in ISLANDS.items() for isl in d.values()}
    islands: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in conn.execute("SELECT taxon_id, islands FROM pdf_mentions WHERE kind = 'heading' "
                          "AND islands IS NOT NULL AND decision != 'rejected'"):
        for isl in r["islands"].split(","):
            if isl in island_area:
                islands[r["taxon_id"]][island_area[isl]].add(isl)
    for r in conn.execute("SELECT taxon_id, area, island FROM taxon_islands"):
        islands[r["taxon_id"]][r["area"]].add(r["island"])
    evidence: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM taxon_evidence ORDER BY taxon_id, kind, ref"):
        evidence[r["taxon_id"]].append({"kind": r["kind"], "ref": r["ref"], "license": r["license"],
                                        "credit": r["credit"], "note": r["note"]})
    wd = {r["gbif_key"]: dict(r) for r in conn.execute(
        "SELECT * FROM wikidata_taxa WHERE qid IS NOT NULL")}
    bugguide = dict(conn.execute("SELECT gbif_key, bugguide_id FROM bugguide_links"))
    for k, v in wd.items():          # Wikidata's BugGuide id where entobase has none
        if v["bugguide_id"] and v["confidence"] == "high" and str(v["bugguide_id"]).isdigit():
            bugguide.setdefault(k, int(v["bugguide_id"]))
    wiki = {r["taxon_id"]: {
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
            "source": "iNaturalist" if r["source"] == "inaturalist" else "Wikimedia Commons",
            "page": r["page_url"], "license": license_label(r["license_code"]),
            "license_url": r["license_url"], "attribution": r["attribution"],
            "retrieved": r["fetched_at"]})
    fetched = dict(conn.execute("SELECT gbif_key, fetched_at FROM gbif_taxa"))
    presence_fetched = conn.execute(
        "SELECT MAX(fetched_at) FROM taxon_presence WHERE source = 'gbif'").fetchone()[0]

    def common_of(t: dict) -> str | None:
        """Curated, then iNaturalist's (as used locally), then Wikidata's English, then GBIF's."""
        inat = inat_by_name.get((t["name"], t["rank"].lower()))
        if "common_name" in (t["curated_fields"] or ""):
            return clean_common(t["common_name"], t["name"])
        w = wd.get(t["gbif_key"]) or {}
        wcommon = json.loads(w["commons"])[0] if w.get("commons") and \
            w.get("confidence") == "high" else None
        return clean_common((inat or {}).get("common") or wcommon or t["common_name"], t["name"])

    def brief(t: dict) -> dict:
        return {"id": t["taxon_id"], "rank": t["rank"], "name": t["name"], "common": common_of(t)}

    records = {}
    for tid, t in taxa.items():
        kids = sorted((taxa[c] for c in children[tid]),
                      key=lambda k: (k["status"] == "synonym", k["name"].casefold()))
        inat = inat_by_name.get((t["name"], t["rank"].lower()))
        w = wd.get(t["gbif_key"]) or {}
        links = []
        if t["gbif_key"]:
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
        if t["gbif_key"] in bugguide:
            links.append({"system": "bugguide", "label": "BugGuide",
                          "url": f"https://bugguide.net/node/view/{bugguide[t['gbif_key']]}",
                          "confidence": "high", "note": "North American guide"})
        if tid in wiki:
            links.append({"system": "wikipedia", "label": "Wikipedia", "url": wiki[tid]["url"],
                          "confidence": "high"})
        if w.get("qid"):
            links.append({"system": "wikidata", "label": "Wikidata",
                          "url": f"https://www.wikidata.org/wiki/{w['qid']}",
                          "confidence": w["confidence"],
                          "note": None if w["confidence"] == "high" else
                          f"Wikidata names it {w['name']}"})
        records[tid] = {
            "id": tid, "rank": t["rank"], "name": t["name"], "authority": t["authorship"],
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
                          "thumb": card_thumb(photos.get(k["taxon_id"]) or [])}
                         for k in kids],
            "families": families.get(tid, []),
            "presence": presence_of(tid),
            "islands": [{"area": a, "label": AREA_SHORT[a],
                         "islands": sorted(i for i in islands[tid][a]
                                           if i not in (AREA_SHORT[a], "Palau", "Marshall Is."))}
                        for a in config.AREA_CODES if a in islands.get(tid, {})],
            "regions": regions_of(tid),
            "literature": lit.get(tid, []),
            "evidence": evidence.get(tid, []),
            "photos": photos.get(tid, []), "wikipedia": wiki.get(tid), "map": None,
            "sections": [],
            "conservation": {"iucn": w["iucn"], "qid": w["qid"]}
            if w.get("iucn") and w.get("confidence") == "high" else None,
            "links": links,
            "inat": inat and {"id": inat["id"], "common": inat["common"],
                              "observations": inat["observations"]},
            "sources": {"gbif": {"key": t["gbif_key"], "fetched_at": fetched.get(t["gbif_key"]),
                                 "presence_fetched_at": presence_fetched}},
        }
    return records


def _record_path(site: Path, tid: int) -> Path:
    return site / "data" / "t" / str(tid // 1000) / f"{tid}.js"


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


def build(conn, target: str = "public", site: Path | None = None) -> dict[str, int]:
    """Copy the app shell and write every changed record, the search index and meta.js."""
    from . import search

    assert target in TARGETS, target
    site = site or config.SITE_DIR / target
    site.mkdir(parents=True, exist_ok=True)
    for src in WEBAPP_DIR.rglob("*"):
        # The curation admin exists only in the local build (and needs `guaminsects serve`).
        if target == "public" and src.name.startswith("admin."):
            (site / src.relative_to(WEBAPP_DIR)).unlink(missing_ok=True)
            continue
        if src.is_file() and src.name != ".DS_Store":
            dest = site / src.relative_to(WEBAPP_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    if target == "local":
        # The local build opens PDFs on this computer: a link, so nothing is copied, and the
        # public build (deployed) never has one.
        link = site / "literature"
        if not link.is_symlink():
            link.symlink_to(config.LITERATURE_DIR)
    # Thumbnails ship with the site (the one kind of image we host); photos are hotlinked.
    from .enrich.photos import THUMB_DIR

    if THUMB_DIR.exists():
        dest = site / "media" / "thumbs"
        dest.mkdir(parents=True, exist_ok=True)
        have = {p.name for p in dest.glob("*.webp")}
        for src in THUMB_DIR.glob("*.webp"):
            if src.name not in have:
                shutil.copy2(src, dest / src.name)
    records = build_records(conn, target)
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

    idx = search.build(conn, records, site)
    root = config.HEXAPODA_ID if config.HEXAPODA_ID in records else None
    species = [r for r in records.values() if r["rank"] == "Species" and not r["hidden"]
               and r["status"] != "synonym"]
    meta = {
        "built_at": built_at, "root": root, "target": target,
        "title": config.SITE_TITLE, "subtitle": config.SITE_SUBTITLE,
        "home": home_cards(records, root) if root else [],
        "regions": [{"key": AREA_KEYS[a["code"]], "code": a["code"], "label": AREA_SHORT[a["code"]],
                     "name": a["name"]} for a in config.AREAS],
        "search": {"docs": idx["docs"], "shards": idx["shards"], "stopwords": idx["stopwords"]},
        "counts": {
            "taxa": len(records), "species": len(species),
            "guam": sum("gu" in (r["regions"] or []) for r in species),
            "morphospecies": sum(r["status"] == "morphospecies" for r in records.values()),
            "photos": sum(bool(r["photos"]) for r in records.values()),
            "literature": sum(bool(r["literature"]) for r in species),
        },
    }
    (site / "data").mkdir(exist_ok=True)
    _write_if_changed(site / "data" / "meta.js",
                      f"{JS_GLOBAL}.meta({json.dumps(meta, separators=(',', ':'))});\n")
    shipped = [p for p in site.rglob("*") if p.is_file() and "literature" not in p.parts]
    total = sum(p.stat().st_size for p in shipped)
    files = len(shipped)
    return {"records": len(records), "written": written, "removed": removed,
            "search_docs": idx["docs"], "files": files, "megabytes": round(total / 1e6, 1)}
