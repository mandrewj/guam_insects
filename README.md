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
uv run guaminsects build
open index.html                      # redirects to site/public/; or: uv run guaminsects serve (http://localhost:8765)
```

There is one build, `site/public`: the site you open here is the one deployed
(`ops/deploy.sh`, Vercel).

## Curate

The tree is the Catalogue of Life plus the hand edits in `curation/` (add a morphospecies,
rename, move, merge, hide, set native/introduced, tag islands, attach iNaturalist
observations, GBIF records, links or your own photos). Three ways in, all writing the same
files:

- **The editor** (`editor/index.html`; [how it works](docs/EDITOR.md)): open it in a browser,
  from a clone or anywhere. It loads the latest taxonomy from GitHub, has tools for tags,
  vouchers, links, synonyms and new taxa, and a table of every value. Its **Commit** button
  commits to `main` (with your GitHub token, or with your git through
  `uv run guaminsects edit`), which rebuilds and redeploys the site. Everything you add is
  credited to the name you give it.
- **`taxonomy.csv`** at the top of this folder: the whole taxonomy in Darwin Core columns
  (with family on every row, the island groups, sources and a verification level). Every
  build rewrites it, and edits made to it are taken in first. The site's "Download taxonomy"
  box gives the same file for the whole tree or for the taxon on screen and everything
  under it; an edited download goes back in with `uv run guaminsects import <file>`;
- `curation/taxa.csv`, `curation/evidence.csv` and `curation/annotations.csv` directly
  ([format](curation/README.md)).

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
