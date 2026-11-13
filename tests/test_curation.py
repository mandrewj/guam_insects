import csv

import pytest

from guaminsects import config, curation, db

H = config.HEXAPODA_ID
ROOT_ROW = {"taxon_id": str(H), "rank": "Subphylum", "name": "Hexapoda"}


def write_taxa(path, rows):
    curation.write_csv(path, curation.TAXA_COLUMNS, rows)


def gbif_row(conn, key, parent, rank, name, cls=216, status="ACCEPTED", accepted=None):
    conn.execute("INSERT INTO gbif_taxa (gbif_key, parent_key, rank, canonical_name, "
                 "taxonomic_status, accepted_key, class_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (key, parent, rank, name, status, accepted, cls))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.sqlite")
    gbif_row(c, 54, 1, "PHYLUM", "Arthropoda", cls=None)
    gbif_row(c, 216, 54, "CLASS", "Insecta")
    gbif_row(c, 1470, 216, "ORDER", "Coleoptera")
    gbif_row(c, 7779, 1470, "FAMILY", "Scarabaeidae")
    gbif_row(c, 1063, 7779, "GENUS", "Oryctes")
    gbif_row(c, 4995642, 1063, "SPECIES", "Oryctes rhinoceros")
    gbif_row(c, 359, 54, "CLASS", "Arachnida", cls=367)   # not a hexapod
    gbif_row(c, 9999, 359, "SPECIES", "Some spider", cls=367)
    c.execute("INSERT INTO taxon_presence (taxon_id, area, source, records) VALUES "
              "(4995642, 'GU', 'gbif', 12), (9999, 'GU', 'gbif', 3)")
    return c


def paths(tmp_path):
    return tmp_path / "taxa.csv", tmp_path / "evidence.csv"


def test_tree_is_rooted_at_hexapoda_and_drops_non_hexapods(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW])
    stats = curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    rows = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    assert set(rows) == {H, 216, 1470, 7779, 1063, 4995642}
    assert rows[216]["parent_id"] == H
    assert rows[4995642]["lineage"] == f"/{H}/216/1470/7779/1063/4995642/"
    assert rows[H]["origin"] == "curated" and rows[4995642]["origin"] == "gbif"
    assert stats["curated"] == 1


def test_override_keeps_blank_fields_and_records_what_changed(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW, {"taxon_id": "4995642", "common_name":
                                     "coconut rhinoceros beetle", "establishment": "invasive"}])
    curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    t = conn.execute("SELECT * FROM taxa WHERE taxon_id = 4995642").fetchone()
    assert t["name"] == "Oryctes rhinoceros"          # blank name = keep GBIF's
    assert t["common_name"] == "coconut rhinoceros beetle"
    assert t["curated_fields"] == "common_name,establishment"


def test_new_morphospecies_gets_a_stable_id_written_back(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW, {"rank": "Species", "name": "Oryctes sp. GU-1",
                                     "parent_name": "Oryctes", "status": "morphospecies"}])
    cur = curation.load(taxa_csv, ev_csv)
    assert cur.assigned == 1
    with taxa_csv.open() as f:
        saved = list(csv.DictReader(f))
    new_id = int(saved[1]["taxon_id"])
    assert new_id == H + 1
    curation.resolve(conn, cur)
    t = conn.execute("SELECT * FROM taxa WHERE taxon_id = ?", (new_id,)).fetchone()
    assert t["parent_id"] == 1063 and t["status"] == "morphospecies"
    # A second load assigns nothing new: the id is now in the file.
    assert curation.load(taxa_csv, ev_csv).assigned == 0


def test_hidden_propagates_to_descendants(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW, {"taxon_id": "7779", "hidden": "1", "reason": "test"}])
    curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    hidden = dict(conn.execute("SELECT taxon_id, hidden_reason FROM taxa WHERE hidden = 1"))
    assert hidden == {7779: "test", 1063: "under a hidden taxon", 4995642: "under a hidden taxon"}


def test_bad_rows_are_all_reported(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW, {"rank": "Species"},
                          {"taxon_id": "1063", "status": "maybe", "establishment": "alien"}])
    with pytest.raises(curation.CurationError) as e:
        curation.load(taxa_csv, ev_csv)
    msg = str(e.value)
    assert "line 3" in msg and "status 'maybe'" in msg and "establishment 'alien'" in msg


def test_cycle_and_missing_parent_are_errors(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW, {"taxon_id": "1470", "parent_id": "1063"}])
    with pytest.raises(curation.CurationError, match="cycle"):
        curation.resolve(conn, curation.load(taxa_csv, ev_csv))
    write_taxa(taxa_csv, [ROOT_ROW, {"taxon_id": "1470", "parent_id": "123"}])
    with pytest.raises(curation.CurationError, match="parent 123 is not in the tree"):
        curation.resolve(conn, curation.load(taxa_csv, ev_csv))


def test_evidence_needs_a_licence_for_photos(conn, tmp_path):
    taxa_csv, ev_csv = paths(tmp_path)
    write_taxa(taxa_csv, [ROOT_ROW])
    curation.write_csv(ev_csv, curation.EVIDENCE_COLUMNS, [
        {"taxon_id": "4995642", "kind": "photo_url", "ref": "https://example.org/a.jpg"},
        {"taxon_id": "4995642", "kind": "inat_observation", "ref": "12345"}])
    with pytest.raises(curation.CurationError, match="line 2: a photo needs a licence"):
        curation.load(taxa_csv, ev_csv)


def test_lineages_survive_a_cycle():
    lin = db.lineages({1: None, 2: 1, 3: 4, 4: 3})
    assert lin[2] == "/1/2/" and set(lin) == {1, 2, 3, 4}
