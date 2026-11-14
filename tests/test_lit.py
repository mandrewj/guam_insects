"""The literature tool: the name finder, apply, and add on a synthetic PDF (no copyrighted
text anywhere in the repository)."""

import shutil

import pytest

from guaminsects import dataset
from guaminsects.literature import finder, stage, text

TODAY = "2026-11-20"

PAGES = [
    {"page": 4, "method": "text", "text": (
        "   12. Oryctes gigas Castelnau\n   MARIANA IS. Guam: Agana, Tumon. Rota: Sinapalu. "
        "Introduced from Papua before 1950; first collected in 1984.\n"
        "   13. Callirhipis onoi Blair\n   Palau: Koror, Peleliu. Hosts: coconut palm.\n"
        "   14. Zorotypus guineensis Silvestri\n   Yap: Colonia.\n")},
    {"page": 5, "method": "ocr", "text": "Notes on Oryctes rhinoceros and O. gigas in the Marianas."},
]


def lexicon(world):
    return finder.Lexicon(dataset.load(world))


def test_the_finder_makes_accounts_mentions_and_unmatched_headings(world):
    found = finder.scan_pages(PAGES, lexicon(world), in_region=True)
    acc = {c["name"]: c for c in found["candidates"] if c["kind"] == "account"}
    assert set(acc) == {"Oryctes gigas", "Callirhipis onoi"}
    assert acc["Callirhipis onoi"]["islands"] == ["Koror", "Palau", "Peleliu"] and acc["Callirhipis onoi"]["areas"] == ["PW"]
    gigas = acc["Oryctes gigas"]
    assert gigas["taxon_id"] == "ORGIG" and gigas["areas"] == ["GU", "MP"]
    assert gigas["islands"] == ["Guam", "Rota"] and gigas["pages"] == [4]
    assert "first collected in 1984" in gigas["text"] and gigas["hints"]["years"] == [1950, 1984]
    assert "introduced" in gigas["hints"]["status_words"]
    mentions = {c["name"]: c for c in found["candidates"] if c["kind"] == "mention"}
    assert mentions["Oryctes rhinoceros"]["pages"] == [5] and mentions["Oryctes rhinoceros"]["method"] == "ocr"
    assert "Oryctes gigas" in mentions                       # "O. gigas" on page 5 (abbreviated)
    assert [u["name"] for u in found["unmatched"]] == ["Zorotypus guineensis"]
    assert found["unmatched"][0]["islands"] == ["Yap"]


def test_islands_need_context_when_the_name_is_a_common_word():
    assert finder.islands_in("Guam; Saipan: Garapan") == [("GU", "Guam"), ("MP", "Saipan")]
    assert finder.islands_in("the Arno of the river") == []          # ambiguous, no locality list
    assert ("MH", "Arno") in finder.islands_in("Majuro, Arno, Jaluit")


def test_a_section_ends_at_the_next_numbered_species():
    sec = finder.section_text("12. Aus bus Smith\nMARIANA IS. Guam: Agana.\n13. Aus cus (Jones)\nPALAU: Koror.\n")
    assert "Guam" in sec and "Koror" not in sec


def test_first_year_prefers_the_area():
    para = ("Aleurodicus dispersus Russell is a Neotropical species which was first noted in "
            "Hawaii in 1978. It arrived on Guam in 1981, most likely with ornamentals.")
    assert finder.first_year(para, "GU") == 1981


# ---------------------------------------------------------------- apply

def spec(**over):
    rec = {"taxon_id": "ORGIG", "kind": "account", "pages": [4], "areas": ["GU", "MP"],
           "islands": ["Guam", "Rota"], "status": "introduced", "status_area": ["GU"],
           "status_page": 4, "first_record_year": 1984, "name_printed": "Oryctes gigas",
           "hosts": ["coconut palm"],
           "notes": [{"topic": "biology", "text": "Larvae develop in rotting palm trunks.", "pages": "4"}]}
    return {"doc_id": "d1", "written_by": "a model", "records": [rec | over]}


def test_apply_writes_machine_rows_and_sets_an_unknown_nativity(world):
    ds = dataset.load(world)
    ds["literature"] = []
    ds["notes"] = []
    stats = stage.apply(ds, spec(), TODAY)
    assert stats["records"] == 1 and stats["notes"] == 1 and stats["hosts"] == 1
    assert stats["islands"] == 2 and stats["nativity_set"] == 1
    lit = ds["literature"][0]
    assert (lit["review"], lit["method"], lit["areas"], lit["status"], lit["first_record_year"]) == \
        ("machine", "text", "GU | MP", "introduced", "1984")
    assert ds["notes"][0]["note"] == "Larvae develop in rotting palm trunks."
    gigas = next(r for r in ds["taxa"] if r["id"] == "ORGIG")
    assert (gigas["nativity"], gigas["nativity_source"], gigas["nativity_review"]) == ("introduced", "d1", "machine")
    assert dataset.check(ds).items == []
    assert stage.apply(ds, spec(), TODAY)["records"] == 1          # again: the same rows, updated
    assert len([r for r in ds["literature"] if r["taxon_id"] == "ORGIG"]) == 1
    assert len([n for n in ds["notes"] if n["taxon_id"] == "ORGIG"]) == 1


def test_apply_never_overwrites_an_editors_value(world):
    ds = dataset.load(world)
    gigas = next(r for r in ds["taxa"] if r["id"] == "ORGIG")
    gigas.update(nativity="native", nativity_source="editor", nativity_review="editor")
    ds["literature"][0]["review"] = "editor"
    ds["notes"][0]["review"] = "editor"
    stats = stage.apply(ds, spec(), TODAY)
    assert gigas["nativity"] == "native" and stats["nativity_set"] == 0
    assert stats["records"] == 0 and "an editor confirmed that row" in stats["skipped"][0]
    assert ds["notes"][0]["note"] == "Breeds in rotting palm logs."


def test_a_merged_name_is_filed_under_its_taxon(world):
    ds = dataset.load(world)
    ds["literature"] = []
    stage.apply(ds, spec(taxon_id="gbif:2080570", status="", notes=[], hosts=[]), TODAY)
    assert ds["literature"][0]["taxon_id"] == "ORRHI"


def test_a_note_that_copies_the_document_is_refused(world):
    ds = dataset.load(world)
    doc_text = "Larvae develop in rotting palm trunks and the adults fly at dusk. " * 2
    stage.apply(ds, spec(notes=[{"topic": "biology", "pages": "4", "text":
                                 "Larvae develop in rotting palm trunks and the adults fly at dusk."}]), TODAY)
    problems = dataset.check(ds, lambda d: doc_text).items
    assert any("shares eight words" in p for p in problems)
    ds["notes"][-1]["note"] = "Grubs live in dead palm logs."
    assert dataset.check(ds, lambda d: doc_text).items == []


def test_a_bad_record_is_reported_not_written(world):
    ds = dataset.load(world)
    stats = stage.apply(ds, spec(taxon_id="NOPE"), TODAY)
    assert stats["records"] == 0 and "NOPE" in stats["skipped"][0]
    with pytest.raises(stage.ApplyError):
        stage.apply(ds, {"doc_id": "nope", "records": []}, TODAY)
    stage.apply(ds, spec(areas=["XX"]), TODAY)
    assert any("areas item 'XX'" in p for p in dataset.check(ds).items)


def test_citation_format():
    r = {"authors": "Linnavuori, R.", "year": "1960", "title": "Homoptera: Cicadellidae.",
         "container": "Insects of Micronesia", "volume": "6(5)", "pages": "231-344"}
    assert stage.citation(r) == "Linnavuori, R. 1960. Homoptera: Cicadellidae. Insects of Micronesia 6(5): 231-344."


# ---------------------------------------------------------------- a synthetic PDF

def make_pdf(path, lines):
    stream = "BT /F1 11 Tf 40 760 Td 13 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_text(out)


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler is not installed")
def test_add_extracts_text_and_drafts_a_document_row(world, tmp_path, monkeypatch):
    monkeypatch.setattr(text, "TEXT_DIR", tmp_path / "text")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    filler = [f"Line {i} of a synthetic page used only by the tests, with no real content." for i in range(8)]
    make_pdf(inbox / "Author 1990 - A synthetic paper.pdf", ["12. Oryctes gigas Castelnau",
                                                            "MARIANA IS. Guam: Agana."] + filler)
    ds = dataset.load(world)
    lib = tmp_path / "library"
    done = stage.add(ds, inbox, TODAY, library=lib, progress=lambda *_: None)
    assert done[0]["new"] and (lib / "inbox" / "Author 1990 - A synthetic paper.pdf").exists()
    row = ds["documents"][-1]
    assert row["doc_id"] == "author-1990-a-synthetic-paper" and row["year"] == "1990" and row["added_by"] == "lit add"
    # again: known by its content hash
    assert not stage.add(ds, inbox, TODAY, library=lib, progress=lambda *_: None)[0]["new"]
    monkeypatch.setattr(stage.config, "LITERATURE_DIR", lib)
    pages = stage.doc_pages(ds, row["doc_id"])
    assert pages[0]["page"] == 1 and "Oryctes gigas" in pages[0]["text"]
    staged = stage.scan(ds, row["doc_id"])
    assert staged["candidates"][0]["taxon_id"] == "ORGIG" and staged["candidates"][0]["kind"] == "account"
    stage.cite(ds, row["doc_id"], authors="Author, A.", container="A Journal", volume="3", pages="1-9", region="yes")
    stage.cite(ds, row["doc_id"], title="A synthetic paper")
    assert ds["documents"][-1]["citation"] == "Author, A. 1990. A synthetic paper. A Journal 3: 1-9."
