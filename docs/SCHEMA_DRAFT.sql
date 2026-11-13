-- Starting schema for guam_insects. Adapted from reference/entobase/src/entobase/schema.sql.
-- Primary id is the GBIF taxon key. Add every column to db.ADDED_COLUMNS when you change it,
-- and name columns in every INSERT.

CREATE TABLE IF NOT EXISTS taxa (
  gbif_key        INTEGER PRIMARY KEY,
  parent_key      INTEGER,
  rank            TEXT NOT NULL,           -- Phylum..Subspecies
  canonical_name  TEXT NOT NULL,           -- "Oryctes rhinoceros"
  scientific_name TEXT,                    -- with authorship
  authority       TEXT,
  taxonomic_status TEXT,                   -- accepted | synonym | doubtful
  accepted_key    INTEGER,                 -- for a synonym
  lineage         TEXT,                    -- '/54/216/…/' for LIKE "everything under X"
  common_name     TEXT,
  display_default INTEGER DEFAULT 1,       -- hidden placeholders / marine / fossils = 0
  hidden_reason   TEXT,
  terrestrial     INTEGER,                 -- curation decision; NULL = undecided
  establishment   TEXT,                    -- native|endemic|introduced|invasive|unknown (resolved)
  full_name       TEXT
);
CREATE INDEX IF NOT EXISTS taxa_parent ON taxa(parent_key);
CREATE INDEX IF NOT EXISTS taxa_name   ON taxa(canonical_name);

CREATE TABLE IF NOT EXISTS taxon_synonyms (
  gbif_key INTEGER, synonym TEXT, source TEXT, PRIMARY KEY (gbif_key, synonym));

CREATE TABLE IF NOT EXISTS taxon_presence (          -- by area; one GBIF facet per area
  taxon_key INTEGER, area TEXT,                      -- GU, MP, PW, FM, MH or an island code
  records INTEGER, first_year INTEGER, last_year INTEGER,
  source TEXT NOT NULL,                              -- gbif | inat | literature
  citation TEXT, fetched_at TEXT,
  PRIMARY KEY (taxon_key, area, source));
CREATE TABLE IF NOT EXISTS presence_areas (area TEXT PRIMARY KEY, answered_at TEXT, species INTEGER);

CREATE TABLE IF NOT EXISTS establishment (           -- one row per source: do not collapse
  taxon_key INTEGER, area TEXT, status TEXT, source TEXT, citation TEXT, url TEXT, fetched_at TEXT,
  PRIMARY KEY (taxon_key, area, source));

CREATE TABLE IF NOT EXISTS external_links (          -- inat | wikidata | wikipedia | wikispecies | bugguide | iucn | bugwood | itis | bold
  taxon_key INTEGER, system TEXT, external_id TEXT, url TEXT, label TEXT,
  confidence TEXT CHECK (confidence IN ('high','medium','review')), method TEXT, fetched_at TEXT,
  PRIMARY KEY (taxon_key, system));

CREATE TABLE IF NOT EXISTS inat_taxa (inat_id INTEGER PRIMARY KEY, name TEXT, rank TEXT, is_active INTEGER,
  common_name TEXT, ancestor_ids TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS inat_counts (inat_id INTEGER, place_id INTEGER, observations INTEGER,
  fetched_at TEXT, PRIMARY KEY (inat_id, place_id));

CREATE TABLE IF NOT EXISTS photos (
  photo_id TEXT PRIMARY KEY,               -- 'inat:12345' | 'commons:File:…'
  source TEXT, page_url TEXT, license_code TEXT, license_url TEXT, attribution TEXT,
  place_id INTEGER, width INTEGER, height INTEGER,
  display_path TEXT, thumb_path TEXT, status TEXT, fetched_at TEXT);   -- status: pending|ok|failed
CREATE TABLE IF NOT EXISTS taxon_photos (
  taxon_key INTEGER, position INTEGER, photo_id TEXT,
  role TEXT,                               -- own | inherited
  from_taxon_key INTEGER, selected_at TEXT, PRIMARY KEY (taxon_key, position));

CREATE TABLE IF NOT EXISTS wikipedia_articles (taxon_key INTEGER PRIMARY KEY, title TEXT, url TEXT,
  revid INTEGER, rev_timestamp TEXT, html TEXT, text TEXT, fetched_at TEXT, lead_only INTEGER);
CREATE TABLE IF NOT EXISTS wikispecies_pages (taxon_key INTEGER PRIMARY KEY, title TEXT, url TEXT,
  revid INTEGER, wikitext TEXT, html TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS iucn_assessments (taxon_key INTEGER PRIMARY KEY, assessment_id INTEGER,
  category TEXT, criteria TEXT, trend TEXT, year INTEGER, habitats TEXT, threats TEXT,
  url TEXT, fetched_at TEXT);

-- PDF library ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pdf_files (
  pdf_id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, filename TEXT, pages INTEGER,
  citation TEXT,                           -- the full citation the site shows (edit by hand)
  authors TEXT, year INTEGER, title TEXT, journal TEXT, doi TEXT,
  ocr_pages INTEGER, ingested_at TEXT);
CREATE TABLE IF NOT EXISTS pdf_mentions (
  mention_id INTEGER PRIMARY KEY, taxon_key INTEGER, pdf_id INTEGER, page INTEGER,
  name_found TEXT, method TEXT,            -- text | ocr
  kind TEXT,                               -- record | description | key | mention
  snippet TEXT,                            -- ≤ ~2 sentences
  decision TEXT DEFAULT 'pending',         -- pending | accepted | rejected (never overwritten by a rerun)
  UNIQUE (taxon_key, pdf_id, page, name_found));

CREATE TABLE IF NOT EXISTS gbif_maps (taxon_key INTEGER PRIMARY KEY, status TEXT, overlay_path TEXT,
  records INTEGER, min_year INTEGER, max_year INTEGER, error TEXT, fetched_at TEXT);   -- status: ok|group|none|failed
CREATE TABLE IF NOT EXISTS link_audit (taxon_key INTEGER, check_name TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS site_records (taxon_key INTEGER PRIMARY KEY, hash TEXT);
