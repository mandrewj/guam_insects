"""Matching names to the Catalogue of Life, against canned GBIF v2 answers (no network)."""

import pytest

from guaminsects import dataset, match

TODAY = "2026-11-20"


def usage(key, name, rank, status="ACCEPTED", auth=""):
    return {"key": key, "name": name, "canonicalName": name, "rank": rank, "status": status,
            "authorship": auth}


CLASSIFICATION = [usage("L2655", "Hexapoda", "SUBPHYLUM"), usage("H6", "Insecta", "CLASS"),
                  usage("C2L", "Coleoptera", "ORDER"), usage("SCARB", "Scarabaeidae", "FAMILY"),
                  usage("ORYCT", "Oryctes", "GENUS")]


def answer(u, mt="EXACT", synonym=False, accepted=None, classification=None):
    return {"usage": u, "synonym": synonym, "acceptedUsage": accepted or {},
            "classification": classification or CLASSIFICATION,
            "diagnostics": {"matchType": mt}}


class FakeCol:
    """Answers by (scientificName, taxonRank); anything else is NONE."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get_cached(self, path, params=None, refresh=False):
        name = params.get("scientificName")
        self.asked.append(name)
        if name in self.answers:
            return self.answers[name]
        return {"usage": {}, "diagnostics": {"matchType": "NONE"}, "classification": []}


def base_ds():
    ds = dataset.Dataset()
    blank = lambda **kw: {c: "" for c in dataset.schema.table("taxa").names} | kw  # noqa: E731
    ds["taxa"] = [
        blank(id="L2655", rank="Subphylum", name="Hexapoda", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="H6", parent_id="L2655", rank="Class", name="Insecta", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="C2L", parent_id="H6", rank="Order", name="Coleoptera", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="SCARB", parent_id="C2L", rank="Family", name="Scarabaeidae", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="ORYCT", parent_id="SCARB", rank="Genus", name="Oryctes", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="ORRHI", parent_id="ORYCT", rank="Species", name="Oryctes rhinoceros", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="gbif:2080570", accepted_id="ORRHI", rank="Species", name="Scarabaeus rhinoceros", status="synonym", in_col="yes"),
    ]
    return ds


def matcher(answers):
    ds = base_ds()
    return ds, match.Matcher(ds, FakeCol(answers), None, by="the tool", today=TODAY)


def test_a_known_key_and_a_name_in_the_dataset_need_no_request():
    ds, m = matcher({})
    assert m.resolve("Oryctes rhinoceros", "SPECIES", "inat") == "ORRHI"
    assert m.resolve("Scarabaeus rhinoceros", "SPECIES", "literature", key="x1") == "ORRHI"   # a merged name
    assert m.resolve("Oryctes rhinoceros", "SPECIES", "inat") == "ORRHI"                      # keys.csv now
    assert m.col.asked == [] and m.stats["same"] == 2 and m.stats["known"] == 1
    assert {(k["source"], k["key"]): k["taxon_id"] for k in ds["keys"]} == {
        ("inat", "Oryctes rhinoceros"): "ORRHI", ("literature", "x1"): "ORRHI"}


def test_a_col_species_the_dataset_lacks_is_added_flagged_new():
    gigas = usage("ORGIG", "Oryctes gigas", "SPECIES", auth="Castelnau, 1840")
    ds, m = matcher({"Oryctes gigas": answer(gigas, classification=CLASSIFICATION)})
    assert m.resolve("Oryctes gigas", "SPECIES", "inat") == "ORGIG"
    row = next(r for r in ds["taxa"] if r["id"] == "ORGIG")
    assert (row["parent_id"], row["rank"], row["in_col"], row["flag"], row["nativity"]) == \
        ("ORYCT", "Species", "yes", "new", "unknown")
    assert row["added_by"] == "the tool" and row["authorship"] == "Castelnau, 1840"
    assert dataset.check(ds).items == []


def test_a_col_synonym_becomes_a_merged_name():
    old = usage("OLDNM", "Dynastes gigas", "SPECIES", status="SYNONYM")
    gigas = usage("ORGIG", "Oryctes gigas", "SPECIES")
    ds, m = matcher({"Dynastes gigas": answer(old, synonym=True, accepted=gigas)})
    assert m.resolve("Dynastes gigas", "SPECIES", "literature") == "ORGIG"
    syn = next(r for r in ds["taxa"] if r["name"] == "Dynastes gigas")
    assert syn["status"] == "synonym" and syn["accepted_id"] == "ORGIG"
    assert syn["name_match"] == "COL synonym" and "synonym of Oryctes gigas" in syn["match_note"]
    assert dataset.check(ds).items == []


def test_a_fuzzy_match_only_within_the_same_genus():
    near_hit = usage("ORGIG", "Oryctes gigas", "SPECIES")
    other = usage("CALIS", "Callirhipis gigas", "SPECIES")
    ds, m = matcher({"Oryctes gygas": answer(near_hit, mt="FUZZY"),
                     "Dynastes gygas": answer(other, mt="FUZZY")})
    assert m.resolve("Oryctes gygas", "SPECIES", "inat") == "ORGIG"
    assert next(r for r in ds["taxa"] if r["name"] == "Oryctes gygas")["name_match"] == "spelling variant"
    assert m.resolve("Dynastes gygas", "SPECIES", "inat") is None       # another genus: held
    assert any(u["name"] == "Dynastes gygas" and "held for review" in u["note"] for u in ds["unplaced"])


def test_a_name_col_lacks_goes_under_its_genus_flagged_new():
    ds, m = matcher({})
    tid = m.resolve("Oryctes marianus", "SPECIES", "inat")
    row = next(r for r in ds["taxa"] if r["id"] == tid)
    assert tid == "name-1" and row["parent_id"] == "ORYCT" and row["in_col"] == "no"
    assert row["flag"] == "new" and row["name_match"] == "not in Catalogue of Life"
    assert m.resolve("Oryctes marianus", "SPECIES", "inat") == "name-1"   # asked once
    assert set(m.col.asked) == {"Oryctes marianus"} and m.stats["asked"] == 1
    assert dataset.check(ds).items == []


def test_literature_names_need_a_genus_and_to_look_like_names():
    ds, m = matcher({})
    assert m.resolve("Oryctes paratypes", "SPECIES", "literature") is None        # not an epithet
    assert m.resolve("Zorotypus guineensis", "SPECIES", "literature") is None      # no genus anywhere
    assert {u["name"] for u in ds["unplaced"]} == {"Oryctes paratypes", "Zorotypus guineensis",
                                                   "Zorotypus"}       # the missing genus is listed too
    assert m.resolve("Oryctes sagittarius", "SPECIES", "literature") not in (None, "")   # genus in the dataset


def test_a_genus_col_lacks_is_unplaced_without_a_family():
    ds, m = matcher({})
    assert m.resolve("Novogenus", "GENUS", "inat") is None
    assert [u["name"] for u in ds["unplaced"]] == ["Novogenus"]


@pytest.mark.parametrize("a,b,expect", [
    ("Gonocephalum adpressiformis", "Gonocephalum adpressiforme", True),
    ("Oryctes rhinoceros", "Oryctes rhinoceras", True),
    ("Oryctes rhinoceros", "Oryctes gigas", False),
    ("Oryctes rhinoceros", "Dynastes rhinoceros", False)])
def test_near(a, b, expect):
    assert match.near(a, b) is expect


def test_excluded_names_are_never_added_again():
    gigas = usage("ORGIG", "Oryctes gigas", "SPECIES")
    ds, m = matcher({"Oryctes gigas": answer(gigas)})
    ds["unplaced"] = [{"name": "Lithoptilus", "rank": "Genus", "source": "editor", "key": "x",
                       "status": "excluded", "note": "extinct fossil taxon"}]
    m.reindex()
    assert m.resolve("Lithoptilus", "GENUS", "inat") is None
    assert m.resolve("Lithoptilus fossilis", "SPECIES", "literature") is None      # its species too
    assert m.col.asked == [] and not any(r["name"].startswith("Lithoptilus") for r in ds["taxa"])
    assert [u["name"] for u in ds["unplaced"]] == ["Lithoptilus"]                   # not listed again
    ds["unplaced"][0]["name"] = "Oryctes gigas"                                     # a COL taxon by key
    m.reindex()
    assert m.ensure_col(answer(gigas)) is None


class FakeGbifBackbone:
    """/species/match by name and /species/<key>, canned."""

    def __init__(self, matches, species=None):
        self.matches, self.species = matches, species or {}

    def get_cached(self, path, params=None, refresh=False):
        if path == "/species/match":
            return self.matches.get(params["name"], {"matchType": "NONE"})
        return self.species[int(path.rsplit("/", 1)[1])]


def bb(name, key, rank="SPECIES", mt="EXACT", status="ACCEPTED", family="Scarabaeidae", **kw):
    return {"matchType": mt, "canonicalName": name, "usageKey": key, "rank": rank,
            "status": status, "classKey": 216, "family": family, **kw}


def test_unplaced_names_are_placed_from_the_backbone_or_wikipedia():
    ds, m = matcher({})
    m.gbif = FakeGbifBackbone({
        "Oryctes rhinoceras": bb("Oryctes rhinoceros", 1, mt="FUZZY"),             # a misspelling
        "Dynastes marianus": bb("Dynastes marianus", 2, status="SYNONYM", acceptedUsageKey=3),
        "Oryctes sagittarius": bb("Oryctes sagittarius", 4),                       # not in COL: genus is here
        "Newgenus fooensis": bb("Newgenus fooensis", 6, family="Scarabaeidae"),    # genus COL lacks, family here
        "Newgenus": bb("Newgenus", 5, rank="GENUS"),
        "Fossilgenus ancientis": bb("Fossilgenus ancientis", 8, family="Megaptilidae"),
        "Fossilgenus": bb("Fossilgenus", 7, rank="GENUS", family="Megaptilidae"),
        "Oryctes sp": {"matchType": "NONE"}},
        {3: {"key": 3, "canonicalName": "Oryctes boas", "rank": "SPECIES"}})
    class Wiki:
        def get_cached(self, path, params=None, refresh=False):
            t = params["titles"]
            if t == "Oryctes nasicornis var":
                return {"query": {"pages": [{"title": "Oryctes rhinoceros", "extract": "Oryctes rhinoceros is a species of beetle"}]}}
            return {"query": {"pages": [{"title": t, "missing": True}]}}
    m.gbif.matches["Oryctes rhinoceros"] = bb("Oryctes rhinoceros", 1)
    row = lambda n: {"name": n}    # noqa: E731
    assert m.place_unplaced(row("Oryctes rhinoceras")) == "merged"
    syn = next(r for r in ds["taxa"] if r["name"] == "Oryctes rhinoceras")
    assert syn["status"] == "synonym" and syn["accepted_id"] == "ORRHI" and syn["name_match"] == "spelling variant"
    assert m.place_unplaced(row("Oryctes sagittarius")) == "placed"
    sag = next(r for r in ds["taxa"] if r["name"] == "Oryctes sagittarius")
    assert sag["parent_id"] == "ORYCT" and sag["flag"] == "new" and sag["gbif_key"] == "4"
    assert m.place_unplaced(row("Newgenus fooensis")) == "placed"
    assert next(r for r in ds["taxa"] if r["name"] == "Newgenus")["parent_id"] == "SCARB"
    assert m.place_unplaced(row("Fossilgenus ancientis")) == "none"               # its family is not in the tree
    assert m.place_unplaced(row("Oryctes nasicornis var"), Wiki()) == "merged"    # a Wikipedia redirect
    assert m.place_unplaced(row("Nothing here")) == "none"
    assert dataset.check(ds).items == []


def test_a_parent_must_rank_above_the_new_taxon():
    other = usage("OTHGN", "Otheria", "GENUS")
    ds, m = matcher({"Newgenus": answer(other, mt="HIGHERRANK")})
    assert m.resolve("Newgenus", "GENUS", "inat") is None          # COL matched a genus: not a parent for a genus
    assert not any(r["name"] == "Newgenus" for r in ds["taxa"])


def test_run_unplaced_survives_the_dataset_being_rewritten(tmp_path):
    """A checkpoint rewrites the row objects; placed rows must still leave the list."""
    ds, m = matcher({})
    m.gbif = FakeGbifBackbone({"Oryctes sagittarius": bb("Oryctes sagittarius", 4),
                               "Oryctes boas": bb("Oryctes boas", 5)})
    ds["unplaced"] = [{"name": n, "rank": "Species", "source": "literature", "key": n, "status": "unplaced",
                       "note": "", "records": ""} for n in ("Oryctes sagittarius", "Nothing here", "Oryctes boas")]
    ds.root = tmp_path
    stats = match.run_unplaced(ds, m, None, progress=lambda *_: None, every=1,
                               checkpoint=lambda d: dataset.write(d, tmp_path))
    assert stats["placed"] == 2 and stats["none"] == 1
    assert [u["name"] for u in ds["unplaced"]] == ["Nothing here"]
    assert ds["unplaced"][0]["note"].startswith(match.Matcher.TRIED)
