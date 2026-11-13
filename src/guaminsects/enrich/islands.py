"""Island-level presence from GBIF: facet by GADM level-1 unit, never by taxon.

For each area, one request lists its level-1 units with records (gadmLevel1Gid facet), one
request per unit gives its name, and one facet request per (unit, rank) lists the taxon keys
recorded there: about 150 requests for all of Micronesia (docs/LESSONS.md "presence by
area"). Guam is one island and needs no split.

Level-1 units are municipalities (CNMI: Saipan, Tinian, Rota, Northern Islands), states
(Palau, FSM) or atolls (Marshalls). Palau's ten states on Babeldaob are reported as
Babeldaob; the FSM states keep their names (Yap, Chuuk, Pohnpei, Kosrae), which include
their outer islands.
"""

import sys

from .. import config, db
from .gbif_checklist import FACETS, FACET_PAGE, occurrence_filter
from .http import ApiClient

BABELDAOB = {"Aimeliik", "Airai", "Melekeok", "Ngaraard", "Ngarchelong", "Ngardmau",
             "Ngaremlengui", "Ngatpang", "Ngchesar", "Ngiwal"}
RENAME = {"Hatohobei": "Tobi", "Northern Islands": "Northern Islands (CNMI)"}


def island_name(area: str, gadm_name: str) -> str:
    if area == "PW" and gadm_name in BABELDAOB:
        return "Babeldaob"
    return RENAME.get(gadm_name, gadm_name)


def units(client: ApiClient, country: str) -> dict[str, int]:
    d = client.get("/occurrence/search", occurrence_filter(country) + [
        ("limit", 0), ("facet", "gadmLevel1Gid"), ("facetLimit", 200)])
    return {c["name"]: c["count"] for c in (d.get("facets") or [{}])[0].get("counts", [])}


def unit_name(client: ApiClient, country: str, gid: str) -> str | None:
    d = client.get_cached("/occurrence/search", occurrence_filter(country) + [
        ("gadmLevel1Gid", gid), ("limit", 1)])
    res = d.get("results") or [{}]
    return ((res[0].get("gadm") or {}).get("level1") or {}).get("name")


def sweep(conn, client: ApiClient) -> dict[str, int]:
    stats = {"units": 0, "rows": 0}
    for area in config.AREAS:
        if area["code"] == "GU":
            continue
        counts: dict[tuple[int, str], int] = {}
        for gid in units(client, area["gbif"]):
            name = unit_name(client, area["gbif"], gid)
            if not name:
                continue
            isl = island_name(area["code"], name)
            stats["units"] += 1
            for facet in FACETS:
                offset = 0
                while True:
                    d = client.get("/occurrence/search", occurrence_filter(area["gbif"]) + [
                        ("gadmLevel1Gid", gid), ("limit", 0), ("facet", facet),
                        ("facetLimit", FACET_PAGE), ("facetOffset", offset)])
                    got = (d.get("facets") or [{}])[0].get("counts", [])
                    for c in got:
                        k = (int(c["name"]), isl)
                        counts[k] = counts.get(k, 0) + int(c["count"])
                    if len(got) < FACET_PAGE:
                        break
                    offset += FACET_PAGE
        stamp = db.now()
        with conn:
            conn.execute("DELETE FROM taxon_islands WHERE area = ? AND source = 'gbif'",
                         (area["code"],))
            conn.executemany(
                "INSERT INTO taxon_islands (taxon_id, area, island, source, records, fetched_at) "
                "VALUES (?, ?, ?, 'gbif', ?, ?)",
                [(k, area["code"], isl, n, stamp) for (k, isl), n in counts.items()])
        stats["rows"] += len(counts)
        print(f"  islands {area['code']}: {len({i for _, i in counts})} islands, "
              f"{len(counts)} rows", file=sys.stderr)
    return stats
