import pytest

from guaminsects import config, curation, db, site

H = config.HEXAPODA_ID


def gbif_row(conn, key, parent, rank, name):
    conn.execute("INSERT INTO gbif_taxa (gbif_key, parent_key, rank, canonical_name, "
                 "taxonomic_status, class_key) VALUES (?, ?, ?, ?, 'ACCEPTED', 216)",
                 (key, parent, rank, name))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = db.connect(tmp_path / "t.sqlite")
    for k, p, r, n in [(216, 54, "CLASS", "Insecta"), (1470, 216, "ORDER", "Coleoptera"),
                       (7779, 1470, "FAMILY", "Scarabaeidae"), (1063, 7779, "GENUS", "Oryctes"),
                       (11, 1063, "SPECIES", "Oryctes rhinoceros"),
                       (12, 1063, "SPECIES", "Oryctes gigas")]:
        gbif_row(c, k, p, r, n)
    c.executemany("INSERT INTO taxon_presence (taxon_id, area, source, records) VALUES (?,?,?,?)",
                  [(11, "GU", "gbif", 90), (11, "GU", "inat", 30), (12, "PW", "pdf", 1),
                   (12, "GU", "plazi", 1), (1063, "GU", "gbif", 95), (7779, "GU", "gbif", 95)])
    c.execute("INSERT INTO taxon_islands (taxon_id, area, island, source, records) VALUES "
              "(12, 'PW', 'Koror', 'gbif', 1)")
    taxa_csv = tmp_path / "taxa.csv"
    curation.write_csv(taxa_csv, curation.TAXA_COLUMNS,
                       [{"taxon_id": str(H), "rank": "Subphylum", "name": "Hexapoda"},
                        {"taxon_id": "11", "establishment": "invasive"}])
    curation.resolve(c, curation.load(taxa_csv, tmp_path / "ev.csv"))
    monkeypatch.setattr("guaminsects.library.LIBRARY", tmp_path / "library.csv")
    return c


def test_presence_rolls_up_without_double_counting_gbif(conn):
    recs = site.build_records(conn)
    genus = {p["area"]: p for p in recs[1063]["presence"]}
    # GBIF's genus facet already counted every record under it: 95, not 90 + 95.
    assert genus["GU"]["gbif"] == 95
    assert genus["GU"]["inat"] == 30                  # iNat is per leaf taxon: summed
    assert genus["GU"]["species"] == 2                # either source puts a species there
    assert genus["GU"]["literature"] == 1             # species listed in literature
    assert genus["PW"]["species"] == 1
    assert recs[1063]["regions"] == ["gu", "pw"]


def test_species_presence_and_islands(conn):
    recs = site.build_records(conn)
    sp = {p["area"]: p for p in recs[12]["presence"]}
    assert sp["GU"]["literature"] == 1 and sp["PW"]["literature"] == 1
    assert recs[12]["islands"] == [{"area": "PW", "label": "Palau", "islands": ["Koror"]}]
    # Islands roll up to the genus, and the genus card carries them for the identify map.
    assert recs[1063]["islands"][0]["islands"] == ["Koror"]
    kid = next(c for c in recs[7779]["children"] if c["id"] == 1063)
    assert kid["isles"] == ["Koror"] and kid["regions"] == ["gu", "pw"]


def test_counts_and_curated_status(conn):
    recs = site.build_records(conn)
    assert recs[H]["species_count"] == 2 and recs[1470]["species_count"] == 2
    assert recs[11]["establishment"] == "invasive" and recs[11]["curated"] == ["establishment"]
    assert [a["name"] for a in recs[11]["lineage"]] == ["Hexapoda", "Insecta", "Coleoptera",
                                                         "Scarabaeidae", "Oryctes"]


def test_home_cards_list_orders(conn):
    recs = site.build_records(conn)
    assert [c["name"] for c in site.home_cards(recs, H)] == ["Coleoptera"]


def test_taxa_without_their_own_gbif_count_total_their_children(conn):
    recs = site.build_records(conn)
    root = {p["area"]: p for p in recs[H]["presence"]}
    assert root["GU"]["gbif"] == 95       # Scarabaeidae's facet count, carried up
