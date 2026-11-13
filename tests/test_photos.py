from guaminsects.enrich import photos


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
    got = photos._gbif_photos(o, 5)
    assert [g[0] for g in got][1] == "inat:42" and len(got) == 2
    pid, source, page, display, thumb, lic, _url, attribution = got[0]
    assert source == "gbif" and lic == "cc0" and attribution == "NMNH · NMNH USNMENT1"
    assert display.startswith(photos.GBIF_CACHE) and page == "https://www.gbif.org/occurrence/9"
    assert got[1][3].endswith("/photos/42/large.jpg") and got[1][7] == "© Ann"
