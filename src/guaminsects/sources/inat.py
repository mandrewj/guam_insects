"""iNaturalist species counts per area: what iNat has that GBIF lacks, plus observation counts.

One stream, about one request a second (docs/LESSONS.md: iNat 429s come from concurrent
streams, and the user's entobase jobs share this IP). Research grade, wild only.
"""

import sys
import time

import httpx

from .. import config

INAT = "https://api.inaturalist.org/v1"
PAGE = 200
# A species_counts page is an expensive query for iNat, and its throttle is per minute and
# shared with whatever else runs on this IP: after the client's own retries, wait minutes,
# not seconds, and keep going for hours rather than fail the night's run.
PATIENT_WAIT = 300
PATIENT_TRIES = 24
RANKS = {"species": "Species", "subspecies": "Subspecies", "genus": "Genus"}


def patient_get(client, path: str, params: dict, wait: int = PATIENT_WAIT) -> dict:
    for attempt in range(PATIENT_TRIES):
        try:
            return client.get(path, params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or attempt == PATIENT_TRIES - 1:
                raise
            print(f"  iNat 429; waiting {wait} s (try {attempt + 1})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def place_counts(client, place_id: int) -> list[dict]:
    """[{id, name, rank, common, count}] for one place, research grade, wild."""
    out, page = [], 1
    while True:
        d = patient_get(client, "/observations/species_counts", {
            "place_id": place_id, "taxon_id": config.INAT_HEXAPODA, "quality_grade": "research",
            "captive": "false", "per_page": PAGE, "page": page})
        out += [{"id": r["taxon"]["id"], "name": r["taxon"]["name"], "rank": r["taxon"]["rank"],
                 "common": r["taxon"].get("preferred_common_name"), "count": r["count"]}
                for r in d.get("results", [])]
        if len(out) >= d.get("total_results", 0) or not d.get("results"):
            return out
        page += 1


def taxa_by_ids(client, inat_ids: list[int]) -> dict[int, dict]:
    """iNaturalist taxa by id, 30 a request: {id: {name, rank, common, active}}."""
    out: dict[int, dict] = {}
    for i in range(0, len(inat_ids), 30):
        d = patient_get(client, "/taxa/" + ",".join(map(str, inat_ids[i:i + 30])), {})
        for t in d.get("results", []):
            out[t["id"]] = {"name": t.get("name"), "rank": t.get("rank"),
                            "common": t.get("preferred_common_name"),
                            "active": t.get("is_active", True)}
    return out


def search(client, name: str, rank: str) -> dict | None:
    """The active iNaturalist taxon with exactly this name and rank, or None."""
    d = patient_get(client, "/taxa", {"q": name, "rank": rank.lower(), "is_active": "true",
                                      "per_page": 10})
    for t in d.get("results", []):
        if (t.get("name") or "").lower() == name.lower() and (t.get("rank") or "") == rank.lower():
            return {"id": t["id"], "name": t["name"], "rank": t["rank"],
                    "common": t.get("preferred_common_name")}
    return None
