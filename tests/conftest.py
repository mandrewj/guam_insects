"""A small Catalogue of Life world for the tree, site and taxonomy tests.

    Hexapoda L2655 > Insecta H6 > Coleoptera C2L > (suborder Polyphaga)
        > Scarabaeidae SCARB > (subfamily Dynastinae) > Oryctes ORYCT
            > O. rhinoceros ORRHI, O. gigas ORGIG
        > Callirhipidae CALLI > Callirhipis CALIS
        > Rhipiceridae RHIPI (records only at family level: merged by hand into Callirhipidae)

Source names: GBIF Backbone keys (one a duplicate genus with another author, one a COL
synonym, one a species COL lacks), iNaturalist and literature names (name- keys), one a
spelling variant of a name COL lacks.
"""

import pytest

from guaminsects import config, curation, db, ids, names, taxonomy

C = ids.from_col
NAME = ids.NAME_BASE
CRB, GIGAS, ORYCTES_BB, ORYCTES_DUP, MARIANUS, OLD_CRB = 4995642, 12, 1063, 1045882, 777, 2080570
INAT_CRB, ONOI, MARIANA, ORYCTES_NAME = NAME + 1, NAME + 2, NAME + 3, NAME + 4


def col_row(conn, col_id, parent, rank, name, authorship=None, status="accepted", accepted=None):
    conn.execute("INSERT INTO col_taxa (taxon_id, col_id, parent_id, rank, name, authorship, "
                 "status, accepted_id, full) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                 (C(col_id), col_id, C(parent) if parent else None, rank, name, authorship,
                  status, C(accepted) if accepted else None))


def match_row(conn, key, name, rank, taxon=None, parent=0, kind="same", note=None,
              authorship=None):
    conn.execute("INSERT INTO name_matches (key, name, rank, authorship, origin, match_type, "
                 "taxon, parent, kind, note) VALUES (?, ?, ?, ?, 'test', 'EXACT', ?, ?, ?, ?)",
                 (key, name, rank, authorship, C(taxon) if taxon else 0, parent, kind, note))


def presence(conn, key, area, source, n):
    conn.execute("INSERT INTO taxon_presence (taxon_id, area, source, records) VALUES (?, ?, ?, ?)",
                 (key, area, source, n))


def build_world(conn):
    for row in [("L2655", None, "SUBPHYLUM", "Hexapoda"), ("H6", "L2655", "CLASS", "Insecta"),
                ("C2L", "H6", "ORDER", "Coleoptera"), ("DDHNW", "C2L", "SUBORDER", "Polyphaga"),
                ("SCARB", "DDHNW", "FAMILY", "Scarabaeidae"),
                ("DYNST", "SCARB", "SUBFAMILY", "Dynastinae"),
                ("ORYCT", "DYNST", "GENUS", "Oryctes", "Hope, 1837"),
                ("ORRHI", "ORYCT", "SPECIES", "Oryctes rhinoceros", "(Linnaeus, 1758)"),
                ("ORGIG", "ORYCT", "SPECIES", "Oryctes gigas", "Castelnau, 1840"),
                ("CALLI", "DDHNW", "FAMILY", "Callirhipidae"),
                ("CALIS", "CALLI", "GENUS", "Callirhipis", "Latreille, 1829"),
                ("RHIPI", "DDHNW", "FAMILY", "Rhipiceridae")]:
        col_row(conn, *row)
    for key, parent, rank, name, auth in [
            (ORYCTES_BB, None, "GENUS", "Oryctes", "Hope, 1837"),
            (ORYCTES_DUP, None, "GENUS", "Oryctes", "Illiger, 1798"),
            (CRB, ORYCTES_BB, "SPECIES", "Oryctes rhinoceros", "(Linnaeus, 1758)"),
            (GIGAS, ORYCTES_BB, "SPECIES", "Oryctes gigas", None),
            (MARIANUS, ORYCTES_BB, "SPECIES", "Oryctes marianus", "Zimmerman, 1942"),
            (OLD_CRB, None, "SPECIES", "Scarabaeus rhinoceros", "Linnaeus, 1758")]:
        conn.execute("INSERT INTO gbif_taxa (gbif_key, parent_key, rank, canonical_name, "
                     "authorship, taxonomic_status, class_key) VALUES (?, ?, ?, ?, ?, "
                     "'ACCEPTED', 216)", (key, parent, rank, name, auth))
    match_row(conn, ORYCTES_BB, "Oryctes", "GENUS", "ORYCT", authorship="Hope, 1837")
    match_row(conn, ORYCTES_DUP, "Oryctes", "GENUS", "ORYCT", authorship="Illiger, 1798")
    match_row(conn, CRB, "Oryctes rhinoceros", "SPECIES", "ORRHI")
    match_row(conn, GIGAS, "Oryctes gigas", "SPECIES", "ORGIG")
    match_row(conn, MARIANUS, "Oryctes marianus", "SPECIES", parent=ORYCTES_BB,
              kind="not in COL", note="Not in the Catalogue of Life")
    match_row(conn, OLD_CRB, "Scarabaeus rhinoceros", "SPECIES", "ORRHI", kind="COL synonym",
              note="Catalogue of Life: a synonym of Oryctes rhinoceros")
    match_row(conn, INAT_CRB, "Oryctes rhinoceros", "SPECIES", "ORRHI")
    match_row(conn, ONOI, "Callirhipis onoi", "SPECIES", parent=C("CALIS"), kind="not in COL",
              note="Not in the Catalogue of Life")
    match_row(conn, ORYCTES_NAME, "Oryctes", "GENUS", "ORYCT")
    match_row(conn, MARIANA, "Oryctes mariana", "SPECIES", parent=ORYCTES_NAME,
              kind="not in COL", note="Not in the Catalogue of Life")
    for key, area, source, n in [
            (C("ORRHI"), "GU", "gbif", 90), (C("ORYCT"), "GU", "gbif", 95),
            (C("SCARB"), "GU", "gbif", 95), (C("CALIS"), "GU", "gbif", 118),
            (C("CALLI"), "GU", "gbif", 122), (C("RHIPI"), "FM", "gbif", 10),
            (CRB, "GU", "gbif_backbone", 85), (ORYCTES_DUP, "MP", "gbif_backbone", 1),
            (INAT_CRB, "GU", "inat", 30), (GIGAS, "GU", "plazi", 1), (GIGAS, "PW", "pdf", 1),
            (OLD_CRB, "GU", "plazi", 1), (MARIANUS, "PW", "gbif_backbone", 3),
            (MARIANA, "PW", "pdf", 1), (ONOI, "GU", "pdf", 1)]:
        presence(conn, key, area, source, n)
    conn.execute("INSERT INTO taxon_islands (taxon_id, area, island, source, records) VALUES "
                 "(?, 'PW', 'Koror', 'gbif', 1)", (GIGAS,))
    conn.commit()


ROOT_ROW = {"taxon_id": "L2655", "common_name": "hexapods"}
MERGE_ROW = {"taxon_id": "RHIPI", "status": "synonym", "accepted_id": "CALLI",
             "reason": "records labelled Rhipiceridae are Callirhipis"}


@pytest.fixture
def files(tmp_path, monkeypatch):
    taxa_csv, ev_csv = tmp_path / "taxa.csv", tmp_path / "evidence.csv"
    curation.write_csv(taxa_csv, curation.TAXA_COLUMNS, [ROOT_ROW, MERGE_ROW])
    curation.write_csv(ev_csv, curation.EVIDENCE_COLUMNS, [])
    monkeypatch.setattr(curation, "TAXA_CSV", taxa_csv)
    monkeypatch.setattr(curation, "EVIDENCE_CSV", ev_csv)
    reg = tmp_path / "names.csv"
    reg.write_text("id,name,rank,origin,hints\n1,Oryctes rhinoceros,SPECIES,inat,{}\n"
                   "2,Callirhipis onoi,SPECIES,literature,{}\n"
                   "3,Oryctes mariana,SPECIES,literature,{}\n4,Oryctes,GENUS,literature,{}\n")
    monkeypatch.setattr(names, "REGISTRY", reg)
    monkeypatch.setattr("guaminsects.library.LIBRARY", tmp_path / "library.csv")
    monkeypatch.setattr(taxonomy, "REPO_CSV", tmp_path / "taxonomy.csv")
    monkeypatch.setattr(taxonomy, "SNAPSHOT", tmp_path / "taxonomy.last.csv")
    monkeypatch.setattr(config, "CURATED_PHOTOS_DIR", tmp_path / "photos")
    return taxa_csv, ev_csv


@pytest.fixture
def conn(tmp_path, files):
    c = db.connect(tmp_path / "t.sqlite")
    build_world(c)
    curation.resolve(c, curation.load(*files))
    c.execute("INSERT INTO inat_place_counts (inat_id, place_id, area, name, rank, observations) "
              "VALUES (1, 7316, 'GU', 'Oryctes rhinoceros', 'species', 30)")
    c.commit()
    return c


def write_taxa(path, rows):
    curation.write_csv(path, curation.TAXA_COLUMNS, rows)
