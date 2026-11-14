from guaminsects import dupes


def row(id_, name, rank="Species", parent="", authorship="", **kw):
    r = {"id": id_, "name": name, "rank": rank, "parent_id": parent, "authorship": authorship,
         "status": "accepted", "hidden": "", "gbif_key": "", "added_by": "", "verified": ""}
    r.update(kw)
    return r


def ds(*taxa, links=()):
    return {"taxa": list(taxa), "records": [], "literature": [], "photos": [], "links": list(links)}


def kinds(rows):
    return {(r["kind"], tuple(sorted((r["id_a"], r["id_b"])))) for r in rows}


def test_same_name_variant_and_recombination_are_found():
    fam = row("F", "Tenebrionidae", "Family")
    a = ds(fam,
           row("a1", "Alphitobius diaperinus", parent="F", authorship="(Panzer, 1797)"),
           row("a2", "Alphitobius  Diaperinus", parent="F", authorship="(Panzer, 1797)"),
           row("p1", "Polistes olivaceous", parent="F"),
           row("p2", "Polistes olivaceus", parent="F", authorship="(Degeer, 1773)"),
           row("m1", "Acalolepta marianarum", parent="F", authorship="(Aurivillius, 1908)"),
           row("m2", "Prosoplus marianarum", parent="F", authorship="Aurivillius, 1908"),
           row("b1", "Culex bicolor", parent="F", authorship="Giles, 1901"),
           row("b2", "Culex discolor", parent="F", authorship="Giles, 1901"))
    got = kinds(dupes.find(a))
    assert ("same-name", ("a1", "a2")) in got
    assert ("variant", ("p1", "p2")) in got
    assert ("recombination", ("m1", "m2")) in got
    assert not any(ids == ("b1", "b2") for _, ids in got)       # sister species, not a variant


def test_synonyms_and_hidden_taxa_are_left_out():
    a = ds(row("a1", "Aus bus"), row("a2", "Aus bus", status="synonym"), row("a3", "Aus bus", hidden="yes"))
    assert dupes.find(a) == []
