"""The displayed tree, derived by `resolve` from the Catalogue of Life, the name matches and
curation/*.csv. Writes `taxa`, `taxon_keys` (any source key -> the taxon it is shown as) and
`taxon_names` (other names shown with a taxon: the synonym rows of taxonomy.csv).

What is in the tree:
  - COL taxa with records of their own (GBIF records under COL keys, or a source name that
    matched them), and their ancestors at the main ranks: class, order, family, genus,
    species, subspecies. Ranks in between (suborder, superfamily, subfamily, tribe, ...)
    are kept in `extra` for taxonomy.csv but skipped in the displayed tree.
  - Names COL does not have, from any record (GBIF Backbone, iNaturalist, literature),
    under the parent their match found, flagged in_col = 0 with a note.
  - Curated taxa (IOG-n) and every override in curation/taxa.csv.

Source names that match the same taxon are shown as one: a COL synonym, a spelling variant,
a duplicate GBIF Backbone entry. A name COL lacks that sits next to a sibling one spelling
apart (or with another gender ending) is merged into it, with a note. A curator can undo any
merge (status accepted, with a parent) or make one (status synonym, with accepted_id).
"""

import json
from collections import defaultdict

from . import db, ids, names
from .enrich.col import MAIN_RANKS

TITLE = {**MAIN_RANKS, "VARIETY": "Variety", "FORM": "Form"}
HIGHER = {"Subphylum", "Class", "Order", "Family"}
EXTRA_RANKS = {"SUBORDER": "suborder", "SUPERFAMILY": "superfamily",
               "SUBFAMILY": "subfamily", "TRIBE": "tribe", "SUBGENUS": "subgenus"}
INT_FIELDS = ("parent_id", "accepted_id", "hidden", "verified")
SOURCE_LABELS = {"gbif": "GBIF", "gbif_backbone": "GBIF Backbone", "inat": "iNaturalist",
                 "plazi": "Plazi", "pdf": "literature", "checklist": "crop pest list"}


def _accepted(status: str | None) -> bool:
    s = (status or "accepted").lower()
    return s.startswith("accepted") or s.startswith("provisionally")


def build(conn, cur) -> dict[str, int]:
    from .curation import OVERRIDE_FIELDS, CurationError

    col = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM col_taxa")}
    matches = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM name_matches")}
    backbone = {r["gbif_key"]: dict(r) for r in conn.execute(
        "SELECT gbif_key, canonical_name, authorship, vernacular_name FROM gbif_taxa")}
    curated = {ids.to_int(r["taxon_id"]): r for r in cur.rows if r["taxon_id"]}
    evidence_ids = {ids.to_int(e["taxon_id"]) for e in cur.evidence}
    presence: dict[int, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT DISTINCT taxon_id, source FROM taxon_presence"):
        presence[r[0]].add(r[1])
    errors: list[str] = []
    stats = {"col": 0, "not_in_col": 0, "curated": 0, "merged_names": 0, "spelling_merges": 0,
             "unplaced": 0, "unmatched_keys": 0}

    def col_accepted(t: int) -> int:
        seen = set()
        while t in col and not _accepted(col[t]["status"]) and col[t]["accepted_id"] \
                and t not in seen:
            seen.add(t)
            t = col[t]["accepted_id"]
        return t

    # Curated merges (status synonym + accepted_id) and splits (a merged name made its own).
    merge: dict[int, int] = {}
    split: set[int] = set()
    for tid, r in curated.items():
        if r["status"] == "synonym" and r["accepted_id"]:
            merge[tid] = ids.to_int(r["accepted_id"])
        elif r["status"] in ("accepted", "doubtful", "morphospecies") and \
                ids.kind(tid) in ("gbif", "name"):
            split.add(tid)

    def base(k: int) -> int | None:
        kind = ids.kind(k)
        if kind == "col":
            return col_accepted(k) if k in col else None
        if kind in ("gbif", "name"):
            if k in split:
                return k
            m = matches.get(k)
            if not m:
                return None
            return col_accepted(m["taxon"]) if m["taxon"] else k
        return k

    def target(k: int, depth: int = 0) -> int | None:
        t = base(k)
        if t is not None and t in merge and depth < 20:
            return target(merge[t], depth + 1)
        return t

    # ---------------------------------------------------------------- what is wanted
    def rank_of(t: int) -> str | None:
        if ids.kind(t) == "col":
            return TITLE.get(col[t]["rank"]) if t in col else None
        if t in curated and curated[t]["rank"]:
            return curated[t]["rank"]
        m = matches.get(t)
        return TITLE.get(m["rank"]) if m else None

    wanted: set[int] = set()
    for k, srcs in presence.items():
        t = target(k)
        if t is None:
            stats["unmatched_keys"] += 1
            continue
        # COL taxa need records under COL itself (or another source than the Backbone):
        # the Backbone's own classification is what this replaces. Above genus, only GBIF
        # records count (a family named in a list is not a record of the family).
        own = srcs - {"gbif_backbone"} if ids.kind(t) == "col" else srcs
        if rank_of(t) in HIGHER:
            own &= {"gbif", "gbif_backbone"} if ids.kind(t) != "col" else {"gbif"}
        if own:
            wanted.add(t)
    for tid in set(curated) | evidence_ids:
        if tid not in merge:
            t = target(tid)
            if t is not None:
                wanted.add(t)
    for tid in curated:                      # curated new taxa
        if ids.kind(tid) == "curated" and tid not in merge:
            wanted.add(tid)

    # ---------------------------------------------------------------- placing them
    nodes: dict[int, dict] = {}

    def node(tid, rank, name, authorship, parent, origin, in_col, note=None, extra=None):
        nodes[tid] = {"taxon_id": tid, "ext_id": ids.to_ext(tid), "parent_id": parent,
                      "rank": rank, "name": name, "authorship": authorship,
                      "status": "accepted", "accepted_id": None, "origin": origin,
                      "in_col": in_col, "match_note": note, "extra": extra or {},
                      "gbif_key": tid if ids.kind(tid) == "gbif" else None,
                      "common_name": None, "establishment": None, "hidden": 0,
                      "hidden_reason": None, "note": None, "verified": 0,
                      "curated_fields": None}

    def add_col(t: int) -> int | None:
        """Add a COL taxon and its main-rank ancestors; returns the displayed node (the
        nearest main-rank taxon at or above t)."""
        chain, x = [], t
        while x is not None and x in col:
            chain.append(x)
            x = col[x]["parent_id"]
        if not chain or col[chain[-1]]["rank"] != "SUBPHYLUM":
            return None                   # not under Hexapoda
        shown = None
        extra: dict[str, str] = {}
        for x in reversed(chain):         # root first
            c = col[x]
            if c["rank"] in EXTRA_RANKS:
                extra[EXTRA_RANKS[c["rank"]]] = c["name"]
                continue
            if c["rank"] not in TITLE:
                continue
            if x not in nodes:
                node(x, TITLE[c["rank"]], c["name"], c["authorship"], shown, "col", 1,
                     extra=dict(extra))
            shown = x
        return shown

    unplaced: list[int] = []

    def place(t: int, depth: int = 0) -> int | None:
        if t in nodes:
            return t
        if depth > 30:
            return None
        kind = ids.kind(t)
        if kind == "col":
            return add_col(t)
        r = curated.get(t)
        if kind == "curated":
            if not r:
                return None
            node(t, r["rank"], r["name"], r["authorship"] or None, None, "curated", 0)
            return t                     # parent set from the curated row below
        m = matches.get(t)
        if not m or not TITLE.get(m["rank"]):
            unplaced.append(t)
            return None
        pk = ids.to_int(r["parent_id"]) if r and r["parent_id"] else m["parent"]
        pt = target(pk) if pk else None
        parent = place(pt, depth + 1) if pt is not None else None
        if parent is None and not (r and r["parent_name"]):
            unplaced.append(t)
            return None
        bb = backbone.get(t, {})
        node(t, TITLE[m["rank"]], m["name"], m["authorship"], parent, ids.kind(t), 0,
             note=m["note"], extra=dict(nodes[parent]["extra"]) if parent in nodes else {})
        nodes[t]["common_name"] = bb.get("vernacular_name")
        return t

    for t in sorted(wanted):
        place(t)
    if (root := add_col(ids.from_col("L2655"))) is None:
        errors.append("the Catalogue of Life's Hexapoda (L2655) is not in col_taxa; "
                      "run `guaminsects col`")

    # Siblings COL lacks that are the same name, or one spelling apart, as another sibling
    # are one taxon: the first (a COL taxon if there is one) keeps the place.
    auto: dict[int, tuple[int, str]] = {}
    by_parent: dict[tuple, list[int]] = defaultdict(list)
    for tid, n in nodes.items():
        by_parent[(n["parent_id"], n["rank"])].append(tid)
    for group in by_parent.values():
        group.sort(key=lambda x: (nodes[x]["in_col"] == 0, ids.kind(x) != "gbif", x))
        for i, a in enumerate(group):
            if nodes[a]["in_col"] or a in auto or a in curated:
                continue
            for b in group[:i]:
                if b in auto:
                    continue
                na, nb = nodes[a]["name"], nodes[b]["name"]
                if na == nb:
                    auto[a] = (b, "same name")
                elif names.near(na, nb):
                    auto[a] = (b, f"matched by spelling: {na} → {nb}")
                if a in auto:
                    break
    for a, (b, _) in auto.items():
        for n in nodes.values():
            if n["parent_id"] == a:
                n["parent_id"] = b
    stats["spelling_merges"] = sum(why != "same name" for _, why in auto.values())

    def shown(k: int) -> int | None:
        """The displayed taxon a key belongs to. A COL taxon at an intermediate rank (a
        subfamily) climbs to its nearest displayed ancestor; one at a main rank that is not
        in the tree has none (its records are not Micronesian)."""
        t = target(k)
        while t in auto:
            t = auto[t][0]
        if t is not None and t not in nodes and ids.kind(t) == "col" and t in col:
            x = t
            while x in col and col[x]["rank"] not in TITLE:
                x = col[x]["parent_id"]
            t = x if x != t else None
        return t if t in nodes else None

    for a in auto:
        del nodes[a]

    # ---------------------------------------------------------------- curated overrides
    by_name: dict[str, list[int]] = defaultdict(list)
    for tid, n in nodes.items():
        by_name[n["name"]].append(tid)
    for tid, r in curated.items():
        if tid in merge:
            if shown(merge[tid]) is None:
                errors.append(f"taxa.csv: {r['taxon_id']} is merged into {r['accepted_id']}, "
                              "which is not in the tree")
            continue
        t = tid if tid in nodes else shown(tid)
        if t is None or t not in nodes:
            errors.append(f"taxa.csv: {r['taxon_id']} ({r['name'] or 'no name'}) is not in the "
                          "tree; check the id, or run `guaminsects match`")
            continue
        n, changed = nodes[t], []
        for f in OVERRIDE_FIELDS:
            v = r[f]
            if v == "" or f == "accepted_id":
                continue
            if f in INT_FIELDS:
                v = ids.to_int(v) if f == "parent_id" else int(v)
                if f == "parent_id":
                    v = shown(v) if shown(v) is not None else v
            n[f] = v
            changed.append(f)
        if r["parent_name"] and not r["parent_id"]:
            hits = by_name.get(r["parent_name"], [])
            if len(hits) != 1:
                errors.append(f"taxa.csv: parent_name {r['parent_name']!r} for {n['name']} matches "
                              f"{len(hits)} taxa; give parent_id instead")
            else:
                n["parent_id"] = hits[0]
                changed.append("parent_id")
        if n["hidden"]:
            n["hidden_reason"] = r["reason"] or "curated"
        n["curated_fields"] = ",".join(changed) or None
        if n["status"] not in ("accepted", "doubtful", "morphospecies"):
            n["status"] = "accepted"

    for n in nodes.values():
        p = n["parent_id"]
        if p is not None and p not in nodes:
            errors.append(f"{n['name']} ({n['ext_id']}): parent {ids.to_ext(p)} is not in the tree")
    roots = [n for n in nodes.values() if n["parent_id"] is None]
    if len(roots) > 1:
        errors.append("more than one root: " + ", ".join(f"{n['name']} ({n['ext_id']})"
                                                         for n in roots[:10]))
    lineage = db.lineages({tid: n["parent_id"] for tid, n in nodes.items()})
    reported: set[int] = set()
    for tid in nodes:
        top = int(lineage[tid].strip("/").split("/")[0])
        if nodes[top]["parent_id"] is None or nodes[top]["parent_id"] not in nodes or \
                top in reported:
            continue
        path, x = [], top
        while x not in path:
            path.append(x)
            x = nodes[x]["parent_id"]
        loop = path[path.index(x):]
        if not reported & set(loop):
            errors.append("these would sit under their own descendants (a cycle): " +
                          " > ".join(f"{nodes[y]['name']} ({nodes[y]['ext_id']})" for y in loop))
        reported |= set(path)
    for e in cur.evidence:
        if shown(ids.to_int(e["taxon_id"])) is None:
            errors.append(f"evidence.csv: taxon_id {e['taxon_id']} is not in the tree")
    if errors:
        raise CurationError("\n".join(errors))

    hidden_ids = {tid for tid, n in nodes.items() if n["hidden"]}
    for tid, n in nodes.items():
        if not n["hidden"] and any(f"/{h}/" in lineage[tid] for h in hidden_ids):
            n["hidden"], n["hidden_reason"] = 1, "under a hidden taxon"

    # ---------------------------------------------------------------- keys and names
    all_keys = set(presence) | set(matches) | set(nodes) | set(curated) | evidence_ids
    for table, column in names.KEYED:
        all_keys |= {r[0] for r in conn.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL")}
    key_rows, name_rows = [], []
    used_by: dict[int, set[str]] = defaultdict(set)
    for k, srcs in presence.items():
        used_by[k] |= {SOURCE_LABELS.get(s, s) for s in srcs}
    for k in all_keys:
        t = shown(k)
        if t is None:
            continue
        how = "self" if t == k else (
            "curated merge" if k in merge or base(k) in merge else
            auto[k][1] if k in auto else (matches.get(k) or {}).get("kind") or ids.kind(k))
        key_rows.append((k, t, how))
        if t == k or (ids.kind(k) == "col" and k not in merge):
            continue
        m = matches.get(k) or {}
        if ids.kind(k) == "col":            # a COL taxon merged into another by hand
            m = {"name": col[k]["name"], "authorship": col[k]["authorship"],
                 "rank": col[k]["rank"]} if k in col else {}
        nm = m.get("name") or (curated.get(k) or {}).get("name") or ""
        auth = m.get("authorship") or None
        target_node = nodes[t]
        differs = nm and nm != target_node["name"]
        other_author = ids.kind(k) == "gbif" and auth and target_node["authorship"] and \
            auth != target_node["authorship"]
        if not (differs or other_author or k in merge or k in auto):
            continue
        kind = ("curated merge" if k in merge else "spelling variant" if k in auto and
                auto[k][1] != "same name" else m.get("kind") or "same name")
        if kind == "same" or (kind == "same name" and not differs):
            kind = "same name, other author" if other_author else "same name"
        note = (curated[k]["reason"] if k in merge and curated[k]["reason"] else
                auto[k][1] if k in auto else m.get("note"))
        name_rows.append((k, t, nm, auth, TITLE.get(m.get("rank") or ""), kind,
                          note, ", ".join(sorted(used_by.get(k, ())))))
    stats["merged_names"] = len(name_rows)
    # A COL taxon's GBIF Backbone key (same name), for links keyed on it (BugGuide, Wikidata).
    for k, t, _how in key_rows:
        if ids.kind(k) == "gbif" and nodes[t]["gbif_key"] is None and \
                backbone.get(k, {}).get("canonical_name") == nodes[t]["name"]:
            nodes[t]["gbif_key"] = k
            if not nodes[t]["common_name"]:
                nodes[t]["common_name"] = backbone[k]["vernacular_name"]
    stats["unplaced"] = len(set(unplaced))
    stats["col"] = sum(n["in_col"] == 1 for n in nodes.values())
    stats["not_in_col"] = sum(n["in_col"] == 0 and n["origin"] != "curated" for n in nodes.values())
    stats["curated"] = sum(n["origin"] == "curated" for n in nodes.values())

    cols = ["taxon_id", "gbif_key", "parent_id", "rank", "name", "authorship", "status",
            "accepted_id", "origin", "common_name", "establishment", "hidden", "hidden_reason",
            "note", "verified", "curated_fields", "ext_id", "in_col", "match_note", "extra"]
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM taxa")
        conn.executemany(
            f"INSERT INTO taxa ({', '.join(cols)}, lineage, depth, resolved_at) "
            f"VALUES ({', '.join('?' for _ in cols)}, ?, ?, ?)",
            [[*(json.dumps(n[c], sort_keys=True) if c == "extra" else n[c] for c in cols),
              lineage[tid], lineage[tid].count("/") - 2, stamp] for tid, n in nodes.items()])
        conn.execute("DELETE FROM taxon_keys")
        conn.executemany("INSERT INTO taxon_keys (key, taxon_id, how) VALUES (?, ?, ?)", key_rows)
        conn.execute("DELETE FROM taxon_names")
        conn.executemany(
            "INSERT INTO taxon_names (name_id, taxon_id, name, authorship, rank, kind, note, "
            "sources) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", name_rows)
        conn.execute("DELETE FROM taxon_evidence")
        conn.executemany(
            "INSERT OR REPLACE INTO taxon_evidence (taxon_id, kind, ref, license, credit, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(shown(ids.to_int(e["taxon_id"])), e["kind"], e["ref"], e["license"] or None,
              e["credit"] or None, e["note"] or None) for e in cur.evidence])
    stats["taxa"] = len(nodes)
    stats["hidden"] = sum(n["hidden"] for n in nodes.values())
    stats["root"] = ids.to_ext(root) if root else None
    return stats
