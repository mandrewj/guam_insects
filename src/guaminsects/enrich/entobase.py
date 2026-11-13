"""BugGuide links through the user's entobase database, read-only (CLAUDE.md rule 1).

entobase already matched ~55,000 BugGuide taxa to GBIF keys. We copy (gbif key -> BugGuide
node) for the keys in our tree into `bugguide_links`, so the site can link "BugGuide" where
the species has a page there. BugGuide itself is never fetched. The public build shows a link
only; BugGuide text is not copied (it belongs to its contributors, and carries ai-train=no).
"""

import sqlite3

from .. import config, db

ENTOBASE_DB = config.ROOT.parent / "entobase" / "data.nosync" / "entobase.sqlite"


def sync(conn) -> dict[str, int]:
    if not ENTOBASE_DB.exists():
        return {"entobase": 0}
    src = sqlite3.connect(f"file:{ENTOBASE_DB}?mode=ro", uri=True, timeout=60)
    try:
        rows = src.execute(
            "SELECT CAST(e.external_id AS INTEGER), e.taxon_id, t.scientific_name, t.rank, "
            "e.confidence FROM external_links e JOIN taxa t ON t.bugguide_id = e.taxon_id "
            "WHERE e.system = 'gbif' AND e.confidence IN ('high', 'medium')").fetchall()
    finally:
        src.close()
    ours = {r[0] for r in conn.execute("SELECT gbif_key FROM taxa WHERE gbif_key IS NOT NULL")}
    keep = [r for r in rows if r[0] in ours]
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM bugguide_links WHERE source = 'entobase'")
        conn.executemany(
            "INSERT OR REPLACE INTO bugguide_links (gbif_key, bugguide_id, name, rank, "
            "confidence, source, fetched_at) VALUES (?, ?, ?, ?, ?, 'entobase', ?)",
            [(*r, stamp) for r in keep])
    return {"entobase_links": len(rows), "in_our_tree": len(keep)}
