"""BugGuide links through the user's entobase database, read-only (CLAUDE.md rule 1).

entobase already matched ~55,000 BugGuide taxa to GBIF keys. For each taxon with a GBIF key we
add (taxon -> BugGuide node) to links.csv, so the site can link "BugGuide" where the species
has a page there. BugGuide itself is never fetched. The site shows a link only; BugGuide text
is not copied (it belongs to its contributors, and carries ai-train=no).
"""

import sqlite3
from pathlib import Path

from .. import config

ENTOBASE_DB = config.ROOT.parent / "entobase" / "data.nosync" / "entobase.sqlite"


def entobase_rows(path: Path = ENTOBASE_DB) -> list[tuple]:
    if not path.exists():
        # An empty list would make refresh() delete every tool-made BugGuide link.
        raise FileNotFoundError(f"entobase database not found: {path} (BugGuide links are read from it)")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    try:
        return src.execute(
            "SELECT CAST(e.external_id AS INTEGER), e.taxon_id, t.scientific_name, t.rank, "
            "e.confidence FROM external_links e JOIN taxa t ON t.bugguide_id = e.taxon_id "
            "WHERE e.system = 'gbif' AND e.confidence IN ('high', 'medium')").fetchall()
    finally:
        src.close()


def refresh(ds, taxa: list[str], today: str, rows: list[tuple] | None = None) -> dict[str, int]:
    rows = entobase_rows() if rows is None else rows
    by_key: dict[int, list[tuple]] = {}
    for r in rows:
        by_key.setdefault(r[0], []).append(r)
    mine = set(taxa)
    names = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    ds["links"] = [r for r in ds["links"] if not (
        r["taxon_id"] in mine and r["system"] == "bugguide" and r["added_by"] == "refresh bugguide")]
    n = 0
    for t in taxa:
        row = names.get(t)
        if not row or not row["gbif_key"] or any(
                x["taxon_id"] == t and x["system"] == "bugguide" for x in ds["links"]):
            continue
        cands = by_key.get(int(row["gbif_key"]), [])
        best = next((c for c in cands if c[2] == row["name"]), cands[0] if cands else None)
        if best:
            ds["links"].append({"taxon_id": t, "system": "bugguide", "value": str(best[1]),
                                "label": "", "confidence": "high" if best[4] == "high" else "medium",
                                "note": "", "added_by": "refresh bugguide", "added": today})
            n += 1
    return {"entobase_links": len(rows), "linked": n}
