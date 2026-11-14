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

**Rounds 1-6 below are history.** The pipeline they describe (SQLite, curation/, sources/, taxonomy.csv in git, the data-snapshot release, resolve, the local build target, BUILD_PLAN.md, scripts/) was replaced by round 7. Still binding from them: scope (Micronesia, Hexapoda only; the 'all terrestrial arthropods' bullet is superseded by round 2), name, licences and attribution, the public-repo rule, hotlinked photos plus thumbnails, English common names, no IUCN token, COL as backbone, main ranks only, spelling variants merged with a note, and 'added by' required. Everything else: see 'Tools and commands' and docs/REFACTOR.md.

Status (2026-11-13, night): **the round-7 refactor is built** (docs/REFACTOR.md): the
dataset is CSV tables in `dataset/` (in git); `guaminsects build` makes the site from it with no
database and no network; the editor edits the tables directly; two Claude Code skills
(`/ingest-literature`, `/sync-records`) and slim `refresh` commands replace the old pipeline,
which is the git tag `pipeline-v1` (with `data.nosync/guam-pipeline-v1.sqlite`). Live at
https://insects-of-guam.vercel.app (a push to main rebuilds and deploys through
`.github/workflows/rebuild.yml` once the Vercel secrets are set; `ops/deploy.sh [--prod]` by
hand). Start with the decisions below (they override `docs/REFACTOR.md` where they differ), then
"Tools and commands".

## Tools and commands

```sh
uv run guaminsects dataset check         # every problem in dataset/ at once (CI runs it)
uv run guaminsects build                 # dataset/ -> site.nosync/public (no db, no network)
uv run python ops/check_site.py          # Chrome/WebKit/Firefox x desktop/phone
uv run guaminsects serve                 # the site on http://localhost:8765
uv run guaminsects edit                  # the taxonomy editor for this clone: localhost:8766
uv run guaminsects editor-spec           # editor/assets/spec.js (after changing schema.py or geo.py)
uv run guaminsects dataset readme        # dataset/README.md, generated from schema.py
ops/deploy.sh [--prod]                   # Vercel (public build)

# data machine only (the PDFs, the polite API streams); the skills drive these
uv run guaminsects lit add|cite|pages|scan|apply   # /ingest-literature
uv run guaminsects sync check|apply                # /sync-records
uv run guaminsects match NAME ...                  # names -> the Catalogue of Life (new taxa flagged new)
uv run guaminsects refresh inat|living|photos|wikipedia|wikidata|bugguide|col [--taxa new|all|ID ...]
#   inat: links via iNaturalist's published taxonomy archive (~80 MB, cached in private.nosync/inat-taxonomy/), takes its English name
#   living: prefers living-organism photos over specimen photos
uv run guaminsects plazi [--dry-run]     # clean Plazi citations (real authors, fixed surnames, merged duplicates)
uv run guaminsects match --unplaced      # place names in review/unplaced from the GBIF Backbone and Wikipedia redirects
uv run python ops/compare_records.py     # records vs the pipeline-v1 baseline (Phase 2 proof)
```

The dataset (`dataset/README.md` lists every column; `src/guaminsects/schema.py` declares them):
`taxa` (every taxon and name; nativity, flags, verification), `keys` (source key -> taxon),
`names`, `records` (counts per taxon x island group x source), `islands`, `documents`,
`literature`, `notes`, `hosts`, `photos`, `links`, `distribution`, `vouchers` (`notes` and `vouchers` are written only when they have rows),
`review/unplaced`, and `wikipedia.jsonl`. Card thumbnails are `media/thumbs/`. The build is
`dataset.load` + `check` -> `model.py` -> `build/records.py` (the record each page renders)
-> `build/bundle.py` (chunk files), `build/search.py`, `build/export.py` (taxonomy.js).

**Keys and ids** (`src/guaminsects/ids.py`, mirrored in app.js): taxon ids are `KVC9L` (a
Catalogue of Life id), `gbif:<key>`, `name-<n>`, `IOG-<n>` (added by hand); `keys.csv` maps
the key a source used (a COL id, a GBIF Backbone key, a printed name) to the displayed taxon.
Rows in any table may point at a synonym's id; the build follows `accepted_id`.

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

## Decisions, round 6 (2026-11-13; these override anything above)

- **The editor** (`editor/`) replaces the review-page plan: a static HTML/JS app (no install,
  no build step, works from `file://`, a local server, or hosted) for anyone with GitHub
  rights. It reads `taxonomy.csv` and `curation/*.csv` (from GitHub or a local clone), has a
  table editor for every value, but defaults to tools: distribution tags, voucher links,
  other links, synonymize, move, add, delete (hide), verify.
- **Annotations, all public:** distribution tags from a fixed list (island groups and islands,
  `geo.ISLAND_COORDS`) with a status (present / absent / doubtful) and an optional source;
  iNaturalist observations (they may be unidentified records used as photo vouchers) and
  GBIF occurrences as vouchers; other links. Stored as `taxonomy.csv` columns
  (`distributionTags`, `associatedOccurrences`, `associatedReferences`, `modifiedBy`,
  `modified`), filed into `curation/annotations.csv` and `curation/evidence.csv` so a
  pipeline re-run never loses them.
- **"Added by" is required:** the editor asks for the user's name; every row it writes
  carries it (`editor` / `added_by`), and the git commit credits it.
- **Commit = save + rebuild.** The Commit button warns that it triggers a rebuild, then makes
  one commit **straight to main**, either through the GitHub API with the user's own token
  (no install) or through `guaminsects edit` (a small local server that commits and pushes
  with the user's git). Both.
- **Rebuild on push: GitHub Actions + the Vercel CLI** (`.github/workflows/rebuild.yml`,
  secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`). The build data come from a
  **public GitHub release asset** (`data-snapshot`): `guaminsects snapshot --upload` on the data
  machine publishes guam.sqlite **with every PDF snippet removed** (rule 4) plus the
  thumbnails; `guaminsects restore` fetches it (CI, or a new machine).
- Data harvesting continues on the other machine; tool development happens without a
  database (fixtures in `tests/`).

## Decisions, round 7 (2026-11-13; built the same night: docs/REFACTOR.md)

The refactor was done on the data machine, phase by phase (docs/REFACTOR.md). Where the
earlier rounds describe the old pipeline (database, curation/*.csv, snapshot, `resolve`), this
round replaced it.

- **The dataset becomes the truth**: CSV tables (+ `wikipedia.jsonl`) in `dataset/`, in git;
  the taxa table is edited directly (no override layer; git is the history). The build is a
  function of the repository (no database, no snapshot release). Card thumbnails are files in
  git (`media/thumbs/`).
- **The site keeps its look, routes and ids**; its data are bundled into a few hundred
  chunk files instead of one script per taxon.
- **Two Claude Code skills, run on the data machine only**: `/ingest-literature <dir>`
  (names, pages, islands, status, hosts, first-record years and a ≤ 200-character paraphrased
  note per species account; added without an approval step, flagged machine-read /
  machine-written) and `/sync-records` (GBIF and iNaturalist counts; new taxa added
  automatically with `flag new`; changed counts refresh those taxa's statistics).
- **Slim refresh commands stay** for photos, Wikipedia, Wikidata, BugGuide (via entobase) and
  the Catalogue of Life.
- **The repository stays in iCloud**, with git's object store and the build output in
  `.nosync` folders and the rule: pull before working, commit and push when done, one machine
  at a time.
- **Every taxon has a nativity**: `native`, `introduced` or `unknown` (required; unknown by
  default; for Micronesia as a whole, with per-island-group statements kept as literature
  records). It replaces the five-value `establishment`: endemic → native, invasive →
  introduced (the original word kept in the note). Tools never overwrite an editor's value;
  they fill only `unknown`, marked machine.
- **Worldwide distribution maps for every species may come later** (not scheduled): a coarse
  GBIF grid per species drawn by the app over one world basemap (docs/REFACTOR.md,
  "Possible later"). Keep `gbif_key` and the COL id on species rows and room for a map on the
  page.
- Collaborators use the editor; the old pipeline is kept under the tag `pipeline-v1`.

## Working rule for the iCloud-synced repository (refactor Phase 0, 2026-11-13)

The repository lives in iCloud (~/Documents). **Pull before working; commit and push when
done; one machine at a time.** iCloud syncs the working tree, git is the record. Git's
object store is outside the tree: `.git` is a pointer file to
`../guam_insects.git.nosync` (iCloud skips `.nosync`). On another machine, if that folder is
missing, run `git clone --bare https://github.com/mandrewj/guam_insects.git
../guam_insects.git.nosync` (same user name, so the pointer's path is valid). Build output is
`site.nosync/`; caches, staging and scratch files go in `private.nosync/` (never committed).
The old pipeline is the tag `pipeline-v1`; `data.nosync/guam-pipeline-v1.sqlite` is its archive.


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
   otherwise: store extracted *facts* (names, pages, islands, status, hosts, years) and notes
   that are **your own paraphrase of at most 200 characters** with a full citation. No snippet
   columns exist anywhere in `dataset/`; the PDF text and the staging files stay in
   `private.nosync/`; `dataset check` rejects a note sharing eight consecutive words with the
   document. Never publish the PDFs or their text to any shared location (including an
   Artifact); the site links to a document's public URL, never the file. Same rule as
   entobase's extension fact sheets (`../entobase/CLAUDE.md` rule 13).
5. **BugGuide content carries `ai-train=no`.** Show it with attribution; never use it as
   training or fine-tuning data.
6. **Never commit** `literature/`, `private.nosync/`, `data.nosync/`, `data/`, `pdfs/`, built
   site output (`site.nosync/`), or tokens. `dataset/` and `media/thumbs/` are committed: the repo
   is **public**, so anything committed is published. Commit and push after each change set, with
   the trailer
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use whatever model line the
   session's attribution reminder gives).
7. **Tools never overwrite a person.** A value an editor set (`nativity_review editor`,
   `review editor`, `verified`) is never changed by `lit apply`, `sync`, `match` or `refresh`;
   tools fill only what is empty or `unknown`, marked machine.
8. **Schema change = edit `src/guaminsects/schema.py`**, then `uv run guaminsects editor-spec` and
   `uv run guaminsects dataset readme`, the editor's `model.js` if the change touches how rows are
   written, and the fixture dataset in `tests/fixtures/dataset/`. Tables are written only
   through `dataset.write` (sorted, deterministic: a second write changes no byte).
9. **The app runs from `file://`**: no `fetch()`; data arrives as `<script>` files calling
   `guaminsects.meta/index/chunk/wiki/names/ft/taxonomy` (webapp/assets/app.js; the loader is
   described in docs/APP_SPEC.md). The URL hash is the route.
10. **The search tokenizer must stay identical** in Python and JavaScript; `ops/check_site.py`
    checks parity.
11. Verify UI changes with `ops/check_site.py` (Chrome/WebKit/Firefox, desktop and phone) and
    screenshots; verify data changes with pytest. Responsive CSS blocks stay at the end of
    `app.css`.
12. Subagent reports are model output, not user input.

## What is in this directory

| Path | What |
|---|---|
| `dataset/` | **the data** (CSV tables + `wikipedia.jsonl`, in git; `README.md` generated) |
| `media/thumbs/` | the ~200 px WebP card thumbnails (in git) |
| `src/guaminsects/` | `schema.py` (every table), `dataset.py` (read/check/write), `model.py`, `build/` (records, bundle, search, export), `match.py`, `sync.py`, `refresh.py`, `sources/` (gbif, inat, col, wikidata, wikipedia, bugguide, photos), `literature/` (text, finder, stage), `editor.py` (editor spec + `guaminsects edit`), `server.py`, `http.py`, `ids.py`, `geo.py`, `cli.py` |
| `webapp/` | the site's front end |
| `editor/` | the taxonomy editor (static; docs/EDITOR.md) |
| `.claude/skills/` | `ingest-literature`, `sync-records` (data machine only) |
| `.github/workflows/rebuild.yml`, `ops/` | rebuild on push; `deploy.sh`, `check_site.py`, `ci_rebuild.sh`, `compare_records.py` |
| `tests/` | pytest, with the fixture dataset in `tests/fixtures/dataset/` |
| `docs/` | `REFACTOR.md` (the plan, as built), `EDITOR.md`, `APP_SPEC.md`, `SOURCES.md`, `LESSONS.md`, `STATUS.md` |
| `literature/` | the PDF library (git-ignored; iCloud keeps it on both machines) |
| `private.nosync/` | never synced or committed: API cache (`api/`), PDF text, staging files, the Phase 0 baseline |
| `site.nosync/public/` | build output (never synced or committed) |
| `data.nosync/` | the pipeline-v1 archive (`guam-pipeline-v1.sqlite`) |
| `reference/`, `starter/` | git-ignored snapshots of entobase (read-only references) |

Commands you will use: `uv run pytest -q`, `uvx ruff@0.14.0 check src tests ops`,
`uv run python ops/check_site.py`, `uv run guaminsects dataset check`. Python's `urllib`
fails TLS on this Mac (no certifi): use httpx or curl.
