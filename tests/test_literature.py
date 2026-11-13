from guaminsects import library, literature
from guaminsects.enrich.photos import commons_license, commons_size
from guaminsects.site import card_thumb, clean_common, license_label


def test_islands_need_context_for_ambiguous_names():
    assert literature.islands_in("MARIANAS: Guam, Saipan, Rota.") == [
        ("GU", "Guam"), ("MP", "Saipan"), ("MP", "Rota")]
    # Lower-case "rota" is a word; capitalised, it is the island.
    assert literature.islands_in("the rota of collecting") == []
    assert literature.islands_in("Taken on Rota at light.") == [("MP", "Rota")]
    assert literature.islands_in("CAROLINES: Ponape, Kusaie; Truk: Moen.") == [
        ("FM", "Pohnpei"), ("FM", "Kosrae"), ("FM", "Chuuk"), ("FM", "Chuuk")]


def test_heading_lines():
    text = ("   12. Oryctes rhinoceros (Linnaeus)\n"
            "Callirhipis onoi Blair, 1940\n"
            "Culex annulirostris marianae Bohart and Ingram\n"
            "Larvae were found in rotting logs on Guam.\n"
            "The species is common.\n")
    names = [(m.group(1), m.group(2), m.group(3)) for m in literature.HEADING_RE.finditer(text)]
    assert ("Oryctes", "rhinoceros", None) in names
    assert ("Callirhipis", "onoi", None) in names
    assert ("Culex", "annulirostris", "marianae") in names
    assert not any(g == "Larvae" for g, _, _ in names)


def test_canonical_drops_authors_and_rank_words():
    assert literature.canonical("Cephonodes armatus subspecies marianna Rothschild and Jordan") \
        == "Cephonodes armatus marianna"
    assert literature.canonical("Herse convolvuli (Linnaeus 1758) Rothschild") == "Herse convolvuli"


def test_iom_index_entries():
    html = ('<strong>Volume 6(5).</strong>1960. Homoptera. Cicadellidae. Linnavuori, R. Pp. '
            '231-344 [<a href="pdf/iom6-5cicadell.pdf">pdf</a> ]. Membracidae. Kato, M. Pp. '
            '345-351 [<a href="pdf/iom6-5mem.pdf">pdf</a> ].<br />'
            '<strong>Volume 8(4)</strong>. 1972. Psocoptera. Thornton, I.M.W., Lee, S.S. &amp; '
            'Chui, W.D. Pp. 45-144 [<a href="pdf/iom8-4pso.pdf">pdf</a> ]')
    e = library.parse_iom_index(html)
    assert [(x["volume"], x["group"], x["title"], x["authors"], x["pages"]) for x in e] == [
        ("6(5)", "Homoptera", "Cicadellidae", "Linnavuori, R", "231-344"),
        ("6(5)", "Homoptera", "Membracidae", "Kato, M", "345-351"),
        ("8(4)", "", "Psocoptera", "Thornton, I.M.W., Lee, S.S. & Chui, W.D", "45-144")]
    assert e[1]["url"].endswith("pdf/iom6-5mem.pdf")
    assert library.match_iom("IOM 6-5 Membracidae.pdf", e) is e[1]
    row = {"authors": "Kato, M", "year": "1960", "title": "Homoptera: Membracidae",
           "series": "Insects of Micronesia 6(5)", "pages": "345-351", "file": "x.pdf"}
    assert library.citation(row) == ("Kato, M. 1960. Homoptera: Membracidae. "
                                     "Insects of Micronesia 6(5): 345-351.")


def test_commons_licences():
    lic = lambda s: commons_license({"LicenseShortName": {"value": s}})  # noqa: E731
    assert lic("CC BY-SA 4.0")[0] == "cc-by-sa"
    assert lic("CC BY 2.0")[0] == "cc-by"
    assert lic("Public domain")[0] == "cc0"
    assert lic("CC0")[0] == "cc0"
    assert lic("CC BY-NC-ND 4.0") is None
    assert lic("GFDL") is None
    assert commons_size("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/"
                        "960px-X.jpg", 330).endswith("/330px-X.jpg")


def test_site_helpers():
    assert clean_common("Coconut rhinoceros beetle, Asiatic rhinoceros beetle", "Oryctes") == \
        "Coconut rhinoceros beetle"
    assert clean_common("Oryctes rhinoceros", "Oryctes rhinoceros") is None
    assert license_label("cc-by-nc-sa") == "CC BY-NC-SA" and license_label("cc0") == "CC0"
    portrait = {"thumb": "p", "w": 600, "h": 900, "of_id": None}
    landscape = {"thumb": "l", "w": 900, "h": 600, "of_id": None}
    borrowed = {"thumb": "b", "w": 900, "h": 600, "of_id": 5}
    assert card_thumb([portrait, landscape]) == "l"
    assert card_thumb([portrait, borrowed]) == "p"     # never swap own for borrowed


def test_establishment_year_prefers_the_area():
    from guaminsects.establishment import PARAGRAPH, first_year

    para = ("Aleurodicus dispersus Russell, the spiralling whitefly, is a Neotropical species "
            "which was first noted in Hawaii in 1978. It arrived on Guam in 1981, most likely "
            "with ornamentals.")
    assert first_year(para, "GU") == 1981
    assert first_year("It was first collected in 1984 at which time it was abundant.", "GU") == 1984
    text = ("     Stenocatantops splendens (Thunberg) was first collected in 1984.\n"
            "     Thrips pa/mi Karny was first noted in Guam in 1983.")
    paras = PARAGRAPH.split(text)
    assert len(paras) == 2 and first_year(paras[0], "GU") == 1984


def test_pdf_decisions_survive_and_apply(tmp_path, monkeypatch):
    from guaminsects import db

    monkeypatch.setattr(literature, "DECISIONS_CSV", tmp_path / "pdf_decisions.csv")
    conn = db.connect(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO pdf_mentions (taxon_id, file, page, name_found, kind, areas) "
                 "VALUES (11, 'a.pdf', 3, 'Oryctes rhinoceros', 'heading', 'GU')")
    literature.presence_rows(conn)
    assert conn.execute("SELECT COUNT(*) FROM taxon_presence WHERE source = 'pdf'").fetchone()[0] == 1
    literature.decide(conn, "a.pdf", 3, "Oryctes rhinoceros", "rejected", "t")
    assert literature.load_decisions()[("a.pdf", 3, "Oryctes rhinoceros")]["decision"] == "rejected"
    assert conn.execute("SELECT COUNT(*) FROM taxon_presence WHERE source = 'pdf'").fetchone()[0] == 0
    literature.decide(conn, "a.pdf", 3, "Oryctes rhinoceros", "pending", "t")
    assert literature.load_decisions() == {}


def test_species_section_ends_at_the_next_numbered_species():
    text = ("12. Aus bus Smith\nMARIANA IS. Guam: Agana.\n13. Aus cus (Jones)\nPALAU: Koror.\n")
    sec = literature.section_text(text)
    assert "Guam" in sec and "Koror" not in sec
