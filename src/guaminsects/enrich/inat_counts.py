"""iNaturalist species counts per area: what iNat has that GBIF lacks, plus observation counts.

One stream, about one request a second (docs/LESSONS.md: iNat 429s come from concurrent
streams, and the user's entobase jobs share this IP). Research grade, wild only.
"""

import sys
import time

import httpx

from .. import config, db
from .http import ApiClient

INAT = "https://api.inaturalist.org/v1"
PAGE = 200
# A species_counts page is an expensive query for iNat, and its throttle is per minute and
# shared with whatever else runs on this IP: after the client's own retries, wait minutes,
# not seconds, and keep going for hours rather than fail the night's run.
PATIENT_WAIT = 300
PATIENT_TRIES = 24
GBIF_RANKS = {"species": "SPECIES", "subspecies": "SUBSPECIES", "genus": "GENUS"}


def patient_get(client: ApiClient, path: str, params: dict) -> dict:
    for attempt in range(PATIENT_TRIES):
        try:
            return client.get(path, params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or attempt == PATIENT_TRIES - 1:
                raise
            print(f"  iNat 429; waiting {PATIENT_WAIT} s (try {attempt + 1})", file=sys.stderr)
            time.sleep(PATIENT_WAIT)
    raise RuntimeError("unreachable")


def place_counts(client: ApiClient, place_id: int) -> list[dict]:
    out, page = [], 1
    while True:
        d = patient_get(client, "/observations/species_counts", {
            "place_id": place_id, "taxon_id": config.INAT_HEXAPODA, "quality_grade": "research",
            "captive": "false", "per_page": PAGE, "page": page})
        out += d.get("results", [])
        if len(out) >= d.get("total_results", 0) or not d.get("results"):
            return out
        page += 1


def sweep(conn, client: ApiClient, refresh_days: int = 7) -> dict[str, int]:
    """Replace each area's rows; an area answered within `refresh_days` is skipped, so an
    interrupted run resumes where it stopped."""
    done = {}
    for area in config.AREAS:
        fresh = conn.execute("SELECT COUNT(*) FROM inat_place_counts WHERE place_id = ? AND "
                             "fetched_at > datetime('now', ?)",
                             (area["inat"], f"-{refresh_days} days")).fetchone()[0]
        if fresh:
            done[area["code"]] = fresh
            continue
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


def link_names(conn, reg=None) -> dict[str, int]:
    """Give each iNat name a name- key and write source='inat' presence under it; `guaminsects
    match` then puts the names on the Catalogue of Life (iNat's taxonomy is close to COL's).

    A taxon GBIF already has records for still gets an 'inat' row: the two counts are shown
    side by side, never summed (they overlap, since research-grade iNat flows into GBIF).
    """
    from ..names import Registry

    reg = reg or Registry()
    names = conn.execute(
        "SELECT name, rank, area, SUM(observations) n FROM inat_place_counts "
        "WHERE rank IN ('species', 'subspecies', 'genus') GROUP BY name, rank, area").fetchall()
    rows = [(reg.key_for(r["name"], GBIF_RANKS[r["rank"]], "inat"), r["area"], r["n"])
            for r in names]
    reg.save()
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM taxon_presence WHERE source = 'inat'")
        conn.executemany(
            "INSERT INTO taxon_presence (taxon_id, area, source, records, fetched_at) "
            "VALUES (?, ?, 'inat', ?, ?) ON CONFLICT (taxon_id, area, source) "
            "DO UPDATE SET records = records + excluded.records",
            [(k, a, n, stamp) for k, a, n in rows])
    return {"names": len({k for k, _, _ in rows}), "rows": len(rows)}
