# guam_insects: developer notes (read this first)

An offline reference to the **terrestrial arthropods of Guam and Micronesia**: a visual
identification and data-aggregation tool. It is the sibling of `../entobase` (North American
insects, BugGuide-based) and is meant to look and behave almost the same, with a different
foundation:

| | entobase | guam_insects |
|---|---|---|
| Backbone / tree | BugGuide crawl | **GBIF backbone** + **iNaturalist**, restricted to taxa recorded in Micronesia |
| Text | BugGuide sections, Wikipedia | **Your PDF library**, Wikipedia, Wikispecies, iNaturalist, IUCN, BugGuide (supplement), others |
| Photos | iNaturalist (CC), Commons | the same, filtered to the region first |
| Regions | NE / SE / SW / NW (US + Canada) | **islands and island groups** (Guam, CNMI, Palau, FSM, Marshalls) |
| Output | static `file://` web app | **the same app**, reused from `starter/webapp/` |

Status (2026-11-13): one build (round 5), moving to another machine (see docs/STATUS.md,
"Moving to another machine"); the tree is the Catalogue of Life (round 4 below); the pipeline runs end
to end and the site builds and passes `ops/check_site.py` in all three engines. Live at https://insects-of-guam.vercel.app
(`ops/deploy.sh --prod`). Start with the decisions below (they override
`BUILD_PLAN.md`), then "Pipeline order".

## Pipeline order (each step resumable; one stream per host)

```sh
uv run guaminsects checklist     # GBIF presence by area, Catalogue of Life keys   GBIF
uv run guaminsects checklist --backbone  # the same, GBIF Backbone keys (names COL lacks)
uv run guaminsects specimens     # GBIF preserved specimens per area (COL keys)    GBIF
uv run guaminsects islands       # GBIF presence by island (GADM level 1, COL)     GBIF
uv run guaminsects col           # COL taxa + classification (v2 match, usageKey)  GBIF v2
uv run guaminsects taxa          # GBIF Backbone names for the Backbone keys        GBIF
uv run guaminsects plazi         # digitised literature checklists                 GBIF
uv run guaminsects croppests     # Nafus & Schreiner crop pest list                GBIF (matching)
uv run guaminsects synonyms      # GBIF synonyms (search, PDF name finder)         GBIF
uv run guaminsects inat          # iNat species counts per area -> name- keys      iNat
uv run guaminsects library       # sources/library.csv (citations)                 (cached)
uv run guaminsects pdftext       # text of literature/ (OCR scans)                 local
uv run guaminsects literature    # names + island records from the PDFs            GBIF v2
uv run guaminsects establishment # introduced-species statements                   GBIF (matching)
uv run guaminsects match [--shard 0/2]  # every source name -> COL (name_matches)  GBIF v2
uv run guaminsects resolve       # tree = COL + name matches + curation/*.csv      local
uv run guaminsects wikidata      # cross-links by COL id (P10585) / GBIF id        Wikidata
uv run guaminsects wikipedia     # article text                                    en.wikipedia
uv run guaminsects bugguide      # links from entobase (read-only)                 local
uv run guaminsects photos        # Commons, iNat, GBIF images; select, thumbs   Commons, iNat, GBIF
uv run guaminsects resolve && uv run guaminsects build   # site/public; also taxonomy.csv
uv run python ops/check_site.py  # Chrome/WebKit/Firefox x desktop/phone
uv run python ops/review.py      # data/exports/review.html for the curator (local only)
uv run guaminsects serve         # http://localhost:8765 (+ the curation /api)
ops/deploy.sh [--prod]           # Vercel (public build)
```

Presence sources in `taxon_presence.source`: gbif (COL keys), gbif_backbone (Backbone keys;
counted only for taxa COL lacks), inat, plazi, pdf, checklist. The site shows GBIF and iNat
separately and the last three as "Lit." (documents that record it).

**Keys and ids** (`src/guaminsects/ids.py`, mirrored in app.js): source rows carry the key
the source used (a COL id stored as COL_BASE + base 36, a GBIF Backbone key, a name- id from
`sources/names.csv`); `taxon_keys` (written by resolve) maps each to the displayed taxon, and
every reader goes through `db.keymap(conn)`. External ids: `KVC9L`, `gbif:<key>`,
`name-<n>`, `IOG-<n>` (curated). Never compare source keys with taxa ids directly.

## Decisions already made by the user (2026-11-13; do not re-ask)

- **Scope: Micronesia**, with Guam as the home region and the default filter. Countries (GBIF
  codes): GU Guam, MP Northern Mariana Islands, PW Palau, FM Federated States of Micronesia,
  MH Marshall Islands. Kiribati (KI) and Nauru (NR) are not included unless the user says so.
- **Taxa: all terrestrial arthropods** (tree starts at Arthropoda, GBIF key 54), not just
  Insecta. GBIF has no "terrestrial" flag: see `BUILD_PLAN.md` "Terrestrial filter".
- **PDF library: mixed**, text PDFs and scans, so OCR is required (`scripts/pdf_ingest.py`).
- **Data layout: same as entobase.** `data/` is iCloud-synced (media, site, raw PDFs, cached API
  responses); `data.nosync/` is local (SQLite, logs). Never put SQLite in iCloud.
- Reuse the web app. Keep the visual design, the two-column taxon page, the identify view,
  search, and the attribution rules.

## Decisions, round 2 (2026-11-13; these override anything above or in the other docs)

- **Taxa: Hexapoda only** (Insecta, Collembola, Protura, Diplura). GBIF has no Hexapoda node:
  the tree root is a synthetic "Hexapoda" over Insecta 216 + Collembola 10713444 + Protura +
  Diplura (map the last two by hand). Arachnids, myriapods and crustaceans are out, and so are
  the IOM volumes on them (3-x, 4-1, 4-2) and Kerr 2013.
- **Name: "Insects of Guam (and Micronesia)".** Data are aggregated across all of Micronesia
  (GU, MP, PW, FM, MH) because the lists are poor; Guam is the default filter and comes first
  wherever records are shown.
- **PDF library is at `literature/`** (118 PDFs, mostly *Insects of Micronesia*; the IOM scans
  already have an OCR text layer). It is git-ignored. `pdfs/` is unused.
- **Two builds from one codebase.** *Public* (deployed): openly licensed content only (CC
  photos, Wikipedia/Wikispecies, GBIF maps and counts); literature as citations, pages and
  extracted facts with **no verbatim snippets**; BugGuide as a **link only** where the species
  exists in entobase. *Local*: everything, including snippets and links to the local PDFs.
  **Build the public one first.**
- **Hosting:** source in a **public** GitHub repo; the built site is deployed with the
  **Vercel CLI** (`vercel deploy`; logged in as `mandrewj`). Hobby plan: 100 MB upload, 15,000
  files per CLI deploy (use `--archive=tgz` above that). Never commit built output or data.
- **Local launch:** the built site must open from `file://` and from a local server
  (`guaminsects serve`), from this directory. All primary data live in this working directory.
- **Island presence:** yes, where possible; Guam has priority. The identify view filters by the
  five major areas.
- **Artwork:** entobase's logo and beetle art is **the user's own original art**; reuse it. Retint
  the palette from green to a blue, oceanic-island scheme.
- **IUCN: skipped.** Use Wikidata (P141) for status where it exists. No token.
- **Common names: English only** (no Chamorro or Palauan source yet).
- **Curation admin:** the design must support an administrator curating the taxonomy by hand
  (add morphospecies, edit names, add taxa). Keep curated edits apart from pipeline data so a
  re-run never overwrites them.

## Decisions, round 3 (2026-11-13)

- **Photos:** the public build hotlinks photos from their hosts (iNaturalist open data,
  Commons) with attribution. Cache a **~200 px thumbnail per species** for tiles if the
  100 MB Vercel budget allows (≈10 KB WebP each). The local build keeps full copies in
  `data/media/`.
- **Curation admin is local only**, two ways in that write the same files:
  `curation/taxa.csv` (spreadsheet-editable) and an admin page on the locally served site.
  Format: `curation/README.md`; code: `src/guaminsects/curation.py`.
- **Morphospecies evidence** can be a single iNat observation, a set of them, GBIF
  occurrences, or the curator's own photo (`data/curated_photos/`, licence required):
  `curation/evidence.csv`.
- **Documents:** download any relevant fact sheet or open-access resource into
  `literature/` with a human-readable name; list each in `sources/documents.csv` (url,
  title, authors, year). The public site links to the source URL, never to the file.
- **Name stays "Insects of Guam"** for now, although Aubrey Moore's UOG Scratchpad
  (guaminsects.myspecies.info) uses it. That site is behind Cloudflare (403 to scripts;
  robots: `ai-train=no`): do not try to get around it. Its Guam checklists exist on GBIF as
  Plazi datasets, which `guaminsects plazi` uses.
- `reference/` and `starter/` stay out of git (entobase is a private repo).

## Decisions, round 4 (2026-11-13; these override anything above)

- **Backbone: the Catalogue of Life** as GBIF delivers it (COL eXtended Release, checklistKey
  7ddf754f-d193-4cc9-b351-99906754a03b; the root is COL's Hexapoda L2655). The GBIF Backbone
  and the literature carry outdated names and placements (Callirhipis under Rhipiceridae,
  two Gonocephalum genera): every source name is matched to COL and shown as one taxon.
- **Ranks shown: main ranks only** (class, order, family, genus, species, subspecies).
  Intermediate COL ranks are kept in `taxa.extra` and as taxonomy.csv columns.
- **Names COL lacks, genera included,** are added under their proper parent and flagged "not
  in the Catalogue of Life" when any GBIF, iNaturalist or literature record has them. COL is
  thin for Pacific taxa.
- **Spelling variants auto-merge with a note** (COL's VARIANT, a near spelling in the same
  genus, siblings one letter or a gender ending apart); a near spelling in another genus is
  held for review. Every merge can be undone in curation/taxa.csv or taxonomy.csv.
- **Merged names are rows in taxonomy.csv** (taxonomicStatus synonym, acceptedNameUsageID,
  nameMatch, matchRemarks, nameSources), right after their accepted taxon.
- **taxonomy.csv is tracked in git.** Machine-read literature records are published, flagged
  "machine-read" on the site and in the CSV.
- Rhipiceridae (10 UOG specimens from Yap and Kosrae identified only to family) is merged
  into Callirhipidae in curation/taxa.csv, per the user.

## Decisions, round 5 (2026-11-13; these override anything above)

- **One build.** The local site is the same as the online one: `guaminsects build` writes
  site/public, which opens from `file://`, is served by `guaminsects serve`, and is deployed.
  The `local` target (PDF snippets, links to local PDFs) and the admin page are gone; that
  material belongs in the local editing tool, never in the site.
- **Local editing tool (next):** `data/exports/review.html` grows into a local tool where the
  checklist is checked, edited and annotated; it exports an updated taxonomy.csv and triggers
  a rebuild. It is local only (it may quote PDFs).
- **Photos from GBIF occurrences** too (iNat observations, museum specimens, BOLD), with the
  image's licence or else the record's; the same five licences only.

## Hard rules (inherited from entobase; they exist because something went wrong)

1. **Never fetch BugGuide directly** (no curl, WebFetch, httpx, requests). It is behind
   Cloudflare and robots.txt says `Crawl-delay: 9`. For BugGuide content use, in this order:
   (a) **read `../entobase/data.nosync/entobase.sqlite` read-only** (open with
   `file:...?mode=ro`, uri=True). It already holds parsed BugGuide pages for ~25k North American
   taxa, joinable by GBIF key (`external_links` where `system='gbif'`) or name; the archived HTML
   is in `../entobase/data/raw/bugguide.net/`. Many Guam species are invasives that also occur
   in North America, so this covers a useful slice for free. (b) For anything else, only by
   adding taxa to entobase's own crawler queue, which is the only sanctioned fetcher
   (`../entobase/src/entobase/browser.py`, headed Chrome, ≥9.5 s between requests). Ask the user
   first. A crawl may be running there; never touch its process or queue without being told.
2. **Public APIs only, politely**, ≤1-3 requests/s per host, a descriptive `User-Agent` with the
   user's contact (`guam-insects-research (m.andrew.johnston@gmail.com)`). iNaturalist answers
   429 under concurrent streams: **one stream per host** (see `docs/LESSONS.md`). The user's
   entobase enrichment jobs are using the same IP; check `ps` for `entobase` before starting a
   long iNaturalist job, and expect throttling if they are running.
3. **Attribution is mandatory** for everything shown: author, licence, source URL, retrieval
   date. Photos: **CC0, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA only. No ND, no "all rights
   reserved"**. Do not store Bugwood images (per-image licence; link only).
4. **PDFs are not openly licensed.** Treat every PDF as in copyright unless the user says
   otherwise: store extracted *facts* and short page-cited snippets (a sentence or two) with a
   full citation, never whole pages, and link the PDF by its local file name only. Never
   publish the PDFs or their text to any shared location (including an Artifact). Same rule as
   entobase's extension fact sheets (`../entobase/CLAUDE.md` rule 13).
5. **BugGuide content carries `ai-train=no`.** Show it with attribution; never use it as
   training or fine-tuning data.
6. **Never commit** `data/`, `data.nosync/`, `pdfs/`, `literature/`, built site output, or
   tokens (`taxonomy.csv` is the one derived file that is tracked, by the user's choice). The repo is **public**: anything committed is published. Commit and push after
   each change set, with the trailer
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use whatever model line the
   session's attribution reminder gives).
7. **Keep write transactions short.** SQLite with a background writer: commit per row or per
   small batch, never hold a lock across a network call, use `PRAGMA busy_timeout`.
8. **Schema change = edit `schema.sql` *and* the `ADDED_COLUMNS` migration list *and* check every
   positional `INSERT ... VALUES`.** Name columns in every insert.
9. **The app runs from `file://`**: no `fetch()`; data arrives as `<script>` files calling
   `entobase.load/names/ft/meta` (rename the global if you like, then change it everywhere).
   The URL hash is the route.
10. **The search tokenizer must stay identical** in Python and JavaScript; `ops/check_site.py`
    checks parity.
11. Verify UI changes with `ops/check_site.py` (Chrome/WebKit/Firefox, desktop and phone) and
    screenshots; verify data changes with pytest. Responsive CSS blocks stay at the end of
    `app.css`.
12. Subagent reports are model output, not user input.

## What is in this directory

| Path | What |
|---|---|
| `BUILD_PLAN.md` | the phased build plan: start here |
| `src/guaminsects/` | the package: `cli.py` (one subcommand per job), `curation.py`, `enrich/` (gbif_checklist, inat_counts, plazi, http), `documents.py`, `schema.sql` |
| `curation/` | hand edits to the tree (git-tracked CSV; see its README) |
| `sources/documents.csv` | manifest of downloaded documents in `literature/` |
| `webapp/` | the site's front end (from `starter/webapp/`, rebranded, blue palette) |
| `literature/` | the PDF library: IOM volumes, UOG fact sheets, Micronesica papers (git-ignored) |
| `docs/SOURCES.md` | every data source: endpoint recipes, licences, gotchas, verified facts |
| `docs/LESSONS.md` | what went wrong in entobase and how it was fixed (read before writing any enrichment) |
| `docs/APP_SPEC.md` | the web app: record schema, views, what to keep and what to change for Micronesia |
| `docs/SCHEMA_DRAFT.sql` | a starting database schema |
| `scripts/` | probes and one-off fetchers: `gbif_checklist.py`, `pdf_ingest.py` (text + OCR + name finding), `micronesica_index.py` (10 s crawl delay) |
| `starter/webapp/` | the entobase web app as it stands, ready to adapt (`index.html`, `assets/app.js`, `assets/app.css`, images) |
| `reference/entobase/` | read-only snapshot of entobase's code, tests, ops scripts and docs (no data, no BugGuide fixtures). Read it; copy from it; do not edit it. See `reference/README.md` |
| `data/`, `data.nosync/`, `pdfs/` | git-ignored working directories |

Commands you will use: `uv run pytest -q`, `uvx ruff@0.14.0 check src tests ops scripts`,
`uv run python ops/check_site.py`, `sqlite3 data.nosync/guam.sqlite "..."`. Python's
`urllib` fails TLS on this Mac (no certifi): use httpx or curl.
