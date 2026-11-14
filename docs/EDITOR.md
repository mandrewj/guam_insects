# The taxonomy editor

`editor/` is a static web app (HTML, CSS, plain JavaScript; no build step, no install) for
checking, editing and annotating the checklist. Anyone with write access to the GitHub
repository can use it; what they commit rebuilds and redeploys the site.

```
 editor (browser)                     GitHub main                    GitHub Actions             Vercel
 ───────────────                      ───────────                    ──────────────             ──────
 load taxonomy.csv + curation/*.csv ◄─ latest commit
 edit (a list of operations)
 Commit ───────────────────────────►  one commit: curation/*.csv  ─► rebuild.yml:
   (GitHub token, or                   + taxonomy.csv, credited        restore the data snapshot
    `guaminsects edit` + your git)     to the "added by" name          resolve, build, check ───► deploy
                                                                       commit taxonomy.csv back
 data machine: harvest ─► snapshot --upload (release "data-snapshot") ─┘
```

## Using it

- **Open** `editor/index.html` in a browser: from a clone (double-click; `file://` works),
  through `uv run guaminsects edit` (http://localhost:8766/editor/), or hosted anywhere. It loads
  the latest taxonomy from GitHub (public: no token needed to read). The source label in the
  header opens other choices: this clone, a folder (Chrome/Edge), or the CSV files
  themselves.
- **Your name** is asked once and recorded as *added by* on everything you change
  (`editor` / `added_by` in the curation files, `modifiedBy` in taxonomy.csv) and credited in
  the commit. Everything added in the editor is public.
- **Find** a taxon by name, common name or id, browse the tree, or pick a worklist: not in the
  Catalogue of Life, merged by spelling, literature machine-read only, species on observations
  only, species resting on one or two GBIF records, families with nothing under them, hidden,
  changed, annotated.
- **Tools** on a taxon: distribution tags (a place from the fixed list, present / absent /
  doubtful, with a source), vouchers (iNaturalist observations, identified or not, and GBIF
  records), links, edit fields, synonymize into another taxon, split a name back out, move,
  add a taxon under it (a morphospecies gets an `IOG-` id), add a name, confirm, hide (the
  site's "delete": nothing is lost), and delete for good (only taxa added here).
- **Table**: every column of taxonomy.csv, virtualised (6,600 rows scroll smoothly). White
  cells are editable (double-click, Enter saves); grey ones are computed by the build. A list
  cell is typed in its taxonomy.csv format (below) and becomes the same operations the tools
  make.
- **Changes** lists every operation with its author and an Undo. They are kept in the
  browser (localStorage) until committed, and offered again after a reload.
- **Commit** warns that it triggers a rebuild, then:
  - *GitHub with your token*: a fine-grained personal access token for this repository with
    **Contents: read and write** (github.com/settings/personal-access-tokens/new). One commit
    through the Git Data API, straight onto `main`. If someone committed meanwhile, the editor
    reloads their version, replays your operations on it and tries again; an operation that no
    longer applies is shown for you to undo or redo.
  - *This clone* (`uv run guaminsects edit`): the local server checks the files with
    `curation.load`, commits with your git (author: your editor name), and pushes (rebasing
    once if main moved). `--no-push` keeps the commit local.
  - *Folder* or *download*: the changed files, to commit yourself.
  After a commit the dialog follows the rebuild's workflow run.

## How an edit is stored

Every operation writes what `resolve` reads, using the same rules as `curation.upsert` and
`taxonomy.import_edits`, and updates taxonomy.csv to match, so the table shows the edit at
once:

| operation | curation/ | taxonomy.csv |
|---|---|---|
| tag | annotations.csv `distribution` row (value = place, status, source) | `distributionTags`, `recordedIn` |
| voucher | evidence.csv `inat_observation` / `gbif_occurrence` row | `associatedOccurrences` |
| link | annotations.csv `link` row (value = URL, note = label) | `associatedReferences` |
| set (a field) | taxa.csv override of that field | the cell, `curatedFields` |
| synonymize | taxa.csv `status synonym` + `accepted_id` | the row becomes a synonym row after its accepted taxon; its children and names follow |
| split | taxa.csv `status accepted` + `parent_id` (a COL taxon: the merge is removed) | an accepted row again |
| move | taxa.csv `parent_id` | parent, classification columns |
| add | taxa.csv row with a new `IOG-n` id | a new row |
| add a name | taxa.csv `IOG-n` row, status synonym of the taxon | a synonym row |
| hide / show | taxa.csv `hidden` | `hidden` for it and everything under it |
| confirm | taxa.csv `verified` + `citation` | `verificationStatus` editor confirmed |
| delete | the `IOG-` row and its annotations go | the row goes |

Each row written carries `editor`/`edited` (or `added_by`/`added`) and the operation's reason.
Computed columns (records, literature, verification levels, islands from sources) are
refreshed by the rebuild, which commits the regenerated taxonomy.csv back.

**List cells** in taxonomy.csv (items separated by ` | `):
`distributionTags` `Rota: present (Buden 2004) | Yap: doubtful`;
`associatedOccurrences` `https://www.inaturalist.org/observations/123 | https://www.gbif.org/occurrence/456`;
`associatedReferences` `BOLD <https://boldsystems.org/...> | https://example.org/paper`.

**Places** for distribution tags: the island groups (Guam, CNMI, Palau, FSM, Marshalls) and
every island in `geo.ISLAND_COORDS`. A *present* tag counts as a record in its island group
(shown as "Ed." in the site's presence table, rolled up to the genus and family) and lights
its island on the map; *absent* and *doubtful* tags are listed on the page and count for
nothing.

**Ids.** A new taxon gets `IOG-<n>` (one more than the highest in use) when the operation is
made. If someone else committed that number first, the replay gives it the next free one and
the later operations follow it.

## Files

| file | what |
|---|---|
| `editor/index.html` | the page |
| `editor/assets/spec.js` | **generated** by `uv run guaminsects editor-spec` from curation.py, taxonomy.py and geo.py (columns, ranks, statuses, places); `tests/test_editor.py` fails when it is stale |
| `editor/assets/csv.js` | CSV exactly as Python's csv module writes it, so an unedited file round-trips byte for byte (taxonomy.csv: BOM + `\n`; curation: `\r\n`) |
| `editor/assets/model.js` | the base files + operations → the current state; checks; the files to commit. No DOM |
| `editor/assets/io.js` | loading and committing: GitHub API, the local server, File System Access, files |
| `editor/assets/ui.js` | the page |
| `src/guaminsects/editor.py` | the spec, and `guaminsects edit` (serves only `editor/` and the four files; commit + push) |
| `src/guaminsects/snapshot.py` | `snapshot [--upload]` / `restore`: the build's data as a public release asset |
| `.github/workflows/rebuild.yml`, `ops/ci_rebuild.sh` | the rebuild after a push |

`tests/test_editor.py` runs the editor's own JavaScript in Chromium against the fixture world
and checks that **what the editor shows for an edit is what `resolve` and taxonomy.csv make of
it** (every edited column, and the row order), that bad edits are refused without a trace,
that the local server commits, credits and pushes, and that the whole page works from
`file://`.

## The rebuild (CI)

`.github/workflows/rebuild.yml` runs on every push to `main` that touches the taxonomy,
curation, sources, code or web app:

1. `uv sync`, then `curation.load` and `pytest` (a broken curation file fails here).
2. Unless the `data-snapshot` release or the Vercel secrets are missing (then it stops with a
   notice): `guaminsects restore` (guam.sqlite without PDF text, the thumbnails), `resolve`,
   `ops/deploy.sh --prod` (build, check_site in Chromium, Vercel CLI 65.4.0 with the token).
3. Commits the regenerated taxonomy.csv back as github-actions[bot] (no new run starts).

**Secrets** (repository settings → Secrets and variables → Actions): `VERCEL_TOKEN`
(vercel.com/account/tokens), `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` (from
`site/public/.vercel/project.json` on the data machine: `orgId`, `projectId`).

**The snapshot** must be current: `ops/harvest.sh` runs `guaminsects snapshot --upload` before
it deploys. Run it by hand after any other change to the database. It empties every column
named snippet / context / excerpt / quote / page_text in every table and refuses to publish if
any is left (CLAUDE.md rule 4).

**taxonomy.csv edited in a spreadsheet** is imported by the next build *on the machine where
it was edited* (taxonomy.sync, before committing). A taxonomy.csv that matches its commit is
never read as edits, so a pulled regeneration (CI's or the data machine's) cannot be mistaken
for one. Push spreadsheet edits only after a build has filed them into curation/, or make them
in the editor's table.

## Not yet

- PDF mentions (accept / reject with snippets) need the PDF text, which is never published:
  a later, local-only add-on (an export from the data machine the editor can open).
- Adding a taxon by a Catalogue of Life id the tree does not have (the old curation API
  fetched it); add it as an `IOG-` taxon for now.
- Firefox: the page uses nothing Chromium/WebKit-specific except the optional folder
  picker, but Playwright's Firefox does not start on the development Mac (macOS 27), so it
  is untested there.
