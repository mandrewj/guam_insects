import csv

import pytest
from conftest import (CRB, GIGAS, MARIANA, MARIANUS, MERGE_ROW, OLD_CRB, ONOI, ORYCTES_DUP,
                      ROOT_ROW, C, write_taxa)

from guaminsects import curation, db, ids, names


def taxa(conn):
    return {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}


def keymap(conn):
    return db.keymap(conn)


def test_tree_is_col_at_main_ranks(conn):
    t = taxa(conn)
    by_name = {r["name"]: r for r in t.values()}
    assert by_name["Hexapoda"]["parent_id"] is None
    # Suborder and subfamily are skipped in the tree, and kept for the CSV.
    assert "Polyphaga" not in by_name and "Dynastinae" not in by_name
    assert by_name["Scarabaeidae"]["parent_id"] == C("C2L")
    assert by_name["Oryctes"]["parent_id"] == C("SCARB")
    assert '"subfamily": "Dynastinae"' in by_name["Oryctes rhinoceros"]["extra"]
    assert by_name["Oryctes rhinoceros"]["ext_id"] == "ORRHI"
    assert by_name["Oryctes rhinoceros"]["in_col"] == 1


def test_names_col_lacks_go_under_their_col_parent_flagged(conn):
    t = taxa(conn)
    onoi = t[ONOI]
    assert onoi["parent_id"] == C("CALIS") and onoi["in_col"] == 0
    assert onoi["ext_id"] == "name-2" and "Not in the Catalogue of Life" in onoi["match_note"]
    # A Backbone species COL lacks: under the COL genus its Backbone genus matched.
    assert t[MARIANUS]["parent_id"] == C("ORYCT") and t[MARIANUS]["ext_id"] == "gbif:777"


def test_names_for_the_same_taxon_are_shown_as_one(conn):
    keys = keymap(conn)
    assert keys[CRB] == keys[ids.NAME_BASE + 1] == keys[OLD_CRB] == C("ORRHI")
    assert keys[ORYCTES_DUP] == C("ORYCT")             # the duplicate Backbone genus
    assert keys[MARIANA] == MARIANUS                    # one gender ending apart: merged
    rows = {r["name_id"]: dict(r) for r in conn.execute("SELECT * FROM taxon_names")}
    assert rows[OLD_CRB]["kind"] == "COL synonym" and rows[OLD_CRB]["taxon_id"] == C("ORRHI")
    assert rows[ORYCTES_DUP]["kind"] == "same name, other author"
    assert rows[MARIANA]["kind"] == "spelling variant"
    assert "Oryctes mariana → Oryctes marianus" in rows[MARIANA]["note"]
    assert CRB not in rows                              # the same name: nothing to say


def test_a_curated_merge_removes_a_family_with_family_level_records_only(conn):
    t = taxa(conn)
    assert C("RHIPI") not in t
    assert keymap(conn)[C("RHIPI")] == C("CALLI")
    assert t[C("CALIS")]["parent_id"] == C("CALLI")


def test_a_merged_name_can_be_split_out_again(conn, files):
    taxa_csv, ev_csv = files
    write_taxa(taxa_csv, [ROOT_ROW, MERGE_ROW,
                          {"taxon_id": "name-3", "status": "accepted", "parent_id": "ORYCT",
                           "reason": "a different species"}])
    curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    assert keymap(conn)[MARIANA] == MARIANA
    assert taxa(conn)[MARIANA]["parent_id"] == C("ORYCT")


def test_override_by_col_id_and_hidden_propagates(conn, files):
    taxa_csv, ev_csv = files
    write_taxa(taxa_csv, [ROOT_ROW, MERGE_ROW,
                          {"taxon_id": "ORRHI", "common_name": "coconut rhinoceros beetle",
                           "establishment": "invasive"},
                          {"taxon_id": "SCARB", "hidden": "1", "reason": "test"}])
    curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    t = taxa(conn)
    assert t[C("ORRHI")]["common_name"] == "coconut rhinoceros beetle"
    assert t[C("ORRHI")]["curated_fields"] == "common_name,establishment"
    assert t[C("ORYCT")]["hidden_reason"] == "under a hidden taxon"
    assert t[MARIANUS]["hidden"] == 1


def test_new_morphospecies_gets_a_stable_iog_id(conn, files):
    taxa_csv, ev_csv = files
    write_taxa(taxa_csv, [ROOT_ROW, MERGE_ROW,
                          {"rank": "Species", "name": "Oryctes sp. GU-1", "parent_id": "ORYCT",
                           "status": "morphospecies"}])
    cur = curation.load(taxa_csv, ev_csv)
    assert cur.assigned == 1
    with taxa_csv.open() as f:
        assert list(csv.DictReader(f))[2]["taxon_id"] == "IOG-1"
    curation.resolve(conn, cur)
    t = taxa(conn)[ids.to_int("IOG-1")]
    assert t["parent_id"] == C("ORYCT") and t["status"] == "morphospecies"
    assert curation.load(taxa_csv, ev_csv).assigned == 0


def test_bad_rows_are_all_reported(files):
    taxa_csv, ev_csv = files
    write_taxa(taxa_csv, [ROOT_ROW, {"rank": "Species"},
                          {"taxon_id": "ORYCT", "status": "maybe", "establishment": "alien"},
                          {"taxon_id": "not an id!"}])
    with pytest.raises(curation.CurationError) as e:
        curation.load(taxa_csv, ev_csv)
    msg = str(e.value)
    assert "line 3" in msg and "status 'maybe'" in msg and "establishment 'alien'" in msg
    assert "'not an id!' is not an id" in msg


def test_cycle_and_missing_parent_are_errors(conn, files):
    taxa_csv, ev_csv = files
    write_taxa(taxa_csv, [ROOT_ROW, MERGE_ROW, {"taxon_id": "C2L", "parent_id": "ORYCT"}])
    with pytest.raises(curation.CurationError, match="cycle"):
        curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    write_taxa(taxa_csv, [ROOT_ROW, MERGE_ROW, {"taxon_id": "C2L", "parent_id": "ZZZZ"}])
    with pytest.raises(curation.CurationError, match="parent ZZZZ is not in the tree"):
        curation.resolve(conn, curation.load(taxa_csv, ev_csv))


def test_evidence_needs_a_licence_for_photos(files):
    taxa_csv, ev_csv = files
    curation.write_csv(ev_csv, curation.EVIDENCE_COLUMNS, [
        {"taxon_id": "ORRHI", "kind": "photo_url", "ref": "https://example.org/a.jpg"},
        {"taxon_id": "ORRHI", "kind": "inat_observation", "ref": "12345"}])
    with pytest.raises(curation.CurationError, match="line 2: a photo needs a licence"):
        curation.load(taxa_csv, ev_csv)


def test_upsert_then_clear_drops_the_row(conn, files):
    curation.upsert(conn, {"taxon_id": "ORRHI", "common_name": "CRB"}, editor="t")
    assert taxa(conn)[C("ORRHI")]["common_name"] == "CRB"
    curation.upsert(conn, {"taxon_id": "ORRHI", "common_name": ""}, editor="t")
    assert [r["taxon_id"] for r in curation.load(*files).rows] == ["L2655", "RHIPI"]


def test_bad_edit_changes_nothing(conn, files):
    taxa_csv, _ = files
    before = taxa_csv.read_text()
    with pytest.raises(curation.CurationError):
        curation.upsert(conn, {"taxon_id": "C2L", "parent_id": "ORYCT"}, editor="t")
    assert taxa_csv.read_text() == before
    assert taxa(conn)[C("C2L")]["parent_id"] == C("H6")


def test_morphospecies_with_evidence(conn, files):
    curation.upsert(conn, {"rank": "Species", "name": "Oryctes sp. GU-1", "parent_id": "ORYCT",
                           "status": "morphospecies"}, editor="t")
    curation.add_evidence(conn, {"taxon_id": "IOG-1", "kind": "inat_observation", "ref": "123"},
                          editor="t")
    assert conn.execute("SELECT taxon_id, ref FROM taxon_evidence").fetchone()[:] == \
        (ids.to_int("IOG-1"), "123")


def test_ids_round_trip():
    for ext in ["KVC9L", "4CGSL", "N", "gbif:1045882", "name-12", "IOG-3"]:
        assert ids.to_ext(ids.to_int(ext)) == ext
    assert ids.kind(ids.to_int("KVC9L")) == "col" and ids.to_int(GIGAS) == GIGAS
    assert not ids.valid("kvc9l") and not ids.valid("gbif:x")


def test_spelling_nearness():
    assert names.near("Oryctes mariana", "Oryctes marianus")
    assert names.near("Gonocephalum adpressiformis", "Gonocephalum adpressiforme")
    assert names.near("Anomala sulcatula", "Anomala sulcatulla")
    assert not names.near("Oryctes gigas", "Oryctes rhinoceros")
    assert not names.near("Anomala sulcata", "Adoretus sulcata")


def test_lineages_survive_a_cycle():
    lin = db.lineages({1: None, 2: 1, 3: 4, 4: 3})
    assert lin[2] == "/1/2/" and set(lin) == {1, 2, 3, 4}


def test_a_hand_merge_is_listed_with_its_reason(conn):
    row = conn.execute("SELECT kind, note, taxon_id, name FROM taxon_names WHERE name_id = ?",
                       (C("RHIPI"),)).fetchone()
    assert tuple(row) == ("curated merge", "records labelled Rhipiceridae are Callirhipis",
                          C("CALLI"), "Rhipiceridae")
