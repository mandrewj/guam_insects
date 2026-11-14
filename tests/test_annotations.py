"""Editors' annotations: distribution tags, voucher links (evidence.csv) and other links
(curation/annotations.csv), on the site and in taxonomy.csv (both ways)."""

import csv

import pytest
from conftest import C

from guaminsects import curation, site, taxonomy

ANN = curation.ANNOTATION_COLUMNS


def ann(**kw):
    return {c: "" for c in ANN} | {"added_by": "A. Editor", "added": "2026-11-14"} | kw


def write_ann(files, rows):
    curation.write_csv(files[0].with_name("annotations.csv"), ANN, rows)


def reload(conn, files):
    curation.resolve(conn, curation.load(*files))


def test_bad_annotations_are_all_reported(files):
    write_ann(files, [ann(taxon_id="ORGIG", kind="distribution", value="Atlantis",
                          status="present"),
                      ann(taxon_id="ORGIG", kind="distribution", value="Rota", status="rare"),
                      ann(taxon_id="ORGIG", kind="link", value="www.example.org"),
                      ann(taxon_id="ORGIG", kind="distribution", value="Yap", status="present",
                          added_by="")])
    with pytest.raises(curation.CurationError) as e:
        curation.load(*files)
    msg = str(e.value)
    assert "Atlantis" in msg and "rare" in msg and "needs a URL" in msg and "added_by" in msg


def test_tag_on_a_taxon_not_in_the_tree_is_refused(conn, files):
    write_ann(files, [ann(taxon_id="gbif:4242", kind="distribution", value="Guam",
                          status="present")])
    with pytest.raises(curation.CurationError, match="not in the tree"):
        reload(conn, files)


def test_present_tag_is_a_record_absent_is_not(conn, files):
    write_ann(files, [
        ann(taxon_id="ORGIG", kind="distribution", value="Rota", status="present",
            source="Buden 2004"),
        ann(taxon_id="ORGIG", kind="distribution", value="Marshalls", status="absent"),
        ann(taxon_id="ORGIG", kind="link", value="https://example.org/gigas",
            note="Field notes")])
    reload(conn, files)
    recs = site.build_records(conn)
    gigas, genus = recs[C("ORGIG")], recs[C("ORYCT")]
    assert [(d["place"], d["status"], d["added_by"]) for d in gigas["distribution"]] == [
        ("Rota", "present", "A. Editor"), ("Marshalls", "absent", "A. Editor")]
    assert "mp" in gigas["regions"] and "mh" not in gigas["regions"]
    mp = next(p for p in gigas["presence"] if p["area"] == "MP")
    assert mp["editor"] == "present" and mp["gbif"] == 0
    assert any(x["area"] == "MP" and "Rota" in x["islands"] for x in gigas["islands"])
    assert "mp" in genus["regions"]                     # rolled up to the genus
    link = next(lk for lk in gigas["links"] if lk["system"] == "editor")
    assert link["label"] == "Field notes" and "A. Editor" in link["note"]


def test_taxonomy_csv_shows_annotations_and_who(conn, files):
    write_ann(files, [ann(taxon_id="ORGIG", kind="distribution", value="Rota",
                          status="doubtful", source="Buden 2004"),
                      ann(taxon_id="ORGIG", kind="link", value="https://example.org/g")])
    curation.write_csv(files[1], curation.EVIDENCE_COLUMNS, [
        {"taxon_id": "ORGIG", "kind": "inat_observation", "ref": "123", "editor": "B. Other",
         "edited": "2026-11-15"}])
    reload(conn, files)
    gigas = next(r for r in taxonomy.rows(conn) if r["taxonID"] == "ORGIG")
    assert gigas["distributionTags"] == "Rota: doubtful (Buden 2004)"
    assert gigas["associatedReferences"] == "https://example.org/g"
    assert gigas["associatedOccurrences"] == "https://www.inaturalist.org/observations/123"
    assert (gigas["modifiedBy"], gigas["modified"]) == ("B. Other", "2026-11-15")


def test_cell_formats_round_trip():
    a = ann(value="Rota", status="present", source="Buden 2004, p. 3")
    assert taxonomy.parse_tag(taxonomy.format_tag(a)) == {
        "value": "Rota", "status": "present", "source": "Buden 2004, p. 3"}
    assert taxonomy.parse_tag("Yap: absent") == {"value": "Yap", "status": "absent", "source": ""}
    with pytest.raises(ValueError):
        taxonomy.parse_tag("Yap: rare")
    assert taxonomy.parse_link("Notes <https://x.org/a>") == {"value": "https://x.org/a",
                                                               "note": "Notes"}
    assert taxonomy.parse_occurrence("https://inaturalist.org/observations/55?x=1") == (
        "inat_observation", "55")
    assert taxonomy.parse_occurrence("https://www.gbif.org/occurrence/9/") == (
        "gbif_occurrence", "9")
    with pytest.raises(ValueError):
        taxonomy.parse_occurrence("https://example.org/observations/1")


def _edit(path, change):
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    change(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=taxonomy.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_list_cells_edited_in_a_spreadsheet_are_filed(conn, files):
    taxonomy.write(taxonomy.rows(conn))

    def change(rows):
        g = next(r for r in rows if r["taxonID"] == "ORGIG")
        g["distributionTags"] = "Guam: present | Yap: doubtful (photo only)"
        g["associatedOccurrences"] = "https://www.inaturalist.org/observations/777"
        g["associatedReferences"] = "BOLD <https://boldsystems.org/x>"
    _edit(taxonomy.REPO_CSV, change)
    stats = taxonomy.sync(conn, editor="C. Sheet")
    assert stats["changed"] == 3
    cur = curation.load(*files)
    tags = {(a["value"], a["status"], a["source"], a["added_by"]) for a in cur.annotations
            if a["kind"] == "distribution"}
    assert tags == {("Guam", "present", "", "C. Sheet"), ("Yap", "doubtful", "photo only",
                                                          "C. Sheet")}
    assert [(e["kind"], e["ref"], e["editor"]) for e in cur.evidence] == [
        ("inat_observation", "777", "C. Sheet")]
    assert any(a["kind"] == "link" and a["note"] == "BOLD" for a in cur.annotations)

    # The rewritten file shows them; removing one there removes its row.
    taxonomy.write(taxonomy.rows(conn))
    _edit(taxonomy.REPO_CSV, lambda rows: next(
        r for r in rows if r["taxonID"] == "ORGIG").update(distributionTags="Guam: present"))
    taxonomy.sync(conn, editor="C. Sheet")
    cur = curation.load(*files)
    assert [a["value"] for a in cur.annotations if a["kind"] == "distribution"] == ["Guam"]


def test_importing_what_is_already_filed_changes_nothing(conn, files):
    write_ann(files, [ann(taxon_id="ORGIG", kind="distribution", value="Guam",
                          status="present")])
    curation.write_csv(files[0], curation.TAXA_COLUMNS, curation.load(*files).rows + [
        {c: "" for c in curation.TAXA_COLUMNS} | {"taxon_id": "ORRHI",
                                                   "common_name": "coconut rhinoceros beetle",
                                                   "editor": "A. Editor", "edited": "2026-11-14"}])
    reload(conn, files)
    before = (files[0].read_text(), files[0].with_name("annotations.csv").read_text())
    # An old taxonomy.csv as the baseline, the new one as the edit: what the editor app
    # commits (curation rows and the matching taxonomy.csv together).
    old = taxonomy.rows(conn)
    for r in old:
        if r["taxonID"] == "ORGIG":
            r["distributionTags"] = ""
        if r["taxonID"] == "ORRHI":
            r["vernacularName"] = ""
    taxonomy.write(taxonomy.rows(conn))
    stats = taxonomy.import_edits(conn, taxonomy.REPO_CSV, "someone else",
                                  baseline={r["taxonID"]: {k: str(v) for k, v in r.items()}
                                            for r in old})
    assert stats["changed"] == 0
    assert (files[0].read_text(), files[0].with_name("annotations.csv").read_text()) == before
