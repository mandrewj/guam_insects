"""`guaminsects refresh <photos|wikipedia|wikidata|bugguide|col> [--taxa new|all|<ids>]`.

Slim refreshes of one outside source each, run on demand (and by `sync apply` for the taxa it
adds), writing the dataset tables directly. They keep the polite client, the licence filter
and the attribution rules; API answers are cached in private.nosync/api/ (a cache, safe to
delete). `bugguide` reads ../entobase's database read-only and nothing else (CLAUDE.md rule 1).
"""

from . import config, ids
from .http import ApiClient
from .sources import bugguide, photos, wikidata, wikipedia
from .sources import col as colapi
from .sources import gbif as gbifapi

WHAT = ["wikidata", "wikipedia", "bugguide", "photos", "col"]
ORDER = ["wikidata", "bugguide", "wikipedia", "photos", "col"]       # wikipedia needs wikidata's link


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


def run(ds, what: str, taxa: list[str], today: str, progress=print) -> dict:
    """One refresh over these taxa; returns its statistics."""
    if what == "wikidata":
        http = wikidata.client()
        try:
            return wikidata.refresh(ds, taxa, http, today, progress)
        finally:
            http.close()
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
