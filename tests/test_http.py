from guaminsects.enrich.http import cache_path


def test_cache_path_is_readable_and_stable(tmp_path):
    p = cache_path("https://api.gbif.org/v1/species/match",
                   {"name": "Oryctes rhinoceros", "kingdom": "Animalia"}, root=tmp_path)
    assert p == tmp_path / "api.gbif.org/v1/species/match/kingdom=Animalia&name=Oryctes+rhinoceros.json"
    assert cache_path("https://api.gbif.org/v1/species/216", None, root=tmp_path) == \
        tmp_path / "api.gbif.org/v1/species/216/index.json"


def test_long_queries_are_hashed(tmp_path):
    params = [("taxonKey", k) for k in range(60)]
    p = cache_path("https://api.gbif.org/v1/occurrence/search", params, root=tmp_path)
    assert len(p.stem) == 24 and p.parent == tmp_path / "api.gbif.org/v1/occurrence/search"
