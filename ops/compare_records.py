"""Compare the records built from dataset/ with the baseline (the old pipeline's records in
private.nosync/baseline/t, kept by refactor Phase 0). Prints, per field, how many taxa differ
and examples. Fields in INTENDED differ on purpose (docs/REFACTOR.md).

    uv run python ops/compare_records.py [--field NAME] [--examples N]
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guaminsects import dataset  # noqa: E402
from guaminsects.build import records as rec  # noqa: E402

BASE = ROOT / "private.nosync" / "baseline" / "t"
# Differences made on purpose: nativity replaces the five-value establishment; the override
# layer (curated) is gone; fetch timestamps are not kept in the dataset.
INTENDED = {"establishment", "curated", "nativity", "nativity_source", "nativity_review",
            "sources"}


def baseline() -> dict[int, dict]:
    out = {}
    for f in BASE.rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        body = text[len("guaminsects.load("):text.rindex(");")]
        r = json.loads(body)
        r.pop("built_at", None)
        r.pop("hash", None)
        out[r["id"]] = r
    return out


def ws(v):
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v


def norm(field: str, v, r: dict):
    """Forms of a value that are equal for our purposes."""
    if field == "synonyms":
        return sorted(v)
    if field == "alt_common":
        return sorted(x for x in v if x != r.get("common"))
    if field in ("photos",):
        return [{k: (x[k][:10] if k == "retrieved" and x.get(k) else ws(x[k])) for k in x} for x in v]
    if field == "wikipedia" and v:
        v = dict(v)
        v["retrieved"] = (v.get("retrieved") or "")[:10]
        v["preview"] = re.sub(r"\s+", " ", v.get("preview") or "")
        return v
    if field == "literature":
        out = []
        for e in v:
            e = {k: ws(x) for k, x in e.items() if k != "dataset"}
            e["areas"] = sorted(e["areas"])
            out.append(e)
        return out
    if field == "children":
        return [{k: x[k] for k in x if k != "est"} for x in v]
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--field")
    ap.add_argument("--examples", type=int, default=3)
    args = ap.parse_args()
    ds = dataset.load()
    new = rec.build_records(ds)
    old = baseline()
    print(f"baseline {len(old)} records, new {len(new)}")
    for tid in sorted(set(old) - set(new))[:10]:
        print("  missing in new:", tid, old[tid]["name"])
    for tid in sorted(set(new) - set(old))[:10]:
        print("  not in baseline:", tid, new[tid]["name"])
    diff: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    keys: dict[str, Counter] = defaultdict(Counter)
    for tid in sorted(set(old) & set(new)):
        o, n = old[tid], new[tid]
        for f in sorted(set(o) | set(n)):
            if f in INTENDED:
                continue
            a, b = norm(f, o.get(f), o), norm(f, n.get(f), n)
            if json.loads(json.dumps(a)) != json.loads(json.dumps(b)):
                diff[f] += 1
                if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                    for x, y in zip(a, b, strict=True):
                        if isinstance(x, dict) and isinstance(y, dict):
                            keys[f].update(k for k in set(x) | set(y) if x.get(k) != y.get(k))
                elif isinstance(a, list) and isinstance(b, list):
                    keys[f]["(length)"] += 1
                if len(examples[f]) < args.examples:
                    examples[f].append((tid, o["name"], a, b))
    if not diff:
        print("all fields equal (apart from the intended ones)")
        return 0
    for f, n in diff.most_common():
        if args.field and f != args.field:
            continue
        print(f"\n{f}: {n} taxa differ" + (f"  (keys: {dict(keys[f].most_common(8))})" if keys[f] else ""))
        for tid, name, a, b in examples[f]:
            sa, sb = json.dumps(a, ensure_ascii=False)[:300], json.dumps(b, ensure_ascii=False)[:300]
            print(f"  {tid} {name}\n    old {sa}\n    new {sb}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
