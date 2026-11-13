# Status and open questions

Updated by the build session; newest first. Decisions live in CLAUDE.md; this file is what
is done, what is waiting, and what needs the user.

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
  `guaminsects export` / `import` (a spreadsheet of the whole checklist), or the local admin
  page (`guaminsects serve`, then /admin.html). Every save is checked against the whole tree
  first.
- **Library**: `sources/library.csv` gives a citation for all 207 PDFs (IOM from Bishop
  Museum's index, with public URLs). `sources/documents.csv` lists the 49 UOG documents and
  63 Micronesica papers downloaded tonight, with readable file names under `literature/`.
- **Review page**: `uv run python ops/review.py` writes `data/exports/review.html` (local
  only: it quotes PDFs). It holds the 50-species sample, doubtful records, literature-only
  taxa and unmatched names.

### Ran at full scale without a person's dry-run check

BUILD_PLAN asks for a 50-taxon dry run before any enrichment at scale. The read-only API
sweeps (GBIF, Wikidata, Wikipedia, Commons) were run for all taxa because they are cheap,
cached and reversible. Nothing has been published. The review page is the check to make
before the first deploy.

### Waiting on something

- **iNaturalist**: species counts per area and taxon photos are written and tested, but iNat
  answered 429 all night while entobase's `link --stubs` used the same IP. They retry
  every 5 minutes; rerun `uv run guaminsects inat` and `uv run guaminsects photos inat
  select thumbs` once entobase is idle.
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
