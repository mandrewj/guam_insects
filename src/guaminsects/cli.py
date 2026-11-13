"""Command-line entry point: `uv run guaminsects <command>`."""

import argparse
import csv
import sys

from . import config, curation, db


def gbif_client():
    from .enrich.http import ApiClient
    from .enrich.gbif_checklist import GBIF

    return ApiClient(GBIF, min_interval=0.34)        # ≤3 requests/s (CLAUDE.md rule 2)


def cmd_checklist(args) -> int:
    """GBIF presence sweep: hexapod taxon keys with records in each area."""
    from .enrich import gbif_checklist

    conn = db.connect()
    client = gbif_client()
    gbif_checklist.sweep(conn, client, args.area or None)
    print(f"{client.requests} GBIF requests")
    return 0


def cmd_taxa(args) -> int:
    """Fetch GBIF taxon records for every present or curated key and their ancestors."""
    from .enrich import gbif_checklist

    conn = db.connect()
    cur = curation.load()
    keys = gbif_checklist.present_keys(conn) | set(config.HEXAPOD_CLASSES)
    keys |= {int(r["taxon_id"]) for r in cur.rows if int(r["taxon_id"]) < config.CURATED_ID_BASE}
    keys |= {int(e["taxon_id"]) for e in cur.evidence
             if int(e["taxon_id"]) < config.CURATED_ID_BASE}
    client = gbif_client()
    n = gbif_checklist.fetch_taxa(conn, client, keys, refresh=args.refresh)
    print(f"{n} taxa stored, {client.requests} GBIF requests")
    return 0


def cmd_inat(args) -> int:
    """iNaturalist species counts per area, then GBIF keys for their names."""
    from .enrich import inat_counts
    from .enrich.http import ApiClient

    conn = db.connect()
    if not args.link_only:
        inat = ApiClient(inat_counts.INAT, min_interval=1.0)
        inat_counts.sweep(conn, inat)
        print(f"{inat.requests} iNat requests")
    if args.sweep_only:
        return 0
    gbif = gbif_client()
    stats = inat_counts.link_to_gbif(conn, gbif)
    print(f"iNat names: {stats['matched']} matched to GBIF, {stats['unmatched']} not; "
          f"{gbif.requests} GBIF requests")
    return 0


def cmd_plazi(args) -> int:
    """Literature checklists digitised by Plazi (Insects of Guam 1942-46 and others)."""
    from .enrich import gbif_checklist, plazi

    conn = db.connect()
    client = gbif_client()
    plazi.sweep(conn, client)
    n = gbif_checklist.fetch_taxa(conn, client, plazi.unknown_keys(conn))
    print(f"{n} new GBIF taxa fetched; {client.requests} GBIF requests")
    return 0


def cmd_resolve(args) -> int:
    """Rebuild the taxa table from GBIF + curation/*.csv."""
    conn = db.connect()
    try:
        cur = curation.load()
        stats = curation.resolve(conn, cur)
    except curation.CurationError as e:
        print(f"curation problems:\n{e}", file=sys.stderr)
        return 1
    if cur.assigned:
        print(f"gave {cur.assigned} new taxa ids (written to curation/taxa.csv)")
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def checklist_rows(conn) -> list[dict]:
    pres = {}
    for r in conn.execute("SELECT taxon_id, area, source, records FROM taxon_presence"):
        pres.setdefault(r["taxon_id"], {})[(r["area"], r["source"])] = r["records"]
    names = {r["taxon_id"]: r for r in conn.execute("SELECT taxon_id, rank, name FROM taxa")}
    out = []
    for t in conn.execute("SELECT * FROM taxa ORDER BY lineage"):
        anc = [names[int(x)] for x in t["lineage"].strip("/").split("/")]
        by_rank = {a["rank"]: a["name"] for a in anc}
        row = {"taxon_id": t["taxon_id"], "rank": t["rank"], "name": t["name"],
               "authorship": t["authorship"] or "", "class": by_rank.get("Class", ""),
               "order": by_rank.get("Order", ""), "family": by_rank.get("Family", ""),
               "status": t["status"], "origin": t["origin"], "hidden": t["hidden"],
               "common_name": t["common_name"] or ""}
        p = pres.get(t["taxon_id"], {})
        for a in config.AREA_CODES:
            row[f"{a}_gbif"] = p.get((a, "gbif"), "")
            row[f"{a}_inat"] = p.get((a, "inat"), "")
        out.append(row)
    return out


def cmd_export(args) -> int:
    """Write the resolved checklist to a CSV for reading (edits go in curation/taxa.csv)."""
    conn = db.connect()
    rows = checklist_rows(conn)
    if args.rank:
        rows = [r for r in rows if r["rank"] in args.rank]
    out = args.out or str(config.DATA_DIR / "exports" / "checklist.csv")
    from pathlib import Path

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {out}")
    return 0


def cmd_documents(args) -> int:
    """Download documents listed in sources/documents.csv that are not in literature/ yet."""
    from . import documents

    stats = documents.fetch()
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_build(args) -> int:
    """Write the static site: site/public (deployed) or site/local (everything)."""
    from . import site

    conn = db.connect()
    for target in args.target:
        stats = site.build(conn, target)
        print(f"{target}: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
        if target == "public" and stats["megabytes"] > site.PUBLIC_BUDGET_MB:
            print(f"public build is over the {site.PUBLIC_BUDGET_MB} MB deploy budget",
                  file=sys.stderr)
            return 1
    return 0


def cmd_serve(args) -> int:
    """Serve a built site on localhost (the admin page needs this; file:// works too)."""
    from . import server

    return server.serve(config.SITE_DIR / args.target, args.port)


def cmd_library(args) -> int:
    """Rebuild sources/library.csv (citations for every PDF; hand-checked rows are kept)."""
    from . import library

    print(", ".join(f"{k} {v}" for k, v in library.build().items()))
    return 0


def cmd_pdftext(args) -> int:
    """Extract per-page text from every PDF in literature/ (OCR where a page is a scan)."""
    from . import pdftext

    n = pdftext.extract_all(args.workers)
    print(f"{n} PDFs have text in {pdftext.TEXT_DIR}")
    return 0


def cmd_literature(args) -> int:
    """Find names and island records in the PDF text; GBIF-match literature-only names."""
    from . import literature

    conn = db.connect()
    literature.scan(conn)
    if not args.no_match:
        stats = literature.match_candidates(conn, gbif_client())
        print("candidates: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    print(f"{literature.presence_rows(conn)} taxon-area rows from the library")
    return 0


def cmd_wikidata(args) -> int:
    """Wikidata cross-links by GBIF key: Wikipedia, iNat, BugGuide ids, IUCN, common names."""
    from .enrich import wikidata

    stats = wikidata.sweep(db.connect(), refresh=args.refresh)
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_wikipedia(args) -> int:
    """English Wikipedia text for taxa Wikidata links to an article (CC BY-SA)."""
    from .enrich import wikitext

    stats = wikitext.fetch(db.connect(), args.limit)
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_bugguide(args) -> int:
    """BugGuide links for our taxa from entobase's database (read-only; BugGuide not fetched)."""
    from .enrich import entobase

    print(", ".join(f"{k} {v}" for k, v in entobase.sync(db.connect()).items()))
    return 0


def cmd_photos(args) -> int:
    """Photo candidates (Commons, iNaturalist), selection with borrowing, 200 px thumbnails."""
    from .enrich import photos
    from .enrich.http import ApiClient

    conn = db.connect()
    if "commons" in args.steps:
        print("commons: " + ", ".join(f"{k} {v}" for k, v in photos.commons_sweep(conn).items()))
    if "inat" in args.steps:
        inat = ApiClient(photos.INAT, 1.0)
        print("inat: " + ", ".join(f"{k} {v}" for k, v in
                                   photos.inat_taxon_sweep(conn, inat).items()))
    if "select" in args.steps:
        print("select: " + ", ".join(f"{k} {v}" for k, v in photos.select(conn).items()))
    if "thumbs" in args.steps:
        print("thumbs: " + ", ".join(f"{k} {v}" for k, v in photos.thumbs(conn).items()))
    return 0


def cmd_stats(args) -> int:
    conn = db.connect()
    for r in conn.execute("SELECT rank, COUNT(*) n, SUM(hidden) h FROM taxa GROUP BY rank "
                          "ORDER BY COUNT(*)"):
        print(f"{r['rank']:<12} {r['n']:>6}  ({r['h']} hidden)")
    print()
    for r in conn.execute(
            "SELECT p.area, p.source, COUNT(*) n FROM taxon_presence p JOIN taxa t "
            "ON t.taxon_id = p.taxon_id WHERE t.rank = 'Species' GROUP BY p.area, p.source"):
        print(f"species with {r['source']:<5} records in {r['area']}: {r['n']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="guaminsects", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("checklist", help=cmd_checklist.__doc__)
    p.add_argument("--area", action="append", choices=config.AREA_CODES)
    p.set_defaults(func=cmd_checklist)
    p = sub.add_parser("taxa", help=cmd_taxa.__doc__)
    p.add_argument("--refresh", action="store_true", help="refetch cached taxa")
    p.set_defaults(func=cmd_taxa)
    p = sub.add_parser("inat", help=cmd_inat.__doc__)
    p.add_argument("--link-only", action="store_true", help="skip the iNat sweep")
    p.add_argument("--sweep-only", action="store_true", help="skip matching names to GBIF")
    p.set_defaults(func=cmd_inat)
    p = sub.add_parser("plazi", help=cmd_plazi.__doc__)
    p.set_defaults(func=cmd_plazi)
    p = sub.add_parser("resolve", help=cmd_resolve.__doc__)
    p.set_defaults(func=cmd_resolve)
    p = sub.add_parser("export", help=cmd_export.__doc__)
    p.add_argument("-o", "--out")
    p.add_argument("--rank", action="append")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("documents", help=cmd_documents.__doc__)
    p.set_defaults(func=cmd_documents)
    p = sub.add_parser("build", help=cmd_build.__doc__)
    p.add_argument("target", nargs="*", default=["public"], choices=["public", "local"])
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("serve", help=cmd_serve.__doc__)
    p.add_argument("target", nargs="?", default="local", choices=["public", "local"])
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("library", help=cmd_library.__doc__)
    p.set_defaults(func=cmd_library)
    p = sub.add_parser("pdftext", help=cmd_pdftext.__doc__)
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_pdftext)
    p = sub.add_parser("literature", help=cmd_literature.__doc__)
    p.add_argument("--no-match", action="store_true", help="skip GBIF matching of new names")
    p.set_defaults(func=cmd_literature)
    p = sub.add_parser("wikidata", help=cmd_wikidata.__doc__)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_wikidata)
    p = sub.add_parser("wikipedia", help=cmd_wikipedia.__doc__)
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_wikipedia)
    p = sub.add_parser("bugguide", help=cmd_bugguide.__doc__)
    p.set_defaults(func=cmd_bugguide)
    p = sub.add_parser("photos", help=cmd_photos.__doc__)
    p.add_argument("steps", nargs="*", default=["commons", "inat", "select", "thumbs"],
                   choices=["commons", "inat", "select", "thumbs"])
    p.set_defaults(func=cmd_photos)
    p = sub.add_parser("stats", help="counts by rank and area")
    p.set_defaults(func=cmd_stats)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
