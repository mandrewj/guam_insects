import csv

import pytest
from conftest import MARIANUS, C

from guaminsects import curation, taxonomy


@pytest.fixture
def repo(conn):
    taxonomy.write(taxonomy.rows(conn))
    return conn


def table(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def edit(path, change):
    rows = table(path)
    change(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=taxonomy.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def by_name(rows, name, status="accepted"):
    return next(r for r in rows if r["scientificName"] == name and r["taxonomicStatus"] == status)


def test_rows_are_darwin_core_with_synonym_rows(repo):
    rows = table(taxonomy.REPO_CSV)
    assert list(rows[0]) == taxonomy.COLUMNS
    crb = by_name(rows, "Oryctes rhinoceros")
    assert crb["taxonID"] == "ORRHI" and crb["parentNameUsageID"] == "ORYCT"
    assert crb["family"] == "Scarabaeidae" and crb["subfamily"] == "Dynastinae"
    assert crb["inCatalogueOfLife"] == "yes" and crb["references"].endswith("/ORRHI")
    old = by_name(rows, "Scarabaeus rhinoceros", "synonym")
    assert old["acceptedNameUsageID"] == "ORRHI" and old["nameMatch"] == "COL synonym"
    assert rows.index(old) == rows.index(crb) + 1      # right after its accepted taxon
    onoi = by_name(rows, "Callirhipis onoi")
    assert onoi["inCatalogueOfLife"] == "no" and onoi["family"] == "Callirhipidae"
    assert onoi["literatureSources"] == "" or "[machine-read]" in onoi["literatureSources"]


def test_verification_levels_and_machine_read_remark(repo):
    rows = table(taxonomy.REPO_CSV)
    assert by_name(rows, "Oryctes rhinoceros")["verificationStatus"] == "literature records"
    repo.execute("INSERT INTO taxon_specimens (taxon_id, area, records) VALUES (?, 'GU', 3)",
                 (C("CALIS"),))
    rows = taxonomy.rows(repo)
    assert by_name(rows, "Callirhipis")["specimenRecords"] == 3
    onoi = by_name(rows, "Callirhipis onoi")
    assert onoi["verificationStatus"] == "literature records"
    assert onoi["verificationRemarks"] == "literature records machine-read only"


def test_edits_become_curation_on_sync(repo):
    def change(rows):
        crb = by_name(rows, "Oryctes rhinoceros")
        crb["vernacularName"] = "coconut rhinoceros beetle"
        crb["verificationStatus"] = "editor confirmed"
        crb["gbifRecords"] = "999"                      # computed: left alone
        # merge a name COL lacks into a COL species
        by_name(rows, "Oryctes marianus")["acceptedNameUsageID"] = "ORGIG"
        rows.append({c: "" for c in taxonomy.COLUMNS} | {
            "scientificName": "Oryctes sp. GU-1", "taxonRank": "Species",
            "parentNameUsageID": "ORYCT", "taxonomicStatus": "morphospecies"})
    edit(taxonomy.REPO_CSV, change)
    stats = taxonomy.sync(repo, editor="t")
    assert (stats["changed"], stats["new"], stats["ignored"]) == (2, 1, 1)
    cur = {r["taxon_id"]: r for r in curation.load(curation.TAXA_CSV,
                                                    curation.EVIDENCE_CSV).rows}
    assert cur["ORRHI"]["verified"] == "1"
    assert cur["gbif:777"]["status"] == "synonym" and cur["gbif:777"]["accepted_id"] == "ORGIG"
    rows = taxonomy.rows(repo)
    assert by_name(rows, "Oryctes rhinoceros")["verificationStatus"] == "editor confirmed"
    assert by_name(rows, "Oryctes marianus", "synonym")["acceptedNameUsageID"] == "ORGIG"
    assert by_name(rows, "Oryctes sp. GU-1", "morphospecies")["taxonID"] == "IOG-1"


def test_a_bad_edit_changes_nothing(repo):
    before = curation.TAXA_CSV.read_text()
    edit(taxonomy.REPO_CSV, lambda rows: by_name(rows, "Coleoptera")
         .update(parentNameUsageID="ORYCT"))
    with pytest.raises(curation.CurationError, match="cycle"):
        taxonomy.sync(repo, editor="t")
    assert curation.TAXA_CSV.read_text() == before


def test_subtree_includes_synonym_rows(repo):
    rows = taxonomy.rows(repo)
    names = [r["scientificName"] for r in taxonomy.subtree(rows, "ORYCT")]
    assert names[0] == "Oryctes" and "Scarabaeus rhinoceros" in names
    assert "Callirhipis" not in names
    assert MARIANUS
