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


def evidence_of(ds) -> dict[str, dict]:
    """Per taxon id: how much is recorded (records, literature rows, own photos)."""
    ev: dict[str, dict] = defaultdict(lambda: {"records": 0, "literature": 0, "photos": 0})
    for r in ds["records"]:
        ev[r["taxon_id"]]["records"] += int(r.get("records") or 0)
    for r in ds["literature"]:
        ev[r["taxon_id"]]["literature"] += 1
    for r in ds["photos"]:
        if r.get("role") == "own":
            ev[r["taxon_id"]]["photos"] += 1
    return ev


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


# ---------------------------------------------------------------------------------------
# Evidence from the authorities, and the merge itself

def authority(client, name: str, rank: str) -> dict | None:
    """What the GBIF Backbone (which includes the Catalogue of Life) says of one name: its
    status and, for a synonym, the accepted name. Exact name matches only."""
    d = client.get_cached("/species/match", {"name": name, "rank": rank.upper(), "kingdom": "Animalia"})
    if d.get("matchType") != "EXACT" or fold(d.get("canonicalName")) != fold(name):
        return None
    out = {"status": d.get("status", ""), "key": d.get("usageKey"), "accepted": name}
    if d.get("synonym") or d.get("status") == "SYNONYM":
        key = d.get("acceptedUsageKey")
        if key:
            out["accepted"] = client.get_cached(f"/species/{key}").get("canonicalName") or ""
        else:
            out["accepted"] = ""
    return out


def year(authorship: str) -> str:
    m = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", authorship or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------------------
# Deciding and merging

BY = "guaminsects dupes"
GOOD = {"ACCEPTED"}


def _norm_author(s: str) -> str:
    return re.sub(r"[()\s.]", "", (s or "").lower())


def _moved(a: dict, b: dict) -> bool:
    return a["authorship"].startswith("(") != b["authorship"].startswith("(")


def _gstat(e: dict | None) -> str:
    g = (e or {}).get("gbif")
    if not g:
        return "none"
    return "syn" if "SYNONYM" in g["status"] else g["status"].lower()


def decide(rows: list[dict], by_id: dict, ev: dict, evidence: dict) -> tuple[list[dict], list[dict]]:
    """Split the probable-duplicate pairs into merges (winner, loser, reason, uncertain) and
    pairs kept apart (with the reason). Evidence, in the order the project trusts it: the
    Catalogue of Life (in_col, a COL id), the GBIF Backbone's status and synonym links, and
    iNaturalist's taxonomy; then the original author's parentheses (the later combination is
    the current one), then how much is recorded about each."""

    def link(a, b) -> str:
        """Why these two names are one taxon, or '' (they may be two species)."""
        ea, eb = ev[a["id"]], ev[b["id"]]
        for x, y, e in ((a, b, ea), (b, a, eb)):
            g = e.get("gbif")
            if g and "SYNONYM" in g["status"] and fold(g["accepted"]) == fold(y["name"]):
                return f"GBIF Backbone: {x['name']} is a synonym of {y['name']}"
        if ea.get("inat") and ea.get("inat") == eb.get("inat"):
            return f"both are iNaturalist taxon {ea['inat']}"
        return ""

    def votes(a, b) -> tuple[int, int, list[str]]:
        sa = sb = 0
        why = []
        ea, eb = ev[a["id"]], ev[b["id"]]
        if (a["in_col"] == "yes") != (b["in_col"] == "yes"):
            if a["in_col"] == "yes":
                sa += 1
            else:
                sb += 1
            why.append("Catalogue of Life")
        ga, gb = _gstat(ea), _gstat(eb)
        if ga != gb and "accepted" in (ga, gb):
            if ga == "accepted":
                sa += 1
            else:
                sb += 1
            why.append("GBIF Backbone")
        if bool(ea.get("inat")) != bool(eb.get("inat")):
            if ea.get("inat"):
                sa += 1
            else:
                sb += 1
            why.append("iNaturalist")
        return sa, sb, why

    def pick(a, b, kind) -> tuple[dict, dict, str, bool]:
        sa, sb, why = votes(a, b)
        basis = ", ".join(why)
        if sa != sb:
            w, lo = (a, b) if sa > sb else (b, a)
            return w, lo, basis, False
        pa, pb = a["authorship"].startswith("("), b["authorship"].startswith("(")
        if kind in ("recombination",) and pa != pb:
            w, lo = (a, b) if pa else (b, a)
            return w, lo, "the parenthesised author marks the later combination", True
        ea = evidence[a["id"]]["records"] + 5 * evidence[a["id"]]["literature"] + bool(a["authorship"]) * 3
        eb = evidence[b["id"]]["records"] + 5 * evidence[b["id"]]["literature"] + bool(b["authorship"]) * 3
        w, lo = (a, b) if ea >= eb else (b, a)
        return w, lo, "the better documented name", True

    # a name that pairs with more than one other cannot be settled by pairs
    count: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["kind"] == "recombination":
            count[r["id_a"]] += 1
            count[r["id_b"]] += 1

    merges, kept = [], []
    for r in rows:
        a, b = by_id[r["id_a"]], by_id[r["id_b"]]
        kind = r["kind"]
        why = link(a, b)
        ea, eb = ev[a["id"]], ev[b["id"]]
        if kind == "two-families":
            kept.append({**r, "decision": "kept apart",
                         "reason": "a genus name used twice (homonyms), with different species under each"})
            continue
        if kind == "variant":
            if ea.get("inat") and eb.get("inat") and ea["inat"] != eb["inat"]:
                kept.append({**r, "decision": "kept apart", "reason": "iNaturalist has both as different taxa"})
                continue
            w, lo, basis, unsure = pick(a, b, kind)
            merges.append({"winner": w["id"], "loser": lo["id"], "kind": kind, "uncertain": unsure,
                           "reason": f"spelling variant; {basis}"})
            continue
        if kind in ("same-name", "same-key"):
            w, lo, basis, unsure = pick(a, b, kind)
            merges.append({"winner": w["id"], "loser": lo["id"], "kind": kind, "uncertain": unsure,
                           "reason": f"the same name twice; {basis}"})
            continue
        # recombination: two genera, one epithet
        if why:
            w, lo, basis, unsure = pick(a, b, kind)
            if "synonym of" in why:                      # the Backbone names the accepted one
                loser_name = why.split(": ")[1].split(" is a synonym")[0]
                w, lo = (b, a) if a["name"] == loser_name else (a, b)
                basis = why
                # COL (the project's backbone) accepting the synonym's side outweighs the Backbone
                sa, sb, _ = votes(a, b)
                col_side = a if a["in_col"] == "yes" and b["in_col"] != "yes" else (
                    b if b["in_col"] == "yes" and a["in_col"] != "yes" else None)
                if sa != sb:
                    w, lo = (a, b) if sa > sb else (b, a)
                    basis = f"{why}; resolved by majority of COL, GBIF and iNaturalist"
                elif col_side is not None:               # a tie: the project's backbone is COL
                    w, lo = (col_side, b if col_side is a else a)
                    basis = f"{why}; the Catalogue of Life accepts {w['name']}"
            merges.append({"winner": w["id"], "loser": lo["id"], "kind": kind, "uncertain": False,
                           "reason": basis})
            continue
        same = _norm_author(a["authorship"]) == _norm_author(b["authorship"]) and a["authorship"]
        if (_moved(a, b) and same and year(a["authorship"]) == year(b["authorship"]) != ""
                and count[a["id"]] == 1 and count[b["id"]] == 1):
            w, lo, basis, unsure = pick(a, b, kind)
            merges.append({"winner": w["id"], "loser": lo["id"], "kind": kind, "uncertain": True,
                           "reason": f"same author and year, one in parentheses; {basis}"})
            continue
        kept.append({**r, "decision": "kept apart",
                     "reason": "same epithet in two genera but nothing says they are one species "
                               "(often two species named in one paper)"})
    return merges, kept


def merge(ds, loser_id: str, winner_id: str, reason: str, uncertain: bool, today: str) -> bool:
    """Make `loser` a name of `winner`: its other names, its sub-taxa and every row that points
    at it follow (the build follows accepted_id). The winner keeps what a person set; it takes
    from the loser only what it lacks. An uncertain choice leaves a note on the winner."""
    taxa = {r["id"]: r for r in ds["taxa"]}
    lo, w = taxa.get(loser_id), taxa.get(winner_id)
    if not lo or not w or lo["status"] == "synonym" or w["status"] == "synonym" or lo["rank"] != w["rank"]:
        return False
    empty = ("", "unknown")
    if w["nativity"] in empty and lo["nativity"] not in empty:
        w["nativity"], w["nativity_source"], w["nativity_review"] = (
            lo["nativity"], lo["nativity_source"], lo["nativity_review"])
    if lo["verified"] and not w["verified"] and fold(lo["name"]) == fold(w["name"]):
        for c in ("verified", "verified_by", "verified_date", "verification_source"):
            w[c] = lo[c]
    for c in ("iucn", "gbif_key"):
        if not w[c] and lo[c]:
            w[c] = lo[c]
    names = [x for x in (lo["common_name"], *lo["other_common_names"].split(" | ")) if x]
    if names and not w["common_name"]:
        w["common_name"], names = names[0], names[1:]
    others = [x for x in w["other_common_names"].split(" | ") if x]
    for x in names:
        if x.lower() not in {y.lower() for y in others + [w["common_name"]]}:
            others.append(x)
    w["other_common_names"] = " | ".join(sorted(others))
    lo.update(status="synonym", accepted_id=winner_id, parent_id="", name_match="curated merge",
              match_note=reason[:240], hidden="", hidden_reason="")
    for r in ds["taxa"]:
        if r["id"] != loser_id and r["accepted_id"] == loser_id:
            r["accepted_id"] = winner_id
        elif r["parent_id"] == loser_id and r["status"] != "synonym":
            r["parent_id"] = winner_id
    if uncertain:
        add = f"Merged with {lo['name']}{' ' + lo['authorship'] if lo['authorship'] else ''} ({reason.split(';')[0]})."
        w["note"] = (w["note"] + " " + add).strip() if add not in w["note"] else w["note"]
    if not w["modified_by"] or not (w["modified_by"].lower().startswith(("guaminsects", "refresh", "build"))):
        if not w["modified_by"]:
            w["modified_by"], w["modified"] = BY, today
    return True
