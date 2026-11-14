"""The record each taxon page renders, built from the fixture dataset."""

from conftest import C

from guaminsects import dataset
from guaminsects.build import export, records
from guaminsects.build.records import card_thumb, license_label



def build(world, tmp_path):
    ds = dataset.load(world)
    return ds, records.build_records(ds, thumbs=tmp_path)


def test_presence_counts_col_records_once_and_rolls_up(world, tmp_path):
    _, r = build(world, tmp_path)
    crb = {p["area"]: p for p in r[C("ORRHI")]["presence"]}
    assert crb["GU"]["gbif"] == 90 and crb["GU"]["inat"] == 30
    genus = {p["area"]: p for p in r[C("ORYCT")]["presence"]}
    assert genus["GU"]["gbif"] == 95                  # the genus facet, not 90 + 95
    assert genus["GU"]["species"] == 2 and genus["PW"]["gbif"] == 3
    assert r[C("ORYCT")]["regions"] == ["gu", "pw"] and r[C("ORYCT")]["species_count"] == 3


def test_a_taxon_col_lacks_is_flagged_and_keeps_its_variant(world, tmp_path):
    ds, r = build(world, tmp_path)
    tid = next(t for t, x in r.items() if x["ext"] == "gbif:777")
    assert r[tid]["in_col"] is False and r[tid]["origin"] == "gbif"
    assert [n["kind"] for n in r[tid]["names"]] == ["spelling variant"]


def test_literature_is_machine_read_until_an_editor_confirms(world, tmp_path):
    ds, r = build(world, tmp_path)
    gigas = r[C("ORGIG")]
    assert gigas["literature"][0]["machine_read"] is True and gigas["machine_lit"] == ["GU"]
    assert gigas["presence"][0]["literature"] == 1
    rows = ds["literature"]
    rows[0]["review"] = "editor"
    again = records.build_records(ds, thumbs=tmp_path)[C("ORGIG")]
    assert again["literature"][0]["machine_read"] is False and again["machine_lit"] == []


def test_merged_names_follow_their_taxon(world, tmp_path):
    _, r = build(world, tmp_path)
    assert r[C("CALLI")]["synonyms"] == ["Rhipiceridae"]
    assert r[C("CALLI")]["names"][0]["kind"] == "curated merge"
    fam = {p["area"]: p for p in r[C("CALLI")]["presence"]}
    assert fam["GU"]["gbif"] == 122 and fam["FM"]["gbif"] == 10


def test_nativity_is_on_every_record(world, tmp_path):
    _, r = build(world, tmp_path)
    assert {x["nativity"] for x in r.values()} == {"unknown"}
    assert r[C("ORRHI")]["nativity_source"] is None


def test_export_rows(world, tmp_path):
    ds, r = build(world, tmp_path)
    table = export.rows(ds, r)
    assert table[0]["scientificName"] == "Hexapoda"
    assert len(table) == len(ds["taxa"])
    syn = next(x for x in table if x["scientificName"] == "Scarabaeus rhinoceros")
    assert syn["acceptedNameUsage"] == "Oryctes rhinoceros" and syn["taxonomicStatus"] == "synonym"
    assert export.to_csv(table).splitlines()[0].startswith("taxonID,parentNameUsageID")


def test_helpers():
    assert license_label("cc-by-nc-sa") == "CC BY-NC-SA" and license_label("cc0") == "CC0"
    portrait = {"thumb": "p", "w": 600, "h": 900, "of_id": None}
    landscape = {"thumb": "l", "w": 900, "h": 600, "of_id": None}
    borrowed = {"thumb": "b", "w": 900, "h": 600, "of_id": 5}
    assert card_thumb([portrait, landscape]) == "l"
    assert card_thumb([portrait, borrowed]) == "p"     # never swap own for borrowed
