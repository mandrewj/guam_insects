"""List of Insects and Mites Attacking Crops in Micronesia (Nafus & Schreiner, early 1990s;
HTML by A. Moore & A. Tudela; CSV at github.com/aubreymoore/crop-pest-list).

About 950 (crop, pest) rows with order, family and a distribution code per island group:
B Belau, Y Yap, T Truk, P Pohnpei, K Kosrae, M the Mariana Islands (Guam and the CNMI
together, so it supports no single area here). Values: x present, n new island record,
? unverified (skipped). The list has no licence statement: we use its facts (presence,
host crops) with a citation and link, and copy none of its text. Mites (Acari) are out of
scope.
"""

import csv
import re
import sys

from .. import config, db, ids
from .gbif_checklist import fetch_taxa, match_name
from .http import ApiClient

SOURCE_URL = "https://aubreymoore.github.io/crop-pest-list/"
CSV_URL = "https://raw.githubusercontent.com/aubreymoore/crop-pest-list/gh-pages/crop-pest.csv"
CACHE = config.RAW_DIR / "github.com" / "aubreymoore" / "crop-pest.csv"
DATASET = "nafus-schreiner-crop-pests"
CITATION = ("Nafus, D.M. & Schreiner, I.H. List of insects and mites attacking crops in "
            "Micronesia. University of Guam; HTML version by A. Moore & A. Tudela, Northern "
            "Marianas College; https://aubreymoore.github.io/crop-pest-list/")
CODES = {"B": ("PW", "Palau"), "Y": ("FM", "Yap"), "T": ("FM", "Chuuk"), "P": ("FM", "Pohnpei"),
         "K": ("FM", "Kosrae")}


def canonical(name: str) -> str:
    """'Aonidiella orientalis (Newstead)' -> 'Aonidiella orientalis'."""
    words = name.replace("(", " (").split()
    out = words[:1]
    for w in words[1:]:
        if re.fullmatch(r"[a-z][a-z\-]+", w) and w not in ("var", "sp", "spp", "and"):
            out.append(w)
        else:
            break
    return " ".join(out[:3])


def distribution(code: str) -> list[tuple[str, str]]:
    out = []
    for k, v in re.findall(r"([A-Z]+)=([^A-Z]+)", code):
        if "?" in v:
            continue
        for letter in k:                 # "YP=x" is Yap and Pohnpei
            if letter in CODES:
                out.append(CODES[letter])
    return out


def load() -> list[dict]:
    if not CACHE.exists():
        import httpx

        CACHE.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(CSV_URL, headers={"User-Agent": config.USER_AGENT}, timeout=60)
        r.raise_for_status()
        CACHE.write_text(r.text, encoding="utf-8")
    with CACHE.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["pest_order"] != "Acari"]


def sweep(conn, client: ApiClient) -> dict[str, int]:
    rows = load()
    tree = {r["name"]: r["taxon_id"] for r in conn.execute("SELECT taxon_id, name FROM taxa")}
    keys: dict[str, int | None] = {}
    for r in rows:
        name = canonical(r["pest_scientific_name"])
        if name in keys or " " not in name:
            continue
        if name in tree:
            keys[name] = tree[name]
            continue
        m = match_name(client, name, "SPECIES")
        keys[name] = m and (m.get("acceptedUsageKey") or m.get("usageKey"))
    fetch_taxa(conn, client, {k for k in keys.values() if k and k < ids.COL_BASE})
    presence: dict[tuple[int, str], int] = {}
    islands: set[tuple[int, str, str]] = set()
    hosts: set[tuple[int, str]] = set()
    names = []
    for r in rows:
        name = canonical(r["pest_scientific_name"])
        k = keys.get(name)
        if not k:
            continue
        names.append((k, r["pest_scientific_name"]))
        hosts.add((k, r["crop"].strip()))
        for area, isl in distribution(r["pest_distribution"]):
            presence[(k, area)] = 1
            islands.add((k, area, isl))
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM checklist_sources WHERE dataset_key = ?", (DATASET,))
        conn.execute("INSERT INTO checklist_sources (dataset_key, source, title, citation, areas, "
                     "license, doi, fetched_at) VALUES (?, 'croppests', ?, ?, 'PW,FM', NULL, "
                     "NULL, ?)", (DATASET, "List of Insects and Mites Attacking Crops in "
                                  "Micronesia", CITATION, stamp))
        conn.execute("DELETE FROM checklist_names WHERE dataset_key = ?", (DATASET,))
        conn.executemany("INSERT OR IGNORE INTO checklist_names (dataset_key, source, usage_key, "
                         "nub_key, name, rank) VALUES (?, 'croppests', ?, ?, ?, 'SPECIES')",
                         [(DATASET, i, k, n) for i, (k, n) in enumerate(names)])
        conn.execute("DELETE FROM taxon_presence WHERE source = 'checklist'")
        conn.executemany("INSERT INTO taxon_presence (taxon_id, area, source, records, citation, "
                         "fetched_at) VALUES (?, ?, 'checklist', 1, ?, ?)",
                         [(k, a, DATASET, stamp) for (k, a) in presence])
        conn.execute("DELETE FROM taxon_islands WHERE source = 'croppests'")
        conn.executemany("INSERT OR IGNORE INTO taxon_islands (taxon_id, area, island, source, "
                         "records, fetched_at) VALUES (?, ?, ?, 'croppests', 1, ?)",
                         [(k, a, i, stamp) for (k, a, i) in islands])
        conn.execute("DELETE FROM taxon_hosts WHERE source = 'croppests'")
        conn.executemany("INSERT OR IGNORE INTO taxon_hosts (taxon_id, host, source) VALUES "
                         "(?, ?, 'croppests')", sorted(hosts))
    stats = {"rows": len(rows), "names": len(keys), "matched": sum(bool(v) for v in keys.values()),
             "presence": len(presence), "hosts": len(hosts)}
    print(", ".join(f"{k} {v}" for k, v in stats.items()), file=sys.stderr)
    return stats
