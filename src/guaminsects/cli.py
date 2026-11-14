"""Command-line entry point: `uv run guaminsects <command>`.

    dataset check|readme   validate dataset/ (every problem at once), or write its README
    build                  dataset/ -> site.nosync/public (no database, no network)
    serve                  the built site on localhost
    edit                   the taxonomy editor for this clone (localhost:8766)
    editor-spec            editor/assets/spec.js from schema.py and geo.py
    match NAME ...         put names on the Catalogue of Life (new taxa flagged new)
    sync check|apply       GBIF and iNaturalist counts against records.csv
    refresh WHAT           photos, wikipedia, wikidata, bugguide, col for some taxa
    lit add|cite|scan|apply   the literature tool (the /ingest-literature skill drives it)
"""

import argparse
import sys

from . import config

BUDGET_MB = 90            # Vercel Hobby takes 100 MB per CLI deploy


def cmd_dataset(args) -> int:
    """dataset check | readme: validate dataset/ (every problem at once), or write its README."""
    from . import dataset, schema

    if args.what == "readme":
        dataset.write_text(dataset.DATASET_DIR / "README.md", schema.readme(), bom=False)
        print("dataset/README.md written")
        return 0
    ds = dataset.load()
    problems = dataset.check(ds)
    for line in problems.items[:200]:
        print(line)
    n = len(problems.items)
    print(f"dataset: {len(ds['taxa'])} taxa rows, {n} problem{'s' if n != 1 else ''}"
          + (" (first 200 shown)" if n > 200 else ""))
    return 1 if n else 0


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def cmd_match(args) -> int:
    """Put names on the Catalogue of Life: each is matched, added to taxa.csv flagged new when
    COL lacks it (under its genus), or listed in review/unplaced.csv."""
    from . import dataset, match
    from .http import ApiClient
    from .sources import col as colapi
    from .sources import gbif as gbifapi

    ds = dataset.load()
    gbif = ApiClient(gbifapi.GBIF, 0.34)
    col = ApiClient("https://api.gbif.org", 0.34)
    m = match.Matcher(ds, col, gbif, by="guaminsects match", today=_today())
    if args.unplaced:
        wiki = None if args.no_wikipedia else ApiClient("https://en.wikipedia.org/w/api.php", 1.0)

        def save(d):
            if not dataset.check(d):
                dataset.write(d)

        stats = match.run_unplaced(ds, m, wiki, args.limit, lambda x: print(x, file=sys.stderr),
                                   checkpoint=save)
        problems = dataset.check(ds)
        if problems:
            print("\n".join(problems.items[:20]), file=sys.stderr)
            return 1
        dataset.write(ds)
        print(stats, m.stats)
        return 0
    for name in args.names:
        got = m.resolve(name, args.rank, args.source)
        print(f"{name}: {got or 'unplaced (see dataset/review/unplaced.csv)'}")
    problems = dataset.check(ds)
    if problems:
        print("\n".join(problems.items[:20]), file=sys.stderr)
        return 1
    dataset.write(ds)
    print(m.stats)
    _ = colapi
    return 0


def cmd_sync(args) -> int:
    """sync check | apply: GBIF and iNaturalist counts against dataset/records.csv. `check`
    asks the sources and stages the answers (nothing in dataset/ changes); `apply` writes
    them, adding new taxa flagged new."""
    import json

    from . import dataset, match, refresh, sync
    from .http import ApiClient
    from .sources import gbif as gbifapi
    from .sources import inat as inatapi

    ds = dataset.load()
    today = _today()
    gbif = ApiClient(gbifapi.GBIF, 0.34)
    if args.what == "check":
        inat = ApiClient(inatapi.INAT, 1.0)
        staging = sync.check(ds, gbif, inat, areas=args.area or None, today=today,
                             progress=lambda m: print(m, file=sys.stderr))
        path = sync.save(staging, today)
        print(json.dumps(sync.summarize(ds, staging), indent=1))
        print(f"staged: {path}; {gbif.requests} GBIF + {inat.requests} iNaturalist requests")
        return 0
    path = args.file or sync.latest_staging()
    if not path:
        print("nothing staged: run `guaminsects sync check` first", file=sys.stderr)
        return 1
    staging = sync.load(__import__("pathlib").Path(path))
    col = ApiClient("https://api.gbif.org", 0.34)
    m = match.Matcher(ds, col, gbif, by="guaminsects sync", today=today)
    report = sync.apply(ds, staging, m, gbif=gbif, today=today,
                        refresh_new=lambda d, new: refresh.run_new(
                            d, new, today, lambda x: print(x, file=sys.stderr)),
                        progress=lambda x: print(x, file=sys.stderr))
    problems = dataset.check(ds)
    if problems:
        print("the result does not pass dataset check; nothing written:\n"
              + "\n".join(problems.items[:20]), file=sys.stderr)
        return 1
    dataset.write(ds)
    print(json.dumps({k: v for k, v in report.items() if k != "new_ids"}, indent=1))
    print(f"new taxa: {', '.join(report['new_ids'][:40])}" + (" ..." if len(report["new_ids"]) > 40 else ""))
    return 0


def cmd_refresh(args) -> int:
    """refresh <photos|wikipedia|wikidata|bugguide|col> [--taxa new|all|ID ...]: one outside
    source, for the taxa flagged new, all of them, or the ids given."""
    from . import dataset, refresh

    ds = dataset.load()
    taxa = refresh.pick(ds, args.taxa[0] if args.taxa in (["new"], ["all"]) else args.taxa)
    print(f"{args.what}: {len(taxa)} taxa", file=sys.stderr)
    stats = refresh.run(ds, args.what, taxa, _today(), lambda x: print(x, file=sys.stderr))
    problems = dataset.check(ds)
    if problems:
        print("the result does not pass dataset check; nothing written:\n"
              + "\n".join(problems.items[:20]), file=sys.stderr)
        return 1
    dataset.write(ds)
    print(stats)
    return 0


def cmd_build(args) -> int:
    """Write the static site, site.nosync/public, from dataset/: opened locally and deployed."""
    from . import build

    try:
        stats = build.build()
    except build.BuildError as e:
        print(e, file=sys.stderr)
        return 1
    print("site: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    if stats["megabytes"] > BUDGET_MB:
        print(f"the site is over the {BUDGET_MB} MB deploy budget", file=sys.stderr)
        return 1
    return 0


def cmd_edit(args) -> int:
    """The taxonomy editor for this clone: serve it, commit and push its changes with your git
    (no database needed; the push triggers the rebuild)."""
    from . import editor

    editor.write_spec()
    return editor.serve(args.port, push=not args.no_push)


def cmd_editor_spec(args) -> int:
    """Write editor/assets/spec.js (the editor's columns, ranks, places) from the Python code."""
    from . import editor

    print("editor/assets/spec.js " + ("written" if editor.write_spec() else "unchanged"))
    return 0


def cmd_serve(args) -> int:
    """Serve the built site on localhost (file:// works too)."""
    from . import server

    return server.serve(config.SITE_DIR / "public", args.port)


def cmd_lit(args) -> int:
    """lit add|cite|pages|scan|apply: the literature tool (run by the /ingest-literature
    skill, on the machine that has the PDFs; nothing quoted ever reaches dataset/)."""
    import json
    from pathlib import Path

    from . import dataset
    from .literature import stage

    ds = dataset.load()
    today = _today()

    def finish(note: str) -> int:
        problems = dataset.check(ds, stage.text_of(ds))
        if problems:
            print("the result does not pass dataset check; nothing written:\n"
                  + "\n".join(problems.items[:30]), file=sys.stderr)
            return 1
        if not args.dry_run:
            dataset.write(ds)
        print(note + (" (dry run: nothing written)" if args.dry_run else ""))
        return 0

    try:
        if args.what == "add":
            done = stage.add(ds, Path(args.target), today)
            return finish(json.dumps(done, ensure_ascii=False, indent=1))
        if args.what == "cite":
            fields = {k: getattr(args, k, None) for k in stage.CITE_FIELDS if k != "pages"}
            fields["pages"] = args.pages_cited
            row = stage.cite(ds, args.target, **fields)
            return finish(row["citation"])
        if args.what == "pages":
            lo, hi = stage.parse_pages(args.pages) or (1, 3)
            for p in stage.doc_pages(ds, args.target):
                if lo <= p["page"] <= hi:
                    print(f"--- page {p['page']} ({p['method']}) ---\n{p['text']}")
            return 0
        if args.what == "scan":
            matcher = None
            if args.match:
                from .http import ApiClient
                from .match import Matcher
                from .sources import gbif as gbifapi

                matcher = Matcher(ds, ApiClient("https://api.gbif.org", 0.34),
                                  ApiClient(gbifapi.GBIF, 0.34), by="lit scan", today=today)
            staged = stage.scan(ds, args.target, stage.parse_pages(args.pages), matcher)
            path = stage.save_staging(staged, args.target)
            if matcher is not None:
                dataset.write(ds)
            accounts = sum(c["kind"] == "account" for c in staged["candidates"])
            print(f"{path}: {accounts} species accounts, "
                  f"{len(staged['candidates']) - accounts} mentions, "
                  f"{len(staged['unmatched'])} unmatched headings")
            return 0
        spec = json.loads(Path(args.target).read_text(encoding="utf-8"))
        matcher = None
        if spec.get("new_names"):
            from .http import ApiClient
            from .match import Matcher
            from .sources import gbif as gbifapi

            matcher = Matcher(ds, ApiClient("https://api.gbif.org", 0.34),
                              ApiClient(gbifapi.GBIF, 0.34), by="ingest-literature", today=today)
        stats = stage.apply(ds, spec, today, matcher)
        return finish(json.dumps(stats, ensure_ascii=False, indent=1))
    except stage.ApplyError as e:
        print(e, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="guaminsects", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dataset", help=cmd_dataset.__doc__)
    p.add_argument("what", choices=["check", "readme"], nargs="?", default="check")
    p.set_defaults(func=cmd_dataset)
    p = sub.add_parser("build", help=cmd_build.__doc__)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("serve", help=cmd_serve.__doc__)
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("edit", help=cmd_edit.__doc__)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-push", action="store_true", help="commit locally, do not push")
    p.set_defaults(func=cmd_edit)
    p = sub.add_parser("editor-spec", help=cmd_editor_spec.__doc__)
    p.set_defaults(func=cmd_editor_spec)
    p = sub.add_parser("match", help=cmd_match.__doc__)
    p.add_argument("names", nargs="*")
    p.add_argument("--unplaced", action="store_true", help="try every name on the unplaced list against the GBIF Backbone and Wikipedia")
    p.add_argument("--no-wikipedia", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--rank", default="species", help="species (default), genus, subspecies, family")
    p.add_argument("--source", default="manual")
    p.set_defaults(func=cmd_match)
    p = sub.add_parser("sync", help=cmd_sync.__doc__)
    p.add_argument("what", choices=["check", "apply"])
    p.add_argument("--area", action="append", help="GU MP PW FM MH (default: all)")
    p.add_argument("--file", help="a staged sync file (default: the latest)")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("refresh", help=cmd_refresh.__doc__)
    p.add_argument("what", choices=["photos", "wikipedia", "wikidata", "bugguide", "col"])
    p.add_argument("--taxa", nargs="+", default=["new"], help="new (default), all, or taxon ids")
    p.set_defaults(func=cmd_refresh)
    p = sub.add_parser("lit", help=cmd_lit.__doc__)
    p.add_argument("what", choices=["add", "cite", "pages", "scan", "apply"])
    p.add_argument("target", help="add: a directory of PDFs; cite|pages|scan: a doc_id; apply: an apply file")
    p.add_argument("--pages", help="pages: first pages (default 1-3); scan: only these pages (a-b)")
    p.add_argument("--match", action="store_true", help="scan: match unknown heading names (network)")
    p.add_argument("--dry-run", action="store_true", help="check, change nothing")
    for f in ("title", "authors", "year", "container", "volume", "doi", "url", "licence", "kind", "region"):
        p.add_argument(f"--{f}")
    p.add_argument("--cite-pages", dest="pages_cited")
    p.set_defaults(func=cmd_lit)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
