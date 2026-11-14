"""The dataset tables: migration from the pipeline world, determinism, and the checks."""

import shutil

import pytest

from guaminsects import dataset, migrate, schema


@pytest.fixture
def ds_dir(conn, tmp_path):
    out = tmp_path / "dataset"
    report = migrate.migrate(conn, out, copy_media=False)
    return out, report


def test_migrated_world_passes_the_checks(ds_dir):
    out, report = ds_dir
    ds = dataset.load(out)
    assert dataset.check(ds).items == []
    taxa = {r["id"]: r for r in ds["taxa"]}
    assert taxa["ORRHI"]["name"] == "Oryctes rhinoceros"
    assert taxa["ORRHI"]["nativity"] == "unknown"        # nobody has assessed it
    assert any(r["status"] == "synonym" and r["accepted_id"] == "CALLI" and r["name"] == "Rhipiceridae"
               for r in ds["taxa"])                       # the curated merge is a synonym row
    assert report["taxa"] == sum(r["status"] != "synonym" for r in ds["taxa"])


def test_records_follow_the_key_rules(ds_dir):
    ds = dataset.load(ds_dir[0])
    cells = {(r["taxon_id"], r["area"], r["source"]): int(r["records"]) for r in ds["records"]}
    assert cells[("ORRHI", "GU", "gbif")] == 90          # the Backbone's 85 are the same records
    assert cells[("ORRHI", "GU", "inat")] == 30
    assert cells[("gbif:777", "PW", "gbif")] == 3         # a name COL lacks keeps its Backbone count


def test_write_is_deterministic_and_round_trips(ds_dir, tmp_path):
    out, _ = ds_dir
    ds = dataset.load(out)
    again = tmp_path / "again"
    dataset.write(ds, again)
    for f in out.rglob("*"):
        if f.is_file():
            assert f.read_bytes() == (again / f.relative_to(out)).read_bytes(), f.name


def test_taxa_are_depth_first_with_synonyms_after_their_taxon(ds_dir):
    names = [(r["name"], r["status"]) for r in dataset.load(ds_dir[0])["taxa"]]
    i = names.index(("Oryctes rhinoceros", "accepted"))
    assert names[i + 1][1] == "synonym"                  # Scarabaeus rhinoceros
    assert names[0][0] == "Hexapoda"


@pytest.fixture
def small(ds_dir, tmp_path):
    out = tmp_path / "small"
    shutil.copytree(ds_dir[0], out)
    return dataset.load(out)


def test_check_reports_every_problem(small):
    taxa = small["taxa"]
    sp = next(r for r in taxa if r["name"] == "Oryctes gigas")
    sp["nativity"] = ""                                   # required for an accepted taxon
    next(r for r in taxa if r["name"] == "Oryctes")["rank"] = "Species"   # ranks must descend
    small["records"].append({"taxon_id": "NOPE1", "area": "XX", "source": "gbif", "records": "x"})
    small["photos"].append({"taxon_id": "ORRHI", "position": "9", "photo_id": "inat:1",
                            "role": "own", "licence": "cc-by-nd", "display_url": "http://x",
                            "attribution": "a"})
    msgs = "\n".join(dataset.check(small).items)
    assert "no nativity" in msgs and "does not descend" in msgs
    assert "area 'XX'" in msgs and "'x' is not a whole number" in msgs
    assert "licence 'cc-by-nd'" in msgs


def test_a_cycle_and_a_second_root_are_reported(small):
    taxa = small["taxa"]
    by = {r["name"]: r for r in taxa}
    by["Insecta"]["parent_id"] = by["Coleoptera"]["id"]
    msgs = "\n".join(dataset.check(small).items)
    assert "cycle" in msgs or "expected one root" in msgs


def test_a_note_must_not_copy_the_document(small):
    doc = small["documents"][0]["doc_id"] if small["documents"] else "d1"
    if not small["documents"]:
        small["documents"].append({"doc_id": "d1", "title": "T", "kind": "paper"})
    small["notes"].append({"taxon_id": "ORRHI", "doc_id": doc, "note": "adults bore into the crown "
                           "of coconut palms and cut the folded fronds", "review": "machine"})
    text = "Adults bore into the crown of coconut palms and cut the folded fronds. More text."
    assert dataset.check(small, lambda d: text).items[-1].startswith("notes.csv")
    assert dataset.check(small, lambda d: "nothing alike here at all").items == []
    small["notes"][-1]["note"] = "x" * 201
    assert any("201 characters" in m for m in dataset.check(small).items)


def test_readme_lists_every_table():
    text = schema.readme()
    assert all(f"`{t.file}`" in text for t in schema.TABLES)
