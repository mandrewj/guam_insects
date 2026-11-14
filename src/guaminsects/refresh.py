"""`guaminsects refresh <inat|living|photos|wikipedia|wikidata|bugguide|col> [--taxa new|all|<ids>]`.

Slim refreshes of one outside source each, run on demand (and by `sync apply` for the taxa it
adds), writing the dataset tables directly. They keep the polite client, the licence filter
and the attribution rules; API answers are cached in private.nosync/api/ (a cache, safe to
delete). `bugguide` reads ../entobase's database read-only and nothing else (CLAUDE.md rule 1).
"""

from . import config, ids
from .http import ApiClient
from .sources import bugguide, photos, wikidata, wikipedia
from .sources import inat as inatapi
from .sources import col as colapi
from .sources import gbif as gbifapi

WHAT = ["wikidata", "inat", "wikipedia", "bugguide", "photos", "living", "col"]
ORDER = ["wikidata", "inat", "bugguide", "wikipedia", "photos", "col"]   # wikipedia and photos need the links


def pick(ds, taxa: str | list[str]) -> list[str]:
    """new -> the taxa flagged new; all -> every accepted taxon; else the given ids."""
    accepted = [r for r in ds["taxa"] if r["status"] != "synonym"]
    if taxa == "new":
        return [r["id"] for r in accepted if r["flag"] == "new"]
    if taxa == "all":
        return [r["id"] for r in accepted]
    have = {r["id"] for r in accepted}
    return [t for t in taxa if t in have]


def col_info(ds, taxa: list[str], clb, today: str, progress=print) -> dict[str, int]:
    """English common names and synonyms from COL (ChecklistBank) for COL taxa: other names
    in names.csv (col synonym) and taxa.other_common_names; `common_name` is only filled
    when empty. Existing editor values are never overwritten."""
    by_id = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    n = 0
    mine = {t for t in taxa if t in by_id}
    ds["names"] = [x for x in ds["names"] if not (x["taxon_id"] in mine and x["kind"] == "col synonym")]
    for t in sorted(mine):
        if by_id[t]["in_col"] != "yes" or not ids.valid(t) or ids.kind(ids.to_int(t)) != "col":
            continue
        try:
            info = colapi.info(clb, t)
        except Exception as e:                       # retried next run
            progress(f"  COL info {t}: {e}")
            continue
        for name in info["synonyms"]:
            if name != by_id[t]["name"]:
                ds["names"].append({"taxon_id": t, "name": name, "kind": "col synonym",
                                    "source": "catalogue of life"})
        if info["english"]:
            row = by_id[t]
            if not row["common_name"]:
                row["common_name"] = info["english"][0]
            others = [e for e in info["english"] if e != row["common_name"]]
            row["other_common_names"] = " | ".join(sorted(set(
                [x for x in row["other_common_names"].split(" | ") if x] + others)))
        n += 1
    return {"asked": len(mine), "info": n}


SEARCH_RANKS = {"Species": "species", "Subspecies": "subspecies", "Genus": "genus",
                "Family": "family", "Order": "order"}


def inat_refresh(ds, taxa: list[str], client, today: str, progress=print,
                 index: dict | None = None) -> dict[str, int]:
    """Link each taxon to iNaturalist (an id from Wikidata or an earlier match, else a search
    for the exact name) and take iNaturalist's English name as the common name; the old common
    name moves to other_common_names. A name is taken only when iNaturalist's own taxon name
    agrees with ours (an id from Wikidata that points at another name is marked `review`)."""
    by_id = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    mine = [t for t in taxa if t in by_id]
    links: dict[str, dict] = {}
    for r in ds["links"]:
        if r["system"] == "inaturalist" and r["taxon_id"] in by_id and r["value"].isdigit():
            if r["taxon_id"] not in links or r["confidence"] == "high":
                links[r["taxon_id"]] = r
    stats = {"asked": len(mine), "linked_before": sum(t in links for t in mine), "searched": 0,
             "new_links": 0, "common_names": 0, "mismatch": 0}
    for n, t in enumerate(mine, 1):
        row = by_id[t]
        if t in links or row["rank"] not in SEARCH_RANKS or row["status"] == "morphospecies":
            continue
        stats["searched"] += 1
        if index is not None:             # iNaturalist's published taxonomy: no request
            table = index.index if hasattr(index, "load_commons") else index
            hit = table.get((row["name"], SEARCH_RANKS[row["rank"]]))
            found = {"id": hit, "common": ""} if hit else None
        else:
            found = inatapi.search(client, row["name"], SEARCH_RANKS[row["rank"]])
        if found:
            link = {"taxon_id": t, "system": "inaturalist", "value": str(found["id"]),
                    "label": found["common"] or "", "confidence": "high",
                    "note": "matched by name (iNaturalist)", "added_by": "refresh inat",
                    "added": today}
            ds["links"].append(link)
            links[t] = link
            stats["new_links"] += 1
        if n % 100 == 0:
            progress(f"  iNaturalist search: {n}/{len(mine)} ({stats['new_links']} new links)")
    ids_ = sorted({int(links[t]["value"]) for t in mine if t in links})
    taxonomy = index if hasattr(index, "load_commons") else None
    if taxonomy is not None:
        # From the published file alone: the name check, and the first English name listed
        # (which one iNaturalist prefers is not in the file; no API request is made).
        taxonomy.load_commons(set(ids_))
        info = {i: {"name": taxonomy.names.get(i), "common": (taxonomy.commons.get(i) or [None])[0]}
                for i in ids_}
        stats["no_english_name"] = sum(1 for i in ids_ if not taxonomy.commons.get(i))
    else:
        info = inatapi.taxa_by_ids(client, ids_, progress)
    progress(f"  iNaturalist taxa read: {len(info)}")
    for t in mine:
        link = links.get(t)
        got = info.get(int(link["value"])) if link else None
        if not got or not got.get("name"):
            continue
        row = by_id[t]
        if (got["name"] or "").lower() != row["name"].lower():
            stats["mismatch"] += 1
            link["confidence"] = "review"
            link["note"] = f"iNaturalist names it {got['name']}"
            continue
        if got["common"]:
            link["label"] = got["common"]
            old = row["common_name"]
            if old and _editor_owned(row):
                continue                  # a person's common name is never replaced (rule 7)
            if old != got["common"]:
                if old and old.lower() != got["common"].lower():
                    others = [x for x in row["other_common_names"].split(" | ") if x]
                    if old not in others:
                        row["other_common_names"] = " | ".join(sorted(others + [old]))
                row["common_name"] = got["common"]
                row["other_common_names"] = " | ".join(
                    x for x in row["other_common_names"].split(" | ")
                    if x and x.lower() != got["common"].lower())
                stats["common_names"] += 1
    return stats


TOOL_NAMES = ("guaminsects", "refresh", "migrate", "build", "sync", "match", "plazi", "lit")


def _person(name: str) -> bool:
    return bool(name) and not name.lower().startswith(TOOL_NAMES)


def _editor_owned(row) -> bool:
    """A taxon a person added or edited: its common name is theirs (the table keeps no
    per-column history, so any edit by a person protects the name)."""
    return _person(row.get("modified_by", "")) or _person(row.get("added_by", ""))


def run(ds, what: str, taxa: list[str], today: str, progress=print) -> dict:
    """One refresh over these taxa; returns its statistics."""
    if what == "wikidata":
        http = wikidata.client()
        try:
            return wikidata.refresh(ds, taxa, http, today, progress)
        finally:
            http.close()
    if what == "inat":
        client = ApiClient(inatapi.INAT, 1.0)
        try:
            if not inatapi.TAXONOMY_ZIP.exists():
                progress("  downloading iNaturalist's taxonomy (80 MB, once)")
                inatapi.download_taxonomy()
            progress("  reading the taxonomy")
            return inat_refresh(ds, taxa, client, today, progress, index=inatapi.read_taxonomy())
        finally:
            client.close()
    if what == "wikipedia":
        client = ApiClient(wikipedia.ENWIKI, 1.0)
        try:
            return wikipedia.refresh(ds, taxa, client, today, progress=progress)
        finally:
            client.close()
    if what == "bugguide":
        return bugguide.refresh(ds, taxa, today)
    if what == "photos":
        clients = {"inat": ApiClient(photos.INAT, 1.0), "commons": ApiClient(photos.COMMONS_API, 1.0),
                   "gbif": ApiClient(gbifapi.GBIF, 0.34), "bytes": ApiClient("", 0.5)}
        try:
            return photos.refresh(ds, taxa, clients, today, progress=progress)
        finally:
            for c in clients.values():
                c.close()
    if what == "living":
        clients = {"inat": ApiClient(photos.INAT, 1.0), "bytes": ApiClient("", 0.5)}
        try:
            return photos.prefer_living(ds, clients["inat"], clients["bytes"], today, progress=progress)
        finally:
            for c in clients.values():
                c.close()
    if what == "col":
        clb = ApiClient(colapi.CLB, 0.5)
        try:
            return col_info(ds, taxa, clb, today, progress)
        finally:
            clb.close()
    raise ValueError(f"refresh what? one of {', '.join(WHAT)}")


def run_new(ds, new_ids: list[str], today: str, progress=print) -> dict[str, dict]:
    """What `sync apply` does for the taxa it added: links, Wikipedia, BugGuide, photos."""
    out = {}
    for what in ORDER:
        if what == "col":
            continue
        try:
            out[what] = run(ds, what, new_ids, today, progress)
        except Exception as e:           # a source being down must not lose the run
            out[what] = {"error": str(e)}
            progress(f"  refresh {what}: {e}")
    return out


_ = config
