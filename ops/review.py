"""A review page for the curator: data/exports/review.html (local only: it quotes PDFs).

    uv run python ops/review.py [--sample 50] [--seed 1]

Sections: totals by source; a random sample of species with what each source says; doubtful
records (one or two GBIF records and nothing else, fossil groups, Wikidata name mismatches);
taxa that are in the tree only because of the literature; heading names in the PDFs that
GBIF could not match (old names, OCR errors, undescribed species). Links open the local
build (site/local), so `uv run guaminsects build local` first.
"""

import argparse
import html
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guaminsects import config, db  # noqa: E402

OUT = config.DATA_DIR / "exports" / "review.html"
SITE = "../../site/local/index.html"
AREAS = config.AREA_CODES
FOSSIL_ORDERS = {"Palaeodictyoptera", "Megasecoptera", "Protodonata", "Meganisoptera"}


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def link(tid, name) -> str:
    return f'<a href="{SITE}#/t/{tid}" target="_blank">{e(name)}</a>'


def table(head: list[str], rows: list[list]) -> str:
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) +
            "</table>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    conn = db.connect()
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    names = {t: r["name"] for t, r in taxa.items()}
    pres = defaultdict(lambda: defaultdict(dict))
    for r in conn.execute("SELECT taxon_id, area, source, records FROM taxon_presence"):
        pres[r["taxon_id"]][r["area"]][r["source"]] = r["records"]

    def family(tid):
        for x in taxa[tid]["lineage"].strip("/").split("/"):
            t = taxa.get(int(x))
            if t and t["rank"] == "Family":
                return t["name"]
        return ""

    def order(tid):
        for x in taxa[tid]["lineage"].strip("/").split("/"):
            t = taxa.get(int(x))
            if t and t["rank"] == "Order":
                return t["name"]
        return ""

    def cell(tid, area):
        p = pres[tid].get(area, {})
        bits = [f"{k[0].upper()}{v}" for k, v in sorted(p.items()) if v]
        return " ".join(bits)

    species = [t for t, r in taxa.items() if r["rank"] == "Species" and r["status"] != "synonym"]
    out = ['<!doctype html><meta charset="utf-8"><title>Review · Insects of Guam</title>',
           "<style>body{font:14px/1.45 system-ui;margin:24px;max-width:1300px}table{border-collapse:"
           "collapse;margin:8px 0 20px}td,th{border-bottom:1px solid #ddd;padding:3px 8px;text-align:"
           "left;vertical-align:top}th{background:#f3f6f8}h2{margin-top:32px}.m{color:#666}"
           "code{background:#f3f3f3;padding:0 3px}</style>",
           f"<h1>Review: Insects of Guam (and Micronesia)</h1><p class=m>Built {e(db.now())}. "
           "Cells: G = GBIF records, I = iNaturalist observations, P = Plazi checklists, "
           "D = documents in the PDF library (counts per area). Local only: do not publish.</p>"]

    # 1. totals
    by_src = Counter()
    for tid in species:
        for a in AREAS:
            for s in pres[tid].get(a, {}):
                by_src[(a, s)] += 1
    rows = [[a] + [by_src.get((a, s), 0) for s in ("gbif", "inat", "plazi", "pdf")] +
            [sum(1 for t in species if a in pres[t])] for a in AREAS]
    ranks = Counter(r["rank"] for r in taxa.values())
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    out.append("<h2>Totals</h2>" + table(["area", "GBIF", "iNat", "Plazi", "PDFs", "species, any source"], rows))
    out.append("<p>" + ", ".join(f"{n:,} {r}" for r, n in ranks.most_common()) + ". "
               f"Photos for {q('SELECT COUNT(DISTINCT taxon_id) FROM taxon_photos'):,} taxa; "
               f"Wikipedia for {q('SELECT COUNT(*) FROM wikipedia_articles'):,}; "
               f"BugGuide links for {q('SELECT COUNT(*) FROM bugguide_links'):,}; "
               f"{q('SELECT COUNT(*) FROM pdf_mentions'):,} PDF mentions.</p>")

    # 2. sample
    random.seed(args.seed)
    sample = sorted(random.sample(species, min(args.sample, len(species))),
                    key=lambda t: (order(t), family(t), names[t]))
    lit = Counter(r[0] for r in conn.execute("SELECT taxon_id FROM pdf_mentions"))
    photos = {r[0] for r in conn.execute("SELECT taxon_id FROM taxon_photos WHERE role = 'own'")}
    wiki = {r[0] for r in conn.execute("SELECT taxon_id FROM wikipedia_articles")}
    out.append(f"<h2>Random sample of {len(sample)} species (seed {args.seed})</h2>"
               "<p class=m>Is each name right, and is each island group right? Note anything odd "
               "in the curation file or the admin page.</p>")
    out.append(table(["order", "family", "species", *AREAS, "PDF mentions", "photo", "Wikipedia"],
                     [[e(order(t)), e(family(t)), link(t, names[t]),
                       *[cell(t, a) for a in AREAS], lit.get(t, ""), "yes" if t in photos else "",
                       "yes" if t in wiki else ""] for t in sample]))

    # 3. doubtful
    thin = []
    for t in species:
        srcs = {s for a in pres[t].values() for s in a}
        total = sum(v or 0 for a in pres[t].values() for v in a.values())
        if srcs == {"gbif"} and total <= 2:
            thin.append(t)
    bg = {r[0] for r in conn.execute("SELECT b.gbif_key FROM bugguide_links b")}
    na_thin = [t for t in thin if taxa[t]["gbif_key"] in bg]
    out.append(f"<h2>Doubtful records</h2><p>{len(thin):,} species rest on one or two GBIF records "
               "and nothing else. Of these, "
               f"{len(na_thin)} have a BugGuide page (a North American species), which makes a "
               "mislabelled specimen more likely. They are listed first.</p>")
    rows = [[link(t, names[t]), e(order(t)), e(family(t)),
             " ".join(f"{a}:{pres[t][a].get('gbif')}" for a in AREAS if a in pres[t]),
             "BugGuide" if t in na_thin else ""]
            for t in sorted(thin, key=lambda t: (t not in na_thin, order(t), names[t]))[:150]]
    out.append(table(["species", "order", "family", "GBIF records", ""], rows))
    fossil = [t for t, r in taxa.items() if r["rank"] == "Order" and r["name"] in FOSSIL_ORDERS]
    if fossil:
        out.append("<p><b>Fossil orders in the tree</b> (surely misidentified records; hide them?): " +
                   ", ".join(link(t, names[t]) for t in fossil) + "</p>")
    mism = conn.execute("SELECT w.gbif_key, w.name, t.taxon_id, t.name AS ours FROM wikidata_taxa w "
                        "JOIN taxa t ON t.gbif_key = w.gbif_key WHERE w.confidence = 'review'").fetchall()
    out.append(f"<p><b>Wikidata name mismatches</b> ({len(mism)}; their links are labelled, photos "
               "not used): " + "; ".join(f"{link(r['taxon_id'], r['ours'])} vs {e(r['name'])}"
                                       for r in mism) + "</p>")

    # 4. literature-only
    lit_only = [t for t in species if pres[t] and all(
        set(p) <= {"plazi", "pdf"} for p in pres[t].values())]
    out.append(f"<h2>In the tree only because of the literature ({len(lit_only)})</h2>"
               "<p class=m>Historical records the databases lack, or old names GBIF resolved to "
               "an accepted name. Check a few against the source.</p>")
    out.append(table(["species", "order", *AREAS],
                     [[link(t, names[t]), e(order(t)), *[cell(t, a) for a in AREAS]]
                      for t in sorted(lit_only, key=lambda t: (order(t), names[t]))[:300]]))

    # 5. unmatched heading names
    rows = conn.execute(
        "SELECT name, COUNT(*) n, GROUP_CONCAT(DISTINCT file) files, GROUP_CONCAT(DISTINCT areas) a, "
        "MIN(snippet) s FROM pdf_candidates WHERE gbif_key IS NULL GROUP BY name "
        "HAVING n >= 1 ORDER BY n DESC LIMIT 200").fetchall()
    genera = {r["name"] for r in taxa.values() if r["rank"] == "Genus"}
    rows = [r for r in rows if r["name"].split()[0] in genera]
    out.append(f"<h2>Species headings GBIF could not match, in genera we have ({len(rows)})</h2>"
               "<p class=m>Old combinations, misspellings, OCR errors, or species GBIF lacks. "
               "Real ones can be added as curated taxa (or as synonyms of a taxon we have).</p>")
    out.append(table(["heading name", "times", "documents", "areas", "context"],
                     [[e(r["name"]), r["n"], e((r["files"] or "")[:120]), e(r["a"]),
                       f'<span class=m>{e((r["s"] or "")[:200])}</span>'] for r in rows]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
