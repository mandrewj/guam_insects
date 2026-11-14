"""Cross-links from Wikidata (CC0), keyed on the Catalogue of Life ID (P10585), or for a taxon
COL lacks on the GBIF taxon ID (P846).

One SPARQL query per batch of ids returns the QID, taxon name (P225), iNaturalist taxon ID
(P3151), BugGuide ID (P2464), IUCN status (P141), an image (P18, a Commons file), the English
Wikipedia article and Wikispecies page (sitelinks) and English common names. Batches of 300
keep well inside the public endpoint's 60 s limit; one query at a time.

A Wikidata item matches a taxon only when its P225 agrees with our name (a stale P846 can
point a homonym at the wrong item): disagreements are stored with confidence `review`.
Writes links.csv (wikidata, wikispecies, wikipedia, commons, inaturalist, bugguide), taxa.iucn
and taxa.other_common_names.
"""

import sys
import time
import urllib.parse

from .. import config, ids
from ..dataset import join, split

SPARQL_URL = "https://query.wikidata.org/sparql"
BATCH = 300
QUERY = """
SELECT ?id ?item ?name ?inat ?bg ?iucn ?image ?article ?species ?common WHERE {
  VALUES ?id { %s }
  ?item wdt:%s ?id .
  OPTIONAL { ?item wdt:P225 ?name }
  OPTIONAL { ?item wdt:P3151 ?inat }
  OPTIONAL { ?item wdt:P2464 ?bg }
  OPTIONAL { ?item wdt:P141 ?iucnItem . ?iucnItem rdfs:label ?iucn FILTER(lang(?iucn) = "en") }
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?species schema:about ?item ; schema:isPartOf <https://species.wikimedia.org/> }
  OPTIONAL { ?item wdt:P1843 ?common FILTER(lang(?common) = "en") }
}
"""
OWN_SYSTEMS = ("wikidata", "wikispecies", "wikipedia", "commons")


def run_query(http, values: list[str], prop: str = "P10585") -> list[dict]:
    q = QUERY % (" ".join(f'"{v}"' for v in values), prop)
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


def wanted(ds, taxa: list[str]) -> dict[str, tuple[str, str, str]]:
    """taxon id -> (property, value, our name)."""
    want = {}
    by_id = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    for t in taxa:
        r = by_id.get(t)
        if not r:
            continue
        if r["in_col"] == "yes" and ids.valid(t) and ids.kind(ids.to_int(t)) == "col":
            want[t] = ("P10585", t, r["name"])
        elif r["gbif_key"]:
            want[t] = ("P846", r["gbif_key"], r["name"])
    return want


def apply(ds, found: dict[str, dict], want: dict, today: str) -> dict[str, int]:
    """Write what Wikidata said about each taxon (found: id -> merged binding) into the
    dataset; a link row the editors or entobase made is never touched."""
    stats = {"items": 0, "articles": 0, "inat": 0, "review": 0, "iucn": 0}
    taxa = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    mine = set(found)
    ds["links"] = [r for r in ds["links"] if not (
        r["taxon_id"] in mine and (r["system"] in OWN_SYSTEMS or
                                   (r["system"] == "inaturalist" and "via Wikidata" in r["note"])))]
    for t, v in found.items():
        agrees = (v.get("name") or "") == want[t][2]
        conf = "high" if agrees else "review"
        note = "" if agrees else f"Wikidata names it {v.get('name')}"
        stats["items"] += 1
        stats["review"] += not agrees

        def link(system, value, label="", confidence=conf, n="", t=t):
            ds["links"].append({"taxon_id": t, "system": system, "value": value, "label": label,
                                "confidence": confidence, "note": n, "added_by": "refresh wikidata",
                                "added": today})

        link("wikidata", v["item"].rsplit("/", 1)[-1], n=note)
        if v.get("species"):
            link("wikispecies", v["species"])
        if v.get("article"):
            link("wikipedia", v["article"])
            stats["articles"] += 1
        if v.get("image"):
            link("commons", urllib.parse.unquote(v["image"].rsplit("/", 1)[-1]))
        if v.get("inat") and str(v["inat"]).isdigit():
            link("inaturalist", str(v["inat"]), n="via Wikidata")
            stats["inat"] += 1
        if v.get("bg") and str(v["bg"]).isdigit() and conf == "high" and not any(
                r["taxon_id"] == t and r["system"] == "bugguide" for r in ds["links"]):
            link("bugguide", str(v["bg"]), confidence="high")
        row = taxa[t]
        if conf == "high":
            if v.get("iucn"):
                row["iucn"] = v["iucn"]
                stats["iucn"] += 1
            if v["commons"]:
                names = set(split(row["other_common_names"])) | v["commons"]
                names.discard(row["common_name"])
                row["other_common_names"] = join(sorted(names))
    return stats


def refresh(ds, taxa: list[str], http, today: str, progress=print) -> dict[str, int]:
    want = wanted(ds, taxa)
    found: dict[str, dict] = {}
    for prop in ("P10585", "P846"):
        todo = [t for t in want if want[t][0] == prop]
        for i in range(0, len(todo), BATCH):
            keys = todo[i:i + BATCH]
            by_value = {want[t][1]: t for t in keys}
            for b in run_query(http, list(by_value), prop):
                t = by_value.get(b["id"]["value"])
                if t is None:
                    continue
                v = {f: b[f]["value"] for f in b}
                cur = found.setdefault(t, {"commons": set(), **v})
                if "common" in v:
                    cur["commons"].add(v["common"])
            progress(f"  Wikidata {prop}: {min(i + BATCH, len(todo))}/{len(todo)}")
            time.sleep(2)
    stats = apply(ds, found, want, today)
    stats["asked"] = len(want)
    return stats


def client():
    import httpx

    return httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120)


_ = sys
