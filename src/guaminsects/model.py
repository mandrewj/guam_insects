"""The tree in memory, from the dataset: synonyms to accepted taxa, children, roll-up order.

Taxon ids are held as the internal integers of ids.py (the site's records use them); the
dataset stores the external form. `at(ext)` takes any id a table carries (an accepted taxon's
or a synonym's) to the accepted taxon it is shown as, or None.
"""

from collections import defaultdict

from . import ids
from .dataset import Dataset


class Model:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self.rows: dict[int, dict] = {}
        self.synonym_of: dict[int, int] = {}
        self.syn_rows: dict[int, list[dict]] = defaultdict(list)
        for r in ds["taxa"]:
            if r["status"] == "synonym":
                self.synonym_of[ids.to_int(r["id"])] = ids.to_int(r["accepted_id"])
            else:
                self.rows[ids.to_int(r["id"])] = r
        for r in ds["taxa"]:
            if r["status"] == "synonym":
                a = self.synonym_of[ids.to_int(r["id"])]
                self.syn_rows[a].append(r)
        self.children: dict[int, list[int]] = defaultdict(list)
        for tid, r in self.rows.items():
            if r["parent_id"]:
                p = ids.to_int(r["parent_id"])
                if p in self.rows:
                    self.children[p].append(tid)
        self.roots = [tid for tid, r in self.rows.items() if not r["parent_id"]]
        self.root = self.roots[0] if self.roots else None
        self.order = postorder(self.children, self.roots)      # leaves first

    def at(self, ext: str) -> int | None:
        """The accepted taxon an id in any table stands for."""
        if not ext:
            return None
        t = ids.to_int(ext)
        t = self.synonym_of.get(t, t)
        return t if t in self.rows else None

    def ancestors(self, tid: int) -> list[int]:
        chain, seen = [], {tid}
        pid = self.parent(tid)
        while pid is not None and pid in self.rows and pid not in seen:
            chain.append(pid)
            seen.add(pid)
            pid = self.parent(pid)
        return chain[::-1]

    def parent(self, tid: int) -> int | None:
        p = self.rows[tid]["parent_id"]
        return ids.to_int(p) if p else None


def postorder(children: dict[int, list[int]], roots: list[int]) -> list[int]:
    order, seen, stack = [], set(), [(r, False) for r in roots]
    while stack:
        node, done = stack.pop()
        if done:
            order.append(node)
            continue
        if node in seen:
            continue
        seen.add(node)
        stack.append((node, True))
        stack.extend((c, False) for c in children.get(node, ()))
    return order
