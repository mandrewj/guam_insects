#!/usr/bin/env python3
"""Index Micronesica (open access, CC BY-NC-ND) for insect papers and download their PDFs.

    uv run python scripts/micronesica_index.py index      # volume pages -> data/raw/micronesica/
    uv run python scripts/micronesica_index.py download   # insect papers -> literature/Micronesica/

robots.txt asks for Crawl-delay: 10, so every request waits 10 s (about 12 minutes for the
index, 10 s a paper). Volume pages are cached; a re-run only fetches what is missing. Rows
for the papers are appended to sources/documents.csv with readable file names
("Miller 2019 - Aphidiid parasitoids twenty years post-release in the Mariana Islands.pdf").
"""
import csv
import html
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guaminsects import config, documents  # noqa: E402

BASE = "https://www.micronesica.org"
CACHE = config.RAW_DIR / "micronesica"
OUT_DIR = "Micronesica"
DELAY = 10.5

# Title or abstract must mention one of these (whole words, case-insensitive).
INSECT_WORDS = r"""insects? insecta hexapoda entomolog\w* arthropods? coleoptera beetles? weevils?
 diptera flies mosquito(es)? culicidae drosophil\w* tephritid\w* hymenoptera ants? formicidae
 wasps? bees? lepidoptera butterfl\w+ moths? caterpillars? hemiptera heteroptera homoptera bugs?
 aphids? aphid\w* scales? mealybugs? coccoidea psyllids? whitefl\w+ leafhoppers? planthoppers?
 cicadas? thrips thysanoptera orthoptera crickets? grasshoppers? katydids? odonata dragonfl\w+
 damselfl\w+ termites? isoptera blattodea cockroach\w* mantodea phasmid\w* dermaptera earwigs?
 neuroptera lacewings? collembola springtails? psocoptera lice siphonaptera fleas? trichoptera
 caddisfl\w+ ephemeroptera mayfl\w+ strepsiptera parasitoids? pollinators? oryctes wasmannia
 """.split()
INSECT_RE = re.compile(r"\b(" + "|".join(INSECT_WORDS) + r")\b", re.I)


def get(http: httpx.Client, url: str) -> httpx.Response:
    r = http.get(url)
    time.sleep(DELAY)
    return r


def volume_urls(index_html: str) -> list[str]:
    return sorted({BASE + m for m in re.findall(r'href="(/volumes/[^"]+)"', index_html)})


def parse_volume(page: str) -> list[dict]:
    out = []
    for block in page.split('<div class="article_container">')[1:]:
        cite = re.search(r'<div class="art_container">(.*?)</div>', block, re.S)
        if not cite:
            continue
        text = html.unescape(re.sub(r"<[^>]+>|\s+", " ", cite.group(1))).strip()
        m = re.match(r"\d+\.\s+(?P<authors>.+?)\s+(?P<year>\d{4})[a-z]?\.\s+(?P<title>.+?)\s+"
                     r"Micronesica\.?\s*(?P<where>[^.]*)", text)
        abstract = re.search(r'<div class="abstrat_descripation">(.*?)</div>\s*</div>', block, re.S)
        pdf = re.search(r'href="(https://www\.micronesica\.org/sites/default/files/[^"]+\.pdf)"',
                        block, re.I)
        out.append({
            "citation": text, "authors": m["authors"] if m else "", "year": m["year"] if m else "",
            "title": m["title"].rstrip(".") if m else text, "where": m["where"].strip() if m else "",
            "abstract": html.unescape(re.sub(r"<[^>]+>|\s+", " ", abstract.group(1))).strip()
            if abstract else "",
            "pdf": pdf.group(1) if pdf else "",
        })
    return out


def is_insect(a: dict) -> bool:
    return bool(INSECT_RE.search(f"{a['title']} {a['abstract']}"))


def file_name(a: dict) -> str:
    authors = [x.strip() for x in re.split(r",?\s+and\s+|;\s*|,\s*(?=[A-Z][a-z]+,)", a["authors"])
               if x.strip()]
    first = authors[0].split(",")[0] if authors else "Anon"
    who = first if len(authors) == 1 else (f"{first} & {authors[1].split(',')[0]}"
                                           if len(authors) == 2 else f"{first} et al.")
    title = re.sub(r"[/:\\?*\"<>|]", "-", a["title"])
    title = title[:110].rsplit(" ", 1)[0] if len(title) > 110 else title
    return f"{OUT_DIR}/{who} {a['year']} - {title}.pdf"


def index(http: httpx.Client) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    top = CACHE / "volumes.html"
    if not top.exists():
        top.write_text(get(http, BASE + "/volumes").text)
    articles = []
    for url in volume_urls(top.read_text()):
        cache = CACHE / (url.rsplit("/", 1)[1] + ".html")
        if not cache.exists():
            r = get(http, url)
            if r.status_code != 200:
                print(f"  {r.status_code} {url}", file=sys.stderr)
                continue
            cache.write_text(r.text)
            print(f"  {url}", file=sys.stderr)
        articles += parse_volume(cache.read_text())
    return articles


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "index"
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120,
                      follow_redirects=True) as http:
        articles = index(http)
        insect = [a for a in articles if is_insect(a) and a["pdf"]]
        print(f"{len(articles)} articles, {len(insect)} about hexapods with a PDF",
              file=sys.stderr)
        with (CACHE / "insect_articles.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(insect[0]) + ["file"])
            w.writeheader()
            w.writerows(dict(a, file=file_name(a)) for a in insect)
        if cmd != "download":
            return 0
        have = {r["url"] for r in documents.rows()}
        new_rows = []
        for a in insect:
            if a["pdf"] in have:
                continue
            path = config.LITERATURE_DIR / file_name(a)
            if not path.exists():
                r = get(http, a["pdf"])
                if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    print(f"  {r.status_code} {a['pdf']}", file=sys.stderr)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
            new_rows.append({"file": file_name(a), "url": a["pdf"], "title": a["title"],
                             "authors": a["authors"], "year": a["year"],
                             "publisher": "Micronesica (University of Guam)",
                             "series": f"Micronesica {a['where']}".strip(),
                             "status": "downloaded", "note": "open access, CC BY-NC-ND"})
            with documents.MANIFEST.open("a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=documents.COLUMNS).writerow(new_rows[-1])
        print(f"{len(new_rows)} papers added", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
