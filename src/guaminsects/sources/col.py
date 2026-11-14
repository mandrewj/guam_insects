"""The Catalogue of Life (COL eXtended Release, as GBIF delivers it): match a name, read a
taxon by key, and turn an answer into taxa rows.

`match` puts a name on COL (GBIF's v2 match endpoint):

    EXACT       the same name (an accepted COL taxon, or a COL synonym of one)
    VARIANT     a spelling or gender-ending variant COL recognizes
    FUZZY       a near spelling; accepted only within the same genus (match.py)
    HIGHERRANK  COL does not have the name; the result is the nearest taxon above it
    NONE        nothing (or several equal homonyms: retried with the classification)

Names are matched with the source's order as a hint (the matcher sends some common genera up
to Animalia without one).
"""

from .. import ids
from .gbif import COL_CHECKLIST, COL_HEXAPODA

MATCH = "/v2/species/match"
MAIN_RANKS = {"SUBPHYLUM": "Subphylum", "CLASS": "Class", "ORDER": "Order", "FAMILY": "Family",
              "GENUS": "Genus", "SPECIES": "Species", "SUBSPECIES": "Subspecies",
              "VARIETY": "Variety"}
EXTRA_RANKS = {"SUPERFAMILY": "superfamily", "SUBFAMILY": "subfamily", "TRIBE": "tribe"}
ABOVE_HEXAPODA = {"DOMAIN", "KINGDOM", "PHYLUM", "SUPERKINGDOM", "REALM"}
CLB = "https://api.checklistbank.org"
CLB_DATASET = 316691            # the COL XR GBIF serves (ChecklistBank 3LXR)


def match(client, name: str, rank: str | None = None, authorship: str | None = None,
          hints: dict | None = None, force_hints: bool = False) -> dict:
    """The v2 match answer for one name (cached). `hints` (order, family, ...) are used only
    when the plain match finds several equal homonyms, or with `force_hints`."""
    params = {"checklistKey": COL_CHECKLIST, "scientificName": name}
    if rank:
        params["taxonRank"] = rank.upper()
    if authorship:
        params["authorship"] = authorship
    if force_hints and hints:
        return client.get_cached(MATCH, params | {k: v for k, v in hints.items() if v})
    d = client.get_cached(MATCH, params)
    diag = d.get("diagnostics") or {}
    if diag.get("matchType") == "NONE" and hints and "Multiple" in (diag.get("note") or ""):
        d = client.get_cached(MATCH, params | {k: v for k, v in hints.items() if v})
    return d


def by_key(client, col_id: str) -> dict:
    """One COL taxon and its whole classification (a usageKey match)."""
    return client.get_cached(MATCH, {"checklistKey": COL_CHECKLIST, "usageKey": col_id})


def match_type(d: dict) -> str:
    return (d.get("diagnostics") or {}).get("matchType") or "NONE"


def is_hexapod(d: dict) -> bool:
    keys = {c["key"] for c in d.get("classification") or []}
    return COL_HEXAPODA in keys or (d.get("usage") or {}).get("key") == COL_HEXAPODA


def usage_row(u: dict) -> dict:
    """A taxa.csv-shaped dict for one COL usage (no parent yet)."""
    return {"id": u["key"], "rank": MAIN_RANKS.get((u.get("rank") or "").upper(), ""),
            "name": u.get("canonicalName") or u.get("name") or "",
            "authorship": (u.get("authorship") or "").strip(),
            "status": (u.get("status") or "ACCEPTED").lower()}


def chain(d: dict, target: dict) -> list[dict]:
    """The accepted ancestors of `target` to show, top first, each as a usage_row with its
    parent set and the intermediate ranks (superfamily, subfamily, tribe) collected on the
    rows below them. Only main ranks become rows."""
    rows, extra, parent = [], {}, None
    for c in d.get("classification") or []:
        r = (c.get("rank") or "").upper()
        if r in ABOVE_HEXAPODA or c["key"] == target.get("key"):
            continue
        if r in EXTRA_RANKS:
            extra[EXTRA_RANKS[r]] = c.get("name") or c.get("canonicalName") or ""
            continue
        if r not in MAIN_RANKS:
            continue
        row = usage_row(c) | {"parent_id": parent["id"] if parent else "",
                              **{k: v for k, v in extra.items()}}
        rows.append(row)
        parent = row
    return rows


def classification_extras(d: dict) -> dict:
    """superfamily / subfamily / tribe of the matched taxon, from its classification."""
    return {EXTRA_RANKS[(c.get("rank") or "").upper()]: c.get("name") or c.get("canonicalName") or ""
            for c in d.get("classification") or [] if (c.get("rank") or "").upper() in EXTRA_RANKS}


def info(client, col_id: str) -> dict:
    """English names and synonyms from ChecklistBank (COL's API)."""
    d = client.get_cached(f"/dataset/{CLB_DATASET}/taxon/{col_id}/info")
    english = sorted({v["name"] for v in d.get("vernacularNames") or []
                      if v.get("language") == "eng" and v.get("name")})
    syn = d.get("synonyms") or {}
    names = sorted({s["name"]["scientificName"] for group in ("homotypic", "heterotypic")
                    for s in syn.get(group) or [] if (s.get("name") or {}).get("scientificName")})
    return {"english": english, "synonyms": names}


def ext(col_key: str) -> str:
    return col_key if ids.valid(col_key) else ""
