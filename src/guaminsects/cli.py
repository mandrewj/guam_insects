"""Command-line entry point: `uv run guaminsects <command>`."""

import argparse
import sys

from . import config, curation, db, ids


def gbif_client():
    from .enrich.http import ApiClient
    from .enrich.gbif_checklist import GBIF

    return ApiClient(GBIF, min_interval=0.34)        # ≤3 requests/s (CLAUDE.md rule 2)


def col_client():
    """GBIF's v2 API (the Catalogue of Life match), at the same polite rate."""
    from .enrich.col import GBIF_ROOT
    from .enrich.http import ApiClient

    return ApiClient(GBIF_ROOT, min_interval=0.34)


def cmd_checklist(args) -> int:
    """GBIF presence sweep: hexapod taxon keys with records in each area (COL keys; with
    --backbone, GBIF Backbone keys, used to find names COL lacks)."""
    from .enrich import gbif_checklist

    conn = db.connect()
    client = gbif_client()
    gbif_checklist.sweep(conn, client, args.area or None, col=not args.backbone)
    print(f"{client.requests} GBIF requests")
    return 0


def cmd_col(args) -> int:
    """Catalogue of Life taxa for every COL key with records (and their classifications)."""
    from .enrich import col

    conn = db.connect()
    client = col_client()
    keys = {r[0] for r in conn.execute("SELECT DISTINCT taxon_id FROM taxon_presence "
                                       "WHERE taxon_id >= ? AND taxon_id < ?",
                                       (ids.COL_BASE, ids.NAME_BASE))}
    keys |= {r[0] for r in conn.execute("SELECT taxon FROM name_matches WHERE taxon > 0 "
                                        "UNION SELECT parent FROM name_matches WHERE parent > 0")}
    n = col.fetch_taxa(conn, client, keys, refresh=args.refresh)
    m = col.fetch_taxa(conn, client, col.displayed_ancestors(conn))
    print(f"{n} COL taxa, {m} ancestors, {client.requests} GBIF requests")
    return 0


def cmd_colinfo(args) -> int:
    """From ChecklistBank (COL's own API): the taxa COL marks extinct, then English common
    names and synonyms for every COL taxon in the tree."""
    from .enrich import col
    from .enrich.http import ApiClient

    conn = db.connect()
    clb = ApiClient(col.CLB, min_interval=0.5)
    print(f"{col.extinct_sweep(conn, clb)} extinct taxa")
    if not args.extinct_only:
        keys = [r[0] for r in conn.execute("SELECT taxon_id FROM taxa WHERE in_col = 1 "
                                           "ORDER BY rank = 'Species' DESC, taxon_id")]
        print(f"{col.info_sweep(conn, clb, keys)} taxa asked; {clb.requests} requests")
    return 0


def cmd_match(args) -> int:
    """Put every name a source used on the Catalogue of Life (name_matches)."""
    from . import names

    conn = db.connect()
    client = col_client()
    i, n = (int(x) for x in args.shard.split("/"))
    stats = names.match_all(conn, client, refresh=args.refresh, shard=(i, n))
    print(", ".join(f"{k} {v}" for k, v in stats.items()) + f"; {client.requests} requests")
    return 0


def cmd_taxa(args) -> int:
    """Fetch GBIF taxon records for every present or curated key and their ancestors."""
    from .enrich import gbif_checklist

    conn = db.connect()
    cur = curation.load()
    keys = gbif_checklist.present_keys(conn) | set(config.HEXAPOD_CLASSES)
    keys |= {ids.to_int(r["taxon_id"]) for r in cur.rows
             if ids.kind(ids.to_int(r["taxon_id"])) == "gbif"}
    keys |= {ids.to_int(e["taxon_id"]) for e in cur.evidence
             if ids.kind(ids.to_int(e["taxon_id"])) == "gbif"}
    client = gbif_client()
    n = gbif_checklist.fetch_taxa(conn, client, keys, refresh=args.refresh)
    print(f"{n} taxa stored, {client.requests} GBIF requests")
    return 0


def cmd_inat(args) -> int:
    """iNaturalist species counts per area, then name keys for them (matched by `match`)."""
    from .enrich import inat_counts
    from .enrich.http import ApiClient

    conn = db.connect()
    if not args.link_only:
        inat = ApiClient(inat_counts.INAT, min_interval=1.0)
        inat_counts.sweep(conn, inat)
        print(f"{inat.requests} iNat requests")
    if args.sweep_only:
        return 0
    stats = inat_counts.link_names(conn)
    print(f"iNat names: {stats['names']} names, {stats['rows']} presence rows")
    return 0


def cmd_plazi(args) -> int:
    """Literature checklists digitized by Plazi (Insects of Guam 1942-46 and others)."""
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


def cmd_taxonomy(args) -> int:
    """Take in edits made to taxonomy.csv, then rewrite it from the tree (a build does too)."""
    from . import taxonomy

    conn = db.connect()
    try:
        synced = taxonomy.sync(conn, args.editor)
    except curation.CurationError as e:
        print(f"taxonomy.csv: nothing saved; problems:\n{e}", file=sys.stderr)
        return 1
    if synced:
        _print_import(synced)
    table = taxonomy.rows(conn)
    taxonomy.write(table)
    print(f"{len(table)} taxa -> {taxonomy.REPO_CSV.name}")
    return 0


def _print_import(stats: dict) -> None:
    print(", ".join(f"{k} {v}" for k, v in stats.items() if k != "changes"))
    for c in stats["changes"]:
        print("  " + c)


def cmd_export(args) -> int:
    """Write a copy of the taxonomy CSV: everything, or one taxon and all under it."""
    from pathlib import Path

    from . import taxonomy

    table = taxonomy.rows(db.connect())
    if args.under:
        table = taxonomy.subtree(table, args.under)
    out = Path(args.out or config.DATA_DIR / "exports" / "taxonomy.csv")
    taxonomy.write(table, out, snapshot=False)
    print(f"{len(table)} taxa -> {out}")
    return 0


def cmd_documents(args) -> int:
    """Download documents listed in sources/documents.csv that are not in literature/ yet."""
    from . import documents

    stats = documents.fetch()
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_build(args) -> int:
    """Write the static site, site/public: opened locally and deployed as it is."""
    from . import site

    try:
        stats = site.build(db.connect())
    except curation.CurationError as e:
        print(f"taxonomy.csv has edits that do not fit the tree; nothing saved or built. "
              f"Fix them in taxonomy.csv and build again:\n{e}", file=sys.stderr)
        return 1
    print("site: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    if stats["megabytes"] > site.PUBLIC_BUDGET_MB:
        print(f"the site is over the {site.PUBLIC_BUDGET_MB} MB deploy budget", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args) -> int:
    """Serve the built site on localhost (file:// works too)."""
    from . import server

    return server.serve(config.SITE_DIR / "public", args.port)


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
        stats = literature.match_candidates(conn, col_client())
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
    """Photo candidates (Commons, iNaturalist, GBIF occurrence images), selection with borrowing, 200 px thumbnails."""
    from .enrich import photos
    from .enrich.http import ApiClient

    conn = db.connect()
    if "commons" in args.steps:
        print("commons: " + ", ".join(f"{k} {v}" for k, v in photos.commons_sweep(conn).items()))
    if "inat" in args.steps:
        inat = ApiClient(photos.INAT, 1.0)
        print("inat: " + ", ".join(f"{k} {v}" for k, v in
                                   photos.inat_taxon_sweep(conn, inat).items()))
    if "gbif" in args.steps:
        print("gbif: " + ", ".join(f"{k} {v}" for k, v in
                                   photos.gbif_sweep(conn, gbif_client()).items()))
    if "select" in args.steps:
        print("select: " + ", ".join(f"{k} {v}" for k, v in photos.select(conn).items()))
    if "thumbs" in args.steps:
        print("thumbs: " + ", ".join(f"{k} {v}" for k, v in photos.thumbs(conn).items()))
    return 0


def cmd_islands(args) -> int:
    """GBIF island-level presence (GADM level-1 units), one facet sweep per unit."""
    from .enrich import islands

    print(", ".join(f"{k} {v}" for k, v in islands.sweep(db.connect(), gbif_client()).items()))
    return 0


def cmd_import(args) -> int:
    """Apply an edited taxonomy CSV (a download from the site, or an export): changed
    editable cells and rows with a blank taxonID become curation/taxa.csv rows."""
    from pathlib import Path

    from . import taxonomy

    conn = db.connect()
    path = Path(args.file)
    try:
        if path.resolve() == taxonomy.REPO_CSV.resolve():
            stats = taxonomy.sync(conn, args.editor) or {"changed": 0, "new": 0, "changes": []}
        else:
            stats = taxonomy.import_edits(conn, path, args.editor or taxonomy.default_editor(),
                                          dry_run=args.dry_run)
    except curation.CurationError as e:
        print(f"nothing saved; problems:\n{e}", file=sys.stderr)
        return 1
    _print_import(stats)
    if args.dry_run:
        print("(dry run: nothing saved)")
    elif stats["changed"] or stats["new"]:
        print("curation/taxa.csv updated; run `guaminsects build` to see it")
    return 0


def cmd_specimens(args) -> int:
    """GBIF preserved specimens per area (the "specimen records" verification level)."""
    from .enrich import gbif_checklist

    done = gbif_checklist.specimen_sweep(db.connect(), gbif_client())
    print(", ".join(f"{k} {v}" for k, v in done.items()))
    return 0


def cmd_croppests(args) -> int:
    """Nafus & Schreiner's list of insects attacking crops in Micronesia (Moore's CSV)."""
    from .enrich import croppests

    croppests.sweep(db.connect(), gbif_client())
    return 0


def cmd_establishment(args) -> int:
    """Introduced-species statements from the lists of introductions in the library."""
    from . import establishment

    conn = db.connect()
    establishment.scan(conn, None if args.no_match else gbif_client())
    if not args.no_match:
        stats = establishment.gbif_sweep(conn, gbif_client())
        print("GBIF establishmentMeans: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_synonyms(args) -> int:
    """GBIF synonyms for species and genera (for search and the PDF name finder)."""
    from .enrich import gbif_checklist

    stats = gbif_checklist.fetch_synonyms(db.connect(), gbif_client(), args.refresh)
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
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
    p.add_argument("--backbone", action="store_true", help="GBIF Backbone keys instead of COL")
    p.set_defaults(func=cmd_checklist)
    p = sub.add_parser("colinfo", help=cmd_colinfo.__doc__)
    p.add_argument("--extinct-only", action="store_true")
    p.set_defaults(func=cmd_colinfo)
    p = sub.add_parser("match", help=cmd_match.__doc__)
    p.add_argument("--refresh", action="store_true", help="match every name again")
    p.add_argument("--shard", default="0/1", help="i/n: every n-th key (two streams: 0/2, 1/2)")
    p.set_defaults(func=cmd_match)
    p = sub.add_parser("col", help=cmd_col.__doc__)
    p.add_argument("--refresh", action="store_true", help="refetch cached taxa")
    p.set_defaults(func=cmd_col)
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
    p.add_argument("--under", type=int, help="a taxon id: export it and everything under it")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("taxonomy", help=cmd_taxonomy.__doc__)
    p.add_argument("--editor")
    p.set_defaults(func=cmd_taxonomy)
    p = sub.add_parser("specimens", help=cmd_specimens.__doc__)
    p.set_defaults(func=cmd_specimens)
    p = sub.add_parser("documents", help=cmd_documents.__doc__)
    p.set_defaults(func=cmd_documents)
    p = sub.add_parser("build", help=cmd_build.__doc__)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("serve", help=cmd_serve.__doc__)
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
    p.add_argument("steps", nargs="*", default=["commons", "inat", "gbif", "select", "thumbs"],
                   choices=["commons", "inat", "gbif", "select", "thumbs"])
    p.set_defaults(func=cmd_photos)
    p = sub.add_parser("islands", help=cmd_islands.__doc__)
    p.set_defaults(func=cmd_islands)
    p = sub.add_parser("import", help=cmd_import.__doc__)
    p.add_argument("file")
    p.add_argument("--editor")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("croppests", help=cmd_croppests.__doc__)
    p.set_defaults(func=cmd_croppests)
    p = sub.add_parser("establishment", help=cmd_establishment.__doc__)
    p.add_argument("--no-match", action="store_true", help="skip GBIF matching of new names")
    p.set_defaults(func=cmd_establishment)
    p = sub.add_parser("synonyms", help=cmd_synonyms.__doc__)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_synonyms)
    p = sub.add_parser("stats", help="counts by rank and area")
    p.set_defaults(func=cmd_stats)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
