# Refactor: a dataset in git, a build from it, two Claude Code tools

To be worked through **on the data machine** (it has `data.nosync/guam.sqlite`, the PDF
library and the API caches), one phase at a time, committing and pushing after each. The
decisions are the user's (2026-11-13, CLAUDE.md round 7); this file is the plan.

## Why

The project was built like entobase, for a large fauna that is re-harvested over and over: a
local database rebuilt from cached API answers, a tree recomputed on every build from the
Catalogue of Life plus a layer of hand overrides, and a site of one script per taxon. For
Micronesia that is more machinery than the data need, and it does not travel:

| today | size | problem |
|---|---|---|
| `data.nosync/guam.sqlite`, 30 tables | 60 MB | local only, binary: collaborators cannot see or merge it; CI needs a published snapshot |
| `data/raw/` API cache | 40,000 files, 459 MB | only there for re-harvesting |
| `curation/*.csv` overrides + derived `taxonomy.csv` | small | two places to edit; the editor re-implements the override rules in 770 lines of JavaScript |
| `site/public` | 14,600 files (9,600 record scripts, some stale; 623 search shards) | slow to sync, upload and inspect |
| `data/pdf_text/`, `sources/*.csv`, `data/media/thumbs/` | | scattered |
| code | 11,000 lines | ~40% harvesting code that will rarely run |

## Decisions (the user's)

1. **The dataset is the truth**: about a dozen CSV tables (plus one JSONL file) in `dataset/`,
   in git. The taxa table is edited directly; the override layer goes; git is the history.
2. **Media in git**: card thumbnails as files (`media/thumbs/`, ~26 MB) and the Wikipedia text
   (`dataset/wikipedia.jsonl`, ~8 MB). A clone builds the whole site; only the PDFs are not
   in it.
3. **The tools run on the data machine only.** Collaborators use the editor (or edit the CSVs
   and push).
4. **The repository stays in iCloud** (~/Documents), with safeguards (Phase 0).
5. **Literature tool**: extracts names, pages, islands, status (native / introduced / ...),
   host plants, first-record years, **and a short paraphrased biology note** per species
   account. **No approval step**: the records go in flagged *machine-read* (the notes
   *machine-written*), as literature records do now, and are confirmed later in the editor.
   Claude writes the notes during the ingest session (a script cannot paraphrase); that is
   part of extraction, not a review.
6. **Sync tool**: new taxa with records in Micronesia are **added automatically, flagged**
   `new` (reviewed afterwards in the editor); changed counts trigger a refresh of those
   taxa's statistics.
7. **The other sources keep slim refresh commands** (photos, Wikipedia, Wikidata, BugGuide via
   entobase, the Catalogue of Life), run on demand, writing the dataset tables directly.
8. **Every taxon has a nativity**, one of three: **Native, Introduced, Unknown** (Micronesia
   as a whole; the per-island-group statements stay in literature.csv). It replaces today's
   five-value `establishment` (native, endemic, introduced, invasive, unknown): endemic
   becomes Native, invasive becomes Introduced (see Phase 1). A taxon nobody has assessed
   is Unknown, never blank.
9. **Worldwide distribution maps for every species** may come later: flagged here, not
   scheduled (see "Possible later: worldwide maps").
10. Unchanged: the site's look, routes and behaviour (file:// and served); taxon ids and URLs
   (`#/t/KVC9L`, `gbif:`, `name-`, `IOG-`); the editor's tools and commit flow; the rebuild on
   push; every hard rule in CLAUDE.md (attribution, licences, no PDF text published, BugGuide
   only via entobase's database, polite APIs).

## Target layout

```
dataset/                 THE data (git). README.md generated from schema.py
  taxa.csv               every taxon and every name (synonym rows), with provenance
  keys.csv               source keys -> taxon (GBIF Backbone keys, COL ids, iNat ids, printed names)
  names.csv              other names for search: GBIF/COL synonyms, other English names
  records.csv            counts per taxon x island group x source (GBIF, specimens, iNat), with years
  islands.csv            islands named per taxon, by source
  documents.csv          the bibliography: every document (PDF library, Plazi checklists, crop pest list)
  literature.csv         taxon x document: pages, areas, islands, status, first record, review state
  notes.csv              short paraphrased biology notes per taxon x document
  hosts.csv              host plants per taxon x source
  photos.csv             the photos shown (own, not borrowed), with full attribution
  links.csv              external pages: COL, GBIF, iNat, Wikidata, Wikispecies, Wikipedia, BugGuide, editors' links
  distribution.csv       editors' distribution tags
  vouchers.csv           editors' vouchers: iNat observations, GBIF records, curated photos
  wikipedia.jsonl        one article per line (CC BY-SA, with revision and retrieval date)
  review/unplaced.csv    names with records that could not be placed (for the editor's worklist)
media/thumbs/            ~200 px WebP card thumbnails (git)
media/curated/           curators' own photos (git; licence in vouchers.csv)
webapp/                  the site's front end (look unchanged; new data loader)
editor/                  the taxonomy editor (edits dataset/ directly)
src/guaminsects/
  schema.py              every table: columns, types, enums, keys, references, limits (one source)
  dataset.py             read, check, write the tables (deterministic CSV)
  model.py               the tree in memory: lineage, synonyms -> accepted, roll-ups, levels
  ids.py, geo.py         kept
  build/                 records.py (from site.build_records), bundle.py (chunks), search.py, export.py (Darwin Core)
  match.py               names -> Catalogue of Life / GBIF (from names.py + tree.py's spelling rules)
  http.py                polite client: one stream per host, cache in private.nosync/api/
  sources/               gbif.py, inat.py, col.py, photos.py, wikipedia.py, wikidata.py, bugguide.py
  literature/            text.py (pdftotext + OCR), finder.py (names, headings, islands, status, hosts), stage.py
  sync.py                the GBIF / iNaturalist comparison and refresh
  server.py              `guaminsects serve` and `guaminsects edit`
  cli.py
.claude/skills/
  ingest-literature/SKILL.md
  sync-records/SKILL.md
private.nosync/          never synced, never committed: PDF text, staging files, API cache, scratch DB
site.nosync/public/      build output (never synced, never committed); index.html at the top redirects here
literature/              the PDF library (git-ignored; iCloud keeps it on both machines)
```

Aim: ~6,000-7,000 lines of Python, the old pipeline (gbif_checklist, col, plazi, croppests,
inat_counts, islands, names, tree, curation, taxonomy import/sync, snapshot, review.py)
retired under a git tag.

## The dataset

Conventions for every table (`dataset.py` enforces them, so diffs stay small and merges
easy):

- UTF-8 with a BOM (Excel reads accents), `\n` line endings, a header row, minimal quoting,
  the column order of `schema.py`. Lists inside a cell are separated by ` | `.
- **Rows sorted by key** (taxa: depth-first, children by name, each taxon's names after it;
  others: taxon id then their own key). Writing a table twice gives identical bytes.
- `taxon_id` is the external id (`KVC9L`, `gbif:1045882`, `name-12`, `IOG-3`). Rows may point
  at a synonym's id; the build follows `accepted_id`. So a merge is one cell, and undoing it
  loses nothing.
- Provenance columns where a person or a tool adds rows: `added_by`, `added` (YYYY-MM-DD),
  and on taxa `modified_by`, `modified`.
- Review state where a machine produced the row: `review` = `machine` (name finder, sync,
  Claude-written) | `editor` (a person confirmed it), with `reviewed_by`, `reviewed`.
- **No PDF text anywhere in dataset/**: no snippet columns; `notes.note` is a paraphrase of at
  most 200 characters, and `dataset check` rejects one that shares eight or more consecutive
  words with the document's text (when the text is available locally).

### Tables

`taxa.csv`: one row per taxon and per name.

| column | |
|---|---|
| `id` | the external id (URL `#/t/<id>`); never reused |
| `parent_id` | accepted rows; empty for the root (Hexapoda L2655) |
| `accepted_id` | synonym rows: the taxon it is shown as |
| `rank` | Subphylum, Class, Order, Family, Genus, Species, Subspecies |
| `name`, `authorship` | |
| `status` | accepted, synonym, doubtful, morphospecies |
| `common_name`, `other_common_names` | English (the build still prefers iNat's name in use; see Phase 2) |
| `nativity` | **required**: `native`, `introduced` or `unknown` (default). Shown as the Native / Introduced / Unknown badge |
| `nativity_source`, `nativity_review` | where it came from (a doc_id, `editor`, or empty for unknown); `machine` (set by a tool from a literature statement) or `editor` |
| `iucn` | Wikidata P141 where it exists |
| `superfamily`, `subfamily`, `tribe` | COL's intermediate ranks (not shown as tree nodes) |
| `in_col`, `gbif_key` | yes/no; the GBIF Backbone key where one matches |
| `name_match`, `match_note`, `name_sources` | how the name was matched or merged (today's taxonomy.csv columns) |
| `hidden`, `hidden_reason` | the site's "delete" |
| `verified`, `verified_by`, `verified_date`, `verification_source` | editor confirmed |
| `flag` | `new` (added by a tool, not yet reviewed), empty otherwise |
| `note` | shown on the page |
| `added_by`, `added`, `modified_by`, `modified` | |

`keys.csv`: `source` (gbif, col, inat, literature, plazi, checklist), `key`, `name`,
`taxon_id`, `how` (same, COL synonym, spelling variant, curated merge, ...). This replaces
`name_matches`, `taxon_keys` and `sources/names.csv`. The sync tool reads it to attribute
facet counts without re-matching.

`names.csv`: `taxon_id`, `name`, `kind` (gbif synonym, col synonym, english), `source`: the
11,000 "also known as" names, for search only.

`records.csv`: `taxon_id`, `area` (GU MP PW FM MH), `source` (gbif, gbif_specimens, inat),
`records`, `first_year`, `last_year`, `query_key` (the key the count was asked under),
`refreshed`. This replaces `taxon_presence` (gbif, gbif_backbone, inat) and
`taxon_specimens`. Literature presence comes from `literature.csv`, editors' from
`distribution.csv`.

`islands.csv`: `taxon_id`, `area`, `island`, `source` (gbif, literature, editor), `records`,
`doc_id`.

`documents.csv`: `doc_id` (short, stable: `iom-08-1`, `schreiner-1991`, `plazi-<key>`),
`file` (relative to the library; empty for an online-only document), `title`, `authors`,
`year`, `container` (journal, series), `volume`, `pages`, `doi`, `url` (public),
`licence`, `kind` (monograph, paper, fact sheet, checklist, dataset), `region` (does the
title support Micronesian presence), `citation` (formatted), `added_by`, `added`. This merges
`sources/library.csv`, `sources/documents.csv` and `checklist_sources`.

`literature.csv`: `taxon_id`, `doc_id`, `pages`, `kind` (account = a species section, mention,
checklist entry), `name_printed`, `areas`, `islands`, `status`, `status_area`,
`first_record_year`, `method` (text, ocr, plazi, manual), `review`, `reviewed_by`, `reviewed`,
`added_by`, `added`. This replaces `pdf_mentions` (without the snippet), `checklist_names`,
the crop-pest presence and `establishment`. One row per taxon, document and kind.

`notes.csv`: `taxon_id`, `doc_id`, `pages`, `topic` (biology, habitat, pest, distribution,
identification), `note` (≤ 200 characters, paraphrased), `review`, `written_by` (Claude
model, or an editor's name), `added`. Shown on the page as "From <citation>, p. n:
<note>", marked machine-written until reviewed.

`hosts.csv`: `taxon_id`, `host`, `doc_id`, `pages`, `review`.

`photos.csv`: `taxon_id`, `position`, `photo_id` (`inat:…`, `commons:…`, `gbif:…`), `source`,
`page_url`, `display_url`, `thumb` (file in media/thumbs, or empty), `width`, `height`,
`licence`, `licence_url`, `attribution`, `rights_holder`, `retrieved`. The photos a page shows
(own photos only: the build carries thumbnails up to groups with none, as now). CC0, BY,
BY-SA, BY-NC, BY-NC-SA only (checked).

`links.csv`: `taxon_id`, `system` (col, gbif, inaturalist, wikidata, wikispecies, wikipedia,
bugguide, editor), `value` (id or URL), `label`, `confidence` (high, medium, review), `note`,
`added_by`, `added`. Wikidata ids, iNat ids, BugGuide nodes and the editors' links, in one
place.

`distribution.csv`: `taxon_id`, `place`, `status` (present, absent, doubtful), `source`,
`added_by`, `added`. Today's distribution annotations.

`vouchers.csv`: `taxon_id`, `kind` (inat_observation, gbif_occurrence, photo_file, photo_url),
`ref`, `note`, `licence`, `credit`, `added_by`, `added`. Today's evidence.csv.

`wikipedia.jsonl`: `{"taxon_id", "title", "url", "revid", "rev_timestamp", "retrieved",
"lead_only", "html"}`, sorted by taxon_id.

`review/unplaced.csv`: `name`, `rank`, `source`, `key`, `records`, `note`. Names with records
the matcher could not place. The editor's worklist; adding one under a parent there moves it
into taxa.csv.

### `schema.py`

One declaration per table: columns (name, type, required, enum or pattern, reference to
another table's key, max length) and the sort key. From it:

- `dataset.check()` reports every problem at once, like `curation.load` today: the tree is a
  tree (one root, no cycles, ranks descend), synonyms point at accepted taxa, every reference
  resolves, enums, places (geo.PLACES), licences, URLs, no duplicate keys, the note-copying
  check, and **every accepted taxon has a nativity** (one of the three values).
- `guaminsects editor-spec` writes `editor/assets/spec.js` (as now).
- `dataset/README.md` is generated (the column tables above), so the docs never drift.

## The build

`guaminsects build`: `dataset/` → `site.nosync/public/`. It needs no database and no
network, so it runs in CI and on any clone.

1. `dataset.load()` + `check()` (fails on any problem).
2. `model.py`: synonyms to accepted (any row pointing at a synonym counts for its accepted
   taxon), lineage, children by name, roll-ups leaves first (species per area by any source,
   iNat sums, literature documents per area, GBIF counts as given per rank), islands carried
   up, verification levels (editor confirmed > literature > specimens > unconfirmed, the
   "machine-read only" remark), thumbnails carried up.
3. `build/records.py`: the same record per taxon as `site.build_records` makes today (the
   fields in APP_SPEC.md "The record"), now with `notes`. **Port it field for field**; Phase 2
   proves it.
4. `build/bundle.py`: the data the app loads, as a few hundred files instead of ten thousand.

   | file | contents | loaded |
   |---|---|---|
   | `data/meta.js` | as now (areas, map, counts, build date) | at start |
   | `data/index.js` | every visible taxon as `[id, name, rank, parent, chunk, common, thumb]` | at start (routing, suggestions) |
   | `data/c/<n>.js` | full records of one chunk | on the first visit to a taxon in it |
   | `data/w/<n>.js` | Wikipedia HTML of one chunk | on "Show entire article" |
   | `data/s/<x>.js` | full-text index by a term's first character | on search |
   | `data/taxonomy.js` | the Darwin Core download rows | on the download button |

   **Chunks**: a family and everything under it is one chunk. Families under ~40 KB are
   merged with their order neighbours, families over ~400 KB split by genus, and taxa above
   family get chunks of their own. Expect 150-300 chunks of 50-400 KB, gzip ~4×. The loader
   in `app.js` (`loadRecord(id)`) adds a `<script>` for the chunk and caches it, which still
   works from `file://` (no `fetch`, CLAUDE.md rule 9). The search tokenizer stays identical in
   Python and JavaScript (rule 10).
5. `build/export.py`: `taxonomy.csv` (Darwin Core, same columns as today plus `notes`) into
   the site for the download box. It is **no longer tracked in git**: `dataset/taxa.csv` is the
   editable table.
6. Copy `webapp/` and `media/thumbs/` (only the thumbnails in use).

Result: ~500 files plus the thumbnails (~4,400), instead of 14,600. `ops/check_site.py` keeps
its checks (routes, search parity, lightbox, region filter, no JS errors; three engines, two
sizes) with the new loader.

## The editor

It edits `dataset/` directly, so `model.js` loses the override layer (curated rows,
blank = "the source's value", the IOG-row rules) and becomes plain table edits with checks:

| tool | writes |
|---|---|
| edit a field | the cell in taxa.csv |
| synonymize | `status synonym`, `accepted_id`; the children's `parent_id` move to the accepted taxon |
| split | `status accepted`, `parent_id` |
| move | `parent_id` |
| add a taxon / a name | a taxa.csv row with the next `IOG-n` |
| hide / show, confirm | `hidden`, `verified*` |
| **nativity** (new tool) | `nativity` Native / Introduced / Unknown, `nativity_source` (a document or "editor"), `nativity_review editor` |
| tag / voucher / link | distribution.csv / vouchers.csv / links.csv rows |
| **review** (new) | `review = editor` on literature, notes, hosts rows; clear `flag new` on taxa |

New worklists: *new from a tool* (`flag = new`), *literature machine-read* (by document),
*notes machine-written*, *unplaced names*, *nativity unknown* (species first), *nativity set
by machine* (to confirm), and *nativity in conflict* (a species whose literature statements
disagree with its nativity, or with each other across island groups). The editor loads the tables it edits plus
`records.csv`, `literature.csv`, `notes.csv` and `documents.csv` for display (a few MB; not
`wikipedia.jsonl`). Commit is unchanged (GitHub token, or `guaminsects edit` with git). The
agreement test becomes simple: what the editor writes, `dataset.check()` accepts, and the build
shows.

## Tool 1: `/ingest-literature <directory>`

A Claude Code skill (`.claude/skills/ingest-literature/SKILL.md`) that drives deterministic
commands and does the reading only a model can do. It runs on the data machine.

1. **`guaminsects lit add <dir>`**: for each PDF, a content hash (skip known ones), a copy into
   the library under a readable name, and text into `private.nosync/pdf_text/<hash>.jsonl` (the
   text layer, else OCR with ocrmypdf/tesseract, page by page; today's pdftext.py). A
   `documents.csv` row is drafted from the PDF's metadata and first pages. **Claude completes
   the citation** (authors, year, title, journal, pages, DOI, public URL) by reading the first
   pages; it asks the user only when the document does not say.
2. **`guaminsects lit scan <doc_id>`**: the name finder (today's literature.py: every name in
   taxa.csv, keys.csv and names.csv, abbreviated genera, OCR tolerance, species-account
   headings, bounded sections, island and area words, status phrases) plus host-plant and year
   patterns. Output: `private.nosync/staging/lit-<doc_id>.json`, one candidate per taxon and
   section with its pages and the section's text (private: it never leaves the machine).
3. **Claude reads the candidate sections** (species accounts first; mentions in passing get a
   literature row and no note) and fills, for each: the islands and areas, status, host plants,
   first-record year, and **one paraphrased note** of at most 200 characters (what the account
   says about biology, habitat or pest status; never a copied sentence), with the page. Names
   the finder could not match go to step 4. A clear statement that a species is native or
   introduced (in Micronesia, or in an island group) becomes the literature row's `status`;
   when the taxon's nativity is still `unknown`, `lit apply` sets it from that statement with
   `nativity_review machine` (an editor's value is never overwritten; a disagreement goes to
   the *nativity in conflict* worklist). Large monographs are done in batches of sections,
   by page ranges (`--pages`), so a session reads only species accounts, not whole volumes.
4. **`guaminsects match <names…>`**: Catalogue of Life (GBIF v2 match), then the GBIF Backbone.
   A match goes to keys.csv. A name COL lacks is added under its genus (adding the genus if
   needed) with `flag new` and `added_by` the tool, per decision 6. What cannot be placed goes
   to `review/unplaced.csv`.
5. **`guaminsects lit apply <staging file>`**: validates the staged JSON (schema, references,
   the eight-word copy check against the text, the note length), writes literature.csv,
   notes.csv, hosts.csv and islands.csv (source literature), all `review machine`, then
   `dataset check`.
6. Claude reports (document, records, new taxa, unplaced names, notes written), then commits
   (`Literature: <citation>: 84 records, 3 new taxa, 61 notes`) and pushes. The push rebuilds
   the site; the records show as machine-read until someone reviews them in the editor.

Rules the skill states: PDFs are in copyright (rule 4). Nothing quoted goes in dataset/; the
staging files and text stay in `private.nosync/`; the PDF itself is never committed or
uploaded. Machine-read records are labelled on the site.

## Tool 2: `/sync-records`

A Claude Code skill (`.claude/skills/sync-records/SKILL.md`) around `guaminsects sync`. It
runs on the data machine. Check `ps` for entobase jobs first (iNat 429s; one stream per
host; rule 2).

1. **`guaminsects sync check`**: for each of the five areas, the counts per taxon in as few
   requests as possible:
   - GBIF occurrence facets (COL checklist keys by rank, as gbif_checklist.py does now; then the
     Backbone facet for names COL lacks);
   - preserved-specimen facets;
   - iNaturalist research-grade species_counts per place.
   Each key is mapped through keys.csv. Output: `private.nosync/staging/sync-<date>.json` and a
   summary: new keys, counts changed (by how much), counts gone to zero, unchanged.
2. **`guaminsects sync apply`** (automatic, per decision 6):
   - changed counts: records.csv updated, `refreshed` set;
   - **taxa whose counts changed get their statistics refreshed**: years, the island facet
     (GADM level 1), specimens, and new GBIF photos if the taxon has none;
   - new keys: matched (`guaminsects match`), added to taxa.csv with `flag new` and nativity
     `unknown` (adding a missing genus or family under its COL parent), keys.csv rows, their
     counts. GBIF's `establishmentMeans` is too rarely filled to set nativity from;
   - `refresh photos|wikipedia|wikidata|links --taxa new` for them, with thumbnails;
   - unmatched names go to `review/unplaced.csv`;
   - a taxon whose records vanished is reported, never removed (a person decides; it may be a
     re-identification).
3. Claude reports (new taxa by order, the largest count changes, anything vanished or
   unplaced), runs `dataset check` and `build`, commits (`Sync 2026-12-01: 34 new taxa, 120
   counts changed`) and pushes.

## Refresh commands (decision 7)

`guaminsects refresh <photos|wikipedia|wikidata|bugguide|col> [--taxa new|all|<ids>]`. Each
is a slimmed-down version of today's enrichment (enrich/photos.py, wikitext.py, wikidata.py,
entobase.py, col.py), writing photos.csv + media/thumbs, wikipedia.jsonl, links.csv
(+ taxa.iucn, other_common_names) or taxa.csv names directly. They keep the polite client,
the licence filter and the attribution rules. `bugguide` reads
`../entobase/data.nosync/entobase.sqlite` read-only and nothing else (rule 1). API answers
are cached in `private.nosync/api/` (a cache, safe to delete).

## Phases

Each phase ends with `uv run pytest -q`, ruff, a commit and a push. Phases 1-3 run beside the
old pipeline: nothing is deleted until Phase 7.

### Phase 0: prepare

1. `git pull`; `uv sync`; the tests pass; the current site builds and passes check_site.
2. `git tag pipeline-v1 && git push --tags`: the old code stays retrievable.
3. Copy `data.nosync/guam.sqlite` to `data.nosync/guam-pipeline-v1.sqlite`.
4. **Baseline for Phase 2**: keep the current build's record files
   (`site/public/data/t/**`) in `private.nosync/baseline/` and screenshots
   (`ops/check_site.py --shots private.nosync/baseline/shots`).
5. **iCloud safeguards** (the repository stays in ~/Documents):
   - move git's object store out of sync: `git init --separate-git-dir
     ~/Documents/Research/AI_workflows/guam_insects.git.nosync` (iCloud skips `.nosync`
     names; `.git` becomes a small pointer file). Each machine keeps its own and fetches from
     GitHub; check the pointer's path is valid on both machines (same user name), else
     re-clone the git dir on the other one (`git clone --bare` + fix the pointer);
   - build output to `site.nosync/`, caches and private files to `private.nosync/`, the venv
     already in `venv.nosync/`;
   - a working rule in CLAUDE.md: **pull before working, commit and push when done, one
     machine at a time**. iCloud syncs the working tree, and git is the record.

### Phase 1: schema, dataset, migration

1. `schema.py` and `dataset.py` (read, check, write; deterministic) with tests on a small
   fixture dataset (`tests/fixtures/dataset/`, the Oryctes world of conftest.py as CSV files).
2. **`guaminsects migrate`** (one time; deleted in Phase 7): the resolved tree
   (`taxa`, `taxon_names`, `taxon_keys`, `name_matches`) + curation/*.csv +
   sources/*.csv + the pipeline tables → the dataset tables, following the mapping below.
   Every curated value lands in its column, with its editor and date. **Nativity**: the
   curated `establishment` first (endemic → native, invasive → introduced, with the original
   word kept in `note` when it was endemic or invasive, so nothing is lost), else the
   machine-read statements in `establishment` (Guam's first; `nativity_review machine`;
   statements that disagree → `unknown` + the conflict worklist), else `unknown`. The
   migration report lists how many taxa got each value and from where.

   | today | goes to |
   |---|---|
   | `taxa` + `taxon_names` + curation/taxa.csv | taxa.csv (accepted + synonym rows; extra → superfamily/subfamily/tribe) |
   | `taxon_keys`, `name_matches`, sources/names.csv | keys.csv |
   | `taxon_synonyms`, `col_info`, Wikidata common names | names.csv, taxa.other_common_names |
   | `taxon_presence` (gbif, gbif_backbone, inat), `taxon_specimens` | records.csv |
   | `taxon_presence` (plazi, pdf, checklist), `pdf_mentions` (no snippet), `checklist_names`, `establishment` | literature.csv |
   | `taxon_islands`, island lists of pdf_mentions | islands.csv |
   | sources/library.csv, sources/documents.csv, `checklist_sources` | documents.csv |
   | `taxon_hosts` | hosts.csv |
   | `taxon_photos` (role own) + `photos` (status ok) | photos.csv; data/media/thumbs → media/thumbs |
   | `wikidata_taxa`, `bugguide_links`, iNat ids, curation/annotations.csv links | links.csv, taxa.iucn |
   | curation/annotations.csv distribution | distribution.csv |
   | curation/evidence.csv | vouchers.csv |
   | `wikipedia_articles` | wikipedia.jsonl |
   | `pdf_candidates` (unmatched), unplaced `name_matches` | review/unplaced.csv |
   | `gbif_taxa`, `col_taxa`, `col_extinct`, queries, candidates, caches | not carried (re-fetched by `match` when needed) |

3. **Acceptance**: `dataset check` passes (every accepted taxon has a nativity); counts reconcile (taxa and synonyms with the
   `taxa`/`taxon_names` tables, records with presence rows, literature with mentions, photos,
   links, every curated row); `dataset/` is under ~60 MB with media; `git diff` of a second
   `migrate` run is empty (deterministic).

### Phase 2: the build from the dataset, same output

1. `model.py` + `build/records.py`, writing the **old** site layout (one file per taxon) first.
2. **Acceptance**: every record equals the baseline's, apart from `built_at` and the
   intended change: the status badge shows Native / Introduced / Unknown from `nativity` (the
   badge's look is unchanged; "Unknown" is shown, not hidden, on species pages). Compare
   per field with a script; investigate every difference (the only expected ones are bug
   fixes, listed in the commit message). check_site passes; screenshots match.
3. `taxonomy.csv` export equals the current file in every column (plus `notes`).

### Phase 3: bundled output

1. `build/bundle.py` (chunks, Wikipedia chunks, index, search shards by first character) and
   the `app.js` loader; check_site updated (routes into several chunks, a Wikipedia expand,
   search across shards, file:// and served).
2. **Acceptance**: the site looks and behaves the same (screenshots against Phase 0, three
   engines, two sizes); first load of a species page is no slower from file:// and on a
   phone-sized throttled connection; ~500 data files; deploy a preview (`ops/deploy.sh`), then
   production.

### Phase 4: the editor on the dataset

1. spec.js from schema.py; model.js as plain table edits; io.js loads and commits the dataset
   files; the new review tools and worklists.
2. Tests: the editor's writes pass `dataset.check()` and build. The page from file:// and from
   `guaminsects edit` (the existing UI test, ported). Screenshots.
3. CI (`.github/workflows/rebuild.yml`): `uv sync`, `dataset check`, pytest, build, check_site,
   deploy. **No snapshot, no restore**: the clone is enough. Delete the `data-snapshot` release
   once this deploys.

### Phase 5: matching and the sync tool

1. `match.py` (COL v2 match, Backbone, the spelling-variant and gender-ending rules of
   tree.py, the fossil list, keys.csv).
2. `sync.py` and `guaminsects sync check|apply`; `refresh …`.
3. Tests with recorded API answers (a few JSON fixtures). A first real run (`sync check` only)
   reviewed with the user before the first `apply`.
4. `.claude/skills/sync-records/SKILL.md`.

### Phase 6: the literature tool

1. `literature/text.py`, `finder.py`, `stage.py`; `guaminsects lit add|scan|apply`; the copy
   check.
2. Tests: a small public-domain or synthetic PDF in the fixtures (no copyrighted text in git).
3. `.claude/skills/ingest-literature/SKILL.md`. A first real run on one short fact sheet,
   reviewed with the user, before a monograph.

### Phase 7: retire the old pipeline

1. Delete the replaced modules (gbif_checklist, inat_counts, islands, plazi, croppests,
   names, tree, curation, taxonomy import/sync, snapshot, establishment, documents, library,
   review.py, refresh_all.sh, harvest.sh, migrate) and `curation/`, `sources/`,
   `taxonomy.csv` from git.
2. `data/raw/` (459 MB) → `private.nosync/api-cache-pipeline-v1.tar.zst`, or delete it (the
   tag and the dataset hold everything needed). `data.nosync/guam.sqlite` kept as an archive.
3. Docs: CLAUDE.md (round 7 as built; pipeline order → the tools and refresh commands; the file
   table), README.md, `dataset/README.md` (generated), docs/EDITOR.md, APP_SPEC.md (the
   loader), STATUS.md. Remove BUILD_PLAN.md, SCHEMA_DRAFT.sql and `curation/README.md`.

## Possible later: worldwide maps

The user may want **a worldwide distribution map on every species page** (about 3,000
species). Not scheduled; design notes so the refactor does not rule it out:

- **Source**: GBIF occurrences worldwide for the species' key (GBIF's map API or occurrence
  facets by grid cell), attributed "GBIF.org" with the retrieval date; aggregated counts, no
  individual records.
- **Preferred form: a coarse grid, drawn by the app.** One row per species with the occupied
  cells of a 1° or 2° world grid (a compact string, ~1-5 KB per species, a few MB in all),
  stored as `dataset/world_grid.csv` (or `.jsonl`) and drawn as SVG or canvas over one world
  basemap in `webapp/`. It works from file://, keeps git and Vercel small, and matches the
  island map's look. Micronesia is highlighted on it.
- Rejected: static images per species (3,000 × 30-60 KB = 100-180 MB: over Vercel's budget and
  heavy in git); hotlinked GBIF tiles (online only, no file://).
- **Fetching**: a `refresh worldmap [--taxa new|all|<ids>]` command (one stream to GBIF,
  ≤ 3 requests/s), and `/sync-records` would refresh the grid of taxa whose counts changed.
- **Leave room for it now**: keep `gbif_key` and the COL id on every species row (the map
  query needs one), keep a `map` slot in the record and the taxon page's layout (it is in
  APP_SPEC.md's record already), and size the chunks without the grids (they would go in
  their own files, like Wikipedia).

## Risks and how the plan meets them

| risk | answer |
|---|---|
| the port changes what the site shows | Phase 2 compares every record with the baseline before anything else changes |
| two people edit the same rows | small sorted CSVs merge line by line; the editor replays onto the latest commit (as now) |
| iCloud and git disagree | git's store in `.nosync`, build output and caches in `.nosync`, one machine at a time |
| copyrighted text leaks into git | no snippet columns; notes ≤ 200 characters with the eight-word copy check; staging only in private.nosync |
| a tool adds wrong taxa | `flag new` + the editor's worklist; every tool commit is one revertable commit |
| repository size | ~60 MB with media, growing slowly; thumbnails change only for new taxa |
| losing the ability to re-harvest | the tag `pipeline-v1` and the archived database and cache |

## Open points to settle while working

- Chunk thresholds (40 KB / 400 KB) are starting values: measure in Phase 3.
- Whether `names.csv` (11,000 search-only names) earns its size, or the search index takes
  them straight from the refresh commands.
- How the site labels machine-written notes (a muted "machine-written from …, not yet
  checked" line, like the machine-read literature asterisk). Show the user in Phase 2.
