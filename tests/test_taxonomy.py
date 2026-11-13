import csv

import pytest

from guaminsects import config, curation, taxonomy
from test_curation import conn, files  # noqa: F401  (fixtures)

H = config.HEXAPODA_ID


@pytest.fixture
def repo(conn, files, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(taxonomy, "REPO_CSV", tmp_path / "taxonomy.csv")
    monkeypatch.setattr(taxonomy, "SNAPSHOT", tmp_path / "taxonomy.last.csv")
    curation.resolve(conn, curation.load(*files))
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


def by_name(rows, name):
    return next(r for r in rows if r["scientificName"] == name)


def test_rows_are_darwin_core_with_family_and_depth_first(repo):
    rows = table(taxonomy.REPO_CSV)
    assert list(rows[0]) == taxonomy.COLUMNS
    assert [r["scientificName"] for r in rows] == ["Hexapoda", "Insecta", "Coleoptera",
                                                  "Scarabaeidae", "Oryctes", "Oryctes rhinoceros"]
    crb = by_name(rows, "Oryctes rhinoceros")
    assert crb["family"] == "Scarabaeidae" and crb["parentNameUsage"] == "Oryctes"
    assert crb["recordedIn"] == "GU" and crb["gbifRecords"] == "12"


def test_verification_levels_roll_up(repo):
    rows = table(taxonomy.REPO_CSV)
    assert by_name(rows, "Oryctes rhinoceros")["verificationStatus"] == "unconfirmed"
    repo.execute("INSERT INTO taxon_specimens (taxon_id, area, records) VALUES (4995642, 'GU', 3)")
    rows = taxonomy.rows(repo)
    assert by_name(rows, "Oryctes rhinoceros")["verificationStatus"] == "specimen records"
    assert by_name(rows, "Hexapoda")["specimenRecords"] == 3          # totals its children
    repo.execute("INSERT INTO taxon_presence (taxon_id, area, source, records) VALUES "
                 "(4995642, 'GU', 'plazi', 1)")
    assert by_name(taxonomy.rows(repo), "Coleoptera")["verificationStatus"] == \
        "literature records"


def test_edits_in_the_file_become_curation_on_sync(repo):
    def change(rows):
        crb = by_name(rows, "Oryctes rhinoceros")
        crb["vernacularName"] = "coconut rhinoceros beetle"
        crb["verificationStatus"] = "editor confirmed"
        crb["verificationSource"] = "Moore et al. 2018"
        crb["gbifRecords"] = "999"                      # computed: left alone
        rows.append({c: "" for c in taxonomy.COLUMNS} | {
            "scientificName": "Oryctes sp. GU-1", "taxonRank": "Species",
            "parentNameUsage": "Oryctes", "taxonomicStatus": "morphospecies"})
    edit(taxonomy.REPO_CSV, change)
    stats = taxonomy.sync(repo, editor="t")
    assert (stats["changed"], stats["new"], stats["ignored"]) == (1, 1, 1)
    cur = {r["name"] or r["taxon_id"]: r for r in curation.load(*paths_of()).rows}
    assert cur["4995642"]["common_name"] == "coconut rhinoceros beetle"
    assert cur["4995642"]["verified"] == "1" and cur["4995642"]["citation"] == "Moore et al. 2018"
    assert cur["Oryctes sp. GU-1"]["status"] == "morphospecies"
    rows = taxonomy.rows(repo)
    crb = by_name(rows, "Oryctes rhinoceros")
    assert crb["verificationStatus"] == "editor confirmed" and crb["verifiedBy"] == "t"
    assert by_name(rows, "Oryctes sp. GU-1")["parentNameUsage"] == "Oryctes"
    taxonomy.write(rows)
    assert taxonomy.sync(repo) is None                  # nothing new since the write


def test_a_bad_edit_changes_nothing(repo):
    before = curation.TAXA_CSV.read_text()
    edit(taxonomy.REPO_CSV, lambda rows: by_name(rows, "Oryctes")
         .update(parentNameUsageID="4995642"))          # under its own species: a cycle
    with pytest.raises(curation.CurationError, match="cycle"):
        taxonomy.sync(repo, editor="t")
    assert curation.TAXA_CSV.read_text() == before


def test_unconfirming_clears_the_flag(repo):
    edit(taxonomy.REPO_CSV, lambda rows: by_name(rows, "Oryctes")
         .update(verificationStatus="editor confirmed"))
    taxonomy.sync(repo, editor="t")
    taxonomy.write(taxonomy.rows(repo))
    edit(taxonomy.REPO_CSV, lambda rows: by_name(rows, "Oryctes")
         .update(verificationStatus="unconfirmed"))
    taxonomy.sync(repo, editor="t")
    assert by_name(taxonomy.rows(repo), "Oryctes")["verificationStatus"] == "unconfirmed"
    assert not [r for r in curation.load(*paths_of()).rows if r["taxon_id"] == "1063"]


def test_subtree(repo):
    rows = taxonomy.rows(repo)
    assert [r["scientificName"] for r in taxonomy.subtree(rows, 7779)] == \
        ["Scarabaeidae", "Oryctes", "Oryctes rhinoceros"]
    assert len(taxonomy.subtree(rows, H)) == len(rows)


def paths_of():
    return curation.TAXA_CSV, curation.EVIDENCE_CSV
