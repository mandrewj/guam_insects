from conftest import GIGAS, MARIANUS, ONOI, C

from guaminsects import site


def test_presence_counts_col_records_once(conn):
    recs = site.build_records(conn)
    crb = {p["area"]: p for p in recs[C("ORRHI")]["presence"]}
    # GBIF's count under the COL key; the Backbone name's 85 are the same records.
    assert crb["GU"]["gbif"] == 90
    assert crb["GU"]["inat"] == 30                    # the iNat name, matched to COL
    assert crb["GU"]["literature"] == 1               # Plazi, under the old name
    genus = {p["area"]: p for p in recs[C("ORYCT")]["presence"]}
    assert genus["GU"]["gbif"] == 95                  # the genus facet, not 90 + 95
    assert genus["GU"]["species"] == 2


def test_taxa_col_lacks_keep_their_backbone_records(conn):
    recs = site.build_records(conn)
    m = {p["area"]: p for p in recs[MARIANUS]["presence"]}
    assert m["PW"]["gbif"] == 3 and m["PW"]["literature"] == 1   # incl. the merged spelling
    assert recs[MARIANUS]["in_col"] is False
    assert [n["kind"] for n in recs[MARIANUS]["names"]] == ["spelling variant"]
    assert recs[ONOI]["machine_lit"] == ["GU"]


def test_merged_family_records_count_for_the_family(conn):
    recs = site.build_records(conn)
    fam = {p["area"]: p for p in recs[C("CALLI")]["presence"]}
    assert fam["GU"]["gbif"] == 122 and fam["FM"]["gbif"] == 10


def test_records_link_to_col_and_carry_their_ids(conn):
    rec = site.build_records(conn)[C("ORRHI")]
    assert rec["ext"] == "ORRHI"
    assert rec["links"][0]["url"].endswith("/data/taxon/ORRHI")
    assert "Scarabaeus rhinoceros" in rec["synonyms"]
    assert [a["name"] for a in rec["lineage"]] == ["Hexapoda", "Insecta", "Coleoptera",
                                                    "Scarabaeidae", "Oryctes"]
    assert site.build_records(conn)[GIGAS if GIGAS in site.build_records(conn) else C("ORGIG")]


def test_islands_and_home_cards(conn):
    recs = site.build_records(conn)
    assert recs[C("ORGIG")]["islands"] == [{"area": "PW", "label": "Palau", "islands": ["Koror"]}]
    root = next(t for t, r in recs.items() if not r["lineage"])
    assert [c["name"] for c in site.home_cards(recs, root)] == ["Coleoptera"]
    assert recs[root]["species_count"] == 4          # O. mariana is O. marianus
