---
name: sync-records
description: Refresh the GBIF and iNaturalist record counts in the Insects of Guam dataset, add the new taxa they reveal (flagged new), refresh the statistics of taxa whose counts changed, then commit and push. Data machine only. Use when the user says /sync-records or asks to update records, counts or new species.
---

# /sync-records

Run on the data machine from the repository root. `uv run guaminsects sync check` asks the
sources; `sync apply` writes. Counts, years, islands and new taxa are applied automatically (new
taxa are flagged `new` and reviewed afterwards in the editor); a taxon whose records vanished is
reported, never removed.

## Before you start

- `git pull`. One machine at a time.
- **Check for entobase jobs**: `ps aux | grep -i "[e]ntobase"`. iNaturalist answers 429 under
  concurrent streams and the user's entobase crawl shares this IP (CLAUDE.md rule 2). If one is running,
  tell the user: `sync check` asks iNaturalist (research-grade species counts per place, patiently),
  and it is better to wait or run `--area GU` first.
- Never touch the entobase process or its queue.

## Steps

1. **Check.** `uv run guaminsects sync check` (or `--area GU` ... for some areas). One stream per host,
   at most 3 requests/s to GBIF and 1/s to iNaturalist. It stages the answers in
   `private.nosync/staging/sync-<date>.json` and prints a summary: new keys (Catalogue of Life,
   GBIF Backbone, iNaturalist names), rows added, counts changed (with the ten largest changes), counts
   gone to zero, unchanged. **Nothing in `dataset/` changes.**
2. **Look at the summary** before applying. A very large change in a big taxon, many vanished
   counts, or an area that came back empty is a sign of a failed request or a changed GBIF filter:
   stop and tell the user rather than applying. The first ever run: show the user the summary and
   wait for their go-ahead.
3. **Apply.** `uv run guaminsects sync apply`. It updates `records.csv` (set `refreshed`),
   refreshes years and the island facet (GADM level 1) of taxa whose counts changed, matches new keys
   (`keys.csv`; COL taxa added with their ancestors; names COL lacks under their genus; the rest to
   `dataset/review/unplaced.csv`), adds them to `taxa.csv` with `flag new` and nativity `unknown`
   (GBIF's `establishmentMeans` is too rarely filled to set nativity from), and fetches links,
   Wikipedia text, BugGuide links (via `../entobase`, read-only) and photos (with thumbnails) for
   the new taxa. It runs `dataset check` and writes only if that passes.
4. **Report** to the user: new taxa by order, the largest count changes, anything vanished or
   unplaced.
5. **Verify and commit.** `uv run guaminsects dataset check && uv run guaminsects build` (and
   `uv run pytest -q` if code changed), then commit `dataset/` and `media/` with
   `Sync <date>: <n> new taxa, <n> counts changed` plus the session's trailer, and `git push`
   (the push rebuilds and redeploys the site).

Other refreshes, when asked: `uv run guaminsects refresh photos|wikipedia|wikidata|bugguide|col
--taxa new|all|<ids>` (same polite client; same commit routine).
