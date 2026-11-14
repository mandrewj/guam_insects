from guaminsects.sources import photos


def test_gbif_licences():
    ok = {"http://creativecommons.org/licenses/by-nc/4.0/": "cc-by-nc",
          "CC BY 4.0 (Creative Commons Attribution 4.0 International), "
          "https://creativecommons.org/licenses/by/4.0/": "cc-by",
          "CC BY-NC (Attribution-Non-Commercial)": "cc-by-nc",
          "http://creativecommons.org/licenses/by-sa/4.0/": "cc-by-sa",
          "http://creativecommons.org/publicdomain/zero/1.0/legalcode": "cc0"}
    for text, code in ok.items():
        assert photos.gbif_license(text) == code, text
    for text in ["http://creativecommons.org/licenses/by-nc-nd/4.0/", "All rights reserved",
                 "© Museum", "", None]:
        assert photos.gbif_license(text) is None, text


def test_gbif_images_take_the_image_licence_then_the_records():
    o = {"key": 9, "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
         "institutionCode": "NMNH", "catalogNumber": "USNMENT1",
         "media": [
             {"type": "StillImage", "format": "image/jpeg", "identifier": "https://m.org/a.jpg"},
             {"type": "StillImage", "format": "image/png",
              "identifier": "https://m.org/x_waveform.png"},
             {"type": "StillImage", "identifier": "https://m.org/b.jpg",
              "license": "http://creativecommons.org/licenses/by-nd/4.0/"},
             {"type": "StillImage", "rightsHolder": "Ann",
              "identifier": "https://inaturalist-open-data.s3.amazonaws.com/photos/42/original.jpg",
              "license": "http://creativecommons.org/licenses/by-nc/4.0/"}]}
    got = photos.gbif_photos(o, 5)
    assert [g["photo_id"] for g in got][1] == "inat:42" and len(got) == 2
    first, second = got
    assert first["source"] == "gbif" and first["licence"] == "cc0" and first["attribution"] == "NMNH · NMNH USNMENT1"
    assert first["display_url"].startswith(photos.GBIF_CACHE) and first["page_url"] == "https://www.gbif.org/occurrence/9"
    assert second["display_url"].endswith("/photos/42/large.jpg") and second["attribution"] == "© Ann"


def test_commons_licences_and_sizes():
    lic = lambda s: photos.commons_license({"LicenseShortName": {"value": s}})  # noqa: E731
    assert lic("CC BY-NC-ND 4.0") is None and lic("GFDL") is None
    assert photos.commons_size("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/"
                               "960px-X.jpg", 330).endswith("/330px-X.jpg")
