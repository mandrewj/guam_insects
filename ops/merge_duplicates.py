"""One-off (2026-11-14): merge the probable duplicates that the authorities or the author
conventions settle; write the decisions to private.nosync/exports/merge-decisions.csv.

    uv run python ops/merge_duplicates.py [--dry-run]
"""

import csv
import json
import sys
from datetime import date

from guaminsects import config, dataset, dupes
from guaminsects.http import ApiClient
from guaminsects.sources import gbif as gbifapi
from guaminsects.sources import inat


def main(dry: bool) -> None:
    today = date.today().isoformat()
    ds = dataset.load()
    gb = ApiClient(gbifapi.GBIF, 0.34)
    ix = inat.read_taxonomy().index
    out = config.ROOT / "private.nosync" / "exports"
    merged, kept_all = [], []
    for sweep in range(4):                      # merging genera can create new same-name species
        rows = dupes.find(ds)
        by_id = {r["id"]: r for r in ds["taxa"]}
        ev = {}
        for r in rows:
            for i in (r["id_a"], r["id_b"]):
                if i not in ev:
                    t = by_id[i]
                    ev[i] = {"gbif": dupes.authority(gb, t["name"], t["rank"]),
                             "inat": ix.get((t["name"], t["rank"].lower()))}
        evidence = dupes.evidence_of(ds)
        merges, kept = dupes.decide(rows, by_id, ev, evidence)
        done = 0
        for m in merges:
            if dupes.merge(ds, m["loser"], m["winner"], m["reason"], m["uncertain"], today):
                merged.append({**m, "loser_name": by_id[m["loser"]]["name"], "winner_name": by_id[m["winner"]]["name"]})
                done += 1
        kept_all = kept
        print(f"sweep {sweep}: {len(rows)} pairs, {done} merged, {len(kept)} kept apart")
        if not done:
            break
    problems = dataset.check(ds)
    print("check:", problems.items[:10] if problems else "0 problems")
    if problems:
        return
    with (out / "merge-decisions.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "winner", "winner_name", "loser", "loser_name", "uncertain", "reason"])
        w.writeheader()
        w.writerows(merged)
    with (out / "kept-apart.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(kept_all[0])) if kept_all else None
        if w:
            w.writeheader()
            w.writerows(kept_all)
    if not dry:
        dataset.write(ds)
    json.dump({"merged": len(merged), "kept": len(kept_all)}, sys.stdout)
    print()


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
