# The web app: what to keep, what to change

`starter/webapp/` is entobase's app exactly as it stands (static, no build step, no framework,
vanilla JS ≈1,200 lines + CSS ≈500 lines). The user wants Micronesia's view to be "almost
identical". Keep the structure; change what is listed under **Change**.

## Files

- `index.html`: shell, header (logo, tagline, Identify toggle, search box), footer. Loads
  `data/site/meta.js`, then `app.js`.
- `assets/app.js`: hash router, renderers, search. Find renderers by name rather than reading the
  whole file: `renderTaxon`, `breadcrumb`, `header`, `gallery`, `pageNav`, `children`, `sections`,
  `mapFigure`, `wikipedia`, `worksCited`, `facts`, `classification`, `links`, `attribution`,
  `renderSearch`, `renderIdentify`/`identifyPanel`, `hostPlants`, `factSheets`, `conservation`,
  `showLightbox`, `pinSide`, `familyIndex`, `displayRank`.
- `assets/app.css`: tokens in `:root` (+ dark mode), components, then a desktop density block
  (`min-width: 861px`) and responsive blocks **at the end of the file**.
- `assets/img/`: logo, favicon, `regions.svg` (the identify view's region map).
- Output written by the builder (`guaminsects build`, `src/guaminsects/build/`): `index.html`
  (the shell), `assets/`, and under `data/`:

  | file | contents | loaded |
  |---|---|---|
  | `meta.js` | areas, island map, counts, home cards, build date | at start |
  | `index.js` | which chunk holds each taxon (ids delta-encoded, base 36) | at start (before `meta.js`) |
  | `c/<n>.js` | the full records of one chunk (`guaminsects.chunk(n, {id: record})`) | on the first visit to a taxon in it |
  | `w/<n>.js` | the Wikipedia HTML of the same chunk's taxa (`guaminsects.wiki(n, {id: html})`) | when "Show entire Wikipedia article" is first opened |
  | `s/names.js` | one row per taxon for as-you-type suggestions | on the first search |
  | `s/<x>.js` | full-text index of the terms starting with `<x>` | for the query's terms |
  | `taxonomy.js` | the Darwin Core download rows | on a download button |

  A chunk is a family and everything under it (families over 400 KB split by genus, small
  neighbouring families in one order merged up to 150 KB, each taxon above Family alone), about
  190 files of up to 370 KB. Each file is one `<script>` that calls into `guaminsects`, so it
  works from `file://` (no `fetch`). The app keeps the last few chunks, the one on screen always.
  `media/thumbs/` holds the card thumbnails; photos are hotlinked from their hosts.

## Views (routes)

| Hash | View |
|---|---|
| `#/` | home: orders (here: Arthropoda → classes) as cards with photos |
| `#/t/<id>` | taxon page |
| `#/id/<id>[?r=gu]` | **identify**: every member of a group side by side (photo + range map), filterable by region chips |
| `#/search?q=…` | search results with snippets; suggest-as-you-type from the names index |

### Taxon page (desktop)

Two columns. **Left, sticky** (`.side`, 330 px): photo gallery with thumbnails and caption,
*At a glance* tiles (species count, included taxa, iNat observations, GBIF records), conservation
status, classification table, "Elsewhere" links. **Right** (`.main`): jump links ("On this
page"), families index (for ranks above family), included-taxa cards (with photo thumb, rank,
species count), source sections, the GBIF map after the Range section, host plants, extension
fact sheets, the From-Wikipedia card (150-character preview + "Show entire article"), works
cited. Below both: **Sources & attribution**. Phones: one column, photo first, boxes last
(`.side{display:contents}`).

## The record (what `site.build_records` produces for each taxon)

`id, rank, name, authority, authority_source, common, status, hidden, placeholder, fossil,
species_count, hosts[], conservation, regions[], factsheets[], lineage[], classification[],
children[] (each: id, rank, name, common, species_count, kids, map overlay, regions, thumb, hidden…),
child_groups[], families[], photos[] (display, thumb, w, h, source, page, license, attribution,
retrieved, of/of_id/of_rank for borrowed), wikipedia{title,url,revid,rev_timestamp,retrieved,
preview,html}, map{basemap,overlay,key,na_records,min_year,max_year,retrieved,group}, sections[]
(key, heading, html), works_cited[], links[] (system, label, url, confidence), inat{observations,…},
bugwood{…}, sources{bugguide{…}}`.

## Change for Micronesia

1. **Branding**: title, tagline ("Insects and arthropods of Micronesia, offline"), logo, favicon
   (ask the user; do not reuse the ahasverus artwork without checking its licence).
2. **Regions → islands.** `regions.py` becomes five entries: Guam, CNMI (Saipan/Tinian/Rota/
   Northern Islands), Palau, FSM (Yap, Chuuk, Pohnpei, Kosrae), Marshalls, Guam first. Membership
   from presence rows by area code. Redraw `regions.svg` with `ops/make_region_map.py` (it draws
   from the code sets; it needs a Pacific projection and island polygons: Natural Earth admin-1
   or GADM, both free). Island-level chips on the taxon page ("Recorded on: Guam, Rota").
3. **Maps**: new `BBOX` (≈ lon 130-175 E, lat 0-22 N) and a Guam inset; recompute the CSS crop
   constants (`.map-stack` and `.ip-map`: aspect ratio and `top`/`height` percentages) from the new
   bounds. The map caption says "records in Micronesia" not "in North America".
4. **At a glance**: `iNat obs. (Guam)` and `GBIF records (Micronesia)`; add a **status badge**
   next to the name: *Native*, *Endemic*, *Introduced*, *Invasive*, *Unknown*, with the source.
5. **Sections**: BugGuide sections become "BugGuide (via entobase)" blocks when present. New
   sections from sources: **Literature** (PDF citations with pages; no snippets on the site), Wikipedia,
   Wikispecies (taxonomy/synonymy), IUCN status, "Biology" from any text with citations. Keep the
   "section note" pattern: each block says where its text came from, and attribution lists it.
6. **Search**: index scientific names, synonyms, and common names (English, Chamorro, Palauan
   where a source gives them: ask the user) and full text of what you hold. Tokenizer parity
   with Python is enforced by the check script.
7. **Conservation box**: IUCN instead of NatureServe (the box's layout is reusable).
8. **Remove**: `hostPlants` (NHM HOSTS is Lepidoptera of Britain/N. America), the factsheet
   renderer, NatureServe states table, "Hodges number" cleaning: unless you add equivalents.
9. **Footer/license text** mentions BugGuide's `ai-train=no` and "personal reference". Update
   for the new sources.

## Density and layout decisions already made for entobase (keep)

15 px body text on desktop, 1200 px wrapper, 330 px sticky left column that parks by its bottom
edge (`pinSide`), photos ≤ 300 px tall, 3:2 card thumbnails ≥165 px wide, maps cropped in CSS to
the region of interest and ≤620 px wide, identify tiles with a 175 px photo above a full-width
map, landscape-first thumbnail selection, "On this page" jump links in one row above the content.

## Tests

`ops/check_site.py` (copy it): loads the built site in Chrome, WebKit and Firefox at 1280×900 and
390×844, walks the routes, checks search parity, the lightbox, the region filter, JS errors;
`--shots DIR` saves screenshots. It uses fixtures taxon ids (56, 9216, 168731 in entobase): swap
in ids from your tree. Playwright browsers must be installed (`uv run playwright install`).
