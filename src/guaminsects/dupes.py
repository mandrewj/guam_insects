"""Probable duplicate taxa: a worklist, never an automatic merge.

`guaminsects dupes` reads dataset/ and writes private.nosync/exports/probable-duplicates.csv.
Each row is a pair (or a group) of accepted, visible taxa that are probably one taxon, with
the kind of evidence, a score and what each side has (records, literature, photos, an editor),
so that a person decides which one stays. Merge with the editor's Synonymize tool.

Kinds (strongest first):
  same-name     the same name and rank under two ids (case, accents, spacing ignored)
  same-key      the same GBIF key or iNaturalist taxon on two accepted taxa
  variant       one genus, one rank, epithets a spelling or gender ending apart
  recombination one family, the same epithet (gender ending ignored) and author, two genera
  two-families  a genus (or higher name) filed under two parents
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

EPITHET_END = re.compile(r"(ensis|ense|orum|arum|ii|us|a|um|is|e|i|ae|ata|atus|atum)$")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def distance(a: str, b: str, limit: int = 3) -> int:
    """Edit distance (insert, delete, substitute, swap of neighbours), stopping above `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)
            cur.append(v)
        prev2, prev = prev, cur
        if min(cur) > limit:
            return limit + 1
    return prev[-1]


def surname(authorship: str) -> str:
    """The first author's surname, without parentheses or the year ('(Linnaeus, 1758)' -> 'linnaeus')."""
    a = re.sub(r"[()\[\]]", "", fold(authorship))
    a = re.split(r",|&| and | in | ex ", a)[0].strip()
    return re.sub(r"[^a-z]", "", a.split()[-1]) if a.split() else ""


def find(ds) -> list[dict]:
    taxa = [r for r in ds["taxa"] if r["status"] != "synonym" and not r.get("hidden")]
    by_id = {r["id"]: r for r in ds["taxa"]}
    evidence: dict[str, dict] = defaultdict(lambda: {"records": 0, "literature": 0, "photos": 0})
    for r in ds["records"]:
        evidence[r["taxon_id"]]["records"] += int(r.get("records") or 0)
    for r in ds["literature"]:
        evidence[r["taxon_id"]]["literature"] += 1
    for r in ds["photos"]:
        if r.get("role") == "own":
            evidence[r["taxon_id"]]["photos"] += 1
    inat = defaultdict(set)
    for r in ds["links"]:
        if r["system"] == "inaturalist":
            inat[r["value"]].add(r["taxon_id"])

    def parent_name(r):
        return (by_id.get(r["parent_id"]) or {}).get("name", "")

    def family(r):
        seen = 0
        while r and seen < 12:
            if r["rank"] == "Family":
                return r["name"]
            r, seen = by_id.get(r["parent_id"]), seen + 1
        return ""

    out, seen_pairs = [], set()

    def add(kind, score, a, b, note=""):
        key = tuple(sorted((a["id"], b["id"])))
        if key in seen_pairs or a["id"] == b["id"]:
            return
        seen_pairs.add(key)
        e = lambda r: evidence[r["id"]]          # noqa: E731
        out.append({
            "kind": kind, "score": score,
            "id_a": a["id"], "name_a": a["name"], "authorship_a": a["authorship"], "rank": a["rank"],
            "parent_a": parent_name(a), "id_b": b["id"], "name_b": b["name"],
            "authorship_b": b["authorship"], "parent_b": parent_name(b), "note": note,
            "records_a": e(a)["records"], "records_b": e(b)["records"],
            "literature_a": e(a)["literature"], "literature_b": e(b)["literature"],
            "photos_a": e(a)["photos"], "photos_b": e(b)["photos"],
            "added_by_a": a.get("added_by", ""), "added_by_b": b.get("added_by", ""),
            "verified_a": a.get("verified", ""), "verified_b": b.get("verified", ""),
        })

    # same name and rank
    names = defaultdict(list)
    for r in taxa:
        names[(r["rank"], fold(r["name"]))].append(r)
    for (rank, _), rows in names.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                same_author = surname(a["authorship"]) == surname(b["authorship"])
                add("same-name" if rank in ("Species", "Subspecies") or same_author else "two-families",
                    1.0 if same_author or not (a["authorship"] and b["authorship"]) else 0.9, a, b,
                    "" if same_author else "authorship differs (homonyms?)")

    # the same GBIF key / iNaturalist taxon
    gk = defaultdict(list)
    for r in taxa:
        if r.get("gbif_key"):
            gk[r["gbif_key"]].append(r)
    for rows in gk.values():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                add("same-key", 0.95, a, b, "same GBIF key")
    for v, ids in inat.items():
        rows = [by_id[i] for i in sorted(ids) if i in by_id and by_id[i]["status"] != "synonym" and not by_id[i].get("hidden")]
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["rank"] == b["rank"]:
                    add("same-key", 0.9, a, b, f"same iNaturalist taxon {v}")

    # spelling variants within one genus, and recombinations across genera
    species = [r for r in taxa if r["rank"] == "Species" and len(r["name"].split()) == 2]
    by_genus = defaultdict(list)
    by_fam_ep = defaultdict(list)
    for r in species:
        g, ep = fold(r["name"]).split()
        by_genus[g].append((ep, r))
        by_fam_ep[(family(r), EPITHET_END.sub("", ep))].append((g, r))
    for rows in by_genus.values():
        rows.sort(key=lambda x: x[0])
        for i, (ea, a) in enumerate(rows):
            for eb, b in rows[i + 1:]:
                d = distance(ea, eb)
                if d <= 2 and min(len(ea), len(eb)) >= 5:
                    both = bool(a["authorship"] and b["authorship"])
                    same = surname(a["authorship"]) == surname(b["authorship"])
                    # One author describes sister species with alike epithets (bicolor/discolor), and
                    # two authors can name different species alike (julius/junius): only a
                    # one-letter difference, or a side with no authorship, is a probable variant.
                    if d == 1 or not both:
                        score = 0.85 if (same or not both) else 0.5
                        add("variant", score if d == 1 else 0.6, a, b,
                            f"epithets {ea} / {eb}" + (", same author" if same and both else
                                                       "" if both else ", one has no authorship")
                            + ("" if same or not both else ", different authors: perhaps two species"))
    for (fam, stem), rows in by_fam_ep.items():
        if len(stem) < 4 or not fam:
            continue
        for i, (ga, a) in enumerate(rows):
            for gb, b in rows[i + 1:]:
                if ga != gb and surname(a["authorship"]) == surname(b["authorship"]) and surname(a["authorship"]):
                    moved = a["authorship"].startswith("(") != b["authorship"].startswith("(")
                    add("recombination", 0.9 if moved else 0.75, a, b,
                        f"{ga} / {gb}, same epithet and author, family {fam}"
                        + ("; one author is in parentheses (moved genus)" if moved else ""))

    # higher names filed under two different parents
    return sorted(out, key=lambda r: (-r["score"], r["kind"], r["name_a"]))
