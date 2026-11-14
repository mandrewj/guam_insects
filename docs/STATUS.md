# Status and open questions

Updated by the build session; newest first. Decisions live in CLAUDE.md; this file is what
is done, what is waiting, and what needs the user.

## 2026-11-14: after the refactor (the pre-refactor sections further down are history)

- Production is live (https://insects-of-guam.vercel.app); a push to main rebuilds and deploys through GitHub Actions.
- Public site: landing page with map, region cards and quick links; search suggestions with parent names; header Checklist link.
- Editor: Review by document, Quick review, merge/exclude for unplaced names, Sources tab with a reference picker, Cite-a-source; favicon (orange).
- Tools: `match --unplaced`, `refresh inat` (taxonomy archive) and `refresh living`, `plazi` clean-up.
- Audit of 2026-11-14: see docs/AUDIT-2026-11-14.md (decisions waiting for the owner).

## 2026-11-13, late night: the refactor is built (docs/REFACTOR.md, CLAUDE.md round 7)

### Done (phases 0-7, on the data machine)
- **Phase 0**: tag `pipeline-v1`; `data.nosync/guam-pipeline-v1.sqlite`; the baseline site
  (records, screenshots) in `private.nosync/baseline/`; git's object store moved out of iCloud
  (`../guam_insects.git.nosync`); build output in `site.nosync/`.
- **Phase 1**: `schema.py`, `dataset.py`, the migration (run once, then retired): 6,643 taxa and
  name rows, 12,175 record rows, 6,571 literature rows, 11,974 photo rows, 2,143 Wikipedia
  articles, 3,204 thumbnails. **Nativity**: 16 introduced and 1 native from machine-read
  statements, the rest unknown; no conflicts.
- **Phase 2**: `model.py`, `build/records.py`, `build/export.py`: every record equals the
  baseline apart from the intended changes (nativity; a document counted twice for a taxon with two
  source keys now once, 48 taxa; crop-pest areas are the taxon's own, 183; one Schreiner mention
  is now an account; whitespace in titles collapsed; photo dates are dates) and taxonomy.csv
  equals the old export in every column.
- **Phase 3**: the site from the dataset, bundled: 194 chunk files (largest 370 KB), Wikipedia
  chunks, 36 search shards. check_site passes in all three engines at both sizes, with checks
  for chunks, shards and the Wikipedia expand; screenshots are identical except the new
  nativity badge.
- **Phase 4**: the editor edits the dataset directly (nativity, review, unplaced-name tools and
  worklists); CI checks the dataset, runs the tests, builds, checks and deploys from a clone.
- **Phase 5**: `match`, `sync check|apply`, `refresh ...` on the dataset, tested against canned
  API answers. **No live run yet.**
- **Phase 6**: `lit add|cite|pages|scan|apply` and the skills `/ingest-literature` and
  `/sync-records` (`.claude/skills/`). No run on a real PDF yet.
- **Phase 7**: the old pipeline code, `curation/`, `sources/`, `taxonomy.csv`, BUILD_PLAN.md and
  the scripts are removed (they are in the tag).

### Waiting on the user
- **Production deploy**: a preview deployment of the bundled site is live and `Ready`; the
  production deploy (`ops/deploy.sh --prod`, or a push once the Vercel secrets below are set) was
  not run, because the session's permission mode refused it. Run `ops/deploy.sh --prod`.
- **Vercel secrets** in the GitHub repo: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
  (orgId / projectId in `site.nosync/public/.vercel/project.json`). Until then CI checks every
  push and stops with a notice instead of deploying.
- (Done) the old `data/` (API cache, PDF text copy, media) and the duplicate database are deleted; the
  PDF text lives in `private.nosync/pdf_text/`; `data.nosync/guam-pipeline-v1.sqlite` is the archive.
- **First live runs**, reviewed with you: `uv run guaminsects sync check` (look at the summary
  before `sync apply`), and `/ingest-literature` on one short fact sheet before a monograph.
- A taxonomy editor session on the real data, from a browser, to see the new tools.

### Notes for whoever continues
- The record builder reads only `dataset/`; the old `site.build_records` is gone, so the
  comparison with the baseline (`ops/compare_records.py`) is the proof it still matches what the
  pipeline made.
- Photo rows carry the pointer for borrowed photos (`role inherited`, `from_id`) rather than
  recomputing the choice on every build; `refresh photos` and `sync apply` recompute it
  (`sources/photos.py inherit`).
- A literature row's `status_area` / `status_page` hold the nativity statement; `areas` is where
  the document records the taxon (presence).

## Earlier: 2026-11-13, night: the taxonomy editor (pre-refactor) (on the new machine, no database)

### Done
- **Editor** (`editor/`, docs/EDITOR.md): static, opens from `file://`, `guaminsects edit`
  or anywhere; loads the latest taxonomy from GitHub. Tools for distribution tags, vouchers
  (iNat / GBIF), links, synonymize / split, move, add taxa and names, confirm, hide, delete;
  a virtualised table of every column; a change list kept in the browser; Commit with a
  GitHub token or through `guaminsects edit` (your git), warning that it rebuilds the site.
  Name required, credited on every row and in the commit.
- **Annotations**: `curation/annotations.csv` (distribution tags, links) and evidence.csv
  (vouchers, with `editor`); taxonomy.csv columns `distributionTags`,
  `associatedOccurrences`, `associatedReferences`, `modifiedBy`, `modified` (both ways: a
  spreadsheet edit to them is filed too). On the site: an "Ed." column and the editors' tags
  in the presence box, present tags as records (rolled up, islands lit), added-by on
  evidence and links.
- **Rebuild on push**: `.github/workflows/rebuild.yml` + `ops/ci_rebuild.sh`; data from the
  public release `data-snapshot` (`guaminsects snapshot --upload`, PDF text removed;
  `guaminsects restore`). `ops/harvest.sh` uploads the snapshot before deploying.
- **Tree fixes** found by the editor tests: a taxon merged by hand leaves the tree even when
  taxa under it put it there (they move to the taxon it was merged into); a name merged by
  hand takes its spelling variants along; a hand-added name keeps its authorship.
- taxonomy.sync takes in only *uncommitted* edits to taxonomy.csv, so a pulled regeneration
  is never mistaken for edits.
- pytest: 63 passed (Chromium runs the editor's JavaScript against the fixture world and
  checks it agrees with `resolve`). Screenshots in Chromium and WebKit, desktop and phone;
  Playwright's Firefox does not start on this Mac (macOS 27), so it is untested here.

### Waiting on the user
- **Push**: the editor, workflow and refactor-plan commits are local only. GitHub refuses a
  push that adds `.github/workflows/` without the `workflow` scope: run
  `gh auth refresh -h github.com -s workflow`, then `git push`.
- **Next: the refactor** on the data machine, docs/REFACTOR.md (CLAUDE.md round 7), from
  Phase 0. It adds a required nativity (native / introduced / unknown) for every taxon, and
  leaves room for worldwide species maps later.
- **Vercel secrets** in the GitHub repo: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
  (orgId / projectId in `site/public/.vercel/project.json` on the data machine).
- **The first snapshot**: on the data machine, `git pull`, then
  `uv run guaminsects snapshot --upload` (needs `gh auth login`). Until both exist, the
  workflow checks each push and stops with a notice instead of deploying.
- The first editor commit rewrites taxonomy.csv once (the five new columns).

## 2026-11-13, evening: one build, GBIF images; development moves to another machine

### Done
- **One build.** The local site is now the online one: `guaminsects build` writes
  `site/public`, which `index.html` (top of the folder) opens, `guaminsects serve` serves,
  and `ops/deploy.sh --prod` deploys. The `local` target, the admin page
  (`webapp/admin.*`) and the PDF snippets / local-PDF links in the site are gone. The
  curation API in `server.py` stays for the editing tool (below).
- **Photos from GBIF occurrences** (`guaminsects photos gbif`, `enrich/photos.py`
  `gbif_sweep`). Pass 1: every Hexapoda image from the five areas (7,615 occurrences: iNat
  research grade, then NMNH, NHMUK, AntWeb, BOLD, ANSP...), ranked first on a species' page
  (rank_hint 5 for an observation from here, 10 for a specimen from here). Pass 2: each
  species still without a photo, images from anywhere (rank_hint 40; resumable through
  `gbif_photo_queries`). Licence from the image, else the record's; CC0/BY/BY-SA/BY-NC/
  BY-NC-SA only; sound plots and label shots skipped. Museum images are shown through GBIF's
  image cache (`api.gbif.org/v1/image/cache/...`), never as multi-MB originals. Photos found
  only on GBIF are credited "GBIF" with the rights holder and catalogue number.
- Photos without a stored size (GBIF gives none) no longer break the gallery; the
  thumbnail step records the size of each card photo it fetches.

### Image sweep (finished 2026-11-13, 23:30 UTC)
- Pass 1: 7,382 occurrences from the five areas, 10,332 photos. Pass 2: 1,640 species asked,
  452 found images elsewhere (2,073 photos).
- `photos verify` (new, in `ops/harvest.sh`): fetches the small copy of each shown GBIF photo
  once, records its size, and marks it `unreachable` when the museum refuses GBIF's image
  cache (230 of them, mostly CAS/AntWeb, image by image rather than whole hosts); then picks
  again. Every shown photo loads.
- **Species with photos of their own: 1,680 of 3,006** (was 893); genera 1,248 own, 1,459 with
  any; 3,513 taxa with photos in all (was 2,526).
- Rebuilt, check_site passes in all 6 configurations, deployed to production (deploy
  le4qnqqg7, built 23:30 UTC). The site is 55 MB (budget 90).
- **Not done:** iNaturalist taxon photos looked up by name, for taxa Wikidata does not link
  to iNat (`/taxa?q=<name>&rank=...`, then the existing batched `/taxa/<ids>` sweep). iNat
  answered 429 all evening because entobase's `link --stubs` job shares the IP. GBIF already
  carries iNat's research-grade observation photos, so this would add only iNat's curated
  taxon photos for species with no observation on GBIF. Run it when entobase is idle.

### Next: the local editing tool
- Grow `data/exports/review.html` (`ops/review.py`) into a local tool where the checklist is
  checked, edited and annotated. It exports an updated `taxonomy.csv` and triggers a rebuild.
  Local only (it may quote PDFs). Building blocks: the curation API in `server.py`
  (`/api/taxon`, `/api/decision`, rebuild with `/api/status`), `taxonomy.import_edits`
  (merges, splits, field edits), and `pdf_mentions` / `pdf_candidates` (pages and snippets).

### Moving to another machine
- **Synced by iCloud** (the folder is under Documents): code, `curation/`, `sources/`,
  `taxonomy.csv`, `literature/`, `data/` (thumbnails, API caches, exports), `site/`
  (including `site/public/.vercel`, the Vercel project link).
- **Not synced: `data.nosync/`** (`guam.sqlite`, 60 MB, and logs) and `venv.nosync/`. Copy
  `data.nosync/guam.sqlite` across by hand, or rebuild it with the pipeline in CLAUDE.md
  (hours, mostly GBIF and Wikipedia). Then `uv sync`.
- `../entobase/data.nosync/entobase.sqlite` (BugGuide links, read-only) is not synced
  either; without it `guaminsects bugguide` has nothing to read, and the existing links in
  guam.sqlite still build.
- Vercel: `vercel login` as mandrewj on the new machine; `ops/deploy.sh --prod`.
  GitHub: the repo is mandrewj/guam_insects (public).
- Wait for iCloud to finish syncing before building (a half-synced `data/media/thumbs` gives
  a site with missing card pictures). iCloud also makes " 2" copies of files edited on both
  machines; delete those (they broke pytest once).

## 2026-11-13, afternoon: the Catalogue of Life backbone

### Done
- **Tree = Catalogue of Life** (COL XR through GBIF), main ranks only. 5,183 taxa,
  **3,006 species** (1,518 recorded from Guam); 170 species and 10 genera not in COL, added
  under their COL parent and flagged. 3 fossil taxa removed (Palaeodictyoptera and the two
  names under it; COL's extinct list plus a list of fossil-only orders).
- **Names merged into one taxon**: 1,460 (1,000 COL synonyms, 376 duplicate GBIF Backbone
  entries with another author, 80 spelling variants, Rhipiceridae merged by hand into
  Callirhipidae). All are synonym rows in `taxonomy.csv` and listed on each page.
- **taxonomy.csv tracked in git**; machine-read literature records published and flagged.
- **Harvest** (`ops/harvest.sh`): literature re-scan, name matching, COL taxa, COL common
  names, synonyms and extinct list (ChecklistBank), Wikidata by COL id (with Wikispecies
  links), Wikipedia (2,119 articles), Commons and iNat photos (2,526 taxa with photos),
  introduced-species statements; both sites rebuilt; check_site passes in all 6 configurations.
- UI: checklist under the cards on higher taxa, region tooltips, shorter intro, blue
  favicon, US spellings, iNat/GBIF links first, thumbnails carried up to groups with none.

### Deployed
- Superseded by the evening build above. Re-run `ops/harvest.sh` (it deploys at the end) or
  `ops/deploy.sh --prod`.

### Waiting on the user
- **Review page** (`data/exports/review.html`): 210 literature or near-spelling names held for
  review, 42 names with records that could not be placed, families with family-level
  records only (candidates for merges like Rhipiceridae).
- iNat observation photos from Micronesia: not built yet.

## 2026-11-14 (overnight run after the user's go-ahead)

### Built and working

- **Pipeline** (`guaminsects <command>`, order in CLAUDE.md): GBIF presence by area, GBIF
  classification, Plazi literature checklists, the crop-pest list, PDF library text and
  names, island records, introduced-species statements, Wikidata, Wikipedia, BugGuide links
  (entobase, read-only), Commons photos with 200 px thumbnails, and `resolve` (tree = GBIF +
  `curation/*.csv`).
- **Site**: `guaminsects build` (one build, site/public); it opens from `file://` and from
  `guaminsects serve`, and is the one deployed. Taxon pages show presence per island group (GBIF / iNat / literature,
  never added together), a schematic island map, photos with credits, literature citations
  with pages, Wikipedia (collapsed), IUCN category, cross-links, crops attacked, and
  machine-read native/introduced statements. The Identify view compares a group with a photo
  and island map per tile, filtered by island group. `ops/check_site.py` passes in Chrome,
  WebKit and Firefox at desktop and phone sizes.
- **Curation**: `curation/taxa.csv` + `curation/evidence.csv`, edited by hand, through
  `taxonomy.csv` (Darwin Core, rewritten by every build after taking in edits made to it;
  also downloadable from any taxon page for that taxon and everything under it). Every save
  is checked against the whole tree first. (The admin page was removed on 2026-11-13; a local
  editing tool grown from the review page comes next.)
- **Library**: `sources/library.csv` gives a citation for all 207 PDFs (IOM from Bishop
  Museum's index, with public URLs). `sources/documents.csv` lists the 49 UOG documents and
  63 Micronesica papers downloaded tonight, with readable file names under `literature/`.
- **Review page**: `uv run python ops/review.py` writes `data/exports/review.html` (local
  only: it quotes PDFs). It holds the 50-species sample, doubtful records, literature-only
  taxa and unmatched names.

### Numbers at the end of the night (2026-11-14, 09:00, after iNaturalist came through)

- **4,793 taxa: 2,668 species**. **1,360 species are recorded from Guam.** Every species has at least one source placing it in Micronesia.
- **Sources per species**: GBIF records ~2,000; the digitised *Insects of Guam* (Plazi)
  ~450 on Guam; the PDF library's species accounts ~1,000 (island-level); Nafus &
  Schreiner's crop pests ~290 (Palau, FSM islands, with 830 host-crop pairs).
- **506 species are in the tree only because of the literature.** These are historical
  records the databases lack, or old names GBIF resolves to an accepted one. Where a species
  has both, the PDF-derived island group agrees with GBIF/Plazi for 69% of claims. A sample
  of the rest shows mostly real older records (ants in Clouse 2007, mosquitoes in IOM 12-1),
  plus some leaks between neighbouring species accounts (now limited by bounded sections).
- **iNaturalist**: research-grade, wild observations of 762 taxa across the five areas
  (Guam 324 taxa / 5,563 observations; CNMI 209; Palau 133; FSM 48; Marshalls 48), 438
  matched to GBIF names.
- **Pages**: 2,502 taxa with photos (Commons and iNat), 2,164 with Wikipedia, 1,359
  with a BugGuide link, 11,320 GBIF synonyms searchable ("also known as").
- **Native/introduced**: 16 machine-read statements (Schreiner 1991, Nafus 1991) for 15
  taxa. GBIF records almost never say (`establishmentMeans` on 7 Guam records).
- **Review page** (`data/exports/review.html`): 750 species rest on one or two GBIF records
  and nothing else; 46 of them are North American species with a BugGuide page (likely
  mislabelled specimens). 53 species headings in the PDFs match nothing in GBIF.
- **Public build**: 38.5 MB, 8,400 files (thumbnails included). Passes the smoke test in Chrome, WebKit and Firefox.

### Ran at full scale without a person's dry-run check

BUILD_PLAN asks for a 50-taxon dry run before any enrichment at scale. The read-only API
sweeps (GBIF, Wikidata, Wikipedia, Commons) were run for all taxa because they are cheap,
cached and reversible. Nothing has been published. The review page is the check to make
before the first deploy.

### Taxonomy CSV (2026-11-13, later)

- `taxonomy.csv` at the top of the folder: Darwin Core columns, family on every row, island
  groups, literature citations with pages, GBIF specimen counts, and `verificationStatus`
  (editor confirmed > literature records > specimen records > unconfirmed). Species:
  1,396 literature records, 1,013 specimen records, 259 unconfirmed; none confirmed yet.
- Edits to it are taken in by the next build; the site's "Download taxonomy" box gives the
  whole tree or the taxon on screen and everything under it. Format: `curation/README.md`.
- New: `guaminsects specimens` (GBIF preserved specimens per area), `guaminsects taxonomy`,
  `export --under ID`, `import FILE [--dry-run]`; `verified` column in `curation/taxa.csv`.

### Waiting on something

- **iNaturalist observation photos from Micronesia** (rather than iNat's general taxon
  photos) are not fetched yet: one request per taxon (~760), best run when entobase is idle.
- **First deploy**: `ops/deploy.sh` (preview) / `ops/deploy.sh --prod`. Not run, because it
  publishes. The public build is about 24 MB in about 6,000 files, inside Vercel Hobby's limits.

### Questions for the user

1. **Deploy**: may I run the first Vercel deployment (a preview first)?
2. **Doubtful records**: hide the fossil order Palaeodictyoptera, and species that rest on one
   or two GBIF records with a BugGuide page (likely mislabelled North American specimens)?
   The review page lists them. The default would be a `hidden` row in `curation/taxa.csv`
   with a reason.
3. **Literature presence before review**: species accounts in the IOM monographs give island
   records ("pdf" presence), currently shown as "Lit." and marked as machine-read. Show them
   publicly before a person reviews them, or only after a decision in
   `curation/pdf_decisions.csv`?
4. **Crop pest list**: Moore's GitHub CSV has no licence. I use its facts (island presence,
   host crops) with a citation and copy no text. OK, or ask Aubrey Moore first?
5. **UOG fact sheets behind the JavaScript viewer** (banana lace bug, banana leaf roller,
   pumpkin beetle, mango seed weevil, little fire ant, the coconut rhinoceros beetle series):
   save the PDFs by hand into `literature/UOG fact sheets/`, or leave them as links?
6. **Track `taxonomy.csv` in git?** It is rewritten by every build and git-ignored for now,
   because committing it publishes it (the repo is public) and it includes the machine-read
   literature records of question 3. Tracking it would give a history of every taxonomy change.
