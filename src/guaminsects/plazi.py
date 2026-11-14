"""Clean up the Plazi documents (checklists Plazi digitised and GBIF serves).

Plazi's citations carry the uploader's user name as if it were an author ("Swezey O H, carolina
(1942)"), misspell some surnames, and list some papers twice. `clean` parses the real authors
out of each citation, fixes near-miss surnames against the surnames that occur elsewhere in
the bibliography, and writes a proper citation; `merge_duplicates` unites documents that are
the same paper (same year, first author and title, fuzzily), filing every row of the duplicate
under the one kept (a library document with its PDF wins).
"""

import re
from collections import Counter
from difflib import SequenceMatcher

from .dataset import join, split
from .match import _distance

USERNAME = re.compile(r"^[a-z][a-z0-9_\-]*$")        # an all-lowercase word: an uploader
CONTAINER = {"1942": ("Insects of Guam I", "Bernice P. Bishop Museum Bulletin 172"),
             "1946": ("Insects of Guam II", "Bernice P. Bishop Museum Bulletin 189")}


def _initials(given: str) -> str:
    return "".join(p[0].upper() + "." for p in re.split(r"[\s.\-]+", given) if p)


def parse_name(token: str) -> tuple[str, str] | None:
    """(surname, initials) from 'Swezey O H', 'O. H. Swezey', 'Ronald M. Clouse', or None for
    an uploader's user name or an artefact."""
    token = token.replace("·", "").strip()
    if not token or USERNAME.match(token):
        return None
    words = token.replace(".", " ").split()
    if len(words) == 1:
        return words[0].title() if words[0].isupper() else words[0], ""
    if all(len(w) == 1 for w in words[1:]):                    # Surname I I
        return (words[0].title() if words[0].isupper() else words[0]), _initials(" ".join(words[1:]))
    # Given names first: the last word is the surname
    return words[-1], _initials(" ".join(words[:-1]))


def authors_of(citation: str) -> list[tuple[str, str]]:
    head = re.split(r"\s*\(\d{4}\)", citation, maxsplit=1)[0]
    out = []
    for token in re.split(r",\s*", head):
        parsed = parse_name(token)
        if parsed and parsed[0]:
            out.append(parsed)
    return out


def surname_fixes(authors: list[list[tuple[str, str]]], known: Counter) -> dict[str, str]:
    """A surname that is one or two letters from a much more common one is a misspelling."""
    seen = Counter(s for a in authors for s, _ in a) + known
    fixes = {}
    for s, n in seen.items():
        near = [(c, m) for m, c in seen.items() if m != s and m[:1].lower() == s[:1].lower()
                and _distance(s.lower(), m.lower()) <= (1 if len(s) < 8 else 2) and c >= 3 * n and c >= 3]
        if near:
            fixes[s] = max(near)[1]
    return fixes


def format_authors(authors: list[tuple[str, str]]) -> str:
    return ", ".join(f"{s}, {i}".rstrip(", ") if i else s for s, i in authors)


def clean(ds, library_surnames: list[str] | None = None) -> dict:
    """Rewrite authors, citation (and the Insects of Guam container) of every Plazi document."""
    plazi = [d for d in ds["documents"] if d["doc_id"].startswith("plazi-")]
    parsed = {d["doc_id"]: authors_of(d["citation"]) for d in plazi}
    known = Counter()
    for d in ds["documents"]:
        if not d["doc_id"].startswith("plazi-"):
            for a in split(d["authors"].replace("; ", " | ")) or [d["authors"]]:
                m = re.match(r"([A-Z][\w'\-]+),", a.strip())
                if m:
                    known[m.group(1)] += 1
    fixes = surname_fixes(list(parsed.values()), known)
    changed = 0
    for d in plazi:
        year = (re.search(r"\((\d{4})\)", d["citation"]) or [None, d["year"]])[1]
        au = [(fixes.get(s, s), i) for s, i in parsed[d["doc_id"]]]
        d["authors"] = format_authors(au)
        d["year"] = year or d["year"]
        if year in CONTAINER and "Guam" in d["title"] + d["citation"] and not d["container"]:
            d["container"], d["volume"] = CONTAINER[year][0], ""
            d["pages"] = ""
        doi = d["doi"]
        d["citation"] = (f"{d['authors'].rstrip('.')}. " if d["authors"] else "") + f"{d['year']}. " + \
            d["title"].rstrip(".") + "." + (f" {d['container']}." if d["container"] else "") + \
            " Plazi taxonomic treatments database" + (f" (doi: {doi})" if doi else "") + "."
        changed += 1
    return {"documents": changed, "surname_fixes": fixes}


def _words(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def find_duplicates(ds, threshold: float = 0.85) -> list[tuple[str, str, float]]:
    """(drop, keep, title similarity): a Plazi document that is another document again (same
    year, same first surname within a letter or two, titles alike)."""
    docs = [d for d in ds["documents"] if d["year"]]
    first = {d["doc_id"]: (split(d["authors"].replace("; ", " | ").replace(", ", " | ", 0)) or [""])[0] for d in docs}
    out = []
    for d in docs:
        if not d["doc_id"].startswith("plazi-"):
            continue
        s1 = re.match(r"[^,]+", d["authors"] or "")
        for o in docs:
            if o is d or o["year"] != d["year"]:
                continue
            if o["doc_id"].startswith("plazi-") and o["doc_id"] > d["doc_id"]:
                continue                       # of two Plazi duplicates, the later id is dropped
            s2 = re.match(r"[^,;]+", o["authors"] or "")
            if not (s1 and s2) or _distance(s1.group(0).lower(), s2.group(0).strip().lower()) > 2:
                continue
            r = SequenceMatcher(None, _words(d["title"]), _words(o["title"])).ratio()
            if r >= threshold:
                out.append((d["doc_id"], o["doc_id"], round(r, 2)))
    _ = first
    best: dict[str, tuple] = {}
    for drop, keep, r in out:
        if drop not in best or r > best[drop][2]:
            best[drop] = (drop, keep, r)
    return list(best.values())


def merge(ds, drop: str, keep: str) -> int:
    """File everything that used document `drop` under `keep`, then remove `drop`."""
    docs = {d["doc_id"]: d for d in ds["documents"]}
    k, x = docs[keep], docs[drop]
    for f in ("doi", "url", "licence"):
        if not k[f] and x[f]:
            k[f] = x[f]
    by_key = {(r["taxon_id"], r["kind"]): r for r in ds["literature"] if r["doc_id"] == keep}
    moved = 0
    rows = []
    for r in ds["literature"]:
        if r["doc_id"] != drop:
            rows.append(r)
            continue
        moved += 1
        have = by_key.get((r["taxon_id"], r["kind"]))
        if have is None:
            r["doc_id"] = keep
            by_key[(r["taxon_id"], r["kind"])] = r
            rows.append(r)
            continue
        for col in ("areas", "islands", "pages"):
            have[col] = join(dict.fromkeys(split(have[col]) + split(r[col])))
        for col in ("status", "status_area", "first_record_year", "status_page", "name_printed"):
            if not have[col]:
                have[col] = r[col]
        if r["review"] == "editor" or have["review"] == "editor":
            have["review"] = "editor"
        elif not r["review"] or not have["review"]:
            have["review"] = have["review"] and r["review"]
    ds["literature"] = rows
    for table in ("notes", "hosts", "islands"):
        for r in ds[table]:
            if r["doc_id"] == drop:
                r["doc_id"] = keep
    seen: set = set()
    ds["islands"] = [r for r in ds["islands"] if (key := (r["taxon_id"], r["area"], r["island"],
                                                          r["source"], r["doc_id"])) not in seen and not seen.add(key)]
    for r in ds["taxa"]:
        if r["nativity_source"] == drop:
            r["nativity_source"] = keep
    ds["documents"] = [d for d in ds["documents"] if d["doc_id"] != drop]
    return moved
