"""The search tokenizer and the postings format for the static app (ported from entobase; the
tokenizer must not drift: ops/check_site.py checks it against webapp/assets/app.js).

`build/search.py` writes the indexes: data/s/names.js (as-you-type suggestions) and one
full-text shard per first character of a term, each mapping term -> postings "id:tf,id:tf"
with ids delta-encoded in base 36 (tf omitted when 1). The browser tokenizes queries with the
same rules (`tokens` in app.js); the stopword list is shipped in meta.js.
"""

import re
import unicodedata
from collections import Counter, defaultdict

STOPWORDS = sorted(set("""
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has
have having he her here hers him his how i if in into is it its itself just may me might more most
my no nor not now of off on once only or other our ours out over own same she should so some such
than that the their theirs them then there these they this those through to too under until up
upon us very was we were what when where which while who whom why will with would you your yours
""".split()))
NAME_WEIGHT = 5          # a word in the taxon's names counts as much as 5 occurrences in text
SPLIT_RE = re.compile(r"[^a-z0-9]+")
TAG_RE = re.compile(r"<[^>]+>")
_STOP = set(STOPWORDS)
JS_GLOBAL = "guaminsects"


def fold(text: str) -> str:
    """Lowercase and strip accents: 'Mécoptères' -> 'mecopteres'."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def stem(t: str) -> str:
    """Tiny plural stripper, mirrored exactly in app.js."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("sses"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokens(text: str) -> list[str]:
    return [stem(t) for t in SPLIT_RE.split(fold(text)) if len(t) >= 2 and t not in _STOP]


def b36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            return out


def encode_postings(postings: dict[int, int]) -> str:
    parts, prev = [], 0
    for tid in sorted(postings):
        tf = postings[tid]
        parts.append(b36(tid - prev) + (f":{tf}" if tf != 1 else ""))
        prev = tid
    return ",".join(parts)


def _names(r: dict) -> list[str]:
    """Common names, then synonyms: an old name finds the taxon under its current one."""
    out = []
    for c in (r["common"], (r.get("inat") or {}).get("common"), *r.get("alt_common", []),
              *r.get("synonyms", [])):
        if c and c.lower() not in {x.lower() for x in out}:
            out.append(c)
    return out


def documents(conn, records: dict[int, dict]) -> dict[int, Counter]:
    """Weighted term counts per taxon: names (x NAME_WEIGHT), then the text the page shows
    (notes, section prose, literature titles). Wikipedia and PDF text join as they arrive."""
    docs: dict[int, Counter] = defaultdict(Counter)
    for tid, r in records.items():
        for t in tokens(" ".join([r["name"], *_names(r)])):
            docs[tid][t] += NAME_WEIGHT
        text = [r.get("note") or ""]
        text += [TAG_RE.sub(" ", s["html"]) for s in r.get("sections", [])]
        text += [w["title"] for w in r.get("literature", [])]
        if r.get("wikipedia"):
            text.append(TAG_RE.sub(" ", r["wikipedia"].get("html") or ""))
        for t in tokens(" ".join(text)):
            docs[tid][t] += 1
    return docs


def _context(r: dict) -> str:
    """'Coleoptera › Scarabaeidae' for display beside a name suggestion."""
    return " › ".join(a["name"] for a in r["lineage"] if a["rank"] in ("Order", "Family"))
