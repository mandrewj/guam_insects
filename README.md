# Insects of Guam (and Micronesia)

An aggregated reference to the hexapods (insects, springtails, proturans, diplurans) of Guam,
the Northern Mariana Islands, Palau, the Federated States of Micronesia and the Marshall
Islands. Regional lists are thin, so the site pools what each source knows, with Guam first
everywhere:

- **Records**: GBIF (including the University of Guam Insect Collection) and iNaturalist,
  counted per island group and, where the data allow, per island.
- **Literature**: the 1940s *Insects of Guam* (digitised by Plazi), the *Insects of
  Micronesia* monographs, *Micronesica* papers, University of Guam extension fact sheets,
  and Nafus & Schreiner's list of crop pests. Names and island records are read from the
  text and cited with page numbers.
- **Pages**: Wikipedia, Wikidata, Commons and iNaturalist photos (with credits), IUCN
  category, native/introduced statements, and BugGuide links where the species has a page.

## Use it

```sh
uv sync                              # Python 3.13 (venv in venv.nosync; see CLAUDE.md)
uv run guaminsects build public local
open site/local/index.html           # or: uv run guaminsects serve  (http://localhost:8765)
```

`site/public` is what gets deployed (`ops/deploy.sh`, Vercel). `site/local` adds what may not
be published: short passages from the PDFs, links to the files on this computer, and the
curation admin.

## Curate

The tree is GBIF's backbone plus the hand edits in `curation/` (add a morphospecies, rename,
move, hide, set native/introduced, attach iNaturalist observations, GBIF records or your own
photos). Three ways in, all writing the same files:

- the admin page: `uv run guaminsects serve`, then http://localhost:8765/admin.html;
- a spreadsheet of the whole checklist: `uv run guaminsects export`, edit
  `data/exports/checklist.csv`, then `uv run guaminsects import data/exports/checklist.csv`;
- `curation/taxa.csv` and `curation/evidence.csv` directly ([format](curation/README.md)).

Every change is checked against the whole tree before it is saved, and
`uv run python ops/review.py` writes a review page of doubtful records and unmatched names.

## Refresh the data

`ops/refresh_all.sh` runs every step in order, one stream per web service; CLAUDE.md lists
the steps. Each is resumable and caches its answers in `data/raw/`. `uv run pytest -q` and
`uv run python ops/check_site.py` (Chrome, WebKit, Firefox; desktop and phone) check it.

## Not in this repo

The data (`data/`, `data.nosync/`), the PDF library (`literature/`, copyrighted) and the
built sites (`site/`). `sources/library.csv` and `sources/documents.csv` list every document
with its citation and source.

- **Code licence:** MIT (see `LICENSE`). It covers the code only, not the data or content.
- **Content licences:** everything shown on the site carries its source's own licence and
  credit (photos CC only; no ND, no all-rights-reserved).
