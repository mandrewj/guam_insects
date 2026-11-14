"""The data the app loads, bundled into a few hundred files (instead of one script per taxon).

    data/index.js     which chunk holds each taxon (ids delta-encoded, base 36)   at start
    data/c/<n>.js     the full records of one chunk                               on first visit
    data/w/<n>.js     the Wikipedia HTML of the same chunk's taxa                 on "Show entire article"

Chunks keep a family and everything under it together, so browsing a family loads one file.
A taxon above Family has a chunk of its own. A family over MAX_UNIT bytes is split by genus; small
families next to each other (same order) share a chunk. Loading works from file:// because each
file is a <script> that calls guaminsects.chunk / guaminsects.wiki (CLAUDE.md rule 9).
"""

import json
from pathlib import Path

from ..search import b36

JS_GLOBAL = "guaminsects"
MAX_UNIT = 400_000          # a family bigger than this is split by genus
TARGET = 150_000            # neighbouring small families are merged up to this size
ABOVE_FAMILY = {"Subphylum", "Class", "Order"}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def assign_chunks(records: dict[int, dict], sizes: dict[int, int]) -> dict[int, int]:
    """taxon id -> chunk number (0, 1, 2, ...)."""
    kids: dict[int, list[int]] = {}
    root = None
    for tid, r in records.items():
        if r["lineage"]:
            kids.setdefault(r["lineage"][-1]["id"], []).append(tid)
        else:
            root = tid
    for v in kids.values():
        v.sort(key=lambda c: (records[c]["name"].casefold(), c))

    sub_size: dict[int, int] = {}

    def total(tid: int) -> int:
        if tid not in sub_size:
            sub_size[tid] = sizes[tid] + sum(total(c) for c in kids.get(tid, ()))
        return sub_size[tid]

    def members(tid: int) -> list[int]:
        out, stack = [], [tid]
        while stack:
            t = stack.pop()
            out.append(t)
            stack.extend(reversed(kids.get(t, ())))
        return out

    # Units in depth-first order, each tagged with the order it sits under (merging stays
    # within one order).
    units: list[tuple[int, list[int]]] = []

    def pack(tid: int, group: int) -> None:
        r = records[tid]
        if r["rank"] in ABOVE_FAMILY:
            units.append((tid, [tid]))
            for c in kids.get(tid, ()):
                pack(c, tid if r["rank"] == "Order" else group)
        elif total(tid) <= MAX_UNIT:
            units.append((group, members(tid)))
        else:
            units.append((group, [tid]))
            for c in kids.get(tid, ()):
                pack(c, group)

    pack(root, root)
    chunk_of: dict[int, int] = {}
    n, cur_group, cur_size, cur = -1, None, 0, False
    for group, ids_ in units:
        size = sum(sizes[t] for t in ids_)
        solo = len(ids_) == 1 and records[ids_[0]]["rank"] in ABOVE_FAMILY
        if solo or not cur or group != cur_group or cur_size + size > TARGET:
            n += 1
            cur_group, cur_size, cur = group, 0, not solo
        cur_size += size
        for t in ids_:
            chunk_of[t] = n
    return chunk_of


def index_script(chunk_of: dict[int, int]) -> str:
    """{chunk: "id,delta,delta,..."}: ids sorted, deltas in base 36."""
    by_chunk: dict[int, list[int]] = {}
    for tid, n in chunk_of.items():
        by_chunk.setdefault(n, []).append(tid)
    body = {}
    for n, tids in sorted(by_chunk.items()):
        prev, parts = 0, []
        for t in sorted(tids):
            parts.append(b36(t - prev))
            prev = t
        body[str(n)] = ",".join(parts)
    return f"{JS_GLOBAL}.index({dumps(body)});\n"


def write_if_changed(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def write(records: dict[int, dict], out: Path) -> dict:
    """Write data/index.js, data/c/*.js and data/w/*.js; returns counts."""
    light, wiki = {}, {}
    for tid, r in records.items():
        w = r.get("wikipedia")
        if w:
            wiki[tid] = w["html"]
            r = {**r, "wikipedia": {k: v for k, v in w.items() if k != "html"} | {"has_html": True}}
        light[tid] = r
    body = {tid: dumps(r) for tid, r in light.items()}
    sizes = {tid: len(s.encode()) for tid, s in body.items()}
    chunk_of = assign_chunks(light, sizes)
    by_chunk: dict[int, list[int]] = {}
    for tid, n in chunk_of.items():
        by_chunk.setdefault(n, []).append(tid)
    data = out / "data"
    keep = set()
    written = 0
    for n, tids in sorted(by_chunk.items()):
        tids.sort()
        rows = ",".join(f'"{t}":{body[t]}' for t in tids)
        p = data / "c" / f"{n}.js"
        keep.add(p)
        written += write_if_changed(p, f"{JS_GLOBAL}.chunk({n},{{{rows}}});\n")
        have = [t for t in tids if t in wiki]
        if have:
            rows = ",".join(f'"{t}":{json.dumps(wiki[t], ensure_ascii=False)}' for t in have)
            p = data / "w" / f"{n}.js"
            keep.add(p)
            written += write_if_changed(p, f"{JS_GLOBAL}.wiki({n},{{{rows}}});\n")
    for sub in ("c", "w"):
        for stale in (data / sub).glob("*.js") if (data / sub).exists() else ():
            if stale not in keep:
                stale.unlink()
    write_if_changed(data / "index.js", index_script(chunk_of))
    biggest = max(((p.stat().st_size, p.name) for p in keep), default=(0, ""))
    return {"chunks": len(by_chunk), "chunk_files_written": written,
            "largest_chunk_kb": round(biggest[0] / 1000), "chunk_of": chunk_of}
