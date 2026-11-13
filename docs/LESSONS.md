# Lessons from entobase (read before writing any enrichment)

Each item is something that went wrong, and what now prevents it. The code for the fixes is in
`reference/entobase/src/entobase/`.

## Rate limits and long jobs

- **iNaturalist 429s come from running streams at once.** Four streams (photos, counts, linking,
  recounts) hit the API together and the whole run died on `429 normal_throttling`, losing
  hours of work. Fixes: `ApiClient` waits `Retry-After` (else 30 s × attempt, capped 120 s) on
  429 and 5xx backoff; every job commits per row or per batch (`link` commits every 30 name
  searches) so it is **resumable**; `ops/link_all.sh` runs **one stream per host** and waits on
  each PID. A job that hits a 429 after its retries must log and move on, never mark the item
  "missing" (an early Wikipedia bug stored a 429 as "article not found" for 180 days).
- Throttled name searching runs at ~25-30 requests a minute in practice. Budget hours, not
  minutes, for 15k lookups, and print progress every 30 (`iNat name search: 3480/15364`).
- Never hold a SQLite write transaction across a network call. A `bugwood --details` pass held
  the write lock for ~100 rows and other jobs got "database is locked". Commit per row; set
  `PRAGMA busy_timeout`.
- Checks that scan thousands of items must be **chunked and resumable** (`--limit`, `--refresh`,
  "answered within N days → skip").

## Data model

- **Stubs vs parsed taxa.** entobase has a taxon known only from a tree page (26k species store
  just the epithet) and later "parsed" with a page. In your project every taxon has a name from
  GBIF, so you should not need that split, but you will still have taxa with no photo, no text, no
  link. Model status per *source* (`external_links.confidence`, `taxon_photos`, ...) not per
  taxon, and let the app show what exists.
- **Confidence on every link**: `high` (an identifier from a second source agrees), `medium`
  (exact name match, rank and family agree), `review` (they disagree). A `review` link supplies
  **no photos** (otherwise a wrong match puts the wrong animal on a page). `linkaudit.py`
  cross-checks the four link systems and demotes disagreements.
- **GBIF name match**: accept EXACT; accept FUZZY only if canonical names agree; never
  HIGHERRANK. Subspecies sharing a species' key must not get their own occurrence rows.
- **Authorship** (e.g. "Linnaeus, 1758") comes from several sources of different quality; store
  each source's value (`taxon_authorship`) and rank them in code rather than overwriting.
- **Hidden things**: placeholders (`cf-x`, `sp-one`, `undescribed`), fossils, and anything under
  a hidden parent are hidden by `annotate.py`; hide by rule + `curation.toml`, never by deleting.
- **Common names**: take the first of (local source, iNat, Bugwood), then clean furniture
  (`clean_common`: "Hodges#4671" suffixes and stray " 0").

## Photos

- Licence filter at selection time (CC0, BY, BY-SA, BY-NC, BY-NC-SA). Store the licence, author,
  URL and retrieval date with the file. Store **resized WebP copies** (display ≈ 1000 px, thumb
  ≈ 320 px); total size matters (the site is opened from disk and synced through iCloud).
- **Foreign photos**: a higher taxon's photo can show a species that does not occur in the region
  (an African species on a family page). Select only photos of species that occur here
  (`photos --foreign` reselects). iNat's per-place observation counts give **false zeros** on
  stale identifications, so treat GBIF presence as an override.
- **Borrowing** (`inherit`): a taxon with no photo of its own borrows one from the best species
  it contains and says whose picture it is (`from_taxon_id`); the borrowed photo is never counted
  as the taxon's own, and never lent onward twice. Prefer a **landscape** photo (width ≥ 1.2 ×
  height) for tiles; portraits left dead space in the grid.
- Photos on Commons: read the licence per file (`extmetadata`), not per page.

## Maps

- One shared basemap PNG plus a small transparent 32-colour overlay per taxon (5-25 KB) is
  far smaller than a map per taxon; the app stacks them.
- GBIF's ad-hoc map endpoint 503s on empty tiles: `groupmaps.py` reads errors as empty and notes
  "N tile(s) unavailable", retrying after 14 days.
- Cropping a map is done **in CSS** on the stored sheet (an aspect-ratio box, the image
  positioned `top: -25.899%; height: 140.511%`), so changing the crop never regenerates files.
  For Micronesia re-derive the numbers: a Web-Mercator sheet's y fraction for latitude φ is
  `(π - ln(tan(π/4 + φ/2))) / 2π` relative to the sheet's own bounds.

## Presence by area

Ask GBIF once per **area** with a `speciesKey` facet, not once per taxon (64 requests instead of
40,000). Rows are upserted and each area commits. Taxa that share a GBIF key all get rows.
Stale rows are deleted per area so a corrected record disappears.

## The web app

- `file://` forbids `fetch()`: the data are `<script>` files that call a loader. Record files are
  sharded `data/t/<id//1000>/<id>.js`; the name index and a sharded full-text index load on demand.
- The **hash is the route**. In-page jumps use `data-*` plus JavaScript (`a.cite`, `a.jump`), never
  `href="#id"`.
- Sanitise any HTML you copy from a source: relative links made absolute, `#` links unwrapped,
  scripts dropped, external links `target=_blank rel=noopener`, in-text images replaced by a
  note when not stored locally.
- Build incrementally with a content hash per record (`site_records`); a full rebuild of 65k
  records takes minutes.
- The sticky left column on the taxon page parks by *bottom* edge when taller than the window:
  `pinSide()` sets `top` from the column's height (CSS alone cannot).
- Smoke test every UI change in three engines (`ops/check_site.py`). A flaky "region filter
  narrows" check passed on rerun: it reads a count right after the selector appears.

## Process

- Verify a data change with a test *and* a look at 20 real rows. Several bugs (relative URLs in
  prose, "Hodges#N" in common names, 73 pages marked done with no archive) were obvious on
  inspection and invisible to tests.
- Write the docs as you go (`CLAUDE.md` rules, `docs/APP_SPEC.md`): a rule gets added each time
  something costs a day.
- Do not kill or restart processes the user owns (here: the BugGuide crawl); ask.
