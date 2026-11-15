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


def test_checklist_nodes_flag_what_is_recorded_from_guam(world, tmp_path):
    """The header's "Guam only" filter reads a trailing 1 on a checklist node and the children's
    gu_species count; a group's count is the species under it recorded from Guam."""
    _, r = build(world, tmp_path)
    genus = r[C("ORYCT")]
    assert genus["gu_species"] == 2
    flagged = [n for n in genus["checklist"] if len(n) > 4 and n[4] == 1]
    assert len(flagged) == genus["gu_species"]
    for kid in genus["children"]:
        assert (kid["gu_species"] > 0) == ("gu" in (kid["regions"] or []))


def test_a_gbif_taxon_page_link_shows_beside_the_species_link(world, tmp_path):
    ds = dataset.load(world)
    ds["links"].append({"taxon_id": "ORRHI", "system": "gbif_taxon", "value": "THDPS", "label": "",
                        "confidence": "high", "note": "", "added_by": "t", "added": "2026-11-15"})
    r = records.build_records(ds, thumbs=tmp_path)[C("ORRHI")]
    urls = [x["url"] for x in r["links"] if x["system"] == "gbif"]
    assert "https://www.gbif.org/taxon/THDPS" in urls and len(urls) == 2


def test_the_editor_tally_sums_the_editor_commit_titles():
    from guaminsects.build import count_editor_changes
    subjects = ["Editor: 63 changes by M. Andrew Johnston", "Editor: 1 change by A. B.",
                "Editor: a rejected token no longer blocks loading", "Data: 9 changes", "Editor: 9 changes by X"]
    assert count_editor_changes(subjects) == 73
