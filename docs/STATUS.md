# Status and open questions

Updated by the build session; newest first. Decisions live in CLAUDE.md; this file is what
is done, what is waiting, and what needs the user.

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

### Waiting on the user
- **Deploy**: the live site (https://insects-of-guam.vercel.app) is the interim COL build from
  11:00. `ops/deploy.sh --prod` publishes this one (the session's permission check stopped
  the agent from deploying).
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
- **Site**: `guaminsects build public local`; both open from `file://` and from
  `guaminsects serve`. Taxon pages show presence per island group (GBIF / iNat / literature,
  never added together), a schematic island map, photos with credits, literature citations
  with pages, Wikipedia (collapsed), IUCN category, cross-links, crops attacked, and
  machine-read native/introduced statements. The Identify view compares a group with a photo
  and island map per tile, filtered by island group. `ops/check_site.py` passes in Chrome,
  WebKit and Firefox at desktop and phone sizes.
- **Curation**: `curation/taxa.csv` + `curation/evidence.csv`, edited by hand, through
  `taxonomy.csv` (Darwin Core, rewritten by every build after taking in edits made to it;
  also downloadable from any taxon page for that taxon and everything under it), or the local admin
  page (`guaminsects serve`, then /admin.html). Every save is checked against the whole tree
  first.
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
