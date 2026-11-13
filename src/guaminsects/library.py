"""The catalogue of the PDF library: one row per file in literature/ with its citation.

sources/library.csv is the file the site cites from (git-tracked, hand-editable). `build`
fills it from three places and never overwrites a row a person has edited (`checked` = 1):

- Insects of Micronesia: Bishop Museum's index page (data/raw/bishopmuseum/iom.html), which
  lists every part with year, group, author, pages and its own PDF, which is the public URL
  the site links to. Local files are matched on volume, part and group ("IOM 6-5
  Membracidae.pdf" is 6(5), Membracidae).
- sources/documents.csv: fact sheets and papers downloaded by this project.
- Anything else in literature/: a row with the file name only, for a person to complete.
"""

import csv
import html
import re
from pathlib import Path

from . import config, documents

LIBRARY = config.SOURCES_DIR / "library.csv"
IOM_INDEX = config.RAW_DIR / "bishopmuseum" / "iom.html"
IOM_BASE = "https://hbs.bishopmuseum.org/pubs-online/"
COLUMNS = ["file", "kind", "authors", "year", "title", "series", "pages", "url", "scope",
           "hexapod", "checked", "note"]
# IOM parts that are not about hexapods (the site's scope is Hexapoda).
NON_HEXAPOD = ("Pseudoscorpionida", "Scorpionida", "Opiliones", "Ixodoidea", "Araneina",
               "Acarina", "Macrochaelidae", "Pauropoda", "Crustacea", "Map of area")


def parse_iom_index(text: str) -> list[dict]:
    """[{volume: '6(5)', year, group, title, authors, pages, url}] from the index page."""
    out = []
    for m in re.finditer(r"<strong>\s*Volume\s+([\d()]+)\s*\.?\s*</strong>(.*?)(?=<strong>\s*Volume|"
                         r"</td>|$)", text, re.S):
        volume, body = m.group(1), m.group(2)
        # One volume entry can hold several parts, each ending in its own [pdf] link.
        plain = re.sub(r'<a href="(pdf/[^"]+)">pdf</a>', r" @@\1@@ ", body)
        plain = html.unescape(re.sub(r"<[^>]+>", " ", plain))
        plain = re.sub(r"\s+", " ", plain).strip(" .")
        year_m = re.match(r"\.?\s*(\d{4})\.\s*(.*)", plain)
        if not year_m:
            continue
        year, rest = year_m.groups()
        group = None
        pieces = re.split(r"@@(pdf/[^@]+)@@", rest)
        texts, urls = pieces[0::2], pieces[1::2]
        for i, url in enumerate(urls):
            t = re.sub(r"^[\s.\[\]]+|[\s\[\]]+$", "", texts[i]).strip(" .")
            t = re.sub(r"\[?\s*Micronesica\s[^\]]*\]?", "", t).strip(" .[")
            pm = re.search(r"\s*[Pp]p\.\s*([\d\- ]+)", t)
            pages = pm.group(1).strip() if pm else ""
            head = t[:pm.start()] if pm else t
            # Authors run from the first "Surname, I." to the end: "Thornton, I.M.W., Lee,
            # S.S. & Chui, W.D." The subjects come before them, separated by full stops.
            am = AUTHOR_RE.search(head)
            authors = head[am.start():].strip(" .,[") if am else ""
            subjects = [p.strip(" ,.") for p in (head[:am.start()] if am else head).split(". ")
                        if p.strip(" ,.")]
            if not authors and len(subjects) > 1 and re.fullmatch(rf"[{UPPER}][\w'\-]+",
                                                                  subjects[-1]):
                authors = subjects.pop()            # "Lygaeidae. Barber." (no initials given)
            # "Gressitt, J.L. ix + 257 pp" (volumes 1 and 2 give a page count, not a range)
            pc = re.search(r"\s+([ivxl]+\s*\+\s*)?\d+\s*pp$", authors)
            if pc:
                pages, authors = pc.group(0).strip(), authors[:pc.start()].strip(" .")
            if i == 0 and len(subjects) > 1:
                group = subjects[0]
                subjects = subjects[1:]
            elif i == 0 and len(subjects) == 1 and not authors:
                pass
            title = ". ".join(subjects)
            out.append({"volume": volume, "year": year, "group": group or "", "title": title,
                        "authors": authors, "pages": pages,
                        "url": IOM_BASE + url})
    return out


UPPER = "A-ZÀ-ÖØ-Þ"
AUTHOR_RE = re.compile(rf"(?:^|[\s.,])([{UPPER}][\w'\-]+(?: [{UPPER}][a-z]+)?, (?:[{UPPER}]\.\s?)+)")
FILE_RE = re.compile(r"^IOM (\d+)(?:-(\d+))? (.+?)\.pdf$")


def match_iom(fname: str, entries: list[dict]) -> dict | None:
    m = FILE_RE.match(fname)
    if not m:
        return None
    vol = m.group(1) + (f"({m.group(2)})" if m.group(2) else "")
    words = [w for w in re.split(r"[\s,()]+", m.group(3).lower()) if len(w) > 3]
    cands = [e for e in entries if e["volume"] == vol]
    if len(cands) == 1:
        return cands[0]
    for e in cands:
        hay = f"{e['group']} {e['title']}".lower()
        if words and words[0][:6] in hay:
            return e
    return None


def build() -> dict[str, int]:
    old = {}
    if LIBRARY.exists():
        with LIBRARY.open(newline="", encoding="utf-8") as f:
            old = {r["file"]: r for r in csv.DictReader(f)}
    iom = parse_iom_index(IOM_INDEX.read_text(encoding="utf-8")) if IOM_INDEX.exists() else []
    docs = {r["file"]: r for r in documents.rows() if r["file"]}
    rows, stats = [], {"iom": 0, "documents": 0, "unknown": 0, "kept": 0}
    for pdf in sorted(config.LITERATURE_DIR.rglob("*.pdf")):
        rel = str(pdf.relative_to(config.LITERATURE_DIR))
        if old.get(rel, {}).get("checked") == "1":
            rows.append(old[rel])
            stats["kept"] += 1
            continue
        row = {c: "" for c in COLUMNS} | {"file": rel, "checked": "0", "hexapod": "1"}
        e = match_iom(pdf.name, iom)
        if e:
            row |= {"kind": "monograph", "authors": e["authors"], "year": e["year"],
                    "title": f"{e['group']}: {e['title']}" if e["group"] else e["title"],
                    "series": f"Insects of Micronesia {e['volume']}", "pages": e["pages"],
                    "url": e["url"], "scope": "Micronesia"}
            if any(w in row["title"] for w in NON_HEXAPOD):
                row["hexapod"] = "0"
            stats["iom"] += 1
        elif rel in docs:
            d = docs[rel]
            row |= {"kind": "fact sheet" if "fact sheet" in rel.lower() or "Pest" in rel
                    else "paper", "authors": d["authors"], "year": d["year"],
                    "title": d["title"], "series": d["series"] or d["publisher"],
                    "url": d["url"], "scope": scope_of(rel, d)}
            stats["documents"] += 1
        else:
            row["note"] = "complete by hand"
            stats["unknown"] += 1
        if rel in old and old[rel].get("note") and not row["note"]:
            row["note"] = old[rel]["note"]
        rows.append(row)
    LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    with LIBRARY.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return stats


ELSEWHERE = re.compile(r"\b(Hawai|Samoa|Florida|India|New Zealand|Fiji|Tonga|Papua|"
                       r"Philippine|Japan|Australia|Upolu|Nauru)", re.I)


def scope_of(rel: str, d: dict) -> str:
    """Which region a document's island mentions can stand for. A UOG sheet is about Guam;
    a Micronesica paper about Micronesia unless its title names somewhere else."""
    if rel.startswith(("UOG ", "checklists/")) or "Guam" in d["title"]:
        return "Guam"
    if ELSEWHERE.search(d["title"]):
        return "other"
    if "Micronesica" in d["publisher"] or "Micronesia" in d["title"]:
        return "Micronesia"
    return ""


def rows() -> list[dict]:
    with LIBRARY.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def citation(r: dict) -> str:
    """'Linnavuori, R. 1960. Homoptera: Cicadellidae. Insects of Micronesia 6(5): 231-344.'"""
    bits = []
    if r["authors"]:
        bits.append(r["authors"].rstrip("."))
    if r["year"]:
        bits.append(r["year"])
    head = ". ".join(bits) + ". " if bits else ""
    title = (r["title"] or Path(r["file"]).stem).rstrip(".")
    where = r["series"] + (f": {r['pages']}" if r["pages"] else "") if r["series"] else ""
    return f"{head}{title}." + (f" {where}." if where else "")
