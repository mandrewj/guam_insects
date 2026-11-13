# Data sources: recipes, licences, gotchas

Everything here was learned running entobase; "verified" means checked against the live API on
2026-11-13. Always send `User-Agent: guam-insects-research (m.andrew.johnston@gmail.com)`.
`reference/entobase/src/entobase/enrich/http.py` (`ApiClient`) already does rate-spacing, retries,
`Retry-After` on 429, and backoff on 5xx: reuse it.

## GBIF (https://api.gbif.org/v1)  no key, CC0/CC BY data (per dataset)

| Need | Call |
|---|---|
| Name → key | `GET /species/match?name=Oryctes%20rhinoceros&kingdom=Animalia` → `usageKey`, `canonicalName`, `matchType` (EXACT/FUZZY/HIGHERRANK/NONE), `status`, `acceptedUsageKey`. Verified: 4995642. Treat HIGHERRANK as no match |
| Taxon | `GET /species/{key}` (classification keys `kingdomKey…speciesKey`, `authorship`, `taxonomicStatus`) |
| Children / synonyms | `GET /species/{key}/children?limit=1000&offset=`; `/species/{key}/synonyms` |
| Species with records in a country | `GET /occurrence/search?country=GU&taxonKey=54&limit=0&facet=speciesKey&facetLimit=1000&facetOffset=0` (see `scripts/gbif_checklist.py`). Facet counts are records. Verified counts: Arthropoda species with records: GU 1,586; MP 829; PW 1,274; FM 1,504; MH 1,085 |
| Records for one taxon | `GET /occurrence/search?taxonKey=…&country=GU&limit=300&offset=` (hard cap: `offset + limit ≤ 100,000`; use the download API above that, which needs a GBIF account) |
| Quality | `hasCoordinate=true&hasGeospatialIssue=false`; filter `basisOfRecord` (`PRESERVED_SPECIMEN`, `HUMAN_OBSERVATION`, `MACHINE_OBSERVATION`; exclude `FOSSIL_SPECIMEN`); read `establishmentMeans` (NATIVE/INTRODUCED/INVASIVE…; often empty) and `occurrenceStatus` |
| Density map tiles | `https://tile.gbif.org/3857/omt/{z}/{x}/{y}@2x.png?style=osm-bright` (basemap); `https://api.gbif.org/v2/map/occurrence/density/{z}/{x}/{y}@2x.png?srs=EPSG:3857&taxonKey=KEY&bin=hex&hexPerTile=110&style=classic.poly` (overlay). Ad-hoc map over many keys: `…/v2/map/occurrence/adhoc/{z}/{x}/{y}@1x.png?…&taxonKey=k1&taxonKey=k2` (≤100 keys per request); **it answers 503 for a tile with no records**: read that as empty |

Gotchas: country totals count *records*, so a handful of old specimens in one dataset can dominate;
GBIF's backbone is not a checklist authority for every group, so keep the source and the matched
key per taxon; many Micronesian records carry `country=GU` for the island but the coordinates are
sloppy (check `COUNTRY_COORDINATE_MISMATCH`); a species can be in the list only because of one
mis-ID; always show record counts and year ranges. GBIF citation: "Occurrence data: GBIF.org,
accessed <date>" (as entobase's captions do). Dataset-level licences vary (CC0, CC BY, CC BY-NC);
you are showing counts and a density picture, not individual records. If you ever display single
records, read each record's licence.

## iNaturalist (https://api.inaturalist.org/v1)  no key for reads; ≈1 request/s; iNat asks for under ~10k requests a day

| Need | Call |
|---|---|
| Place ids | `GET /places/autocomplete?q=Guam` → Guam **7316** (verified), Palau **7320**, Federated States of Micronesia **10322**, Marshall Islands **10324**, Commonwealth of the Northern Mariana Islands **8355** (all verified) |
| Species per place | `GET /observations/species_counts?place_id=7316&taxon_id=47120&per_page=500&page=N` (47120 = Arthropoda; add `quality_grade=research`). Pages of 500; read `total_results`. Each result carries `count` and a `taxon` object |
| Taxon | `GET /taxa/{id}` (rank, `is_active`, `ancestor_ids`, `wikipedia_url`, `default_photo`, `taxon_photos`) |
| Name search | `GET /taxa?q=Oryctes%20rhinoceros&rank=species` : accept only if the name matches exactly and the taxon is active |
| Photos | `GET /taxa/{id}` returns `taxon_photos` with `license_code` and attribution. Allowed: `cc0`, `cc-by`, `cc-by-sa`, `cc-by-nc`, `cc-by-nc-sa`. Skip `cc-by-nd`, `cc-by-nc-nd`, and null (all rights reserved). Photo sizes: swap `square`/`medium` in the URL for `large`/`original` |
| Observation photos from a place | `GET /observations?place_id=7316&taxon_id=…&quality_grade=research&photos=true&per_page=…&order_by=votes` |

Gotchas: **429 under concurrency** (entobase hit it by running several iNat streams at once: see
LESSONS.md); a `species_counts?per_page=0` probe returned a non-JSON answer once (cause not established: it may have been a 429 because entobase jobs were running); use `per_page=1` for a count-only call;
iNat's taxonomy differs from GBIF's: match by name and verify, never trust a name search blindly;
iNat observations in Guam include many cultivated/captive records (`captive=false`).
Observation counts are *our* statistic: store per place and show "iNat obs. (Guam)".

## Wikidata (https://query.wikidata.org/sparql)  CC0

One SPARQL query returns QID + iNat id (P3151) + GBIF id (P846) + BugGuide id (P2464) + name
(P225) + enwiki article for many taxa at once: see `reference/.../enrich/wikidata.py` (it is
keyed on P2464 for entobase; here key on `?item wdt:P846 ?gbif` with a `VALUES ?gbif { … }` list
of ≤500 keys per query). Also `P141` (IUCN status), `P627` (IUCN taxon ID), `P18` (image),
`P1843` (common name). Ask politely: one query at a time, with a descriptive User-Agent. The
public endpoint times out at 60 s.

## Wikipedia (https://en.wikipedia.org/w/api.php)  CC BY-SA 4.0

Full text: `action=query&prop=extracts|revisions|info&titles=…&redirects=1&rvprop=ids|timestamp&inprop=url`
(add `exintro=1` for the lead only; very long articles can time out: fall back to the lead).
Store revision id, timestamp, retrieval date, and the licence. Drop reference-type sections.
`enrich/wikitext.py` does all of this. Title lookup via Wikidata sitelinks is safer than name search.
A name-only title match needs a taxon check (`P31 = Q16521`) or you link disambiguation pages
and homonyms (entobase fixed this: `TAXON_ITEM`).

## Wikispecies (https://species.wikimedia.org/w/api.php)  CC BY-SA 4.0

Same MediaWiki API (verified: `?action=query&titles=Oryctes%20rhinoceros&format=json&redirects=1`
returns page 328127). Wikispecies pages are wikitext templates (taxonavigation, synonymy, type
data, references): `action=parse&prop=wikitext` or `prop=extracts` and parse the template.
Wikidata has the sitelink (`specieswiki`), the cleaner route to the title.

## IUCN Red List (https://api.iucnredlist.org/api/v4)  **token required**

Unauthenticated calls answer 403 (verified). The user must provide `IUCN_TOKEN` in the
environment (free registration). Endpoints of interest: `/taxa/scientific_name?genus_name=…&species_name=…`
then `/assessment/{assessment_id}`. Fields: category, criteria, population trend, year
assessed, habitats, threats, systems. Read the current Terms of Use before storing text
(IUCN's terms restrict commercial use; for a personal reference citing the assessment and linking
is the safe default).

## BugGuide

Only via `../entobase`: see `CLAUDE.md` rule 1. Join by GBIF key through entobase's `external_links`.
Show with BugGuide's contributor credits and dates; `ai-train=no`.

## Bugwood (https://api.bugwoodcloud.org/v2)  keyless, **read-only**

`GET /subject?division=1&pagesize=1000&page=N` (list, then filter by name), `GET /subject/{id}`
(ITIS ids, image count, nativity). `search=` without `searchon`. Never use write endpoints or
`/login`. Images: CC BY / CC BY-NC 3.0 *per image*: link, do not store. `insectimages.org` 403s
curl. `reference/.../enrich/bugwood.py` is the working client.

## Other sources the user named or that fit

- **GISD** (Global Invasive Species Database, iucngisd.org), **CABI Compendium**, **PIER**
  (hear.org/pier): invasive/pest status; check each site's terms before scraping, prefer APIs.
- **Bishop Museum** and **Guam Department of Agriculture** checklists, **Pacific Insects**
  (monograph series), **Gressitt** and other classic Micronesian literature: this is the PDF
  library's territory.
- **BOLD** (barcode records), **GenBank**: optional "barcoded" badge.
- **ITIS** (taxonomic serial numbers; Bugwood carries them).
- **Catalogue of Life** (`https://api.checklistbank.org`) as a second opinion on names.

## Licence summary (what the site must show)

| Source | Licence | Show |
|---|---|---|
| Wikipedia, Wikispecies | CC BY-SA 4.0 | title, revision, date, licence link |
| iNaturalist photos | per photo (allowed list above) | author, licence, link, retrieval date |
| GBIF | per dataset; counts/maps | "GBIF.org, accessed <date>" |
| Wikidata | CC0 | optional |
| Commons | per file | author, licence, link |
| IUCN | see terms | category + citation + link |
| BugGuide | © contributors; `ai-train=no` | contributors, dates, link |
| PDFs | © their authors | citation, page, ≤2-sentence snippet |
| Bugwood images | per image | link only |
