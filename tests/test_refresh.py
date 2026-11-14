"""The refresh sources against canned answers: licences, selection, Wikidata, BugGuide."""

from guaminsects import dataset, refresh
from guaminsects.sources import bugguide, photos, wikidata, wikipedia

TODAY = "2026-11-20"


def taxa_ds():
    blank = lambda **kw: {c: "" for c in dataset.schema.table("taxa").names} | kw  # noqa: E731
    ds = dataset.Dataset()
    ds["taxa"] = [
        blank(id="L2655", rank="Subphylum", name="Hexapoda", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="SCARB", parent_id="L2655", rank="Family", name="Scarabaeidae", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="ORYCT", parent_id="SCARB", rank="Genus", name="Oryctes", status="accepted", nativity="unknown", in_col="yes"),
        blank(id="ORRHI", parent_id="ORYCT", rank="Species", name="Oryctes rhinoceros", status="accepted",
              nativity="unknown", in_col="yes", gbif_key="1063", common_name="Coconut Rhinoceros Beetle"),
        blank(id="ORGIG", parent_id="ORYCT", rank="Species", name="Oryctes gigas", status="accepted", nativity="unknown", in_col="yes"),
    ]
    ds["records"] = [{c: "" for c in dataset.schema.table("records").names} | r for r in [
        {"taxon_id": "ORRHI", "area": "GU", "source": "gbif", "records": "90"},
        {"taxon_id": "ORGIG", "area": "PW", "source": "gbif", "records": "3"}]]
    return ds


def test_licences():
    meta = lambda s: {"LicenseShortName": {"value": s}, "LicenseUrl": {"value": "https://x"}}  # noqa: E731
    assert photos.commons_license(meta("CC BY-SA 4.0"))[0] == "cc-by-sa"
    assert photos.commons_license(meta("CC BY-NC-ND 4.0")) is None
    assert photos.commons_license(meta("Public domain"))[0] == "cc0"
    assert photos.gbif_license("http://creativecommons.org/licenses/by-nd/4.0/") is None
    assert photos.gbif_license("CC BY 4.0 https://creativecommons.org/licenses/by/4.0/") == "cc-by"


def cand(pid, hint, **kw):
    return {"photo_id": pid, "source": "inaturalist", "page_url": "https://p/" + pid,
            "display_url": "https://d/" + pid, "thumb_url": "https://t/" + pid, "licence": "cc-by",
            "licence_url": "https://l", "attribution": "© A", "hint": hint, **kw}


def test_own_rows_take_the_best_hints_without_repeats():
    rows = photos.own_rows({"ORRHI": [cand("b", 20), cand("a", 5), cand("a", 5), cand("c", 40)]}, TODAY)
    assert [(r["photo_id"], r["position"]) for r in rows] == [("a", "0"), ("b", "1"), ("c", "2")]
    assert all(r["role"] == "own" and r["retrieved"] == TODAY for r in rows)


def test_groups_borrow_from_species_recorded_here_and_the_choice_is_stable():
    ds = taxa_ds()
    ds["photos"] = photos.own_rows({"ORRHI": [cand("a", 5, width=300, height=200)],
                                    "ORGIG": [cand("g", 5, width=300, height=200)]}, TODAY)
    n = photos.inherit(ds)
    got = {(p["taxon_id"], p["photo_id"], p["from_id"]) for p in ds["photos"] if p["role"] == "inherited"}
    # Oryctes shows its species (Guam's first); the family and the root show the same two.
    assert ("ORYCT", "a", "ORRHI") in got and ("ORYCT", "g", "ORGIG") in got
    assert ("SCARB", "a", "ORRHI") in got and n == len(got) == 6
    first = sorted((p["taxon_id"], p["position"], p["photo_id"]) for p in ds["photos"])
    photos.inherit(ds)                                    # again: nothing moves
    assert first == sorted((p["taxon_id"], p["position"], p["photo_id"]) for p in ds["photos"])
    assert dataset.check(_with_everything(ds)).items == []


def _with_everything(ds):
    return ds


def test_wikidata_writes_links_and_never_touches_editors_rows():
    ds = taxa_ds()
    ds["links"] = [{c: "" for c in dataset.schema.table("links").names} | r for r in [
        {"taxon_id": "ORRHI", "system": "editor", "value": "https://example.org/x", "label": "x"},
        {"taxon_id": "ORRHI", "system": "inaturalist", "value": "12", "confidence": "medium",
         "note": "matched by name"}]]
    want = wikidata.wanted(ds, ["ORRHI", "ORGIG"])
    assert want["ORRHI"] == ("P10585", "ORRHI", "Oryctes rhinoceros")
    found = {"ORRHI": {"item": "http://www.wikidata.org/entity/Q123", "name": "Oryctes rhinoceros",
                       "inat": "47001", "bg": "81746", "iucn": "Least Concern",
                       "image": "http://commons.wikimedia.org/wiki/Special:FilePath/Oryctes%20r.jpg",
                       "article": "https://en.wikipedia.org/wiki/Oryctes_rhinoceros",
                       "species": "https://species.wikimedia.org/wiki/Oryctes_rhinoceros",
                       "commons": {"coconut rhinoceros beetle", "CRB"}},
             "ORGIG": {"item": "http://www.wikidata.org/entity/Q9", "name": "Oryctes boas",
                       "commons": set()}}
    stats = wikidata.apply(ds, found, want, TODAY)
    links = {(r["taxon_id"], r["system"]): r for r in ds["links"]}
    assert links[("ORRHI", "wikidata")]["value"] == "Q123" and links[("ORRHI", "wikidata")]["confidence"] == "high"
    assert links[("ORRHI", "commons")]["value"] == "Oryctes r.jpg"
    assert links[("ORRHI", "editor")]["label"] == "x"                       # untouched
    assert ("ORRHI", "inaturalist") in links                                 # one of the two iNat rows
    assert links[("ORGIG", "wikidata")]["confidence"] == "review" and "Oryctes boas" in links[("ORGIG", "wikidata")]["note"]
    assert not any(r["taxon_id"] == "ORGIG" and r["system"] == "bugguide" for r in ds["links"])
    taxa = {r["id"]: r for r in ds["taxa"]}
    assert taxa["ORRHI"]["iucn"] == "Least Concern" and "CRB" in taxa["ORRHI"]["other_common_names"]
    assert stats["review"] == 1 and stats["items"] == 2


def test_bugguide_links_come_from_entobase_rows():
    ds = taxa_ds()
    ds["links"] = []
    out = bugguide.refresh(ds, ["ORRHI", "ORGIG"], TODAY, rows=[(1063, 81746, "Oryctes rhinoceros", "Species", "high")])
    assert out["linked"] == 1
    assert [(r["taxon_id"], r["value"]) for r in ds["links"] if r["system"] == "bugguide"] == [("ORRHI", "81746")]


def test_wikipedia_clean_drops_reference_sections_and_makes_links_absolute():
    html = ("<p>Lead <a href='/wiki/Beetle'>beetle</a>.</p><h2>Biology</h2><p>Eats palms.</p>"
            "<h2>References</h2><p>Smith 2001.</p>")
    out, text = wikipedia.clean(html)
    assert "https://en.wikipedia.org/wiki/Beetle" in out and "Smith" not in out
    assert "<h3>Biology</h3>" in out and "Eats palms" in text


def test_pick():
    ds = taxa_ds()
    ds["taxa"][3]["flag"] = "new"
    assert refresh.pick(ds, "new") == ["ORRHI"]
    assert len(refresh.pick(ds, "all")) == 5
    assert refresh.pick(ds, ["ORGIG", "nope"]) == ["ORGIG"]
