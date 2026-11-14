"""English Wikipedia article text for linked taxa (CC BY-SA 4.0, attributed per revision).

The article comes from Wikidata's sitelink for the taxon's item (links.csv `wikipedia`, found
by COL or GBIF id, name checked), never from a title search, so disambiguation pages and
homonyms do not slip in. One TextExtracts request per article; reference-type sections are
dropped; articles are refreshed after REFRESH_DAYS. A 429 is "try again later", never
"missing" (docs/LESSONS.md). Writes dataset/wikipedia.jsonl.
"""

import re
import sys
import urllib.parse
from datetime import date

import httpx
from bs4 import BeautifulSoup, Tag

from ..dataset import tid as tid_order

ENWIKI = "https://en.wikipedia.org/w/api.php"
REFRESH_DAYS = 90
DROP_SECTIONS = re.compile(
    r"^(references?|notes?|citations?|footnotes?|sources?|bibliography|external links?|"
    r"see also|further reading|literature cited|works cited|gallery)$", re.I)
HEADING_SHIFT = {"h2": "h3", "h3": "h4", "h4": "h5", "h5": "h5", "h6": "h5"}
KEEP_TAGS = {"p", "ul", "ol", "li", "b", "i", "em", "strong", "sub", "sup", "br", "h3", "h4",
             "h5", "table", "tr", "td", "th", "tbody", "thead", "dl", "dt", "dd", "span",
             "a", "blockquote"}


def clean(html: str) -> tuple[str, str]:
    """Drop reference-type sections, empty paragraphs and attributes; demote headings."""
    doc = BeautifulSoup(f"<div>{html}</div>", "lxml").div
    out, skip_level = [], None
    for el in list(doc.children):
        if not isinstance(el, Tag):
            if str(el).strip():
                out.append(str(el))
            continue
        if el.name in ("h2", "h3", "h4", "h5", "h6"):
            level = int(el.name[1])
            if skip_level is not None and level > skip_level:
                continue
            skip_level = level if DROP_SECTIONS.match(el.get_text(strip=True)) else None
            if skip_level is not None:
                continue
            el.name = HEADING_SHIFT[el.name]
            el.attrs = {}
        elif skip_level is not None:
            continue
        if el.name == "p" and not el.get_text(strip=True):
            continue
        for t in el.find_all(True):
            if t.name not in KEEP_TAGS:
                t.unwrap()
                continue
            href = t.get("href", "")
            t.attrs = {}
            if t.name == "a":
                # Relative links would point into the site from file:// (and "#..." would
                # replace the route): make them absolute, open externally, or unwrap.
                if href.startswith("/wiki/"):
                    href = "https://en.wikipedia.org" + href
                if href.startswith(("http://", "https://")):
                    t.attrs = {"href": href, "target": "_blank", "rel": "noopener"}
                else:
                    t.unwrap()
        out.append(str(el))
    html_out = "\n".join(out).strip()
    text = BeautifulSoup(html_out, "lxml").get_text(" ", strip=True)
    return html_out, re.sub(r"\s+", " ", text)



def _query(client, title: str, intro_only: bool) -> dict:
    params = {"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
              "titles": title, "prop": "extracts|revisions|info",
              "rvprop": "ids|timestamp", "inprop": "url"}
    if intro_only:
        params["exintro"] = 1
    return (client.get(params=params).get("query", {}).get("pages") or [{}])[0]


def targets(ds, taxa: list[str] | None, today: str) -> list[tuple[str, str]]:
    """(taxon id, article URL) for taxa with a high-confidence Wikipedia link and no article
    fetched in the last REFRESH_DAYS."""
    fresh = {w["taxon_id"] for w in ds.wikipedia if w.get("retrieved") and
             (date.fromisoformat(today) - date.fromisoformat(w["retrieved"])).days < REFRESH_DAYS}
    want = set(taxa) if taxa is not None else None
    out = []
    for r in ds["links"]:
        if r["system"] == "wikipedia" and r["confidence"] == "high" and r["taxon_id"] not in fresh \
                and (want is None or r["taxon_id"] in want):
            out.append((r["taxon_id"], r["value"]))
    return sorted(out, key=lambda x: tid_order(x[0]))


def refresh(ds, taxa: list[str] | None, client, today: str, limit: int | None = None,
            progress=print) -> dict:
    stats = {"articles": 0, "missing": 0, "failed": 0, "lead_only": 0}
    todo = targets(ds, taxa, today)[:limit]
    have = {w["taxon_id"]: w for w in ds.wikipedia}
    for n, (tid, url) in enumerate(todo, 1):
        title = urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")
        lead_only = False
        try:
            page = _query(client, title, intro_only=False)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                stats["failed"] += 1
                continue
            try:
                page, lead_only = _query(client, title, intro_only=True), True
            except Exception:
                stats["failed"] += 1
                continue
        except Exception:
            try:
                page, lead_only = _query(client, title, intro_only=True), True
            except Exception:
                stats["failed"] += 1
                continue
        if page.get("missing") or not page.get("extract"):
            stats["missing"] += 1
            continue
        html, _text = clean(page["extract"])
        rev = (page.get("revisions") or [{}])[0]
        have[tid] = {"taxon_id": tid, "title": page["title"], "url": page.get("fullurl"),
                     "revid": rev.get("revid"), "rev_timestamp": rev.get("timestamp"),
                     "retrieved": today, "lead_only": lead_only, "html": html}
        stats["articles"] += 1
        stats["lead_only"] += lead_only
        if n % 50 == 0:
            progress(f"  Wikipedia: {n}/{len(todo)}")
    ds.wikipedia = list(have.values())
    return stats


_ = sys
