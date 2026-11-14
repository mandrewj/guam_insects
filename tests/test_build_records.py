"""The records built from the dataset equal what the pipeline's site.build_records makes."""

from conftest import C

from guaminsects import dataset, migrate, site
from guaminsects.build import export, records

SAME = ["id", "ext", "in_col", "match_note", "names", "rank", "name", "authority",
        "common", "status", "origin", "hidden", "species_count", "lineage", "checklist",
        "islands", "evidence", "distribution", "hosts", "links",
        "conservation"]


def world(conn, tmp_path):
    out = tmp_path / "dataset"
    migrate.migrate(conn, out, copy_media=False)
    return dataset.load(out)


def test_records_match_the_pipeline(conn, tmp_path):
    old = site.build_records(conn)
    new = records.build_records(world(conn, tmp_path), thumbs=tmp_path)
    assert set(old) == set(new)
    for tid in old:
        for f in SAME:
            assert new[tid][f] == old[tid][f], (old[tid]["name"], f)
        # The fixture has literature presence rows but no documents or mentions to rebuild
        # them from; ops/compare_records.py proves literature on the real data.
        strip = lambda rows: [{k: v for k, v in p.items() if k not in ("literature", "species")}  # noqa: E731
                              for p in rows if p["gbif"] or p["inat"]]
        assert strip(new[tid]["presence"]) == strip(old[tid]["presence"]), old[tid]["name"]
        assert [c["id"] for c in new[tid]["children"]] == [c["id"] for c in old[tid]["children"]]
        assert sorted(new[tid]["synonyms"]) == sorted(old[tid]["synonyms"])


def test_nativity_is_on_every_record(conn, tmp_path):
    new = records.build_records(world(conn, tmp_path), thumbs=tmp_path)
    assert {r["nativity"] for r in new.values()} == {"unknown"}
    assert new[C("ORRHI")]["nativity_source"] is None


def test_export_rows(conn, tmp_path):
    ds = world(conn, tmp_path)
    recs = records.build_records(ds, thumbs=tmp_path)
    table = export.rows(ds, recs)
    assert table[0]["scientificName"] == "Hexapoda"
    assert len(table) == len(ds["taxa"])
    syn = next(r for r in table if r["scientificName"] == "Scarabaeus rhinoceros")
    assert syn["acceptedNameUsage"] == "Oryctes rhinoceros" and syn["taxonomicStatus"] == "synonym"
    assert export.to_csv(table).splitlines()[0].startswith("taxonID,parentNameUsageID")
