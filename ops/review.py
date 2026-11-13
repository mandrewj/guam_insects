"""A review page for the curator: data/exports/review.html (local only: it quotes PDFs).

    uv run python ops/review.py [--sample 50] [--seed 1]

Sections: totals by source; a random sample of species with what each source says; doubtful
records (one or two GBIF records and nothing else, fossil groups, Wikidata name mismatches);
taxa that are in the tree only because of the literature; heading names in the PDFs that
GBIF could not match (old names, OCR errors, undescribed species). Links open the built
site (site/public), so `uv run guaminsects build` first.
"""

import argparse
import html
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guaminsects import config, db, ids  # noqa: E402

OUT = config.DATA_DIR / "exports" / "review.html"
SITE = "../../site/public/index.html"
AREAS = config.AREA_CODES
FOSSIL_ORDERS = {"Palaeodictyoptera", "Megasecoptera", "Protodonata", "Meganisoptera"}


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def link(tid, name) -> str:
    return f'<a href="{SITE}#/t/{ids.to_ext(tid)}" target="_blank">{e(name)}</a>'


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
    keys = db.keymap(conn)
    pres = defaultdict(lambda: defaultdict(dict))
    for r in conn.execute("SELECT taxon_id, area, source, records FROM taxon_presence"):
        tid = keys.get(r["taxon_id"])
        if tid is None or tid not in taxa:
            continue
        src = r["source"]
        if src == "gbif_backbone":
            if taxa[tid]["in_col"]:
                continue
            src = "gbif"
        cell = pres[tid][r["area"]]
        cell[src] = cell.get(src, 0) + (r["records"] or 0)

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
    lit = Counter(keys.get(r[0]) for r in conn.execute("SELECT taxon_id FROM pdf_mentions"))
    photos = {r[0] for r in conn.execute("SELECT taxon_id FROM taxon_photos WHERE role = 'own'")}
    wiki = {keys.get(r[0], r[0]) for r in conn.execute("SELECT taxon_id FROM wikipedia_articles")}
    out.append(f"<h2>Random sample of {len(sample)} species (seed {args.seed})</h2>"
               "<p class=m>Is each name right, and is each island group right? Note anything odd "
               "in curation/taxa.csv or taxonomy.csv.</p>")
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
    bg = {keys.get(r[0]) for r in conn.execute("SELECT b.gbif_key FROM bugguide_links b")}
    na_thin = [t for t in thin if t in bg]
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
    mism = conn.execute("SELECT w.name, t.taxon_id, t.name AS ours FROM taxon_wikidata w "
                        "JOIN taxa t USING (taxon_id) WHERE w.confidence = 'review'").fetchall()
    out.append(f"<p><b>Wikidata name mismatches</b> ({len(mism)}; their links are labelled, photos "
               "not used): " + "; ".join(f"{link(r['taxon_id'], r['ours'])} vs {e(r['name'])}"
                                       for r in mism) + "</p>")

    # 4. the Catalogue of Life switch: what to check
    not_col = [t for t, r in taxa.items() if not r["in_col"] and r["origin"] != "curated"]
    out.append(f"<h2>Not in the Catalogue of Life ({len(not_col)})</h2><p class=m>Names a "
               "source used that COL lacks, placed under the COL taxon their match found. Real "
               "taxa COL is missing, old combinations COL did not recognise, or misspellings. "
               "Merge one into a COL taxon with status synonym + accepted_id (or "
               "acceptedNameUsageID in taxonomy.csv).</p>")
    out.append(table(["taxon", "rank", "under", "family", "note", *AREAS],
                     [[link(t, names[t]), e(taxa[t]["rank"]), e(names.get(taxa[t]["parent_id"])),
                       e(family(t)), f'<span class=m>{e(taxa[t]["match_note"])}</span>',
                       *[cell(t, a) for a in AREAS]]
                      for t in sorted(not_col, key=lambda t: (order(t), family(t), names[t]))]))
    merged = conn.execute("SELECT n.*, t.name AS shown FROM taxon_names n JOIN taxa t USING "
                          "(taxon_id) WHERE n.kind IN ('spelling variant', 'same name') "
                          "ORDER BY t.name").fetchall()
    out.append(f"<h2>Merged by spelling ({len(merged)})</h2><p class=m>Shown as one taxon. "
               "Undo one with status accepted (and a parent) on the name's id.</p>")
    out.append(table(["name", "shown as", "kind", "note", "id"],
                     [[f"<i>{e(r['name'])}</i>", link(r["taxon_id"], r["shown"]), e(r["kind"]),
                       f'<span class=m>{e(r["note"])}</span>', e(ids.to_ext(r["name_id"]))]
                      for r in merged]))
    with_records = {x[0] for x in conn.execute("SELECT DISTINCT taxon_id FROM taxon_presence")}
    held = conn.execute("SELECT * FROM name_matches WHERE note LIKE '%held for review%' "
                        "ORDER BY name").fetchall()
    unplaced = [r for r in conn.execute("SELECT * FROM name_matches WHERE taxon = 0 AND "
                                        "(parent = 0 OR parent IS NULL) ORDER BY name")
                if r["key"] in with_records]
    out.append(f"<h2>Held or unplaced names ({len(held)} held, {len(unplaced)} unplaced)</h2>"
               "<p class=m>Held: a near spelling of a COL name in another genus (shown as its own "
               "taxon). Unplaced: no parent found, so not in the tree; add the parent by hand.</p>")
    out.append(table(["name", "rank", "match", "note", "id"],
                     [[f"<i>{e(r['name'])}</i>", e(r["rank"]), e(r["match_type"]),
                       f'<span class=m>{e(r["note"])}</span>', e(ids.to_ext(r["key"]))]
                      for r in list(held) + unplaced]))
    parents = {x["parent_id"] for x in taxa.values()}
    lonely = [t for t, r in taxa.items() if r["rank"] == "Family" and t not in parents]
    out.append(f"<h2>Families with no genus or species here ({len(lonely)})</h2><p class=m>"
               "Records identified only to family. Some are real; some are an older family "
               "concept (Rhipiceridae for Callirhipis): merge those into the right family.</p>")
    out.append(table(["family", "order", *AREAS],
                     [[link(t, names[t]), e(order(t)), *[cell(t, a) for a in AREAS]]
                      for t in sorted(lonely, key=lambda t: (order(t), names[t]))]))

    # 5. literature-only
    lit_only = [t for t in species if pres[t] and all(
        set(p) <= {"plazi", "pdf"} for p in pres[t].values())]
    out.append(f"<h2>In the tree only because of the literature ({len(lit_only)})</h2>"
               "<p class=m>Historical records the databases lack, or old names GBIF resolved to "
               "an accepted name. Check a few against the source.</p>")
    out.append(table(["species", "order", *AREAS],
                     [[link(t, names[t]), e(order(t)), *[cell(t, a) for a in AREAS]]
                      for t in sorted(lit_only, key=lambda t: (order(t), names[t]))[:300]]))

    # 6. unmatched heading names
    rows = conn.execute(
        "SELECT name, COUNT(*) n, GROUP_CONCAT(DISTINCT file) files, GROUP_CONCAT(DISTINCT areas) a, "
        "MIN(snippet) s FROM pdf_candidates WHERE gbif_key IS NULL GROUP BY name "
        "HAVING n >= 1 ORDER BY n DESC LIMIT 200").fetchall()
    genera = {r["name"] for r in taxa.values() if r["rank"] == "Genus"}
    rows = [r for r in rows if r["name"].split()[0] in genera]
    out.append(f"<h2>Species headings outside the hexapod genera COL knows ({len(rows)})</h2>"
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
