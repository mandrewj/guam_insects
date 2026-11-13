"""The Catalogue of Life (COL eXtended Release, as GBIF serves it): names and classification.

The tree is COL. `fetch_taxa` reads each COL key the occurrence sweeps found (and each a
name match points at) from GBIF's v2 match endpoint by usageKey: one request gives the
taxon and its whole classification, so ancestors come free. Answers are cached under
data/raw/ like every other API.

`match` puts a name a source used (a GBIF Backbone name, iNaturalist, Plazi, a PDF) on COL:

    EXACT       the same name (an accepted COL taxon, or a COL synonym of one)
    VARIANT     a spelling or gender-ending variant COL recognizes ("adpressiformis")
    FUZZY       a near spelling; accepted only within the same genus (names.py)
    HIGHERRANK  COL does not have the name; the result is the nearest taxon above it
    NONE        nothing (or several equal homonyms: retried with the classification)

Names are matched without classification hints first: an outdated family in a source
(Callirhipis in "Rhipiceridae") would otherwise pull the match up to that family.
"""

import json
import sys

from .. import db, ids
from .gbif_checklist import COL_CHECKLIST, COL_HEXAPODA as HEXAPODA  # noqa: F401 (names.py)
from .http import ApiClient

GBIF_ROOT = "https://api.gbif.org"
MATCH = "/v2/species/match"
# COL ranks the site shows; the rest (suborder, superfamily, subfamily, tribe, subgenus, ...)
# are kept in col_taxa and in taxonomy.csv's columns but skipped in the displayed tree.
MAIN_RANKS = {"SUBPHYLUM": "Subphylum", "CLASS": "Class", "ORDER": "Order",
              "FAMILY": "Family", "GENUS": "Genus", "SPECIES": "Species",
              "SUBSPECIES": "Subspecies"}
ABOVE_HEXAPODA = {"DOMAIN", "KINGDOM", "PHYLUM", "SUPERKINGDOM", "REALM"}


def _store(conn, usage: dict, parent: int | None, full: bool, accepted: int | None = None):
    tid = ids.from_col(usage["key"])
    status = (usage.get("status") or "ACCEPTED").lower()
    if full:
        conn.execute(
            "INSERT INTO col_taxa (taxon_id, col_id, parent_id, rank, name, authorship, status, "
            "accepted_id, full, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(taxon_id) DO UPDATE SET parent_id = excluded.parent_id, "
            "rank = excluded.rank, name = excluded.name, authorship = excluded.authorship, "
            "status = excluded.status, accepted_id = excluded.accepted_id, full = 1, "
            "fetched_at = excluded.fetched_at",
            (tid, usage["key"], parent, usage.get("rank"), usage.get("canonicalName") or
             usage.get("name"), (usage.get("authorship") or "").strip() or None, status,
             accepted, db.now()))
    else:                        # an ancestor seen in a classification: name and place only
        conn.execute(
            "INSERT INTO col_taxa (taxon_id, col_id, parent_id, rank, name, status, full, "
            "fetched_at) VALUES (?, ?, ?, ?, ?, 'accepted', 0, ?) ON CONFLICT(taxon_id) DO "
            "UPDATE SET parent_id = excluded.parent_id",
            (tid, usage["key"], parent, usage.get("rank"), usage.get("name"), db.now()))
    return tid


def store_answer(conn, d: dict) -> int | None:
    """Store a v2 match answer: the usage, its accepted name if a synonym, and the chain."""
    usage = d.get("usage")
    if not usage or not usage.get("key"):
        return None
    parent = None
    chain = d.get("classification") or []
    for c in chain:
        if c["rank"] in ABOVE_HEXAPODA or c["key"] == usage["key"]:
            continue
        acc = d.get("acceptedUsage")
        if acc and c["key"] == acc.get("key"):
            continue
        parent = _store(conn, c, parent, full=False)
    acc = d.get("acceptedUsage")
    if d.get("synonym") and acc and acc.get("key"):
        acc_id = _store(conn, acc, parent, full=False)
        return _store(conn, usage, None, full=True, accepted=acc_id)
    return _store(conn, usage, parent, full=True)


def fetch_taxa(conn, client: ApiClient, keys: set[int], refresh: bool = False) -> int:
    """Fetch every COL key (internal ids) not fully known yet, committing each."""
    known = {r[0] for r in conn.execute("SELECT taxon_id FROM col_taxa WHERE full = 1")}
    todo = sorted(k for k in keys if ids.kind(k) == "col" and (refresh or k not in known))
    n = 0
    for k in todo:
        try:
            d = client.get_cached(MATCH, {"checklistKey": COL_CHECKLIST, "usageKey": ids.col_of(k)},
                                  refresh=refresh)
        except Exception as e:      # one bad key must not stop the sweep; retried next run
            print(f"  COL {ids.col_of(k)}: {e}", file=sys.stderr)
            continue
        store_answer(conn, d)
        conn.commit()                 # per taxon: never hold the lock across a request
        n += 1
        if n % 50 == 0:
            print(f"  COL taxa: {n} of {len(todo)}", file=sys.stderr)
    conn.commit()
    return n


def displayed_ancestors(conn) -> set[int]:
    """Ancestors at a main rank known only from a classification: fetch them for authorship."""
    return {r[0] for r in conn.execute(
        "SELECT taxon_id FROM col_taxa WHERE full = 0 AND rank IN (%s)" %
        ",".join("?" * len(MAIN_RANKS)), list(MAIN_RANKS))}


def match(client: ApiClient, name: str, rank: str | None = None, authorship: str | None = None,
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


def match_type(d: dict) -> str:
    return (d.get("diagnostics") or {}).get("matchType") or "NONE"


# ---------------------------------------------------------------- ChecklistBank (COL's API)
CLB = "https://api.checklistbank.org"
CLB_DATASET = 316691            # the COL XR GBIF serves (ChecklistBank 3LXR, COL26.10 XR)
EXTINCT_RANKS = ("superorder", "order", "suborder", "infraorder", "superfamily", "family",
                 "subfamily", "tribe", "genus")


def extinct_sweep(conn, clb: ApiClient) -> int:
    """Replace col_extinct: every hexapod taxon COL marks extinct, rank by rank (the search
    pages to 10,000 rows; every rank above species stays under that). Species are left
    out: a fossil species of a living genus is not what puts fossils in this tree."""
    found: dict[int, tuple[str, str]] = {}
    for rank in EXTINCT_RANKS:
        offset = 0
        while True:
            d = clb.get_cached(f"/dataset/{CLB_DATASET}/nameusage/search", {
                "TAXON_ID": HEXAPODA, "extinct": "true", "status": "accepted", "rank": rank,
                "limit": 1000, "offset": offset})
            for r in d.get("result", []):
                u = r["usage"]
                found[ids.from_col(u["id"])] = (u["name"]["scientificName"], rank)
            offset += 1000
            if d.get("last", True) or offset >= min(d.get("total", 0), 10000):
                break
    with conn:
        conn.execute("DELETE FROM col_extinct")
        conn.executemany("INSERT INTO col_extinct (taxon_id, name, rank) VALUES (?, ?, ?)",
                         [(k, n, r) for k, (n, r) in found.items()])
    return len(found)


def info_sweep(conn, clb: ApiClient, keys: list[int]) -> int:
    """English common names and synonyms from COL for each taxon (one request each, cached;
    committed per taxon)."""
    done = {r[0] for r in conn.execute("SELECT taxon_id FROM col_info")}
    todo = [k for k in keys if ids.kind(k) == "col" and k not in done]
    for n, k in enumerate(todo, 1):
        try:
            d = clb.get_cached(f"/dataset/{CLB_DATASET}/taxon/{ids.col_of(k)}/info")
        except Exception as e:      # retried next run
            print(f"  COL info {ids.col_of(k)}: {e}", file=sys.stderr)
            continue
        english = sorted({v["name"] for v in d.get("vernacularNames") or []
                          if v.get("language") == "eng" and v.get("name")})
        syn = d.get("synonyms") or {}
        names = sorted({s["name"]["scientificName"] for group in ("homotypic", "heterotypic")
                        for s in syn.get(group) or [] if (s.get("name") or {}).get("scientificName")})
        conn.execute("INSERT OR REPLACE INTO col_info (taxon_id, vernacular, synonyms, fetched_at) "
                     "VALUES (?, ?, ?, ?)", (k, json.dumps(english), json.dumps(names), db.now()))
        conn.commit()
        if n % 100 == 0:
            print(f"  COL info: {n} of {len(todo)}", file=sys.stderr)
    return len(todo)
