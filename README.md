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
  category where Wikidata records it, native/introduced statements, and BugGuide links where the species has a page.

## Getting started / contributing

```sh
git clone https://github.com/mandrewj/guam_insects && cd guam_insects
uv sync && uv run playwright install chromium   # the browser is only for ops/check_site.py
uv run guaminsects dataset check && uv run guaminsects build && uv run guaminsects serve   # :8765
uv run guaminsects edit        # the editor on :8766; Commit = commit + push to main (`--no-push` keeps it local)
```

Or open `editor/index.html` and use a fine-grained GitHub token (Contents: read/write) for this repo. Collaborators need write access to the repository. Every push to `main` that touches `dataset/`, `media/`, `src/`, `webapp/`, `editor/`, `ops/` or `tests/` runs CI (`dataset check`, pytest, build, `ops/check_site.py`) and deploys to Vercel when the owner's `VERCEL_*` secrets are set. A normal clone needs none of the iCloud-specific setup in CLAUDE.md.

## Use it

```sh
uv sync                              # Python 3.13 (venv in venv.nosync; see CLAUDE.md)
uv run guaminsects build             # dataset/ -> site.nosync/public (no database, no network)
open index.html                      # redirects to site.nosync/public/; or: uv run guaminsects serve
```

There is one build, `site.nosync/public`: the site you open here is the one deployed
(`ops/deploy.sh`, or a push to `main`: GitHub Actions rebuilds and deploys to Vercel).

## The data

`dataset/` is the data: about a dozen CSV tables and `wikipedia.jsonl`, in git
([every column](dataset/README.md); declared in `src/guaminsects/schema.py`). The taxon table
is the Catalogue of Life's hexapods that have records in Micronesia, plus the names it lacks
(flagged), each with a nativity (native, introduced or unknown). `media/thumbs/` holds the card
thumbnails. A clone builds the whole site; only the PDF library is not in it.

## Edit it

- **The editor** (`editor/index.html`; [how it works](docs/EDITOR.md)): open it in a browser,
  from a clone or anywhere. It loads the latest dataset from GitHub, has tools for tags,
  vouchers, links, synonyms, nativity, new taxa and for reviewing what the tools wrote, and a
  table of every value. Its **Commit** button commits to `main` (with your GitHub token, or
  with your git through `uv run guaminsects edit`), which rebuilds and redeploys the site.
  Everything you add is credited to the name you give it.
- **The CSV files directly**: edit them in a spreadsheet or a text editor and push;
  `uv run guaminsects dataset check` reports every problem at once, and CI runs it.

## Add to it (the data machine)

Two Claude Code skills drive the tools, which need the PDF library and the polite API streams:
`/ingest-literature <directory>` (names, pages, islands, status, hosts, years and short
paraphrased notes from PDFs, flagged machine-read) and `/sync-records` (GBIF and iNaturalist
counts; new taxa flagged `new`). `uv run guaminsects refresh photos|wikipedia|wikidata|bugguide|col`
refreshes one outside source. `uv run pytest -q` and `uv run python ops/check_site.py` (Chrome,
WebKit, Firefox; desktop and phone) check it. The previous pipeline (a database rebuilt from
cached API answers) is the git tag `pipeline-v1`.

## Not in this repo

The PDF library (`literature/`, copyrighted), the PDF text and API cache (`private.nosync/`)
and the built site (`site.nosync/`). Documents are listed in `dataset/documents.csv` with
their citation and public source.

- **Code licence:** MIT (see `LICENSE`). It covers the code only, not the data or content.
- **Content licences:** everything shown on the site carries its source's own licence and
  credit (photos CC only; no ND, no all-rights-reserved).
