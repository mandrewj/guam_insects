"""Literature checklists that Plazi digitised and GBIF serves as CHECKLIST datasets.

The 1940s *Insects of Guam* I and II (Bishop Museum Bulletins 172, 189) came out as one
paper per group ("Sphingidae Of Guam", "Coleoptera Heteromera From Guam" ...), and Plazi
published each as a GBIF checklist (CC0) whose name usages carry a backbone key (`nubKey`).
That gives historical presence on an island with a citation, for about one request per
dataset. Treatments with material citations are also GBIF occurrences (MATERIAL_CITATION),
which the occurrence sweep already counts; this adds the names that have none.

Area comes from the title: a dataset about Guam supports presence on Guam. A title that
names only "Micronesia" or "the Mariana Islands" supports no single area, so its names are
kept (they are literature for the taxon page) without a presence row.
"""

import re
import sys

from .. import db
from .http import ApiClient

PLAZI_ORG = "7ce8aef0-9e92-11dc-8738-b8a03c50a862"
QUERIES = ["Guam", "Micronesia", "Mariana", "Marianas", "Palau", "Caroline", "Marshall",
           "Saipan", "Pohnpei", "Ponape", "Yap", "Truk", "Chuuk", "Kosrae", "Rota", "Tinian"]
AREA_PATTERNS = [
    ("GU", r"\bGuam\b"),
    ("PW", r"\b(Palau|Belau)\b"),
    ("MH", r"\bMarshall"),
    ("MP", r"\b(Northern Mariana|Saipan|Tinian|Rota|Pagan|Agrihan|Anatahan)\b"),
    ("FM", r"\b(Caroline|Yap|Truk|Chuuk|Ponape|Pohnpei|Kosrae|Kusaie)\b"),
]
HEXAPOD_CLASSES = {"Insecta", "Collembola", "Protura", "Diplura"}
NAME_RANKS = {"SPECIES", "SUBSPECIES", "VARIETY", "GENUS"}


def areas_of(title: str) -> list[str]:
    return [code for code, pat in AREA_PATTERNS if re.search(pat, title, re.I)]


def discover(client: ApiClient) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for q in QUERIES:
        offset = 0
        while True:
            d = client.get_cached("/dataset/search", {"q": q, "type": "CHECKLIST",
                                                      "publishingOrg": PLAZI_ORG,
                                                      "limit": 200, "offset": offset})
            for r in d["results"]:
                found.setdefault(r["key"], {"key": r["key"], "title": r["title"]})
            offset += 200
            if d.get("endOfRecords", True) or offset >= d.get("count", 0):
                break
    return found


def usages(client: ApiClient, dataset_key: str) -> list[dict]:
    out, offset = [], 0
    while True:
        d = client.get_cached("/species/search", {"datasetKey": dataset_key, "limit": 1000,
                                                  "offset": offset})
        out += d["results"]
        offset += 1000
        if d.get("endOfRecords", True) or offset >= d.get("count", 0):
            return out


def sweep(conn, client: ApiClient) -> dict[str, int]:
    datasets = discover(client)
    stats = {"datasets": 0, "names": 0, "presence": 0}
    rows, presence = [], {}
    sources = []
    for ds in datasets.values():
        names = [u for u in usages(client, ds["key"])
                 if u.get("class") in HEXAPOD_CLASSES and u.get("rank") in NAME_RANKS
                 and u.get("nubKey")]
        if not names:
            continue                      # crabs, fish, diatoms ...
        meta = client.get_cached(f"/dataset/{ds['key']}")
        citation = (meta.get("citation") or {}).get("text") or ds["title"]
        areas = areas_of(ds["title"])
        sources.append((ds["key"], ds["title"], citation, ",".join(areas) or None,
                        meta.get("license"), meta.get("doi")))
        stats["datasets"] += 1
        for u in names:
            rows.append((ds["key"], u["key"], u["nubKey"], u.get("scientificName"), u["rank"]))
            for a in areas:
                presence[(u["nubKey"], a)] = presence.get((u["nubKey"], a), 0) + 1
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM checklist_sources WHERE source = 'plazi'")
        conn.execute("DELETE FROM checklist_names WHERE source = 'plazi'")
        conn.execute("DELETE FROM taxon_presence WHERE source = 'literature' "
                     "AND citation = 'plazi'")
        conn.executemany(
            "INSERT INTO checklist_sources (dataset_key, source, title, citation, areas, "
            "license, doi, fetched_at) VALUES (?, 'plazi', ?, ?, ?, ?, ?, ?)",
            [(*s, stamp) for s in sources])
        conn.executemany(
            "INSERT OR IGNORE INTO checklist_names (dataset_key, source, usage_key, nub_key, "
            "name, rank) VALUES (?, 'plazi', ?, ?, ?, ?)", rows)
        # records = how many digitised papers list the taxon for the area
        conn.executemany(
            "INSERT INTO taxon_presence (taxon_id, area, source, records, citation, fetched_at) "
            "VALUES (?, ?, 'literature', ?, 'plazi', ?) ON CONFLICT (taxon_id, area, source) "
            "DO UPDATE SET records = excluded.records",
            [(k, a, n, stamp) for (k, a), n in presence.items()])
    stats["names"] = len(rows)
    stats["presence"] = len(presence)
    print(f"Plazi: {stats['datasets']} hexapod checklists of {len(datasets)} found, "
          f"{stats['names']} names, {stats['presence']} taxon-area rows", file=sys.stderr)
    return stats


def unknown_keys(conn) -> set[int]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT n.nub_key FROM checklist_names n LEFT JOIN gbif_taxa g "
        "ON g.gbif_key = n.nub_key WHERE g.gbif_key IS NULL")}
