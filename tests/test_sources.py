import importlib.util
from pathlib import Path

from guaminsects.enrich.plazi import areas_of

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("micronesica_index",
                                              ROOT / "scripts/micronesica_index.py")
mic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mic)


def test_plazi_areas_come_from_the_title():
    assert areas_of("Sphingidae Of Guam") == ["GU"]
    assert areas_of("New ants (Hymenoptera: Formicidae) from Micronesia.") == []
    assert areas_of("Insects of the Mariana Islands") == []       # Guam is one of them
    assert areas_of("Records from Saipan and Rota") == ["MP"]
    assert areas_of("Beetles of Ponape and Palau") == ["PW", "FM"]


ARTICLE = """<div class="article_container"> <div class="article_description">
<div class="art_container"> <b>1.</b> <b>Miller, R.H.</b> <b>2019.</b> Aphidiid Parasitoids
Twenty Years Post-Release in the Mariana Islands. <i>Micronesica.</i> 2019-1: 1-5.
<i>Date Revised/Accepted: 16 October 2019.</i> </div> </div>
<div class="abstrat_descripation"> <div class="rtejustify"> Surveys of <em>Aphis</em>
parasitoids on Guam. </div> </div>
<a href="https://www.micronesica.org/sites/default/files/miller2019proofv1.pdf">Miller 2019</a>
</div>"""


def test_micronesica_article_parse_and_file_name():
    [a] = mic.parse_volume(ARTICLE)
    assert a["authors"] == "Miller, R.H." and a["year"] == "2019"
    assert a["title"] == "Aphidiid Parasitoids Twenty Years Post-Release in the Mariana Islands"
    assert a["pdf"].endswith("miller2019proofv1.pdf")
    assert mic.is_insect(a)
    assert mic.file_name(a) == ("Micronesica/Miller 2019 - Aphidiid Parasitoids Twenty Years "
                                "Post-Release in the Mariana Islands.pdf")
    assert mic.file_name(dict(a, authors="Moore, A.; Jackson, T.; Smith, B.")).startswith(
        "Micronesica/Moore et al. 2019 - ")
    assert not mic.is_insect({"title": "Reef fishes of Palau", "abstract": "Coral reef fish."})


def test_crop_pest_list_parsing():
    from guaminsects.enrich.croppests import canonical, distribution

    assert canonical("Aonidiella orientalis (Newstead)") == "Aonidiella orientalis"
    assert canonical("Dysmicoccus neobrevipes Beardsley") == "Dysmicoccus neobrevipes"
    assert distribution("B=xY=xT=xP=xM=x") == [("PW", "Palau"), ("FM", "Yap"), ("FM", "Chuuk"),
                                              ("FM", "Pohnpei")]      # M: Guam + CNMI, no area
    assert distribution("K=?Y=n") == [("FM", "Yap")]                 # '?' is unverified
    assert distribution("YP=x") == [("FM", "Yap"), ("FM", "Pohnpei")]
