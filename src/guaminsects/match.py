"""Put every name a source used on the Catalogue of Life, and add what COL lacks.

`Matcher.resolve` takes a name (a GBIF Backbone key, an iNaturalist name, a literature
heading, ...) and returns the taxon it is shown as, in this order:

1. keys.csv: this source key was matched before;
2. the dataset: a taxon (or a merged name) with this name and rank is already there;
3. the Catalogue of Life (GBIF's v2 match, with the source's class and order as hints): the
   same name, a COL synonym, a spelling variant, or a near spelling within the same genus;
4. a name COL lacks goes under its genus (added if needed), flagged `new`
   ("not in the Catalogue of Life"); literature names only inside a genus COL or the
   dataset has, and only if they look like names;
5. what cannot be placed goes to review/unplaced.csv for a person.

Every row a match adds is a taxa.csv row flagged `new` with nativity `unknown` and `added_by`
the tool, so the editor's worklist shows them (docs/REFACTOR.md decision 6). The functions
here change the in-memory dataset; the caller writes it.
"""

import re

from . import ids, schema
from .sources import col as colapi
from .sources import gbif as gbifapi

SPECIES_GROUP = {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}
RANK_TITLE = {"SUBPHYLUM": "Subphylum", "CLASS": "Class", "ORDER": "Order", "FAMILY": "Family",
              "GENUS": "Genus", "SPECIES": "Species", "SUBSPECIES": "Subspecies",
              "VARIETY": "Variety"}
ENDINGS = re.compile(r"(us|a|um|is|e|ii|i|ae|es)$")


def _words():
    # Words that end up in heading-shaped lines of the literature without being epithets.
    from .literature import GERMAN_ENGLISH, LATIN_STOP

    return LATIN_STOP | GERMAN_ENGLISH | {
        "paratypes", "holotypes", "types", "dermatitis", "species", "group", "complex", "larvae",
        "nymphs", "adults", "records", "notes", "remarks", "distribution", "material", "examined",
        "key", "keys", "figures", "plates", "table", "tables", "described", "unknown",
        "undescribed", "spec", "indet", "sensu", "lato", "stricto", "auct", "nec", "non",
        "partim"}


def plausible(name: str, rank: str) -> bool:
    """A literature heading that looks like a real binomial (or trinomial)."""
    words = name.split()
    want = {"SPECIES": 2, "SUBSPECIES": 3}.get(rank.upper())
    if want and len(words) != want:
        return False
    stop = _words()
    return all(re.fullmatch(r"[a-z]{3,}(-[a-z]+)?", w) and w not in stop for w in words[1:])


def stem(epithet: str) -> str:
    """Latin epithet without its gender or genitive ending: 'marginatus' -> 'marginat'."""
    return ENDINGS.sub("", epithet.lower())


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near(a: str, b: str) -> bool:
    """Two names of the same rank under the same parent that are one spelling apart, or
    differ only in a gender ending ('Gonocephalum adpressiformis' / '-forme')."""
    wa, wb = a.lower().split(), b.lower().split()
    if len(wa) != len(wb) or wa[:-1] != wb[:-1] or a == b:
        return False
    x, y = wa[-1], wb[-1]
    if stem(x) == stem(y) and min(len(stem(x)), len(stem(y))) >= 4:
        return True
    return len(x) >= 6 and _distance(x, y) <= 1


def _genus(name: str) -> str:
    return name.split()[0] if name else ""


class Matcher:
    def __init__(self, ds, col_client, gbif_client=None, by: str = "match", today: str = ""):
        self.ds, self.col, self.gbif, self.by, self.today = ds, col_client, gbif_client, by, today
        self.stats = {"asked": 0, "same": 0, "col": 0, "new_taxa": 0, "not_in_col": 0,
                      "unplaced": 0, "known": 0}
        self.reindex()

    # --- indexes over the dataset ---------------------------------------------------------
    def reindex(self) -> None:
        self.taxa = {r["id"]: r for r in self.ds["taxa"] if r["status"] != "synonym"}
        self.by_name: dict[tuple[str, str], list[str]] = {}
        self.syn: dict[tuple[str, str], list[str]] = {}
        for r in self.ds["taxa"]:
            idx = self.by_name if r["status"] != "synonym" else self.syn
            target = r["id"] if r["status"] != "synonym" else r["accepted_id"]
            idx.setdefault((r["name"], r["rank"].upper()), []).append(target)
        self.keys = {(k["source"], k["key"]): k["taxon_id"] for k in self.ds["keys"]}
        self.unplaced = {(u["name"], u["source"], u["key"]) for u in self.ds["unplaced"]}
        self.excluded = {u["name"] for u in self.ds["unplaced"] if u["status"] == "excluded"}

    def is_excluded(self, name: str) -> bool:
        """A name an editor excluded, or a species/subspecies of an excluded genus."""
        words = (name or "").split()
        return name in self.excluded or (len(words) > 1 and words[0] in self.excluded)

    def in_dataset(self, name: str, rank: str) -> str | None:
        rank = rank.upper()
        for idx in (self.by_name, self.syn):
            hits = list(dict.fromkeys(idx.get((name, rank), [])))
            if len(hits) == 1:
                return hits[0]
        return None

    # --- adding rows ----------------------------------------------------------------------
    def new_row(self, **kw) -> dict:
        row = {c: "" for c in schema.table("taxa").names}
        row.update(status="accepted", nativity="unknown", added_by=self.by, added=self.today,
                   flag="new")
        row.update(kw)
        return row

    def next_name_id(self) -> str:
        used = [int(r["id"][5:]) for r in self.ds["taxa"] if re.fullmatch(r"name-\d+", r["id"])]
        used += [int(k["taxon_id"][5:]) for k in self.ds["keys"]
                 if re.fullmatch(r"name-\d+", k["taxon_id"])]
        return f"name-{max(used, default=0) + 1}"

    def alloc(self, source: str, key: str) -> str:
        if source == "gbif" and key.isdigit() and f"gbif:{key}" not in {r["id"] for r in self.ds["taxa"]}:
            return f"gbif:{key}"
        return self.next_name_id()

    def add_key(self, source: str, key: str, name: str, taxon: str, how: str = "") -> None:
        if (source, key) in self.keys:
            return
        self.keys[(source, key)] = taxon
        self.ds["keys"].append({"source": source, "key": key, "name": name, "taxon_id": taxon,
                                "how": how})

    def add_taxon(self, row: dict) -> str:
        self.ds["taxa"].append(row)
        if row["status"] == "synonym":
            self.syn.setdefault((row["name"], row["rank"].upper()), []).append(row["accepted_id"])
        else:
            self.taxa[row["id"]] = row
            self.by_name.setdefault((row["name"], row["rank"].upper()), []).append(row["id"])
            self.stats["new_taxa"] += 1
        return row["id"]

    def add_unplaced(self, name: str, rank: str, source: str, key: str, note: str) -> None:
        if (name, source, key) in self.unplaced:
            return
        if self.is_excluded(name):
            return
        self.unplaced.add((name, source, key))
        src = source if source in schema.UNPLACED_SOURCES else "other"
        self.ds["unplaced"].append({"name": name, "rank": rank.title(), "source": src,
                                    "key": key, "records": "", "note": note,
                                    "status": "unplaced", "added_by": self.by, "added": self.today})
        self.stats["unplaced"] += 1

    def ensure_col(self, d: dict) -> str | None:
        """Make sure the COL taxon an answer points at (and its ancestors) is in the
        dataset; returns its id."""
        usage = d.get("usage") or {}
        acc = d.get("acceptedUsage") or {}
        target = acc if d.get("synonym") and acc else usage
        if not target.get("key") or not ids.valid(target["key"]):
            return None
        if self.is_excluded(target.get("canonicalName") or target.get("name") or ""):
            return None
        if target["key"] in self.taxa:
            return target["key"]
        parent_id = ""
        for row in colapi.chain(d, target):
            if row["id"] not in self.taxa:
                self.add_taxon(self.new_row(
                    id=row["id"], parent_id=parent_id or row["parent_id"], rank=row["rank"],
                    name=row["name"], authorship=row["authorship"], in_col="yes",
                    name_match="Catalogue of Life", superfamily=row.get("superfamily", ""),
                    subfamily=row.get("subfamily", ""), tribe=row.get("tribe", "")))
            parent_id = row["id"]
        t = colapi.usage_row(target)
        if not t["rank"]:
            return None
        extras = colapi.classification_extras(d)
        self.add_taxon(self.new_row(
            id=t["id"], parent_id=parent_id, rank=t["rank"], name=t["name"],
            authorship=t["authorship"], in_col="yes", name_match="Catalogue of Life",
            status="doubtful" if t["status"] == "doubtful" else "accepted", **extras))
        return t["id"]

    # --- matching ---------------------------------------------------------------------------
    def hints(self, source: str, key: str, name: str) -> dict:
        """The source's class and order (a family placement is what goes out of date)."""
        hints = {}
        if source == "gbif" and key.isdigit() and self.gbif:
            try:
                t = gbifapi.species(self.gbif, key)
            except Exception:
                return hints
            for rank in ("class", "order"):
                if t.get(rank):
                    hints[rank] = t[rank]
        return hints

    def match_one(self, name: str, rank: str, authorship: str | None, hints: dict) -> dict:
        """COL's answer, as an insect if the plain answer is not a hexapod or stops high."""
        h = {"phylum": "Arthropoda"} | {k: v for k, v in hints.items() if k in ("class", "order")}
        d = colapi.match(self.col, name, rank, authorship, hints=h, force_hints=True)
        usage = d.get("usage") or {}
        weak = not colapi.is_hexapod(d) or usage.get("rank") in ("SUBPHYLUM", "PHYLUM",
                                                                 "KINGDOM", "CLASS")
        if weak and "class" not in hints:
            d2 = colapi.match(self.col, name, rank, authorship, hints=h | {"class": "Insecta"},
                              force_hints=True)
            if colapi.is_hexapod(d2) and colapi.match_type(d2) != "NONE":
                return d2
        return d

    def resolve(self, name: str, rank: str, source: str, key: str | None = None,
                authorship: str | None = None, origin: str | None = None) -> str | None:
        """The taxon this source name is shown as, or None (then it is on the unplaced list)."""
        rank, key = rank.upper(), key if key is not None else name
        origin = origin or source
        if self.is_excluded(name):
            self.stats["excluded"] = self.stats.get("excluded", 0) + 1
            return None
        if (source, key) in self.keys:
            self.stats["known"] += 1
            return self.keys[(source, key)]
        hit = self.in_dataset(name, rank)
        if hit:
            self.add_key(source, key, name, hit, "same")
            self.stats["same"] += 1
            return hit
        self.stats["asked"] += 1
        d = self.match_one(name, rank, authorship, self.hints(source, key, name))
        mt = colapi.match_type(d)
        usage = d.get("usage") or {}
        acc = d.get("acceptedUsage") or {}
        target = acc if d.get("synonym") and acc else usage
        hexapod = colapi.is_hexapod(d)
        same_rank = (usage.get("rank") or "").upper() == rank or (
            (usage.get("rank") or "").upper() in SPECIES_GROUP and rank in SPECIES_GROUP)
        note = None
        if mt in ("EXACT", "VARIANT", "FUZZY") and hexapod and same_rank and target.get("key"):
            fuzzy_ok = mt != "FUZZY" or (rank in SPECIES_GROUP and
                                         _genus(usage.get("canonicalName") or "") == _genus(name))
            if fuzzy_ok:
                tid = self.ensure_col(d)
                if tid:
                    accepted = target.get("canonicalName") or target.get("name")
                    exact = mt == "EXACT" and not d.get("synonym")
                    if exact and self.taxa[tid]["name"] == name:
                        self.add_key(source, key, name, tid, "same")
                    else:
                        kind = "COL synonym" if d.get("synonym") else "spelling variant"
                        why = (f"Catalogue of Life: a synonym of {accepted}" if d.get("synonym")
                               else f"spelling variant of {accepted} (Catalogue of Life)"
                               if mt == "VARIANT" else f"matched by spelling: {name} → {accepted}")
                        self.add_taxon(self.new_row(
                            id=self.alloc(source, key), accepted_id=tid, rank=self.taxa[tid]["rank"],
                            name=name, authorship=authorship or "", status="synonym",
                            in_col="yes" if d.get("synonym") else "no", name_match=kind,
                            match_note=why, flag=""))
                        self.add_key(source, key, name, tid, kind)
                    self.stats["col"] += 1
                    return tid
            else:
                note = f"possibly {usage.get('canonicalName')} (spelling); held for review"
        # COL does not have it: under its genus (a species), species (a subspecies), else the
        # nearest taxon above it that COL matched.
        above = usage if mt == "HIGHERRANK" and hexapod and usage.get("key") else None
        parent = None
        if rank == "SPECIES" and len(name.split()) >= 2:
            parent = self.parent_for(_genus(name), "GENUS", source, origin, above, d)
        elif rank == "SUBSPECIES" and len(name.split()) >= 3:
            parent = self.parent_for(" ".join(name.split()[:2]), "SPECIES", source, origin, above, d)
        elif above and above.get("key") and ids.valid(above["key"]):
            parent = self.ensure_col({"usage": above, "classification": d.get("classification"),
                                      "diagnostics": d.get("diagnostics")})
        if origin == "literature" and (parent is None or not plausible(name, rank)):
            self.add_unplaced(name, rank, source, key,
                              (note or "Not in the Catalogue of Life; its genus is not either")
                              + "; literature name held for review")
            return None
        if parent is None:
            self.add_unplaced(name, rank, source, key, note or "no parent could be found")
            return None
        gkey = None
        if self.gbif and rank in ("SPECIES", "SUBSPECIES", "GENUS"):
            m = gbifapi.backbone_match(self.gbif, name, rank)
            gkey = m.get("usageKey") if m else None
        tid = self.alloc("gbif" if gkey and str(gkey) == key else source, key)
        self.add_taxon(self.new_row(
            id=tid, parent_id=parent, rank=RANK_TITLE.get(rank, rank.title()), name=name,
            authorship=authorship or "", in_col="no", gbif_key=str(gkey or ""),
            name_match="not in Catalogue of Life",
            match_note=note or "Not in the Catalogue of Life"))
        self.add_key(source, key, name, tid, "not in COL")
        self.stats["not_in_col"] += 1
        return tid

    def parent_for(self, name: str, rank: str, source: str, origin: str,
                   above: dict | None, answer: dict) -> str | None:
        """The genus (or species) a name COL lacks goes under: the dataset's, COL's, or the
        one a literature heading names only if COL or the dataset already has it."""
        hit = self.in_dataset(name, rank)
        if hit:
            return hit
        if above and (above.get("rank") or "").upper() == rank and ids.valid(above.get("key", "")):
            return self.ensure_col({"usage": above, "classification": answer.get("classification"),
                                    "diagnostics": answer.get("diagnostics")})
        return self.resolve(name, rank, source, key=name, origin=origin)
