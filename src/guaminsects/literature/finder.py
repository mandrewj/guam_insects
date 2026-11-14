"""The name finder: names, species accounts, islands, status phrases, host and year hints.

For one document, page by page (private.nosync/pdf_text/):

1. **Known names.** Every binomial in the dataset (accepted names, merged names, GBIF and COL
   synonyms) found on a page is a *mention*.
2. **Abbreviated binomials.** "O. rhinoceros" counts when the document so far has used a genus
   starting with O. that has that species.
3. **Species accounts.** Monographs (Insects of Micronesia) give each species a heading line:
   "Oryctes rhinoceros (Linnaeus)" or "3. Callirhipis onoi Blair, 1940". A heading opens a
   section that runs to the next heading; the islands named in it are where the author
   records the species. Headings whose name the dataset lacks are *unmatched*: the skill
   passes them to `guaminsects match` (literature names enter only inside a genus COL or the
   dataset has).

The output is a staging file in private.nosync/staging/: one candidate per taxon and section
with its pages, islands and the section's text. The text is copyrighted like the PDFs
(CLAUDE.md rule 4): it stays in private.nosync/ and never reaches dataset/.
"""

import re
from collections import defaultdict

SECTION_MAX = 3000

# Island gazetteer: name variants in the 1950s-2010s literature -> (area, island).
ISLANDS = {
    "GU": {"Guam": "Guam", "Guahan": "Guam"},
    "MP": {"Saipan": "Saipan", "Tinian": "Tinian", "Rota": "Rota", "Aguijan": "Aguijan",
           "Aguiguan": "Aguijan", "Pagan": "Pagan", "Agrihan": "Agrihan", "Agrigan": "Agrihan",
           "Anatahan": "Anatahan", "Alamagan": "Alamagan", "Sarigan": "Sarigan",
           "Guguan": "Guguan", "Asuncion": "Asuncion", "Maug": "Maug", "Uracas": "Uracas",
           "Farallon de Pajaros": "Uracas", "Medinilla": "Farallon de Medinilla"},
    "PW": {"Palau": "Palau", "Belau": "Palau", "Babelthuap": "Babeldaob",
           "Babeldaob": "Babeldaob", "Koror": "Koror", "Peleliu": "Peleliu",
           "Angaur": "Angaur", "Kayangel": "Kayangel", "Malakal": "Malakal",
           "Arakabesan": "Ngerekebesang", "Ngerkebesang": "Ngerekebesang",
           "Urukthapel": "Ngeruktabel", "Ngeruktabel": "Ngeruktabel", "Eil Malk": "Mecherchar",
           "Sonsorol": "Sonsorol", "Tobi": "Tobi", "Helen Reef": "Helen Reef",
           "Aulupsechel": "Ngeaur"},
    "FM": {"Yap": "Yap", "Ulithi": "Ulithi", "Falalop": "Ulithi", "Woleai": "Woleai",
           "Fais": "Fais", "Ifaluk": "Ifalik", "Ifalik": "Ifalik", "Satawal": "Satawal",
           "Lamotrek": "Lamotrek", "Ngulu": "Ngulu", "Truk": "Chuuk", "Chuuk": "Chuuk",
           "Moen": "Chuuk", "Weno": "Chuuk", "Dublon": "Chuuk", "Tol": "Chuuk",
           "Udot": "Chuuk", "Fefan": "Chuuk", "Uman": "Chuuk", "Ponape": "Pohnpei",
           "Pohnpei": "Pohnpei", "Kusaie": "Kosrae", "Kosrae": "Kosrae", "Pingelap": "Pingelap",
           "Mokil": "Mokil", "Pakin": "Pakin", "Nukuoro": "Nukuoro",
           "Kapingamarangi": "Kapingamarangi", "Mortlock": "Mortlock Is.", "Losap": "Losap",
           "Namonuito": "Namonuito", "Puluwat": "Puluwat", "Pulusuk": "Pulusuk",
           "Eauripik": "Eauripik", "Elato": "Elato", "Sorol": "Sorol"},
    "MH": {"Marshall Is": "Marshall Is.", "Marshall Islands": "Marshall Is.",
           "Majuro": "Majuro", "Kwajalein": "Kwajalein", "Jaluit": "Jaluit", "Arno": "Arno",
           "Eniwetok": "Enewetak", "Enewetak": "Enewetak", "Bikini": "Bikini",
           "Likiep": "Likiep", "Wotje": "Wotje", "Ebon": "Ebon", "Ailinglaplap": "Ailinglaplap",
           "Mili": "Mili", "Maloelap": "Maloelap", "Rongelap": "Rongelap", "Utirik": "Utirik",
           "Ujae": "Ujae", "Namu": "Namu", "Wotho": "Wotho", "Mejit": "Mejit", "Aur": "Aur",
           "Ailuk": "Ailuk", "Lib": "Lib", "Kili": "Kili", "Ujelang": "Ujelang",
           "Namorik": "Namdrik", "Namdrik": "Namdrik", "Rongerik": "Rongerik"},
}
# Short or common words that are island names only in context: need a capital and a
# word boundary, and "Tol", "Lib", "Aur", "Arno", "Ebon", "Mili", "Fais" also need to sit in
# a locality list (next to another island or after a colon), handled in `islands_in`.
AMBIGUOUS = {"Tol", "Lib", "Aur", "Arno", "Ebon", "Mili", "Fais", "Namu", "Uman", "Moen",
             "Pagan", "Tobi", "Kili", "Ant", "Lae"}
_ISLAND_AREA = {name: (area, isl) for area, d in ISLANDS.items() for name, isl in d.items()}
ISLAND_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _ISLAND_AREA), key=len,
                                                reverse=True)) + r")\b")

BINOMIAL = r"([A-Z][a-z]{2,}(?:\s\([A-Z][a-z]+\))?)\s+([a-z]{3,}(?:-[a-z]+)?)"
# A heading line: optional number, binomial, optional subspecies, then an author (capital or
# parenthesis), and short overall. "n. sp." and "new species" headings count too.
HEADING_RE = re.compile(r"^\s{0,12}(?:\d{1,3}\.\s+)?" + BINOMIAL +
                        r"(?:\s+([a-z]{3,}))?\s+(?:\(?[A-Z][A-Za-z'\-]+|n\.\s*sp|new\s+sp)",
                        re.M)
ABBREV_RE = re.compile(r"\b([A-Z])\.\s+([a-z]{3,})\b")
LATIN_STOP = {"and", "the", "from", "with", "this", "that", "sp", "spp", "var", "nov", "new",
              "fig", "pl", "plate", "see", "near", "not", "was", "are", "were", "has", "its",
              "which", "male", "female", "larva", "pupa", "length", "type", "holotype",
              "paratype", "allotype", "collected", "specimens", "species", "genus", "described"}


# Capitalised words that start prose lines in the German and English monographs.
GERMAN_ENGLISH = {"typus", "prosternum", "endglied", "kopf", "zwischenraume", "seiten",
                  "vorderrand", "basis", "stirn", "brunner", "punktreihen", "committee", "glied",
                  "punktierung", "seitenrand", "skulptur", "epipleuren", "unter", "von", "auf",
                  "the", "this", "these", "those", "male", "female", "body", "head", "thorax",
                  "abdomen", "wing", "wings", "length", "color", "colour", "legs", "antenna",
                  "antennae", "specimens", "material", "holotype", "paratypes", "distribution",
                  "remarks", "type", "types", "larva", "pupa", "habitat", "host", "hosts",
                  "figure", "plate", "table", "museum", "island", "islands", "genus", "species"}


SECTION_MAX = 3000
# A species section also ends at the next numbered species line or genus line, even when the
# full heading pattern missed it (OCR, an unusual author format): otherwise one species
# takes the next one's islands.
SECTION_END = re.compile(r"\n\s{0,12}(?:\d{1,3}\.\s+[A-Z][a-z]{2,}\s+[a-z]{3,}|Genus\s+[A-Z][a-z]+\b|"
                         r"[A-Z][a-z]+\s+[a-z]{3,}\s+(?:n\.\s*sp|new\s+species))")


def section_text(chunk: str) -> str:
    """The account of one species: from its heading to the next species, at most
    SECTION_MAX characters. The heading's own line is skipped when looking for the end."""
    first_nl = chunk.find("\n")
    if first_nl < 0:
        return chunk[:SECTION_MAX]
    m = SECTION_END.search(chunk, first_nl)
    return chunk[:m.start()] if m and m.start() < SECTION_MAX else chunk[:SECTION_MAX]


def islands_in(text: str) -> list[tuple[str, str]]:
    """[(area, island)] named in a stretch of text, ambiguous names only in locality lists."""
    out = []
    for m in ISLAND_RE.finditer(text):
        name = m.group(1)
        if name in AMBIGUOUS:
            window = text[max(0, m.start() - 60):m.end() + 60]
            others = [x for x in ISLAND_RE.findall(window) if x != name]
            if not others and not re.search(r":\s*$", text[max(0, m.start() - 3):m.start()]):
                continue
        out.append(_ISLAND_AREA[name])
    return out



PARAGRAPH = re.compile(r"\n(?=\s{3,}[A-Z])")
OPENING = re.compile(r"\s*(?:\d+\.\s*)?" + BINOMIAL)
YEAR = re.compile(r"\b(?:first|initially)\b[^.]{0,80}?\b(?:in|by|during)\s+(1[89]\d\d|20\d\d)"
                  r"|\b(?:arrived|appeared|was found|was collected|was discovered|reached)"
                  r"\b[^.]{0,60}?\b(1[89]\d\d|20\d\d)")


AREA_WORDS = {"GU": r"Guam", "FM": r"Carolines?|Yap|Truk|Chuuk|Ponape|Pohnpei|Kosrae|Kusaie|"
                             r"Palau|Belau", "MH": r"Marshall"}


def first_year(para: str, area: str | None) -> int | None:
    """The year it was first noticed *here*: a sentence naming the area wins ("first noted
    in Hawaii in 1978 ... arrived on Guam in 1981" gives 1981 for Guam)."""
    sentences = re.split(r"(?<=[.;])\s+", para)
    want = re.compile(AREA_WORDS.get(area or "", r"$^"))
    for pick_local in (True, False):
        for sent in sentences:
            if pick_local and not want.search(sent):
                continue
            y = YEAR.search(sent)
            if y:
                return int(y.group(1) or y.group(2))
    return None




def canonical(name: str) -> str:
    """'Cephonodes armatus subspecies marianna Rothschild and Jordan' -> 'Cephonodes armatus marianna'."""
    words = re.sub(r"\b(subspecies|subsp\.|var\.|ssp\.)\s+", "", name).split()
    out = [w for w in words[:1] if w[:1].isupper()]
    for w in words[1:]:
        if re.fullmatch(r"[a-z][a-z\-]+", w) and w not in ("and", "et", "in", "de"):
            out.append(w)
        else:
            break
    return " ".join(out[:3])



STATUS_RE = re.compile(
    r"\b(introduced|adventive|alien|exotic|established|invasive|naturali[sz]ed|native|indigenous|"
    r"endemic|cryptogenic)\b", re.I)
HOST_RE = re.compile(
    r"\b(?:host plants?|hosts?|feeds? on|feeding on|reared from|infest(?:s|ing|ed)|attacks?|"
    r"damag(?:es|ing)|on)\s*:?\s+((?:[A-Z][a-z]{3,}\s+[a-z]{4,}|[a-z]+ (?:palm|tree|plant|bean|grass|"
    r"vine|leaves|fruit)s?)(?:,?\s*(?:and\s+)?(?:[A-Z][a-z]{3,}\s+[a-z]{4,}))*)")
YEAR_RE = re.compile(r"\b(1[89]\d\d|20[0-2]\d)\b")


class Lexicon:
    """name -> accepted taxon id, genus -> epithets, from the dataset."""

    def __init__(self, ds):
        self.names: dict[str, str] = {}
        taxa = {r["id"]: r for r in ds["taxa"]}
        for r in ds["taxa"]:
            if r["rank"] not in ("Species", "Subspecies") or " " not in r["name"]:
                continue
            target = r["accepted_id"] if r["status"] == "synonym" else r["id"]
            if target in taxa:
                self.names.setdefault(r["name"], target)
        accepted = set(self.names.values())
        for n in ds["names"]:            # GBIF and COL synonyms: binomials only
            if " " in n["name"] and n["taxon_id"] in accepted:
                self.names.setdefault(n["name"], n["taxon_id"])
        self.genera: dict[str, set[str]] = defaultdict(set)
        for n in self.names:
            parts = n.split()
            if len(parts) >= 2:
                self.genera[parts[0]].add(parts[1])
        self.pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(
            self.names, key=len, reverse=True)) + r")\b") if self.names else None


def hints(text: str) -> dict:
    """What a model should look at in a section: status words with their sentence, years, and
    host-plant-shaped phrases. Hints only: the skill decides (and paraphrases)."""
    sentences = re.split(r"(?<=[.;])\s+", re.sub(r"\s+", " ", text))
    status = []
    for s in sentences:
        m = STATUS_RE.search(s)
        if m:
            status.append(m.group(1).lower())
    years = sorted({int(y) for y in YEAR_RE.findall(text)})
    hosts = sorted({h.strip() for h in HOST_RE.findall(re.sub(r"\s+", " ", text))})[:12]
    return {"status_words": sorted(set(status)), "years": years[:20], "hosts": hosts}


def scan_pages(pages: list[dict], lex: Lexicon, in_region: bool) -> dict:
    """pages: [{page, method, text}]. Returns {"candidates": [...], "unmatched": [...]}.
    A candidate: {taxon_id, name, kind (account|mention), pages, areas, islands, method,
    text (private), hints}."""
    heads = []                                          # (page index, offset, name)
    for pi, pg in enumerate(pages):
        for m in HEADING_RE.finditer(pg["text"]):
            genus = re.sub(r"\s\(.*\)", "", m.group(1))
            sp = m.group(2)
            if sp in LATIN_STOP:
                continue
            heads.append((pi, m.start(), f"{genus} {sp}" + (
                f" {m.group(3)}" if m.group(3) and m.group(3) not in LATIN_STOP else "")))
    cands: dict[tuple[str, str], dict] = {}
    seen_genera: dict[str, str] = {}
    for pg in pages:
        text = pg["text"]
        found: dict[str, str] = {}
        if lex.pattern:
            for m in lex.pattern.finditer(text):
                found.setdefault(m.group(1), pg["method"])
                seen_genera[m.group(1)[0]] = m.group(1).split()[0]
        for m in ABBREV_RE.finditer(text):
            g = seen_genera.get(m.group(1))
            if g and m.group(2) in lex.genera.get(g, ()) and f"{g} {m.group(2)}" in lex.names:
                found.setdefault(f"{g} {m.group(2)}", "abbrev")
        for name, method in found.items():
            c = cands.setdefault((lex.names[name], "mention"), {
                "taxon_id": lex.names[name], "name": name, "kind": "mention", "pages": [],
                "areas": set(), "islands": set(), "methods": set(), "text": "", "hints": {}})
            if pg["page"] not in c["pages"]:
                c["pages"].append(pg["page"])
            c["methods"].add("ocr" if method == "ocr" else "text")
    unmatched: dict[str, dict] = {}
    for i, (pi, off, name) in enumerate(heads):
        end_pi, end_off = (heads[i + 1][0], heads[i + 1][1]) if i + 1 < len(heads) \
            else (min(pi + 2, len(pages) - 1), None)
        chunk = pages[pi]["text"][off:] if end_pi > pi else pages[pi]["text"][off:end_off]
        for k in range(pi + 1, end_pi + 1):
            chunk += "\n" + (pages[k]["text"][:end_off] if k == end_pi else pages[k]["text"])
        chunk = section_text(chunk)
        isl = sorted(set(islands_in(chunk))) if in_region else []
        tid = lex.names.get(name) or lex.names.get(" ".join(name.split()[:2]))
        page = pages[pi]["page"]
        if tid:
            c = cands.setdefault((tid, "account"), {
                "taxon_id": tid, "name": name, "kind": "account", "pages": [], "areas": set(),
                "islands": set(), "methods": set(), "text": "", "hints": {}})
        else:
            c = unmatched.setdefault(name, {"taxon_id": None, "name": name, "kind": "account",
                                            "pages": [], "areas": set(), "islands": set(),
                                            "methods": set(), "text": "", "hints": {}})
        if page not in c["pages"]:
            c["pages"].append(page)
        c["areas"] |= {a for a, _ in isl}
        c["islands"] |= {i for _, i in isl}
        c["methods"].add("ocr" if pages[pi]["method"] == "ocr" else "text")
        c["text"] += ("\n\n" if c["text"] else "") + chunk
    out = {"candidates": [], "unmatched": []}
    for group, key in ((cands.values(), "candidates"), (unmatched.values(), "unmatched")):
        for c in group:
            out[key].append({
                "taxon_id": c["taxon_id"], "name": c["name"], "kind": c["kind"],
                "pages": sorted(c["pages"]), "areas": sorted(c["areas"]),
                "islands": sorted(c["islands"]),
                "method": "ocr" if "ocr" in c["methods"] else "text",
                "text": c["text"], "hints": hints(c["text"]) if c["text"] else {}})
    # accounts first (they get notes), then mentions in passing, by taxon
    out["candidates"].sort(key=lambda c: (c["kind"] != "account", c["name"]))
    return out
