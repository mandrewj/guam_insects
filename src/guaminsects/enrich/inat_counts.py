"""iNaturalist species counts per area: what iNat has that GBIF lacks, plus observation counts.

One stream, about one request a second (docs/LESSONS.md: iNat 429s come from concurrent
streams, and the user's entobase jobs share this IP). Research grade, wild only.
"""

import sys

from .. import config, db
from .gbif_checklist import match_name, parse_taxon, store_taxon
from .http import ApiClient

INAT = "https://api.inaturalist.org/v1"
PAGE = 500
GBIF_RANKS = {"species": "SPECIES", "subspecies": "SUBSPECIES", "genus": "GENUS"}


def place_counts(client: ApiClient, place_id: int) -> list[dict]:
    out, page = [], 1
    while True:
        d = client.get("/observations/species_counts", {
            "place_id": place_id, "taxon_id": config.INAT_HEXAPODA, "quality_grade": "research",
            "captive": "false", "per_page": PAGE, "page": page})
        out += d.get("results", [])
        if len(out) >= d.get("total_results", 0) or not d.get("results"):
            return out
        page += 1


def sweep(conn, client: ApiClient) -> dict[str, int]:
    done = {}
    for area in config.AREAS:
        rows = place_counts(client, area["inat"])
        stamp = db.now()
        with conn:
            conn.execute("DELETE FROM inat_place_counts WHERE place_id = ?", (area["inat"],))
            conn.executemany(
                "INSERT INTO inat_place_counts (inat_id, place_id, area, name, rank, common_name,"
                " iconic, observations, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(r["taxon"]["id"], area["inat"], area["code"], r["taxon"]["name"],
                  r["taxon"]["rank"], r["taxon"].get("preferred_common_name"),
                  r["taxon"].get("iconic_taxon_name"), r["count"], stamp) for r in rows])
        done[area["code"]] = len(rows)
        print(f"iNat {area['code']}: {len(rows)} taxa", file=sys.stderr)
    return done


def link_to_gbif(conn, gbif: ApiClient) -> dict[str, int]:
    """Give each iNat name a GBIF key (strict match rules) and write source='inat' presence.

    A name GBIF already has records for still gets an 'inat' row: the two counts are shown
    side by side, never summed (they overlap, since research-grade iNat flows into GBIF).
    """
    names = conn.execute(
        "SELECT name, rank, area, SUM(observations) n FROM inat_place_counts "
        "WHERE rank IN ('species', 'subspecies', 'genus') GROUP BY name, rank, area").fetchall()
    keys: dict[tuple[str, str], int | None] = {}
    stats = {"matched": 0, "unmatched": 0}
    rows = []
    for r in names:
        k = (r["name"], r["rank"])
        if k not in keys:
            m = match_name(gbif, r["name"], GBIF_RANKS[r["rank"]])
            key = m and (m.get("acceptedUsageKey") or m.get("usageKey"))
            keys[k] = key
            stats["matched" if key else "unmatched"] += 1
            if key and not conn.execute("SELECT 1 FROM gbif_taxa WHERE gbif_key = ?",
                                        (key,)).fetchone():
                store_taxon(conn, parse_taxon(gbif.get_cached(f"/species/{key}")))
                conn.commit()
        if keys[k]:
            rows.append((keys[k], r["area"], r["n"]))
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM taxon_presence WHERE source = 'inat'")
        conn.executemany(
            "INSERT INTO taxon_presence (taxon_id, area, source, records, fetched_at) "
            "VALUES (?, ?, 'inat', ?, ?) ON CONFLICT (taxon_id, area, source) "
            "DO UPDATE SET records = records + excluded.records",
            [(k, a, n, stamp) for k, a, n in rows])
    return stats
