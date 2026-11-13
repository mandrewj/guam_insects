"""Names and island records from the PDF library.

For each hexapod document in sources/library.csv, page by page (data/pdf_text/):

1. **Known names.** Every binomial in the tree (and the verbatim names Plazi digitised, which
   are often the old combinations) found on the page is a mention.
2. **Abbreviated binomials.** "O. rhinoceros" counts when the page (or the document so far)
   has used a genus starting with O. that has that species.
3. **Species headings.** Monographs (Insects of Micronesia) give each species a heading line:
   "Oryctes rhinoceros (Linnaeus)" or "3. Callirhipis onoi Blair, 1940". A heading opens a
   section that runs to the next heading; the islands named in it are where the author
   records the species. Headings whose name is not in the tree are matched to GBIF and,
   when they are hexapods, become *literature-only* candidates: the historical records the
   occurrence databases lack.

Everything lands in `pdf_mentions` with `decision = 'pending'`; a person's accept/reject is
kept across re-runs (curation/pdf_decisions.csv). Snippets are stored for the local build
only and never published (CLAUDE.md rule 4).
"""

import csv
import json
import re
import sys
from collections import defaultdict

from . import config, db, library, pdftext

DECISIONS_CSV = config.CURATION_DIR / "pdf_decisions.csv"
DECISION_COLUMNS = ["file", "page", "name", "decision", "taxon_id", "editor", "edited", "note"]
SNIPPET = 220                  # characters either side, local build only

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


def load_decisions() -> dict[tuple[str, int, str], dict]:
    if not DECISIONS_CSV.exists():
        return {}
    with DECISIONS_CSV.open(newline="", encoding="utf-8-sig") as f:
        return {(r["file"], int(r["page"]), r["name"]): r for r in csv.DictReader(f)}


def lexicon(conn) -> tuple[dict[str, int], dict[str, set[str]]]:
    """name -> taxon id (tree binomials and Plazi verbatim names), genus -> epithets."""
    names: dict[str, int] = {}
    for r in conn.execute("SELECT taxon_id, name, accepted_id, status FROM taxa "
                          "WHERE rank IN ('Species', 'Subspecies')"):
        tid = r["accepted_id"] if r["status"] == "synonym" and r["accepted_id"] else r["taxon_id"]
        names[r["name"]] = tid
    tree = set(names.values())
    for r in conn.execute("SELECT name, nub_key FROM checklist_names WHERE rank IN "
                          "('SPECIES', 'SUBSPECIES')"):
        canon = canonical(r["name"] or "")
        if canon and r["nub_key"] in tree and canon not in names:
            names[canon] = r["nub_key"]
    for r in conn.execute("SELECT taxon_id, synonym FROM taxon_synonyms"):
        names.setdefault(r["synonym"], r["taxon_id"])
    genera: dict[str, set[str]] = defaultdict(set)
    for n in names:
        parts = n.split()
        if len(parts) >= 2:
            genera[parts[0]].add(parts[1])
    return names, genera


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


def scan(conn) -> dict[str, int]:
    names, genera = lexicon(conn)
    by_len = sorted(names, key=len, reverse=True)
    known_re = re.compile(r"\b(" + "|".join(re.escape(n) for n in by_len) + r")\b")
    decisions = load_decisions()
    docs = {r["file"]: r for r in library.rows() if r["hexapod"] == "1"}
    sha_of = {}
    for path in pdftext.TEXT_DIR.glob("*.jsonl"):
        with path.open() as f:
            first = f.readline()
        if first:
            rec = json.loads(first)
            sha_of[rec["file"]] = rec["sha256"]
    rows, candidates = [], defaultdict(list)
    stats = {"documents": 0, "mentions": 0, "headings": 0, "candidates": 0}
    for fname, doc in docs.items():
        if fname not in sha_of:
            continue
        stats["documents"] += 1
        in_region = doc["scope"] in ("Guam", "Marianas", "Micronesia")
        pages = list(pdftext.pages(sha_of[fname]))
        # Headings across the whole document, so a section can run over a page break.
        heads = []        # (page index, offset, name)
        for pi, pg in enumerate(pages):
            for m in HEADING_RE.finditer(pg["text"]):
                genus = re.sub(r"\s\(.*\)", "", m.group(1))
                sp = m.group(2)
                if sp in LATIN_STOP:
                    continue
                name = f"{genus} {sp}" + (f" {m.group(3)}" if m.group(3) and
                                          m.group(3) not in LATIN_STOP else "")
                heads.append((pi, m.start(), name))
        seen_genera: dict[str, str] = {}
        for pg in pages:
            text = pg["text"]
            found: dict[str, tuple[int, str]] = {}
            for m in known_re.finditer(text):
                found.setdefault(m.group(1), (m.start(), pg["method"]))
                seen_genera[m.group(1)[0]] = m.group(1).split()[0]
            for m in ABBREV_RE.finditer(text):
                g = seen_genera.get(m.group(1))
                if g and m.group(2) in genera.get(g, ()) and f"{g} {m.group(2)}" in names:
                    found.setdefault(f"{g} {m.group(2)}", (m.start(), "abbrev"))
            for name, (pos, method) in found.items():
                rows.append(_row(fname, pg, name, names[name], method, "mention", [], text, pos))
        # Sections: heading to next heading; their islands are the record.
        for i, (pi, off, name) in enumerate(heads):
            end_pi, end_off = (heads[i + 1][0], heads[i + 1][1]) if i + 1 < len(heads) \
                else (min(pi + 2, len(pages) - 1), None)
            chunk = pages[pi]["text"][off:] if end_pi > pi else pages[pi]["text"][off:end_off]
            for k in range(pi + 1, end_pi + 1):
                chunk += "\n" + (pages[k]["text"][:end_off] if k == end_pi else pages[k]["text"])
            chunk = chunk[:6000]
            isl = sorted(set(islands_in(chunk))) if in_region else []
            tid = names.get(name) or names.get(" ".join(name.split()[:2]))
            stats["headings"] += 1
            if tid:
                rows.append(_row(fname, pages[pi], name, tid, pages[pi]["method"], "heading",
                                 isl, pages[pi]["text"], off))
            else:
                candidates[name].append((fname, pages[pi]["page"], isl,
                                         _snippet(pages[pi]["text"], off)))
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM pdf_mentions")
        conn.executemany(
            "INSERT OR IGNORE INTO pdf_mentions (taxon_id, file, page, name_found, method, kind, "
            "areas, islands, snippet, decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["taxon_id"], r["file"], r["page"], r["name"], r["method"], r["kind"],
              ",".join(sorted({a for a, _ in r["islands"]})) or None,
              ",".join(sorted({i for _, i in r["islands"]})) or None, r["snippet"],
              decisions.get((r["file"], r["page"], r["name"]), {}).get("decision", "pending"),
              stamp) for r in rows])
        conn.execute("DELETE FROM pdf_candidates")
        conn.executemany(
            "INSERT INTO pdf_candidates (name, file, page, areas, islands, snippet, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(n, f, p, ",".join(sorted({a for a, _ in isl})) or None,
              ",".join(sorted({i for _, i in isl})) or None, s, stamp)
             for n, hits in candidates.items() for f, p, isl, s in hits])
    stats["mentions"] = len(rows)
    stats["candidates"] = len(candidates)
    print(", ".join(f"{k} {v}" for k, v in stats.items()), file=sys.stderr)
    return stats


def _snippet(text: str, pos: int) -> str:
    s = max(0, pos - SNIPPET)
    return re.sub(r"\s+", " ", text[s:pos + SNIPPET]).strip()


def _row(fname, pg, name, tid, method, kind, islands, text, pos) -> dict:
    return {"file": fname, "page": pg["page"], "name": name, "taxon_id": tid,
            "method": "ocr" if pg["method"] == "ocr" and method != "abbrev" else method,
            "kind": kind, "islands": islands, "snippet": _snippet(text, pos)}


def match_candidates(conn, client) -> dict[str, int]:
    """GBIF-match literature-only heading names; hexapods become candidate taxa."""
    from .enrich.gbif_checklist import fetch_taxa, match_name

    stats = {"genera": 0, "hexapod_genera": 0, "names": 0, "matched": 0, "in_tree": 0}
    names = [r[0] for r in conn.execute("SELECT DISTINCT name FROM pdf_candidates")]
    # Most heading-shaped lines that are not in the tree are prose ("Kopf und", "The
    # family"). Ask GBIF about each distinct first word as a genus first, which is one
    # request per genus, and only then about the species of the real hexapod genera.
    known = {r[0] for r in conn.execute(
        "SELECT canonical_name FROM gbif_taxa WHERE rank = 'GENUS' AND class_key IN (%s)"
        % ",".join(str(k) for k in config.HEXAPOD_CLASSES))}
    genera = {n.split()[0] for n in names}
    stats["genera"] = len(genera)
    hexapod_genera = set(genera & known)
    for g in sorted(genera - known):
        if len(g) < 4 or g.lower() in GERMAN_ENGLISH:
            continue
        if match_name(client, g, "GENUS"):
            hexapod_genera.add(g)
    stats["hexapod_genera"] = len(hexapod_genera)
    names = [n for n in names if n.split()[0] in hexapod_genera]
    keys = {}
    for name in names:
        stats["names"] += 1
        m = match_name(client, name, "SUBSPECIES" if len(name.split()) == 3 else "SPECIES")
        if m:
            keys[name] = m.get("acceptedUsageKey") or m.get("usageKey")
            stats["matched"] += 1
    with conn:
        conn.executemany("UPDATE pdf_candidates SET gbif_key = ? WHERE name = ?",
                         [(k, n) for n, k in keys.items()])
    fetch_taxa(conn, client, set(keys.values()))
    in_tree = {r[0] for r in conn.execute("SELECT taxon_id FROM taxa")}
    stats["in_tree"] = sum(k in in_tree for k in keys.values())
    return stats


def presence_rows(conn) -> int:
    """source='pdf' presence from section headings in regional documents with islands,
    and from GBIF-matched literature-only candidates. Rejected decisions are left out."""
    counts: dict[tuple[int, str], set[str]] = defaultdict(set)
    for r in conn.execute("SELECT taxon_id, file, areas FROM pdf_mentions WHERE kind = "
                          "'heading' AND areas IS NOT NULL AND decision != 'rejected'"):
        for a in r["areas"].split(","):
            counts[(r["taxon_id"], a)].add(r["file"])
    for r in conn.execute("SELECT gbif_key, file, areas FROM pdf_candidates WHERE gbif_key "
                          "IS NOT NULL AND areas IS NOT NULL AND decision != 'rejected'"):
        for a in r["areas"].split(","):
            counts[(r["gbif_key"], a)].add(r["file"])
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM taxon_presence WHERE source = 'pdf'")
        conn.executemany(
            "INSERT INTO taxon_presence (taxon_id, area, source, records, citation, fetched_at) "
            "VALUES (?, ?, 'pdf', ?, 'library', ?)",
            [(t, a, len(files), stamp) for (t, a), files in counts.items()])
    return len(counts)
