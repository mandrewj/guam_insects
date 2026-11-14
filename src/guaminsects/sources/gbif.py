"""GBIF: occurrence facets (counts per taxon in the five areas), years, GADM level-1 islands,
species names and images. Every call is one polite request; nothing is asked per taxon when
a facet can answer for all of them (docs/LESSONS.md "presence by area")."""

import re

from .. import config, ids

GBIF = "https://api.gbif.org/v1"
COL_CHECKLIST = "7ddf754f-d193-4cc9-b351-99906754a03b"   # Catalogue of Life eXtended Release
COL_HEXAPODA = "L2655"
FACETS = ("speciesKey", "genusKey", "familyKey", "orderKey")
COL_FACETS = FACETS + ("classKey",)
FACET_PAGE = 1000
# Everything but fossils and living collections (zoos, insectaries, quarantine colonies).
BASIS = ("PRESERVED_SPECIMEN", "HUMAN_OBSERVATION", "MACHINE_OBSERVATION", "OBSERVATION",
         "MATERIAL_SAMPLE", "MATERIAL_CITATION", "OCCURRENCE")
SPECIMEN_BASIS = ("PRESERVED_SPECIMEN", "MATERIAL_SAMPLE")
BABELDAOB = {"Aimeliik", "Airai", "Melekeok", "Ngaraard", "Ngarchelong", "Ngardmau",
             "Ngaremlengui", "Ngatpang", "Ngchesar", "Ngiwal"}
RENAME = {"Hatohobei": "Tobi", "Northern Islands": "Northern Islands (CNMI)"}
OCC = "/occurrence/search"


def occurrence_filter(country: str, basis: tuple[str, ...] = BASIS,
                      col: bool = True) -> list[tuple[str, str | int]]:
    """Shared filters; a list because GBIF ORs repeated parameters (taxonKey, basisOfRecord).
    `col`: keys and facets in the Catalogue of Life (else the GBIF Backbone)."""
    params: list[tuple[str, str | int]] = [("country", country), ("hasGeospatialIssue", "false"),
                                           ("occurrenceStatus", "PRESENT")]
    if col:
        params += [("checklistKey", COL_CHECKLIST), ("taxonKey", COL_HEXAPODA)]
    else:
        params += [("taxonKey", k) for k in config.HEXAPOD_CLASSES]
    return params + [("basisOfRecord", b) for b in basis]


def facet_counts(client, country: str, facet: str, basis: tuple[str, ...] = BASIS,
                 col: bool = True) -> dict[str, int]:
    """{key as GBIF names it (a COL id, or a Backbone key): records} for one facet, paged."""
    out: dict[str, int] = {}
    offset = 0
    while True:
        params = occurrence_filter(country, basis, col) + [
            ("limit", 0), ("facet", facet), ("facetLimit", FACET_PAGE), ("facetOffset", offset)]
        data = client.get(OCC, params)
        counts = (data.get("facets") or [{}])[0].get("counts", [])
        out.update((c["name"], int(c["count"])) for c in counts)
        if len(counts) < FACET_PAGE:
            return out
        offset += FACET_PAGE


def area_counts(client, country: str, basis: tuple[str, ...] = BASIS,
                col: bool = True) -> dict[str, int]:
    """Every taxon key with records in a country, across the rank facets."""
    out: dict[str, int] = {}
    for facet in (COL_FACETS if col else FACETS):
        out.update(facet_counts(client, country, facet, basis, col))     # a key has one rank
    return out


def species(client, key: int | str) -> dict:
    """One Backbone taxon: name, rank, status, parent and classification keys."""
    return client.get_cached(f"/species/{key}")


def backbone_match(client, name: str, rank: str | None = None) -> dict | None:
    """GBIF name match with entobase's accept rules: EXACT, or FUZZY when the canonical name
    agrees after normalising case and spaces; never HIGHERRANK (a genus for a species)."""
    params = {"name": name, "kingdom": "Animalia"}
    if rank:
        params["rank"] = rank.upper()
    d = client.get_cached("/species/match", params)
    norm = lambda s: " ".join((s or "").lower().split())      # noqa: E731
    if d.get("matchType") == "EXACT" or (d.get("matchType") == "FUZZY" and
                                         norm(d.get("canonicalName")) == norm(name)):
        if d.get("classKey") in config.HEXAPOD_CLASSES:
            return d
    return None


def island_name(area: str, gadm_name: str) -> str:
    if area == "PW" and gadm_name in BABELDAOB:
        return "Babeldaob"
    return RENAME.get(gadm_name, gadm_name)


def taxon_years(client, col_id: str, country: str) -> tuple[int | None, int | None]:
    """First and last year of a COL taxon's records in a country (one year facet)."""
    d = client.get(OCC, [("country", country), ("checklistKey", COL_CHECKLIST),
                         ("taxonKey", col_id), ("hasGeospatialIssue", "false"),
                         ("occurrenceStatus", "PRESENT"), ("limit", 0), ("facet", "year"),
                         ("facetLimit", 400)] + [("basisOfRecord", b) for b in BASIS])
    years = [int(c["name"]) for c in (d.get("facets") or [{}])[0].get("counts", [])
             if str(c["name"]).isdigit()]
    return (min(years), max(years)) if years else (None, None)


def taxon_islands(client, col_id: str, area: dict) -> dict[str, int]:
    """{island: records} for a COL taxon in one area, by GADM level-1 unit (Guam is one
    island and needs no split)."""
    d = client.get(OCC, [("country", area["gbif"]), ("checklistKey", COL_CHECKLIST),
                         ("taxonKey", col_id), ("hasGeospatialIssue", "false"),
                         ("occurrenceStatus", "PRESENT"), ("limit", 0),
                         ("facet", "gadmLevel1Gid"), ("facetLimit", 200)] +
                   [("basisOfRecord", b) for b in BASIS])
    out: dict[str, int] = {}
    for c in (d.get("facets") or [{}])[0].get("counts", []):
        one = client.get_cached(OCC, [("country", area["gbif"]), ("gadmLevel1Gid", c["name"]),
                                      ("limit", 1)])
        name = (((one.get("results") or [{}])[0].get("gadm") or {}).get("level1") or {}).get("name")
        if name:
            isl = island_name(area["code"], name)
            out[isl] = out.get(isl, 0) + int(c["count"])
    return out


def col_key_kind(key: str) -> str:
    """'col' for a Catalogue of Life id, else 'other' (the extended release also holds BOLD
    BINs such as 'BOLD.ADL3763')."""
    return "col" if re.fullmatch(r"[0-9A-Z]{1,7}", key or "") and ids.valid(key) else "other"
