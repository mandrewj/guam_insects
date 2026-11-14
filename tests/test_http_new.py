from guaminsects import http


def test_cache_lives_in_private_nosync():
    p = http.cache_path("https://api.gbif.org/v1/species/216")
    assert "private.nosync/api/api.gbif.org" in str(p)
