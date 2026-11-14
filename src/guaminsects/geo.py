"""Approximate island positions for the schematic island map (taxon page, identify tiles).

Decimal degrees, to about a tenth of a degree: enough to place a dot on a 330 px map of
Micronesia, not for anything else. Names match literature.ISLANDS and enrich/islands.py.
Each area also has `anchor` islands, lit faintly when the area has records but no island
is named.
"""

ISLAND_COORDS = {
    "GU": {"Guam": (13.45, 144.78)},
    "MP": {"Saipan": (15.18, 145.75), "Tinian": (15.0, 145.63), "Rota": (14.15, 145.2),
           "Aguijan": (14.85, 145.55), "Farallon de Medinilla": (16.02, 146.06),
           "Anatahan": (16.35, 145.68), "Sarigan": (16.7, 145.78), "Guguan": (17.31, 145.84),
           "Alamagan": (17.6, 145.83), "Pagan": (18.12, 145.77), "Agrihan": (18.77, 145.67),
           "Asuncion": (19.69, 145.41), "Maug": (20.02, 145.22), "Uracas": (20.54, 144.9),
           "Northern Islands (CNMI)": (18.1, 145.75)},
    "PW": {"Babeldaob": (7.5, 134.6), "Koror": (7.34, 134.48), "Malakal": (7.33, 134.45),
           "Ngerekebesang": (7.35, 134.44), "Ngeruktabel": (7.27, 134.4),
           "Mecherchar": (7.15, 134.36), "Peleliu": (7.0, 134.25), "Angaur": (6.91, 134.13),
           "Ngeaur": (6.91, 134.13), "Kayangel": (8.08, 134.72), "Sonsorol": (5.33, 132.22),
           "Tobi": (3.0, 131.17), "Helen Reef": (2.97, 131.8), "Palau": (7.5, 134.6)},
    "FM": {"Yap": (9.53, 138.13), "Ngulu": (8.3, 137.48), "Ulithi": (10.0, 139.7),
           "Fais": (9.76, 140.52), "Sorol": (8.13, 140.38), "Woleai": (7.37, 143.9),
           "Eauripik": (6.68, 143.05), "Ifalik": (7.25, 144.45), "Elato": (7.5, 146.17),
           "Lamotrek": (7.47, 146.37), "Satawal": (7.37, 147.03), "Puluwat": (7.36, 149.18),
           "Pulusuk": (6.69, 149.31), "Namonuito": (8.6, 150.0), "Chuuk": (7.42, 151.78),
           "Losap": (6.9, 152.73), "Mortlock Is.": (5.45, 153.6), "Nukuoro": (3.85, 154.95),
           "Kapingamarangi": (1.07, 154.78), "Pakin": (7.07, 157.8), "Pohnpei": (6.88, 158.22),
           "Mokil": (6.68, 159.77), "Pingelap": (6.22, 160.7), "Kosrae": (5.32, 162.98)},
    "MH": {"Enewetak": (11.45, 162.25), "Ujelang": (9.8, 160.9), "Bikini": (11.6, 165.4),
           "Rongelap": (11.2, 166.8), "Rongerik": (11.35, 167.45), "Wotho": (10.1, 166.0),
           "Ujae": (9.0, 165.7), "Kwajalein": (8.72, 167.73), "Lib": (8.3, 167.4),
           "Namu": (8.0, 168.2), "Ailinglaplap": (7.4, 168.75), "Jaluit": (6.0, 169.6),
           "Kili": (5.64, 169.12), "Namdrik": (5.6, 168.1), "Ebon": (4.6, 168.7),
           "Likiep": (9.9, 169.2), "Ailuk": (10.3, 169.9), "Utirik": (11.25, 169.8),
           "Mejit": (10.28, 170.88), "Wotje": (9.45, 170.0), "Maloelap": (8.7, 171.1),
           "Aur": (8.2, 171.1), "Majuro": (7.1, 171.2), "Arno": (7.08, 171.6),
           "Mili": (6.1, 171.9), "Marshall Is.": (8.0, 169.0)},
}
# Lit faintly when the area has records but no island named: the main islands.
ANCHORS = {"GU": ["Guam"], "MP": ["Saipan", "Tinian", "Rota"], "PW": ["Babeldaob", "Koror"],
           "FM": ["Yap", "Chuuk", "Pohnpei", "Kosrae"], "MH": ["Majuro", "Kwajalein", "Jaluit"]}
# The map's frame: longitude 130-173 E, latitude 0-21.5 N.
BOUNDS = {"west": 130.0, "east": 173.0, "south": 0.0, "north": 21.5}
# Aliases that are not separate dots on the map.
SKIP = {"Palau", "Marshall Is.", "Ngeaur", "Northern Islands (CNMI)"}


# The places a distribution tag can name (curation/annotations.csv, the editor): the five
# island groups by their short names, then every island. Name -> area code.
GROUPS = {"Guam": "GU", "CNMI": "MP", "Palau": "PW", "FSM": "FM", "Marshalls": "MH"}
PLACES = {**GROUPS, **{name: a for a, d in ISLAND_COORDS.items() for name in d
                       if name not in SKIP}}


def place_area(name: str) -> str | None:
    """The area code of a place a distribution tag names, or None if it is not a place."""
    return PLACES.get(name)


def for_meta() -> dict:
    return {"bounds": BOUNDS, "anchors": ANCHORS,
            "islands": [[a, name, lat, lon] for a, d in ISLAND_COORDS.items()
                        for name, (lat, lon) in d.items() if name not in SKIP],
            "alias": {"Palau": "Babeldaob", "Ngeaur": "Angaur", "Marshall Is.": "Majuro",
                      "Northern Islands (CNMI)": "Pagan"}}
