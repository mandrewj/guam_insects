"""`guaminsects build`: dataset/ -> site.nosync/public. No database and no network.

1. load and check the dataset (any problem stops the build);
2. records.build_records: the record each taxon page renders;
3. bundle: chunk files + index; search: names and full-text shards; export: taxonomy.js;
4. copy webapp/ and the thumbnails in use; write meta.js.
"""

import json
import shutil
from pathlib import Path

from .. import config, dataset, geo
from . import bundle, export, records, search

WEBAPP_DIR = config.ROOT / "webapp"
MEDIA_DIR = config.ROOT / "media"
JS_GLOBAL = "guaminsects"
SPECIES = "Species"


class BuildError(Exception):
    pass


def home_cards(recs: dict[int, dict], root: int) -> list[dict]:
    """The home page lists the orders (and the non-insect classes) as cards: Hexapoda's own
    children are just four classes, one of which holds nearly everything."""
    out = []
    for c in recs[root]["children"]:
        if c["name"] == "Insecta":
            out += list(recs[c["id"]]["children"])
        else:
            out.append(c)
    return sorted(out, key=lambda c: (c["hidden"], -c["species_count"], c["name"]))


def build(ds: dataset.Dataset | None = None, out: Path | None = None, check: bool = True) -> dict:
    ds = ds or dataset.load()
    if check:
        problems = dataset.check(ds)
        if problems:
            raise BuildError("the dataset has problems; fix them (guaminsects dataset check):\n"
                             + "\n".join(problems.items[:30]))
    out = out or config.SITE_DIR / "public"
    out.mkdir(parents=True, exist_ok=True)
    for src in WEBAPP_DIR.rglob("*"):
        if src.is_file() and src.name != ".DS_Store":
            dest = out / src.relative_to(WEBAPP_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.read_bytes() != src.read_bytes():
                shutil.copy2(src, dest)

    recs = records.build_records(ds)
    stats = bundle.write(recs, out)
    stats.pop("chunk_of")
    idx = search.build(recs, out)
    table = export.rows(ds, recs)
    (out / "data").mkdir(exist_ok=True)
    bundle.write_if_changed(out / "data" / "taxonomy.js", export.site_script(table))

    # Thumbnails ship with the site (the one kind of image we host); photos are hotlinked.
    used = {p["thumb"].rsplit("/", 1)[1] for r in recs.values() for p in r["photos"]
            if p["thumb"] and p["thumb"].startswith("media/thumbs/")}
    dest = out / "media" / "thumbs"
    dest.mkdir(parents=True, exist_ok=True)
    for name in used:
        if not (dest / name).exists():
            shutil.copy2(MEDIA_DIR / "thumbs" / name, dest / name)
    for stale in dest.glob("*.webp"):
        if stale.name not in used:
            stale.unlink()

    root = next((tid for tid, r in recs.items() if not r["lineage"]), None)
    species = [r for r in recs.values() if r["rank"] == SPECIES and not r["hidden"]]
    meta = {
        "built_at": dataset_date(ds), "root": root,
        "title": config.SITE_TITLE, "subtitle": config.SITE_SUBTITLE,
        "home": home_cards(recs, root) if root else [],
        "regions": [{"key": a["code"].lower(), "code": a["code"],
                     "label": records.AREA_SHORT[a["code"]], "name": a["name"],
                     "species": sum(a["code"].lower() in (r["regions"] or []) for r in species)}
                    for a in config.AREAS],
        "geo": geo.for_meta(),
        "search": {"docs": idx["docs"], "shards": idx["shards"], "stopwords": idx["stopwords"]},
        "counts": {
            "taxa": len(recs), "species": len(species),
            "genera": recs[root]["genus_count"] if root else 0,
            "guam": sum("gu" in (r["regions"] or []) for r in species),
            "morphospecies": sum(r["status"] == "morphospecies" for r in recs.values()),
            "not_in_col": sum(not r["in_col"] and r["origin"] != "curated" for r in species),
            "photos": sum(bool(r["photos"]) for r in recs.values()),
            "literature": sum(bool(r["literature"]) for r in species),
        },
    }
    bundle.write_if_changed(out / "data" / "meta.js",
                            f"{JS_GLOBAL}.meta({json.dumps(meta, separators=(',', ':'))});\n")
    shipped = [p for p in out.rglob("*") if p.is_file() and ".vercel" not in p.parts]
    return {"records": len(recs), "search_docs": idx["docs"], "files": len(shipped),
            "megabytes": round(sum(p.stat().st_size for p in shipped) / 1e6, 1), **stats}


def dataset_date(ds: dataset.Dataset) -> str:
    """When the data last changed: the newest date any table carries (no clock in the build,
    so the same dataset always builds the same site)."""
    dates = [r[c] for t, c in (("taxa", "modified"), ("taxa", "added"), ("records", "refreshed"),
                               ("photos", "retrieved")) for r in ds[t] if r[c]]
    dates += [w["retrieved"] for w in ds.wikipedia if w.get("retrieved")]
    return max(dates, default="")
