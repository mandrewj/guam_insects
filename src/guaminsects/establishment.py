"""Native or introduced: statements from sources, one row per source (never collapsed).

Two papers in the library are lists of introductions, one paragraph per species opening with
its name: Schreiner 1991 (insects established on Guam after World War II) and Nafus 1991
(new insects in the Carolines and Marshalls). A paragraph-opening name there is a statement
"introduced", usually with the year it was first noticed ("first collected in 1984"). Names
merely mentioned (a parasitoid, a related species) are not.

Rows: `establishment(taxon_id, area, status, source, citation, year, page, auto)`. The site
shows a curated value first (curation/taxa.csv `establishment`), else these statements
with their sources, marked as read by machine.
"""

import json
import re
import sys

from . import db, library, literature, pdftext

# (file in literature/, area it speaks for, or None to take the islands in the paragraph)
LISTS = [
    ("Micronesica/Schreiner 1991 - Sources of New Insects Established on Guam in the Post "
     "World War II Period.pdf", "GU"),
    ("Micronesica/Nafus 1991 - Movement of New Insects into the Carolines and Marshalls in "
     "Recent Years.pdf", None),
]
PARAGRAPH = re.compile(r"\n(?=\s{3,}[A-Z])")
OPENING = re.compile(r"\s*(?:\d+\.\s*)?" + literature.BINOMIAL)
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


def scan(conn, client=None) -> dict[str, int]:
    """`client` (a GBIF ApiClient) also matches paragraph names that are not in the tree."""
    names, _ = literature.lexicon(conn)
    docs = {r["file"]: r for r in library.rows()}
    sha = {}
    for p in pdftext.TEXT_DIR.glob("*.jsonl"):
        with p.open() as f:
            line = f.readline()
        if line:
            rec = json.loads(line)
            sha[rec["file"]] = rec["sha256"]
    rows, unmatched = [], []
    for fname, area in LISTS:
        if fname not in sha:
            print(f"  not extracted yet: {fname}", file=sys.stderr)
            continue
        doc = docs.get(fname, {})
        cite = library.citation(doc) if doc else fname
        pages = list(pdftext.pages(sha[fname]))
        for pg in pages:
            # Paragraphs first (an indented line starting with a capital), then the name
            # that opens each: a paragraph whose name OCR garbled ("Thrips pa/mi") must end
            # the one before it, not run into it.
            for para in PARAGRAPH.split(pg["text"]):
                m = OPENING.match(para)
                if not m:
                    continue
                para = para[:1500]
                genus = re.sub(r"\s\(.*\)", "", m.group(1))
                name = f"{genus} {m.group(2)}"
                tid = names.get(name)
                if not tid and client is not None and genus.lower() not in \
                        literature.GERMAN_ENGLISH and m.group(2) not in literature.LATIN_STOP:
                    from .enrich.gbif_checklist import match_name

                    hit = match_name(client, name, "SPECIES")
                    tid = hit and (hit.get("acceptedUsageKey") or hit.get("usageKey"))
                if not tid:
                    unmatched.append((name, fname, pg["page"]))
                    continue
                areas = [area] if area else sorted({a for a, _ in literature.islands_in(para)}
                                                   - {"GU", "MP", "PW"})
                for a in areas:
                    rows.append((tid, a, "introduced", fname, cite, first_year(para, a),
                                 pg["page"]))
    stamp = db.now()
    with conn:
        conn.execute("DELETE FROM establishment WHERE auto = 1")
        conn.executemany(
            "INSERT OR REPLACE INTO establishment (taxon_id, area, status, source, citation, "
            "year, page, auto, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            [(*r, stamp) for r in rows])
    if client is not None:            # taxa matched here may be new to us: fetch them
        from .enrich.gbif_checklist import fetch_taxa

        fetch_taxa(conn, client, {r[0] for r in rows})
    stats = {"statements": len(rows), "taxa": len({r[0] for r in rows}),
             "unmatched": len(unmatched)}
    print(", ".join(f"{k} {v}" for k, v in stats.items()), file=sys.stderr)
    for n, f, p in unmatched[:40]:
        print(f"  unmatched: {n} ({f.split('/')[-1][:30]} p.{p})", file=sys.stderr)
    return stats
