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


def taxa_by_ids(client, inat_ids: list[int], progress=None) -> dict[int, dict]:
    """iNaturalist taxa by id, 30 a request: {id: {name, rank, common, active}}."""
    out: dict[int, dict] = {}
    for i in range(0, len(inat_ids), 30):
        if progress and i and i % 300 == 0:
            progress(f"  iNaturalist taxa: {i}/{len(inat_ids)}")
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


# --- iNaturalist's published taxonomy (a Darwin Core Archive), for linking without searching -------

TAXONOMY_URL = "https://www.inaturalist.org/taxa/inaturalist-taxonomy.dwca.zip"
TAXONOMY_ZIP = config.PRIVATE_DIR / "inat-taxonomy" / "dwca.zip"


def download_taxonomy(path=TAXONOMY_ZIP) -> None:
    """One 80 MB download of the whole taxonomy (iNaturalist publishes it for this)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", TAXONOMY_URL, headers={"User-Agent": config.USER_AGENT},
                      follow_redirects=True, timeout=600) as r:
        r.raise_for_status()
        tmp = path.with_suffix(".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.rename(path)


class Taxonomy:
    """iNaturalist's taxonomy as published: name -> id for arthropods, id -> name, and the
    English names of the ids asked for (`load_commons`)."""

    def __init__(self, index: dict, names: dict[int, str]):
        self.index, self.names = index, names
        self.commons: dict[int, list[str]] = {}

    def load_commons(self, wanted: set[int], path=TAXONOMY_ZIP) -> None:
        import csv
        import io
        import zipfile

        with zipfile.ZipFile(path) as z, z.open("VernacularNames-english.csv") as raw:
            for r in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                if r["id"].isdigit() and int(r["id"]) in wanted and r["vernacularName"].strip():
                    names = self.commons.setdefault(int(r["id"]), [])
                    if r["vernacularName"].strip() not in names:
                        names.append(r["vernacularName"].strip())


def read_taxonomy(path=TAXONOMY_ZIP, phylum: str = "Arthropoda") -> Taxonomy:
    """Every arthropod taxon in the archive: {(scientific name, rank): iNaturalist id}, where a
    name and rank two taxa share (a homonym within the phylum) maps to None, and {id: name}."""
    import csv
    import io
    import zipfile

    index: dict[tuple[str, str], int | None] = {}
    names: dict[int, str] = {}
    with zipfile.ZipFile(path) as z, z.open("taxa.csv") as raw:
        for r in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
            if r["phylum"] != phylum:
                continue
            key = (r["scientificName"], r["taxonRank"])
            index[key] = int(r["id"]) if key not in index else None
            names[int(r["id"])] = r["scientificName"]
    return Taxonomy(index, names)


def taxonomy_index(path=TAXONOMY_ZIP, phylum: str = "Arthropoda") -> dict[tuple[str, str], int | None]:
    return read_taxonomy(path, phylum).index
