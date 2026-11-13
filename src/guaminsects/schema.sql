-- guam_insects schema. Add every new column to db.ADDED_COLUMNS too, and name the columns in
-- every INSERT (CLAUDE.md rule 8).
--
-- Two layers. Pipeline tables (gbif_taxa, taxon_presence, ...) hold what the sources say and
-- are rewritten freely by re-runs. `taxa` is *derived*: `resolve` rebuilds it from gbif_taxa
-- plus the hand curation in curation/*.csv, so a curated edit is never lost to a re-run.

-- What GBIF says about each key we have seen (cached JSON is in data/raw/api.gbif.org/).
CREATE TABLE IF NOT EXISTS gbif_taxa (
  gbif_key         INTEGER PRIMARY KEY,
  parent_key       INTEGER,
  rank             TEXT,                   -- GBIF style: KINGDOM .. SPECIES, SUBSPECIES
  canonical_name   TEXT,                   -- "Oryctes rhinoceros"
  scientific_name  TEXT,                   -- with authorship
  authorship       TEXT,
  taxonomic_status TEXT,                   -- ACCEPTED | SYNONYM | DOUBTFUL | ...
  accepted_key     INTEGER,                -- for a synonym
  class_key        INTEGER,
  order_key        INTEGER,
  family_key       INTEGER,
  genus_key        INTEGER,
  species_key      INTEGER,
  vernacular_name  TEXT,
  fetched_at       TEXT
);

-- Records per taxon and area. One facet request per (area, rank), never one per taxon.
CREATE TABLE IF NOT EXISTS taxon_presence (
  taxon_id   INTEGER NOT NULL,             -- a GBIF key, or a curated id for evidence rows
  area       TEXT NOT NULL,                -- GU, MP, PW, FM, MH (island codes later)
  source     TEXT NOT NULL,                -- gbif | inat | plazi | pdf | curated
  records    INTEGER,
  first_year INTEGER,
  last_year  INTEGER,
  citation   TEXT,
  fetched_at TEXT,
  PRIMARY KEY (taxon_id, area, source)
);
CREATE TABLE IF NOT EXISTS presence_queries (  -- which (area, facet) sweeps are done, for resume
  area TEXT, source TEXT, facet TEXT, taxa INTEGER, answered_at TEXT,
  PRIMARY KEY (area, source, facet));

-- iNaturalist: species_counts per place (research grade), kept as iNat names them.
CREATE TABLE IF NOT EXISTS inat_place_counts (
  inat_id INTEGER, place_id INTEGER, area TEXT, name TEXT, rank TEXT, common_name TEXT,
  iconic TEXT, observations INTEGER, fetched_at TEXT, PRIMARY KEY (inat_id, place_id));

-- The resolved tree (derived; see top of file). taxon_id = gbif_key for backbone taxa.
CREATE TABLE IF NOT EXISTS taxa (
  taxon_id       INTEGER PRIMARY KEY,
  gbif_key       INTEGER,
  parent_id      INTEGER,
  rank           TEXT NOT NULL,            -- display style: Class, Order, Family, Genus, Species
  name           TEXT NOT NULL,
  authorship     TEXT,
  status         TEXT NOT NULL DEFAULT 'accepted',  -- accepted | synonym | doubtful | morphospecies
  accepted_id    INTEGER,
  origin         TEXT NOT NULL,            -- gbif | curated
  common_name    TEXT,
  establishment  TEXT,                     -- curated value: native | endemic | introduced | ...
  hidden         INTEGER NOT NULL DEFAULT 0,
  hidden_reason  TEXT,
  note           TEXT,
  curated_fields TEXT,                     -- comma list of fields set by hand, for the UI
  lineage        TEXT,                     -- '/900000001/216/1470/…/' : LIKE for "under X"
  depth          INTEGER,
  resolved_at    TEXT
);
CREATE INDEX IF NOT EXISTS taxa_parent ON taxa(parent_id);
CREATE INDEX IF NOT EXISTS taxa_name ON taxa(name);
CREATE INDEX IF NOT EXISTS taxa_gbif ON taxa(gbif_key);

-- Photos and records a curator attached to a taxon (from curation/evidence.csv).
CREATE TABLE IF NOT EXISTS taxon_evidence (
  taxon_id INTEGER, kind TEXT, ref TEXT, license TEXT, credit TEXT, note TEXT,
  PRIMARY KEY (taxon_id, kind, ref));

CREATE TABLE IF NOT EXISTS taxon_synonyms (
  taxon_id INTEGER, synonym TEXT, source TEXT, PRIMARY KEY (taxon_id, synonym));

-- Published checklists (Plazi's digitised papers on GBIF, later others) and their names.
CREATE TABLE IF NOT EXISTS checklist_sources (
  dataset_key TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, citation TEXT,
  areas TEXT,                              -- comma list of area codes the title supports
  license TEXT, doi TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS checklist_names (
  dataset_key TEXT, source TEXT NOT NULL, usage_key INTEGER, nub_key INTEGER, name TEXT,
  rank TEXT, PRIMARY KEY (dataset_key, usage_key));
CREATE INDEX IF NOT EXISTS checklist_names_nub ON checklist_names(nub_key);

-- PDF library: what literature.scan finds. Rebuilt on every scan; decisions survive in
-- curation/pdf_decisions.csv. snippet is for the local build only (never published).
CREATE TABLE IF NOT EXISTS pdf_mentions (
  mention_id INTEGER PRIMARY KEY, taxon_id INTEGER, file TEXT, page INTEGER, name_found TEXT,
  method TEXT,                             -- text | ocr | abbrev
  kind TEXT,                               -- heading (a species section) | mention
  areas TEXT, islands TEXT,                -- from the section, regional documents only
  snippet TEXT, decision TEXT NOT NULL DEFAULT 'pending', created_at TEXT,
  UNIQUE (taxon_id, file, page, name_found, kind));
CREATE INDEX IF NOT EXISTS pdf_mentions_taxon ON pdf_mentions(taxon_id);
CREATE TABLE IF NOT EXISTS pdf_candidates (  -- heading names not in the tree
  candidate_id INTEGER PRIMARY KEY, name TEXT, file TEXT, page INTEGER, areas TEXT,
  islands TEXT, snippet TEXT, gbif_key INTEGER, decision TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT);
CREATE INDEX IF NOT EXISTS pdf_candidates_name ON pdf_candidates(name);

-- Wikidata (CC0) by GBIF key. A row with qid NULL means "asked, no item".
CREATE TABLE IF NOT EXISTS wikidata_taxa (
  gbif_key INTEGER PRIMARY KEY, qid TEXT, name TEXT, inat_id TEXT, bugguide_id TEXT,
  iucn TEXT, image TEXT, article TEXT, commons TEXT,
  confidence TEXT,                         -- high (P225 = our name) | review
  fetched_at TEXT);

CREATE TABLE IF NOT EXISTS wikipedia_articles (
  taxon_id INTEGER PRIMARY KEY, title TEXT, url TEXT, revid INTEGER, rev_timestamp TEXT,
  html TEXT, text TEXT, fetched_at TEXT, lead_only INTEGER NOT NULL DEFAULT 0);

-- BugGuide nodes for our GBIF keys, from entobase's database (read-only) or Wikidata P2464.
CREATE TABLE IF NOT EXISTS bugguide_links (
  gbif_key INTEGER PRIMARY KEY, bugguide_id INTEGER, name TEXT, rank TEXT, confidence TEXT,
  source TEXT, fetched_at TEXT);

-- Photos (hotlinked from their hosts; only a small thumbnail is stored, data/media/thumbs).
CREATE TABLE IF NOT EXISTS photos (
  photo_id TEXT PRIMARY KEY,               -- 'inat:12345' | 'commons:File name.jpg'
  source TEXT, page_url TEXT, display_url TEXT, thumb_url TEXT, license_code TEXT,
  license_url TEXT, attribution TEXT, width INTEGER, height INTEGER,
  status TEXT,                             -- ok | refused (licence not allowed)
  fetched_at TEXT);
CREATE TABLE IF NOT EXISTS photo_candidates (   -- photos that show a taxon; lower hint first
  taxon_id INTEGER, photo_id TEXT, rank_hint INTEGER, PRIMARY KEY (taxon_id, photo_id));
CREATE TABLE IF NOT EXISTS taxon_photos (
  taxon_id INTEGER, position INTEGER, photo_id TEXT, role TEXT, from_taxon_id INTEGER,
  selected_at TEXT, PRIMARY KEY (taxon_id, position));
CREATE TABLE IF NOT EXISTS inat_photo_queries (inat_id INTEGER PRIMARY KEY, asked_at TEXT);

-- Island-level records (GBIF level-1 areas, curated evidence): one row per taxon and island.
CREATE TABLE IF NOT EXISTS taxon_islands (
  taxon_id INTEGER, area TEXT, island TEXT, source TEXT, records INTEGER, fetched_at TEXT,
  PRIMARY KEY (taxon_id, island, source));

-- Host plants (crops) a source records a taxon attacking.
CREATE TABLE IF NOT EXISTS taxon_hosts (
  taxon_id INTEGER, host TEXT, source TEXT, PRIMARY KEY (taxon_id, host, source));

-- Native / introduced statements, one row per source and area (never collapsed).
CREATE TABLE IF NOT EXISTS establishment (
  taxon_id INTEGER, area TEXT, status TEXT, source TEXT, citation TEXT, year INTEGER,
  page INTEGER, auto INTEGER NOT NULL DEFAULT 1, fetched_at TEXT,
  PRIMARY KEY (taxon_id, area, source));
