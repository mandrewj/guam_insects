"""The backbone: which hexapod taxa GBIF has records of in each area, and their classification.

`sweep` asks GBIF once per (area, rank facet) for every taxon key with records there (about 40
requests for all five areas), never once per taxon. `fetch_taxa` then reads /species/{key}
for each of those keys and every ancestor, cached under data/raw/ so re-runs are free.
"""

import sys

from .. import config, db
from .http import ApiClient

GBIF = "https://api.gbif.org/v1"
FACETS = ("speciesKey", "genusKey", "familyKey", "orderKey")
FACET_PAGE = 1000
# Everything but fossils and living collections (zoos, insectaries, quarantine colonies).
BASIS = ("PRESERVED_SPECIMEN", "HUMAN_OBSERVATION", "MACHINE_OBSERVATION", "OBSERVATION",
         "MATERIAL_SAMPLE", "MATERIAL_CITATION", "OCCURRENCE")


def occurrence_filter(country: str) -> list[tuple[str, str | int]]:
    """Shared filters; a list because GBIF ORs repeated parameters (taxonKey, basisOfRecord)."""
    params: list[tuple[str, str | int]] = [("country", country),
                                           ("hasGeospatialIssue", "false"),
                                           ("occurrenceStatus", "PRESENT")]
    params += [("taxonKey", k) for k in config.HEXAPOD_CLASSES]
    params += [("basisOfRecord", b) for b in BASIS]
    return params


def facet_counts(client: ApiClient, country: str, facet: str) -> dict[int, int]:
    """{taxon key: records} for one facet, paged."""
    out: dict[int, int] = {}
    offset = 0
    while True:
        params = occurrence_filter(country) + [("limit", 0), ("facet", facet),
                                               ("facetLimit", FACET_PAGE),
                                               ("facetOffset", offset)]
        data = client.get("/occurrence/search", params)
        counts = (data.get("facets") or [{}])[0].get("counts", [])
        out.update((int(c["name"]), int(c["count"])) for c in counts)
        if len(counts) < FACET_PAGE:
            return out
        offset += FACET_PAGE


def sweep(conn, client: ApiClient, areas: list[str] | None = None) -> dict[str, int]:
    """Replace the GBIF presence rows of each area. Network first, then one short write."""
    done = {}
    for area in config.AREAS:
        if areas and area["code"] not in areas:
            continue
        counts: dict[int, int] = {}
        per_facet = {}
        for facet in FACETS:
            got = facet_counts(client, area["gbif"], facet)
            per_facet[facet] = len(got)
            counts.update(got)          # a key belongs to exactly one rank: no clashes
        stamp = db.now()
        with conn:
            conn.execute("DELETE FROM taxon_presence WHERE area = ? AND source = 'gbif'",
                         (area["code"],))
            conn.executemany(
                "INSERT INTO taxon_presence (taxon_id, area, source, records, fetched_at) "
                "VALUES (?, ?, 'gbif', ?, ?)",
                [(k, area["code"], n, stamp) for k, n in counts.items()])
            conn.executemany(
                "INSERT OR REPLACE INTO presence_queries (area, source, facet, taxa, answered_at) "
                "VALUES (?, 'gbif', ?, ?, ?)",
                [(area["code"], f, n, stamp) for f, n in per_facet.items()])
        done[area["code"]] = len(counts)
        print(f"GBIF {area['code']}: " + ", ".join(f"{f} {n}" for f, n in per_facet.items()),
              file=sys.stderr)
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
    todo = sorted(keys - known) if not refresh else sorted(keys)
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
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT taxon_id FROM taxon_presence WHERE taxon_id < ?",
        (config.CURATED_ID_BASE,))}


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
