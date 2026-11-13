# Build plan

Goal: an offline, `file://` web app for the terrestrial arthropods of Micronesia, built from
GBIF + iNaturalist (backbone, records, photos, ranges), the user's PDF library (descriptions,
keys, records, citations), and supplements (Wikipedia, Wikispecies, Wikidata, IUCN, BugGuide via
entobase's database, Bugwood links). Read `CLAUDE.md` and `docs/LESSONS.md` first.

Work in phases; each ends in something that runs, is tested, and is committed. Do not start a
phase's enrichment at scale before its dry run on ~50 taxa has been looked at by a person.

## Phase 0: setup (1 session)

- `uv init`-style project: package `guaminsects` (src layout), CLI `guaminsects`, Python ≥3.13,
  deps like entobase (`httpx`, `beautifulsoup4`, `lxml`, `pillow`, `markdownify`, `playwright` for
  `check_site.py`) plus `pymupdf` is optional (the scripts use poppler + tesseract:
  `brew install poppler tesseract`, already present on this Mac).
- venv outside iCloud (`venv.nosync`, symlink `.venv`): iCloud hides `.pth` files inside `.venv`.
- Copy and adapt: `reference/entobase/src/entobase/{config,db,enrich/http}.py`, the test layout,
  `ops/check_site.py`. New `config.py`: paths `data/`, `data.nosync/`, SQLite
  `data.nosync/guam.sqlite`, contact for the User-Agent.
- Answer the open questions in `CLAUDE.md` with the user; put the PDFs at `pdfs/`.
- `git init`, private repo after the user agrees.

## Phase 1: checklist and tree (the backbone)

1. **Species list.** `scripts/gbif_checklist.py` (works: 1,586 Arthropoda species with Guam
   records, 829 CNMI, 1,274 Palau, 1,504 FSM, 1,085 Marshalls, as of 2026-11-13) pages GBIF's
   `speciesKey` facet by country. Extend it to the full set of *taxon keys* (species and also
   records identified only to genus/family: facet `genusKey`, `familyKey`) so a genus with no
   species-level record still gets a page. Keep `(taxon, country, records, first/last year)`.
2. **iNaturalist.** For each country's iNat place (Guam 7316, CNMI 8355, Palau 7320, FSM 10322,
   Marshalls 10324) use `GET /v1/observations/species_counts?place_id=…&taxon_id=47120
   (Arthropoda)&per_page=500&page=N` to get species that iNat has but GBIF lacks (research grade
   iNat is mostly already in GBIF, but not instantly) and observation counts. This is the
   Micronesia analogue of entobase's `inat_na_counts`.
3. **Name resolution.** `GET /v1/species/match?name=…&kingdom=Animalia` (GBIF) to get
   `usageKey`, accepted key, status and `matchType`; **only accept EXACT, or FUZZY after checking
   the canonical names agree** (entobase: `enrich/gbifmatch.py`). `GET /v1/species/{key}` gives
   the classification; `/species/{key}/children` gives the tree downward.
4. **Taxonomy tree.** Build `taxa` from the accepted GBIF taxa that have Micronesian records plus
   every ancestor up to Arthropoda. Primary id = `gbif_key`. Store rank, canonical name,
   authorship, parent, lineage string (`/54/216/…/`, as entobase does: it makes "everything under
   X" a `LIKE` query), status, and `display_default`. Hide synonyms; map them to the accepted name
   so search finds them.
5. **Terrestrial filter.** GBIF has no habitat flag. Start from class level: keep Insecta,
   Arachnida, Chilopoda, Diplopoda, Symphyla, Pauropoda, Collembola (Entognatha), and from
   Malacostraca only terrestrial isopods (Oniscidea) and land crabs/hermit crabs if the user
   wants them (ask); drop marine/freshwater classes (Ostracoda, Copepoda, Branchiopoda,
   Thecostraca, Pycnogonida, most Malacostraca). Put the decisions in `curation.toml` as entobase
   does for exclusions. The checklist will contain marine arthropods; expect to review ~100 names
   by hand. Mites (Acari) are mostly parasites/marine; ask the user whether to include.
6. **Annotate.** Port `annotate.py` ideas: placeholders (`sp.`, `cf.`), fossils, higher-taxon
   hiding (the rules and counts are in the reference code).
7. **Test:** unit tests for name matching, lineage building, filtering; a 50-species dry run.

## Phase 2: photos and links (iNaturalist + Commons)

Port `enrich/{inat,photos,wikidata,wikipedia,linkaudit}.py` with these changes:

- The link key is the GBIF key, not a BugGuide ID. Wikidata gives `P846` (GBIF), `P3151`
  (iNaturalist), `P225` (name), `P2464` (BugGuide, useful for Phase 5) and the enwiki article in
  one SPARQL query keyed on `P846` for the keys you have. Verify an iNat taxon with
  `GET /v1/taxa/{id}`, and accept a name-search match only if the canonical names agree and the
  iNat taxon is active. Record confidence (`high/medium/review`) and run the audit
  (`linkaudit.py`) that cross-checks iNat, GBIF, Wikidata and Wikipedia and demotes
  disagreements to `review`.
- **Photos: Micronesia first.** For each taxon, fetch iNaturalist photos with
  `place_id` in the Micronesian places, then fall back to anywhere (a local photo of a local
  animal is the whole point; a photo from Brazil may be a different species once the name is
  stale). Licences CC0/BY/BY-SA/BY-NC/BY-NC-SA only. Store resized WebP copies (display ~1000
  px, thumb ~320 px) in `data/media/`, record author, licence, URL and retrieval date. Port the
  selection logic in `photos.py` and its tests (`test_photo_selection.py`), including: higher
  taxa **borrow** a photo from a species they contain (`inherit`, with `from_taxon_id`), prefer a
  **landscape** photo for tiles, never show a borrowed photo as the taxon's own.
- Wikimedia Commons (via Wikidata P18 or a category search) as a second photo source. Commons
  licences vary per file: read `extmetadata`.

## Phase 3: PDF library (the part entobase does not have)

`scripts/pdf_ingest.py` already extracts per-page text (poppler) with a tesseract OCR fallback,
and finds names from a list. The pipeline to build around it:

1. `extract` all PDFs → `data/pdf_text/<sha256>.jsonl`. Record the bibliographic metadata per PDF
   (author, year, title, journal; start by hand in a CSV the user can edit, then try
   CrossRef `GET https://api.crossref.org/works?query.bibliographic=…` for matches). Citations are
   what the site shows.
2. **Name finding.** Build a names file from the checklist (accepted names *and* synonyms from GBIF
   `/species/{key}/synonyms`, since 1950s Micronesian literature uses old names). Run `find`. Add
   abbreviated-binomial resolution ("O. rhinoceros" after "Oryctes rhinoceros" on the same page)
   and OCR tolerance (edit distance ≤1 on names ≥ 8 characters; flag as `ocr`).
   For names *not* in the checklist, run GBIF's name parser or the GNfinder tool on the text
   to discover species the checklist lacks (historical records are exactly what PDFs add).
3. **Hits table** `pdf_mentions(taxon_id, pdf_id, page, method, snippet, kind)` where `kind` is
   `record` (locality + date nearby), `description`, `key`, `mention`. A simple classifier is fine
   at first: a short snippet and a human decision is better than a clever wrong one. Give the
   user a review page (a generated HTML list, like `entobase.html` in the parent folder) to accept
   or reject hits per taxon, and store decisions so a re-run never overwrites them.
4. **What the site shows:** per taxon, a "Literature" section: citation, page, a snippet of at
   most ~2 sentences, and the local PDF file name (the user can open it). Figures and plates: only
   if the user decides to; crop to a file with attribution, and ask first (copyright).
5. Historical records as presence: a PDF that says "Guam, Rota, 1936" is a record the user may
   want on the island table. Store with `source='literature'` and the citation; never merge with
   GBIF counts.

## Phase 4: text and status supplements

Port `enrich/wikitext.py` (full English Wikipedia text, CC BY-SA, revision + date) and
`wikipedia.py`. Add, each its own small module with a cache table, a retrieval date, a licence
and a test:

- **Wikispecies** (`species.wikimedia.org`, MediaWiki API, text CC BY-SA): taxonomy, synonymy,
  type information, references. Best for obscure taxa that have no Wikipedia article.
- **IUCN Red List** (API v4, token required): category, criteria, population trend, assessment
  year, habitat and threat text. Cite and link; check the terms (non-commercial use; attribute).
  Species-level only; Guam has endemics with assessments (e.g. the Mariana eight-spot butterfly,
  *Hypolimnas octocula marianensis*, is a classic).
- **Establishment means:** GBIF occurrence `establishmentMeans` (native, introduced, invasive),
  the **Global Invasive Species Database** (GISD) and **CABI Compendium**, the **Pacific Islands
  Ecosystems at Risk (PIER)** database. "Native, endemic to the Marianas, introduced, invasive"
  is a first-class filter and badge for this project: more useful here than in North America.
  Treat each source's statement as data with its own citation; do not collapse them.
- **Bugwood**: reuse `enrich/bugwood.py` (read-only API, link only). Bugwood covers many Guam
  pests (coconut rhinoceros beetle, little fire ant).
- **BOLD / GenBank** accession counts as a "barcoded?" badge are cheap (`https://portal.boldsystems.org`
  API; check the current endpoint) and useful for a DNA-minded user. Optional.
- Other possible sources the user mentioned as "other sources": Pacific Biodiversity Information
  Forum, Bishop Museum checklists (PDFs), the Hawaiian/Micronesian arthropod literature in
  Pacific Insects (PDFs, many OCR). Ask before adding a new one.

## Phase 5: BugGuide, through entobase only

Join `../entobase/data.nosync/entobase.sqlite` (read-only!) to your taxa by GBIF key. Where it
matches, copy the BugGuide sections as a *separate source block* with the contributors and dates
exactly as entobase renders them (reference `src/entobase/site.py` `build_records`, `sanitize`).
Do not write to that database, and do not fetch BugGuide. A matched taxon missing from
entobase's tree can be offered to the user as a list for a future entobase crawl.

## Phase 6: ranges and island presence

- **Island presence** from GBIF (`country` and `stateProvince`/`gadmLevel1Gid`/`gadmGid`
  filters; Guam is one island, but CNMI is Saipan/Tinian/Rota, Palau and FSM have state-level
  units: Yap, Chuuk, Pohnpei, Kosrae) and iNat places, plus literature (Phase 3). Ask by area,
  not by taxon (entobase rule 16: facet once per area, not once per taxon: 64 requests instead of
  40,000). Table `taxon_presence(taxon_id, area, records, first_year, last_year, source)`.
- **Maps.** entobase draws a GBIF density overlay on a cached basemap (`enrich/gbif.py`,
  `groupmaps.py`). For islands the world is tiny, so crop **tightly**: Micronesia is roughly
  lon 130-175 E, lat 0-22 N. Rewrite `BBOX` and the CSS crop (see `docs/APP_SPEC.md`), draw at a
  higher zoom, and consider a separate Guam inset map as the default. Group maps (for a genus
  with no GBIF map) work the same way.
- **Regions filter** on the identify view: replace NE/SE/SW/NW with Guam, CNMI, Palau, FSM,
  Marshalls, ordered Guam first; the logic (`regions.py`, `site.regions_of_codes`) is the same.

## Phase 7: the site

`starter/webapp/` is the entobase app. Port `site.py` (`build_records`, `build`, sanitisation,
incremental writes with content hashes) and `search.py` (names index + sharded full-text index).
Follow `docs/APP_SPEC.md` for what to change. Then `ops/check_site.py` (cross-browser smoke
test), screenshots, and the same density work the user asked for in entobase (two-column taxon
page, sticky left column, landscape thumbnails, identify tiles with maps).

## Phase 8: operations

`ops/link_all.sh`, `ops/gbif_refresh.sh`, `ops/enrich_all.sh` are the staged runners in the
reference: one stream per host, resumable, a log per stream. The daily crawler scripts are not
needed (no BugGuide crawl here).

## Terrestrial filter and other judgement calls (ask the user in one batch)

- Marine/freshwater arthropods: drop (default). Crabs and isopods on land: ask.
- Mites: ask. Parasites (lice, fleas): include as insects.
- Cultivated/greenhouse records and museum specimens with bad coordinates: GBIF issues flags
  (`COORDINATE_ROUNDED`, `COUNTRY_COORDINATE_MISMATCH`, `ZERO_COORDINATE`): exclude those from
  presence and maps by passing `hasGeospatialIssue=false`, and always say how many records
  there are.
- Taxa recorded in Micronesia **only** by one old, doubtful specimen: show, but with the record
  count and the year range, so the reader can judge.
- Names: the GBIF backbone is the spine. Where a Micronesian checklist (Pacific Insects, Bishop
  Museum) uses a different name, keep both, search both, display the accepted name with the
  other as a synonym.

## Definition of done for a first usable release

A user can open `data/site/index.html`, filter to Guam, drill Arthropoda → Insecta → order →
family → genus → species, see a photo and a map, a status badge (native/introduced/invasive),
the literature cited, Wikipedia text where it exists, and a complete attribution block, with
search that finds scientific names, synonyms and common names. Check `ops/check_site.py` passes.
