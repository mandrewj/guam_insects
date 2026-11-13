# Insects of Guam (and Micronesia)

An aggregated reference to the hexapods (insects, springtails, proturans, diplurans) of Guam,
the Northern Mariana Islands, Palau, the Federated States of Micronesia and the Marshall
Islands. Regional lists are thin, so the site pools what each source knows: GBIF records
(including the University of Guam Insect Collection), iNaturalist observations, the 1940s
*Insects of Guam* and the *Insects of Micronesia* series, University of Guam extension fact
sheets, Wikipedia and Wikidata, with Guam first everywhere.

Status: **in development.** The checklist pipeline runs; the site is being ported from
entobase (the author's North American insect reference).

```sh
uv sync                                 # Python 3.13; venv lives in venv.nosync (see CLAUDE.md)
uv run guaminsects checklist            # GBIF: hexapod taxa with records, per area
uv run guaminsects taxa                 # GBIF classification for each (cached in data/raw/)
uv run guaminsects inat                 # iNaturalist species counts per area
uv run guaminsects plazi                # digitised literature checklists (Insects of Guam ...)
uv run guaminsects resolve              # tree = GBIF + curation/*.csv
uv run guaminsects export               # data/exports/checklist.csv
uv run guaminsects documents            # download the library listed in sources/documents.csv
uv run pytest -q
```

- **Curation:** `curation/taxa.csv` and `curation/evidence.csv` hold hand edits (morphospecies,
  renames, added taxa). See [curation/README.md](curation/README.md).
- **Not in this repo:** the data (`data/`, `data.nosync/`), the PDF library (`literature/`,
  copyrighted) and the built site (`site/`). The site is deployed with the Vercel CLI.
- **Content licences:** everything shown on the site carries its source's own licence and
  credit (photos CC only; no ND, no all-rights-reserved).
