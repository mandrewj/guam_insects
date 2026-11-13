"""Cross-links from Wikidata (CC0), keyed on the GBIF taxon ID (P846).

One SPARQL query per batch of GBIF keys returns the QID, taxon name (P225), iNaturalist
taxon ID (P3151), BugGuide ID (P2464, used to find entobase's page), IUCN status (P141),
an image (P18, a Commons file), and the English Wikipedia article and English common name.
Batches of 300 keys stay well inside the public endpoint's 60 s limit. One query at a time.

A Wikidata item matches a taxon only when its P225 agrees with our name (a stale P846 can
point a homonym at the wrong item): disagreements are stored with confidence 'review'.
"""

import json
import sys
import time

import httpx

from .. import config, db

SPARQL_URL = "https://query.wikidata.org/sparql"
BATCH = 300
QUERY = """
SELECT ?gbif ?item ?name ?inat ?bg ?iucn ?image ?article ?common WHERE {
  VALUES ?gbif { %s }
  ?item wdt:P846 ?gbif .
  OPTIONAL { ?item wdt:P225 ?name }
  OPTIONAL { ?item wdt:P3151 ?inat }
  OPTIONAL { ?item wdt:P2464 ?bg }
  OPTIONAL { ?item wdt:P141 ?iucnItem . ?iucnItem rdfs:label ?iucn FILTER(lang(?iucn) = "en") }
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?item wdt:P1843 ?common FILTER(lang(?common) = "en") }
}
"""


def run_query(http: httpx.Client, keys: list[int]) -> list[dict]:
    q = QUERY % " ".join(f'"{k}"' for k in keys)
    for attempt in range(4):
        r = http.post(SPARQL_URL, data={"query": q},
                      headers={"Accept": "application/sparql-results+json"})
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, float(r.headers.get("Retry-After", 10 * (attempt + 1)))))
            continue
        r.raise_for_status()
        return r.json()["results"]["bindings"]
    r.raise_for_status()
    return []


def sweep(conn, refresh: bool = False) -> dict[str, int]:
    taxa = {r["gbif_key"]: r["name"] for r in conn.execute(
        "SELECT gbif_key, name FROM taxa WHERE gbif_key IS NOT NULL")}
    done = set() if refresh else {r[0] for r in conn.execute("SELECT gbif_key FROM wikidata_taxa")}
    todo = sorted(set(taxa) - done)
    stats = {"asked": len(todo), "items": 0, "articles": 0, "inat": 0, "review": 0}
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120) as http:
        for i in range(0, len(todo), BATCH):
            keys = todo[i:i + BATCH]
            rows: dict[int, dict] = {}
            for b in run_query(http, keys):
                k = int(b["gbif"]["value"])
                v = {f: b[f]["value"] for f in b}
                cur = rows.setdefault(k, {"commons": set(), **v})
                if "common" in v:
                    cur["commons"].add(v["common"])
            stamp = db.now()
            with conn:
                for k in keys:            # a key with no item is an answer too: not asked again
                    v = rows.get(k)
                    if v is None:
                        conn.execute("INSERT OR REPLACE INTO wikidata_taxa (gbif_key, fetched_at) "
                                     "VALUES (?, ?)", (k, stamp))
                        continue
                    agrees = (v.get("name") or "") == taxa[k]
                    stats["items"] += 1
                    stats["articles"] += "article" in v
                    stats["inat"] += "inat" in v
                    stats["review"] += not agrees
                    conn.execute(
                        "INSERT OR REPLACE INTO wikidata_taxa (gbif_key, qid, name, inat_id, "
                        "bugguide_id, iucn, image, article, commons, confidence, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (k, v["item"].rsplit("/", 1)[-1], v.get("name"), v.get("inat"),
                         v.get("bg"), v.get("iucn"), v.get("image"), v.get("article"),
                         json.dumps(sorted(v["commons"])) if v["commons"] else None,
                         "high" if agrees else "review", stamp))
            print(f"  Wikidata: {min(i + BATCH, len(todo))}/{len(todo)}", file=sys.stderr)
            time.sleep(2)
    return stats
