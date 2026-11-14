"""`guaminsects sync check | apply`: GBIF and iNaturalist counts against records.csv.

check   For each of the five areas, the counts per taxon in as few requests as possible:
        GBIF occurrence facets (Catalogue of Life keys by rank, then the GBIF Backbone facet
        for names COL lacks), preserved-specimen facets, iNaturalist research-grade
        species_counts. Nothing is written to the dataset: the answer goes to
        private.nosync/staging/sync-<date>.json with a summary (new keys, counts changed,
        counts gone to zero, unchanged).
apply   (automatic, docs/REFACTOR.md decision 6) records.csv updated; taxa whose counts changed
        get their statistics refreshed (years, the island facet); new keys are matched,
        added to taxa.csv flagged `new` with nativity `unknown`; a taxon whose records
        vanished is reported, never removed (a person decides: it may be a re-identification).

The dataset is changed in memory; the caller (cli.py) writes it.
"""

import json
from collections import defaultdict
from pathlib import Path

from . import config, ids
from .sources import col as colapi
from .sources import gbif as gbifapi
from .sources import inat as inatapi

AREAS = {a["code"]: a for a in config.AREAS}


def staging_path(today: str) -> Path:
    return config.STAGING_DIR / f"sync-{today}.json"


# --- check: ask the sources ------------------------------------------------------------------

def check(ds, gbif, inat, areas: list[str] | None = None, today: str = "",
          backbone: bool = True, specimens: bool = True, progress=print) -> dict:
    """Ask GBIF and iNaturalist; returns the staging dict (not written anywhere)."""
    out: dict = {"date": today, "areas": {}}
    for code, area in AREAS.items():
        if areas and code not in areas:
            continue
        a: dict = {"col": gbifapi.area_counts(gbif, area["gbif"]),
                   "specimens": {}, "backbone": {}, "inat": []}
        progress(f"GBIF {code}: {len(a['col'])} taxa")
        if specimens:
            a["specimens"] = gbifapi.area_counts(gbif, area["gbif"], gbifapi.SPECIMEN_BASIS)
        if backbone:
            a["backbone"] = gbifapi.area_counts(gbif, area["gbif"], col=False)
        a["inat"] = [r for r in inatapi.place_counts(inat, area["inat"])
                     if r["rank"] in inatapi.RANKS]
        progress(f"iNat {code}: {len(a['inat'])} taxa")
        out["areas"][code] = a
    return out


# --- mapping source keys to taxa ----------------------------------------------------------------

class KeyMap:
    def __init__(self, ds):
        self.ds = ds
        self.reindex()

    def reindex(self) -> None:
        ds = self.ds
        self.taxa = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
        self.syn = {r["id"]: r["accepted_id"] for r in ds["taxa"] if r["status"] == "synonym"}
        self.keys = {(k["source"], k["key"]): k["taxon_id"] for k in ds["keys"]}
        self.by_name: dict[tuple[str, str], str] = {}
        for r in ds["taxa"]:
            tid = r["accepted_id"] if r["status"] == "synonym" else r["id"]
            self.by_name.setdefault((r["name"], r["rank"].upper()), tid)

    def shown(self, tid: str | None) -> str | None:
        tid = self.syn.get(tid, tid)
        return tid if tid in self.taxa else None

    def col(self, key: str) -> str | None:
        return self.shown(self.keys.get(("col", key)) or (key if key in self.taxa or key in self.syn else None))

    def backbone(self, key: str) -> str | None:
        return self.shown(self.keys.get(("gbif", key)) or self.keys.get(("gbif", str(key)))
                          or (f"gbif:{key}" if f"gbif:{key}" in self.taxa else None))

    def inat(self, name: str, rank: str) -> str | None:
        return self.shown(self.keys.get(("inat", name)) or self.by_name.get((name, rank.upper())))


def desired(ds, staging: dict) -> tuple[dict, dict]:
    """The records rows the staged answers make: {(taxon, area, source): n}, and the keys
    nothing maps to: {"col": {key: n}, "backbone": {...}, "inat": {(name, rank): n}}."""
    km = KeyMap(ds)
    rows: dict[tuple[str, str, str], int] = defaultdict(int)
    unmapped: dict[str, dict] = {"col": {}, "backbone": {}, "inat": {}}
    for code, a in staging["areas"].items():
        for src, counts in (("gbif", a["col"]), ("gbif_specimens", a["specimens"])):
            for key, n in counts.items():
                if gbifapi.col_key_kind(key) != "col":
                    continue                        # BOLD BINs and the like: not taxa here
                t = km.col(key)
                if t is None:
                    unmapped["col"][key] = unmapped["col"].get(key, 0) + n
                else:
                    rows[(t, code, src)] += n
        for key, n in a["backbone"].items():
            t = km.backbone(key)
            # GBIF counts under a Backbone name count only for a taxon COL lacks; for one in
            # COL, GBIF's count under the COL key already includes them.
            if t is None:
                unmapped["backbone"][key] = unmapped["backbone"].get(key, 0) + n
            elif km.taxa[t]["in_col"] != "yes":
                rows[(t, code, "gbif")] += n
        for r in a["inat"]:
            t = km.inat(r["name"], r["rank"])
            if t is None:
                k = (r["name"], r["rank"])
                unmapped["inat"][k] = unmapped["inat"].get(k, 0) + r["count"]
            else:
                rows[(t, code, "inat")] += r["count"]
    return dict(rows), unmapped


def summarize(ds, staging: dict) -> dict:
    """What would change: new keys, changed counts, gone to zero, unchanged."""
    want, unmapped = desired(ds, staging)
    swept = set(staging["areas"])
    have = {(r["taxon_id"], r["area"], r["source"]): int(r["records"] or 0)
            for r in ds["records"] if r["area"] in swept}
    km = KeyMap(ds)
    sources = {"gbif", "gbif_specimens", "inat"}
    changed, gone, same, added = [], [], 0, []
    for k, n in want.items():
        if k not in have:
            added.append((k, n))
        elif have[k] != n:
            changed.append((k, have[k], n))
        else:
            same += 1
    for k, n in have.items():
        if k not in want and k[2] in sources and km.shown(k[0]):
            gone.append((k, n))
    changed.sort(key=lambda c: -abs(c[2] - c[1]))
    return {"areas": sorted(swept),
            "new_keys": {"col": len(unmapped["col"]), "backbone": len(unmapped["backbone"]),
                         "inat": len(unmapped["inat"])},
            "new_rows": len(added), "changed": len(changed), "gone_to_zero": len(gone),
            "unchanged": same,
            "largest_changes": [{"taxon": k[0], "area": k[1], "source": k[2], "was": a, "now": b}
                                for k, a, b in changed[:10]],
            "vanished": [{"taxon": k[0], "area": k[1], "source": k[2], "was": n}
                         for k, n in gone[:30]],
            "unmapped_col": dict(sorted(unmapped["col"].items(), key=lambda x: -x[1])[:20])}


# --- apply: change the dataset ---------------------------------------------------------------------

def apply(ds, staging: dict, matcher, gbif=None, today: str = "", refresh_new=None,
          stats_limit: int = 400, progress=print) -> dict:
    """Update records.csv from the staged answers; add new taxa (flagged new); refresh the
    statistics of taxa whose counts changed; `refresh_new(ds, ids)` fetches photos, Wikipedia,
    Wikidata and BugGuide links for the new ones."""
    before = {r["id"] for r in ds["taxa"]}
    want, unmapped = desired(ds, staging)
    # New keys first: each is matched (or added) and counted on the next pass.
    for key in unmapped["col"]:
        try:
            d = colapi.by_key(matcher.col, key)
        except Exception as e:                       # one bad key must not stop the run
            progress(f"  COL {key}: {e}")
            continue
        if colapi.is_hexapod(d):
            matcher.ensure_col(d)
    for key in unmapped["backbone"]:
        if gbif is None:
            break
        try:
            t = gbifapi.species(gbif, key)
        except Exception as e:
            progress(f"  GBIF {key}: {e}")
            continue
        rank = (t.get("rank") or "").upper()
        if rank in ("SPECIES", "SUBSPECIES", "GENUS") and t.get("canonicalName") \
                and t.get("taxonomicStatus") == "ACCEPTED" and t.get("classKey") in config.HEXAPOD_CLASSES:
            matcher.resolve(t["canonicalName"], rank, "gbif", key=str(key),
                            authorship=(t.get("authorship") or "").strip() or None)
    for (name, rank), _n in unmapped["inat"].items():
        matcher.resolve(name, rank, "inat")
    matcher.reindex()
    want, unmapped = desired(ds, staging)

    swept = set(staging["areas"])
    old = {(r["taxon_id"], r["area"], r["source"]): r for r in ds["records"]}
    km = KeyMap(ds)
    keep = [r for r in ds["records"] if r["area"] not in swept or r["source"] not in
            ("gbif", "gbif_specimens", "inat")]
    new_rows, changed_taxa, vanished = [], set(), []
    for (t, area, src), n in sorted(want.items()):
        prior = old.get((t, area, src))
        if prior is None or int(prior["records"] or 0) != n:
            changed_taxa.add(t)
        new_rows.append({"taxon_id": t, "area": area, "source": src, "records": str(n),
                         "first_year": prior["first_year"] if prior and int(prior["records"] or 0) == n else "",
                         "last_year": prior["last_year"] if prior and int(prior["records"] or 0) == n else "",
                         "query_key": prior["query_key"] if prior else "", "refreshed": today})
    for k, r in old.items():
        if k not in want and r["area"] in swept and r["source"] in ("gbif", "gbif_specimens", "inat") \
                and km.shown(k[0]):
            vanished.append({"taxon": k[0], "area": k[1], "source": k[2], "was": int(r["records"] or 0)})
    ds["records"] = keep + new_rows

    new_ids = sorted({r["id"] for r in ds["taxa"]} - before)
    stats_for = [t for t in sorted(changed_taxa) if gbif and ids.valid(t) and ids.kind(ids.to_int(t)) == "col"
                 and km.taxa.get(t, {}).get("rank") in ("Species", "Subspecies", "Genus")]
    refreshed = refresh_statistics(ds, stats_for[:stats_limit], gbif, today, progress) if gbif else 0
    if refresh_new and new_ids:
        refresh_new(ds, [t for t in new_ids if t in {r["id"] for r in ds["taxa"] if r["status"] != "synonym"}])
    return {"new_taxa": len(new_ids), "new_ids": new_ids, "counts_changed": len(changed_taxa),
            "statistics_refreshed": refreshed, "vanished": vanished,
            "unplaced": len(ds["unplaced"]), "matcher": dict(matcher.stats)}


def refresh_statistics(ds, taxa: list[str], gbif, today: str, progress=print) -> int:
    """First and last year per area, and the islands (GADM level 1) of each taxon."""
    rows = {(r["taxon_id"], r["area"], r["source"]): r for r in ds["records"]}
    n = 0
    for t in taxa:
        for code, area in AREAS.items():
            r = rows.get((t, code, "gbif"))
            if not r:
                continue
            first, last = gbifapi.taxon_years(gbif, t, area["gbif"])
            r["first_year"], r["last_year"] = str(first or ""), str(last or "")
            if code != "GU":
                ds["islands"] = [i for i in ds["islands"] if not (
                    i["taxon_id"] == t and i["area"] == code and i["source"] == "gbif")]
                for isl, cnt in gbifapi.taxon_islands(gbif, t, area).items():
                    ds["islands"].append({"taxon_id": t, "area": code, "island": isl,
                                          "source": "gbif", "records": str(cnt), "doc_id": ""})
        n += 1
        if n % 25 == 0:
            progress(f"  statistics: {n}/{len(taxa)}")
    return n


# --- staging files ------------------------------------------------------------------------------------

def save(staging: dict, today: str) -> Path:
    path = staging_path(today)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(staging, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_staging() -> Path | None:
    files = sorted(config.STAGING_DIR.glob("sync-*.json")) if config.STAGING_DIR.exists() else []
    return files[-1] if files else None

