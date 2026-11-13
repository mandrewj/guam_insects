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

## Catalogue of Life, through GBIF (https://api.gbif.org/v2)  CC BY 4.0 (COL); the tree's backbone

The tree is COL's eXtended Release as GBIF serves it (checklistKey
`7ddf754f-d193-4cc9-b351-99906754a03b`; ChecklistBank dataset 3LXR, release "COL26.10 XR"
when first fetched on 2026-11-13). COL ids are short codes of digits and capitals (`KVC9L`).

- **Occurrences under COL keys**: `/v1/occurrence/search?checklistKey=<COL>&taxonKey=L2655`
  (L2655 = Hexapoda) with `facet=speciesKey|genusKey|familyKey|orderKey|classKey`. The facet
  values are COL ids. Without checklistKey a COL id finds nothing.
- **A taxon and its classification in one call**: `/v2/species/match?checklistKey=<COL>&usageKey=KVC9L`
  (usage, acceptedUsage for a synonym, classification including itself). ChecklistBank's
  `/dataset/316691/taxon/{id}/classification` gives the same chain without the taxon.
- **Name matching**: `/v2/species/match?checklistKey=<COL>&scientificName=...&taxonRank=...`.
  matchType EXACT / VARIANT (spelling or gender variant) / FUZZY / HIGHERRANK (COL lacks
  the name; the result is the taxon above) / NONE. `taxonRank` does not separate homonyms
  ("Multiple equal matches for Diplura"); a classification hint does (`phylum=Arthropoda`).
  **A family hint can mislead**: Callirhipis onoi with family=Rhipiceridae matches up to
  Rhipiceridae; without it, to the genus in Callirhipidae. So match without hints first.
- Answers take ~0.8 s each (the v2 endpoint is slow): ~1 request/s per stream in practice.
- The bulk GBIF-key-to-COL mapping (download.checklistbank.org/col/gbif) sits behind a bot
  challenge: not used.
- Web pages: `https://www.catalogueoflife.org/data/taxon/<id>`; GBIF records in Micronesia:
  `https://www.gbif.org/occurrence/search?checklist_key=<COL>&country=GU&...&taxon_key=<id>`.
- Wikidata has COL ids as P10585.

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

## Added 2026-11-13 (guam_insects build): what each new source gives and how we use it

| Source | Command | What | Licence / rule |
|---|---|---|---|
| **Plazi checklists on GBIF** (the 1940s *Insects of Guam* I & II, papers on Micronesian taxa) | `guaminsects plazi` | GBIF CHECKLIST datasets from publisher Plazi (`7ce8aef0-9e92-11dc-8738-b8a03c50a862`); name usages carry `nubKey`. 53 hexapod checklists, ~1,300 Guam taxon rows | CC0. GBIF's dataset search is **full text** ("Yap" returns 3,000 datasets): only fetch datasets whose **title** names the region (`plazi.REGION_TITLE`) |
| **Bishop Museum IOM index** (hbs.bishopmuseum.org/pubs-online/iom.html) | `guaminsects library` | Every *Insects of Micronesia* part: volume, year, group, authors, pages, PDF URL (the public link) | Cite and link; the page is UTF-8 |
| **UOG extension fact sheets** | `guaminsects documents` | 45 PDFs (ADAP, Guam Pest Series, Urban Pests UP-01..15, bulletins). Newer sheets (banana lace bug, CRB series...) sit in a JavaScript viewer at publications-press.uog.edu with no PDF link: listed as link-only | Copyright UOG: cite and link only |
| **Micronesica** (micronesica.org, open access since vol. 31) | `scripts/micronesica_index.py` | 941 articles indexed, 63 about hexapods downloaded | CC BY-NC-ND. robots.txt `Crawl-delay: 10` |
| **Crop pest list** (Nafus & Schreiner; Moore's CSV on GitHub) | `guaminsects croppests` | ~950 (crop, pest) rows, distribution by B/Y/T/P/K; M = all Marianas (no single area) | No licence stated: facts + citation only |
| **Wikidata by GBIF key** (P846) | `guaminsects wikidata` | QID, P225 name (checked against ours), P3151 iNat, P2464 BugGuide, P141 IUCN, P18 image, enwiki, P1843 English name. 300 keys a query | CC0 |
| **Wikimedia Commons** files from P18 | `guaminsects photos commons` | Per-file licence from `extmetadata`. **Only standard thumbnail widths work** (330, 960, ...; https://w.wiki/GHai): others answer 400 | Per file; CC0/PD, BY, BY-SA (BY-NC/BY-NC-SA too); no ND, no GFDL-only |
| **entobase's database** (read-only) | `guaminsects bugguide` | GBIF key -> BugGuide node for 1,100 of our taxa | Link only; BugGuide never fetched |

Not usable by script (Cloudflare challenge, do not try to get around it): **guaminsects.myspecies.info**
(Moore's Scratchpad; its Guam lists are the Plazi datasets above) and **AntWiki** (ant data comes
through AntWeb in GBIF and Clouse 2007 in the library). iNaturalist answered 429 for hours on
2026-11-13 while entobase's `link --stubs` ran: `inat_counts.patient_get` waits 5 min a try.

GBIF `establishmentMeans` (native/introduced) is almost never filled for Micronesian insects
(7 Guam records, 2026-11-14). Introduced status comes from the literature (Schreiner 1991,
Nafus 1991) and from curation.
