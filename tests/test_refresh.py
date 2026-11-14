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


def test_inat_refresh_links_and_takes_inaturalist_common_names():
    ds = taxa_ds()
    ds["links"] = [{c: "" for c in dataset.schema.table("links").names} | r for r in [
        {"taxon_id": "ORRHI", "system": "inaturalist", "value": "47001", "confidence": "high", "note": "via Wikidata"}]]

    class Inat:
        def get(self, path, params=None):
            if path == "/taxa":
                if params["q"] != "Oryctes gigas":
                    return {"results": []}
                return {"results": [{"id": 9, "name": "Oryctes gigas", "rank": "species", "preferred_common_name": "Giant Rhino Beetle"},
                                    {"id": 10, "name": "Oryctes gigas", "rank": "genus"}]}
            ids = [int(x) for x in path.rsplit("/", 1)[1].split(",")]
            names = {47001: {"name": "Oryctes rhinoceros", "preferred_common_name": "Coconut Rhinoceros Beetle"},
                     9: {"name": "Oryctes gigas", "preferred_common_name": "Giant Rhino Beetle"}}
            return {"results": [{"id": i, "rank": "species", **names[i]} for i in ids]}

    stats = refresh.inat_refresh(ds, ["ORRHI", "ORGIG", "ORYCT"], Inat(), TODAY, progress=lambda *_: None)
    taxa = {r["id"]: r for r in ds["taxa"]}
    assert taxa["ORRHI"]["common_name"] == "Coconut Rhinoceros Beetle"
    assert taxa["ORRHI"]["other_common_names"] == ""            # the same name in another case is not kept twice
    assert taxa["ORGIG"]["common_name"] == "Giant Rhino Beetle"
    links = {(r["taxon_id"], r["system"]): r for r in ds["links"]}
    assert links[("ORGIG", "inaturalist")]["value"] == "9" and links[("ORGIG", "inaturalist")]["confidence"] == "high"
    assert stats["new_links"] == 1 and stats["common_names"] == 1
    assert dataset.check(ds).items == []
    # a Wikidata id that points at a different name is marked for review and gives no common name
    ds["links"][0]["value"] = "9"
    taxa["ORRHI"]["common_name"] = "Keep me"
    refresh.inat_refresh(ds, ["ORRHI"], Inat(), TODAY, progress=lambda *_: None)
    assert taxa["ORRHI"]["common_name"] == "Keep me" and ds["links"][0]["confidence"] == "review"


def test_plazi_authors_duplicates_and_container():
    from guaminsects import plazi

    blank = lambda **kw: {c: "" for c in dataset.schema.table("documents").names} | kw  # noqa: E731
    cite = lambda a, y, t: f"{a} ({y}). {t}. Plazi.org taxonomic treatments database."    # noqa: E731
    ds = taxa_ds()
    ds["documents"] = [
        blank(doc_id="swezey-1942-coleoptera", file="x.pdf", title="Miscellaneous families of Guam Coleoptera",
              authors="Swezey, O.H.", year="1942", container="Insects of Guam I", url="https://pub.example/1"),
        blank(doc_id="plazi-aaaaaaaa", title="Miscellaneous Families Of Guam Coleoptera", year="1942",
              citation=cite("Swezey O H, carolina", 1942, "Miscellaneous Families Of Guam Coleoptera"), doi="10.5281/z1"),
        blank(doc_id="plazi-bbbbbbbb", title="Sphingidae Of Guam", year="1942",
              citation=cite("Swezry O H, carolina", 1942, "Sphingidae Of Guam")),
        blank(doc_id="plazi-cccccccc", title="Bees of Guam", year="1942",
              citation=cite("Swezey O H, Williams F X, admin", 1942, "Bees of Guam")),
        blank(doc_id="plazi-dddddddd", title="New ants from Micronesia", year="2007",
              citation=cite("Clouse R M, Stierhof T", 2007, "New ants from Micronesia")),
        blank(doc_id="plazi-eeeeeeee", title="New ants from Micronesia.", year="2007",
              citation=cite("Clouse R M, plazi", 2007, "New ants from Micronesia.")),
    ]
    ds["literature"] = [{c: "" for c in dataset.schema.table("literature").names} | r for r in [
        {"taxon_id": "ORRHI", "doc_id": "plazi-aaaaaaaa", "kind": "checklist", "areas": "GU", "method": "plazi"},
        {"taxon_id": "ORRHI", "doc_id": "swezey-1942-coleoptera", "kind": "checklist", "areas": "GU | MP", "review": "editor", "method": "plazi"},
        {"taxon_id": "ORGIG", "doc_id": "plazi-aaaaaaaa", "kind": "checklist", "areas": "GU", "method": "plazi"}]]
    out = plazi.clean(ds)
    docs = {d["doc_id"]: d for d in ds["documents"]}
    assert docs["plazi-aaaaaaaa"]["authors"] == "Swezey, O.H."            # the uploader "carolina" is gone
    assert docs["plazi-bbbbbbbb"]["authors"] == "Swezey, O.H." and out["surname_fixes"] == {"Swezry": "Swezey"}
    assert docs["plazi-cccccccc"]["authors"] == "Swezey, O.H., Williams, F.X."
    assert docs["plazi-bbbbbbbb"]["container"] == "Insects of Guam I"
    assert docs["plazi-dddddddd"]["citation"].startswith("Clouse, R.M., Stierhof, T. 2007. New ants from Micronesia.")
    dups = {(d, k) for d, k, _ in plazi.find_duplicates(ds)}
    assert dups == {("plazi-aaaaaaaa", "swezey-1942-coleoptera"), ("plazi-eeeeeeee", "plazi-dddddddd")}
    moved = plazi.merge(ds, "plazi-aaaaaaaa", "swezey-1942-coleoptera")
    assert moved == 2
    lit = {(r["taxon_id"], r["doc_id"]): r for r in ds["literature"]}
    assert set(lit) == {("ORRHI", "swezey-1942-coleoptera"), ("ORGIG", "swezey-1942-coleoptera")}
    assert lit[("ORRHI", "swezey-1942-coleoptera")]["review"] == "editor"
    assert docs["swezey-1942-coleoptera"]["doi"] == "10.5281/z1"
    assert "plazi-aaaaaaaa" not in {d["doc_id"] for d in ds["documents"]}
    assert dataset.check(ds).items == []


def test_living_photos_go_first(tmp_path):
    ds = taxa_ds()
    ds["links"] = [{c: "" for c in dataset.schema.table("links").names} | {
        "taxon_id": "ORGIG", "system": "inaturalist", "value": "9", "confidence": "high"}]
    ds["photos"] = (photos.own_rows({"ORRHI": [cand("gbif:1:a", 5), cand("inat:7", 20), cand("commons:x.jpg", 30)]}, TODAY)
                    + photos.own_rows({"ORGIG": [cand("gbif:2:b", 5)]}, TODAY))
    for p in ds["photos"]:
        p["thumb"] = p["photo_id"].replace(":", "_") + ".webp"

    class Inat:
        def get(self, path, params=None):
            return {"results": [{"id": 9, "taxon_photos": [{"photo": {
                "id": 55, "license_code": "cc-by", "url": "https://s/square.jpg", "attribution": "© Ann",
                "original_dimensions": {"width": 900, "height": 600}}}, {"photo": {
                "id": 56, "license_code": "all-rights-reserved", "url": "https://s/square.jpg"}}]}]}

    class Bytes:
        def get_bytes(self, url):
            import io

            from PIL import Image
            b = io.BytesIO()
            Image.new("RGB", (400, 300), "green").save(b, "JPEG")
            return b.getvalue()

    media = tmp_path / "thumbs"
    stats = photos.prefer_living(ds, Inat(), Bytes(), TODAY, media=media, progress=lambda *_: None)
    order = lambda t: [p["photo_id"] for p in sorted(  # noqa: E731
        (p for p in ds["photos"] if p["taxon_id"] == t and p["role"] == "own"), key=lambda p: int(p["position"]))]
    assert order("ORRHI") == ["inat:7", "commons:x.jpg", "gbif:1:a"]            # tiers, stable
    assert order("ORGIG") == ["inat:55", "gbif:2:b"]                            # iNaturalist's licensed photo first
    assert stats["reordered"] == 1 and stats["replaced"] == 1 and stats["thumbs_made"] == 2
    thumbs = [p for p in ds["photos"] if p.get("thumb")]
    assert {p["position"] for p in thumbs} == {"0"}                              # only card photos keep a file
    assert sorted(f.name for f in media.glob("*.webp")) == sorted(p["thumb"] for p in thumbs)
    assert dataset.check(ds).items == []
