"""Which hexapod taxa GBIF has records of in each area.

`sweep` asks GBIF once per (area, rank facet) for every taxon key with records there (about 40
requests for all five areas), never once per taxon. GBIF interprets every occurrence against
two taxonomies: the Catalogue of Life (COL XR, the tree this site uses; keys like "KVC9L",
stored as ids.from_col) and the legacy GBIF Backbone (integer keys, source 'gbif_backbone').
The Backbone sweep is kept for one job: finding the names COL does not have (enrich/col.py).
`fetch_taxa` reads /species/{key} for Backbone keys and their ancestors, for their names.
"""

import sys

from .. import config, db, ids
from .http import ApiClient

GBIF = "https://api.gbif.org/v1"
FACETS = ("speciesKey", "genusKey", "familyKey", "orderKey")
COL_FACETS = FACETS + ("classKey",)
COL_CHECKLIST = "7ddf754f-d193-4cc9-b351-99906754a03b"   # Catalogue of Life eXtended Release
COL_HEXAPODA = "L2655"
FACET_PAGE = 1000
# Everything but fossils and living collections (zoos, insectaries, quarantine colonies).
BASIS = ("PRESERVED_SPECIMEN", "HUMAN_OBSERVATION", "MACHINE_OBSERVATION", "OBSERVATION",
         "MATERIAL_SAMPLE", "MATERIAL_CITATION", "OCCURRENCE")
# Physical specimens in a collection: the "specimen records" level of verification.
SPECIMEN_BASIS = ("PRESERVED_SPECIMEN", "MATERIAL_SAMPLE")


def occurrence_filter(country: str, basis: tuple[str, ...] = BASIS,
                      col: bool = True) -> list[tuple[str, str | int]]:
    """Shared filters; a list because GBIF ORs repeated parameters (taxonKey, basisOfRecord).
    `col`: keys and facets in the Catalogue of Life (else the GBIF Backbone)."""
    params: list[tuple[str, str | int]] = [("country", country),
                                           ("hasGeospatialIssue", "false"),
                                           ("occurrenceStatus", "PRESENT")]
    if col:
        params += [("checklistKey", COL_CHECKLIST), ("taxonKey", COL_HEXAPODA)]
    else:
        params += [("taxonKey", k) for k in config.HEXAPOD_CLASSES]
    params += [("basisOfRecord", b) for b in basis]
    return params


def facet_key(name: str, col: bool) -> int:
    return ids.from_col(name) if col else int(name)


def facet_counts(client: ApiClient, country: str, facet: str,
                 basis: tuple[str, ...] = BASIS, col: bool = True) -> dict[int, int]:
    """{taxon key (internal id): records} for one facet, paged."""
    out: dict[int, int] = {}
    offset = 0
    while True:
        params = occurrence_filter(country, basis, col) + [("limit", 0), ("facet", facet),
                                               ("facetLimit", FACET_PAGE),
                                               ("facetOffset", offset)]
        data = client.get("/occurrence/search", params)
        counts = (data.get("facets") or [{}])[0].get("counts", [])
        out.update((facet_key(c["name"], col), int(c["count"])) for c in counts)
        if len(counts) < FACET_PAGE:
            return out
        offset += FACET_PAGE


def sweep(conn, client: ApiClient, areas: list[str] | None = None,
          col: bool = True) -> dict[str, int]:
    """Replace the GBIF presence rows of each area (source 'gbif' for COL keys,
    'gbif_backbone' for Backbone keys). Network first, then one short write."""
    source = "gbif" if col else "gbif_backbone"
    done = {}
    for area in config.AREAS:
        if areas and area["code"] not in areas:
            continue
        counts: dict[int, int] = {}
        per_facet = {}
        for facet in (COL_FACETS if col else FACETS):
            got = facet_counts(client, area["gbif"], facet, col=col)
            per_facet[facet] = len(got)
            counts.update(got)          # a key belongs to exactly one rank: no clashes
        stamp = db.now()
        with conn:
            conn.execute("DELETE FROM taxon_presence WHERE area = ? AND source = ?",
                         (area["code"], source))
            conn.executemany(
                "INSERT INTO taxon_presence (taxon_id, area, source, records, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [(k, area["code"], source, n, stamp) for k, n in counts.items()])
            conn.executemany(
                "INSERT OR REPLACE INTO presence_queries (area, source, facet, taxa, answered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [(area["code"], source, f, n, stamp) for f, n in per_facet.items()])
        done[area["code"]] = len(counts)
        print(f"GBIF {source} {area['code']}: " + ", ".join(f"{f} {n}" for f, n in per_facet.items()),
              file=sys.stderr)
    return done


def specimen_sweep(conn, client: ApiClient) -> dict[str, int]:
    """Replace taxon_specimens: GBIF preserved specimens and material samples per area,
    by the same facets as `sweep` (COL keys; about 25 requests for all five areas)."""
    done = {}
    for area in config.AREAS:
        counts: dict[int, int] = {}
        for facet in COL_FACETS:
            counts.update(facet_counts(client, area["gbif"], facet, SPECIMEN_BASIS))
        stamp = db.now()
        with conn:
            conn.execute("DELETE FROM taxon_specimens WHERE area = ?", (area["code"],))
            conn.executemany(
                "INSERT INTO taxon_specimens (taxon_id, area, records, fetched_at) "
                "VALUES (?, ?, ?, ?)", [(k, area["code"], n, stamp) for k, n in counts.items()])
        done[area["code"]] = len(counts)
        print(f"GBIF specimens {area['code']}: {len(counts)} taxa", file=sys.stderr)
    return done


def parse_taxon(d: dict) -> dict:
    return {
        "gbif_key": d["key"],
        "parent_key": d.get("parentKey"),
        "rank": d.get("rank"),
        "canonical_name": d.get("canonicalName") or d.get("scientificName"),
        "scientific_name": d.get("scientificName"),
        "authorship": (d.get("authorship") or "").strip() or None,
        "taxonomic_status": d.get("taxonomicStatus"),
        "accepted_key": d.get("acceptedKey"),
        "class_key": d.get("classKey"),
        "order_key": d.get("orderKey"),
        "family_key": d.get("familyKey"),
        "genus_key": d.get("genusKey"),
        "species_key": d.get("speciesKey"),
        "vernacular_name": d.get("vernacularName"),
    }


COLUMNS = list(parse_taxon({"key": 0}).keys()) + ["fetched_at"]


def store_taxon(conn, row: dict) -> None:
    row = dict(row, fetched_at=db.now())
    conn.execute(f"INSERT OR REPLACE INTO gbif_taxa ({', '.join(COLUMNS)}) "
                 f"VALUES ({', '.join('?' for _ in COLUMNS)})", [row[c] for c in COLUMNS])


def fetch_taxa(conn, client: ApiClient, keys: set[int], refresh: bool = False) -> int:
    """Fetch every key and its ancestors (up to Arthropoda). Commits every 50 taxa."""
    known = {r[0] for r in conn.execute("SELECT gbif_key FROM gbif_taxa")}
    # Repair: any stored taxon whose parent (or accepted name) was never fetched.
    gaps = {k for row in conn.execute("SELECT parent_key, accepted_key FROM gbif_taxa")
            for k in row if k and k not in known and k != config.ARTHROPODA_KEY}
    todo = sorted((keys | gaps) - known) if not refresh else sorted(keys | gaps)
    queued = set(todo)
    fetched = 0
    while todo:
        key = todo.pop()
        try:
            d = client.get_cached(f"/species/{key}", refresh=refresh)
        except Exception as e:   # one bad key must not stop the sweep; it is retried next run
            print(f"  /species/{key}: {e}", file=sys.stderr)
            continue
        row = parse_taxon(d)
        store_taxon(conn, row)
        fetched += 1
        nxt = [row["parent_key"], row["accepted_key"]]
        for k in nxt:
            if k and k not in known and k not in queued and k != config.ARTHROPODA_KEY:
                queued.add(k)
                todo.append(k)
        if fetched % 50 == 0:
            conn.commit()
            print(f"  GBIF taxa: {fetched} fetched, {len(todo)} to go", file=sys.stderr)
    conn.commit()
    return fetched


def present_keys(conn) -> set[int]:
    """GBIF Backbone keys with presence of any kind (their names are matched to COL)."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT taxon_id FROM taxon_presence WHERE taxon_id < ?", (ids.COL_BASE,))}


def match_name(client: ApiClient, name: str, rank: str | None = None) -> dict | None:
    """GBIF name match with entobase's accept rules: EXACT, or FUZZY when the canonical name
    agrees after normalising case and spaces; never HIGHERRANK (a genus for a species)."""
    params = {"name": name, "kingdom": "Animalia"}
    if rank:
        params["rank"] = rank.upper()
    d = client.get_cached("/species/match", params)
    mt = d.get("matchType")
    if mt == "EXACT" or (mt == "FUZZY" and _norm(d.get("canonicalName")) == _norm(name)):
        if d.get("classKey") in config.HEXAPOD_CLASSES:
            return d
    return None


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def fetch_synonyms(conn, client: ApiClient, refresh: bool = False) -> dict[str, int]:
    """GBIF synonyms of every species and genus in the tree, into taxon_synonyms (source
    'gbif'). Old Micronesian literature uses old names: search and the PDF name finder
    read these. One request per taxon, cached; resumable."""
    done = set() if refresh else {r[0] for r in conn.execute(
        "SELECT DISTINCT taxon_id FROM taxon_synonyms WHERE source IN ('gbif', 'gbif:none')")}
    todo = [r[0] for r in conn.execute(
        "SELECT taxon_id FROM taxa WHERE gbif_key = taxon_id AND rank IN ('Species', "
        "'Subspecies', 'Genus') ORDER BY rank != 'Species', taxon_id") if r[0] not in done]
    stats = {"asked": len(todo), "synonyms": 0}
    for i, tid in enumerate(todo, 1):
        try:
            d = client.get_cached(f"/species/{tid}/synonyms", {"limit": 100})
        except Exception as e:      # retried on the next run
            print(f"  synonyms {tid}: {e}", file=sys.stderr)
            continue
        names = {(r.get("canonicalName") or "").strip() for r in d.get("results", [])} - {""}
        with conn:
            if names:
                conn.executemany("INSERT OR IGNORE INTO taxon_synonyms (taxon_id, synonym, "
                                 "source) VALUES (?, ?, 'gbif')", [(tid, n) for n in names])
            else:                    # asked, none: remembered so a re-run skips it
                conn.execute("INSERT OR IGNORE INTO taxon_synonyms (taxon_id, synonym, source) "
                             "VALUES (?, '', 'gbif:none')", (tid,))
        stats["synonyms"] += len(names)
        if i % 200 == 0:
            print(f"  synonyms: {i}/{len(todo)}", file=sys.stderr)
    return stats
