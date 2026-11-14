# The taxonomy editor

`editor/` is a static web app (HTML, CSS, plain JavaScript; no build step, no install) for
checking, editing and annotating the checklist. Anyone with write access to the GitHub
repository can use it; what they commit rebuilds and redeploys the site.

```
 editor (browser)                     GitHub main                    GitHub Actions             Vercel
 ───────────────                      ───────────                    ──────────────             ──────
 load dataset/*.csv ◄──────────────── latest commit
 edit (a list of operations)
 Commit ───────────────────────────►  one commit: dataset/*.csv   ─► rebuild.yml:
   (GitHub token, or                   credited to the "added by"      dataset check, pytest
    `guaminsects edit` + your git)     name                            build, check_site ───────► deploy
 data machine: the tools (/ingest-literature, /sync-records) commit the same tables ─┘
```

## Using it

- **Open** `editor/index.html` in a browser: from a clone (double-click; `file://` works),
  through `uv run guaminsects edit` (http://localhost:8766/editor/), or hosted anywhere. It loads
  the latest dataset from GitHub (public: no token needed to read). The source label in the
  header opens other choices: this clone, a folder (Chrome/Edge), or the CSV files
  themselves.
- **Your name** is asked once and recorded as *added by* on everything you change
  (`added_by`, `modified_by`, `reviewed_by` in the dataset tables) and credited in
  the commit. Everything added in the editor is public.
- **Find** a taxon by name, common name or id, browse the tree, or pick a worklist: new from a
  tool, literature machine-read, notes machine-written, species with nativity unknown,
  nativity set by a tool (to confirm), nativity in conflict, unplaced names, not in the
  Catalogue of Life, merged by spelling, species on observations only, families with nothing
  under them, hidden, changed, annotated.
- **Tools** on a taxon: distribution tags (a place from the fixed list, present / absent /
  doubtful, with a source), vouchers (iNaturalist observations, identified or not, and GBIF
  records), links, edit fields, synonymize into another taxon, split a name back out, move,
  add a taxon under it (a morphospecies gets an `IOG-` id), add a name, confirm, **nativity**
  (native / introduced / unknown, with a source), **review** (confirm or reject each
  machine-read literature row, machine-written note or host plant; clear a tool's `new` flag),
  place an unplaced name under a parent, hide (the site's "delete": nothing is lost), and
  delete for good (only taxa added here).
- **Table**: the taxa columns (or a preset), virtualised (6,600 rows scroll smoothly). White
  cells are editable (double-click, Enter saves); grey ones are computed from the other tables.
  A list cell is typed in its format (below) and becomes the same operations the tools make.
- **Sources** (tab, and the pickers): `documents.csv` is the one bibliography. Every literature row,
  note, host plant, distribution tag and nativity value points at a reference by its id, so
  correcting a citation corrects it everywhere. The tab lists every reference with what cites it
  (search, **Edit…**, **×** for an uncited one, **＋ New reference…**). Wherever a source is asked
  for (a distribution tag, **Nativity…**, **Cite a source…**) there is a search box over all
  references ending in **＋ New reference…**, which creates it inline (a reference already there
  with the same title, year and first author is reused, never duplicated). **Cite a source…** on a
  taxon adds a confirmed literature row (account, mention or checklist; pages, island groups,
  islands, status, first-record year).
- **Review** (tab): every document with machine-read rows. Pick one (it then shows first, with a
  dropdown to switch) to see **every** machine-made row of it, paged and filterable: **Confirm**,
  **Edit…** (correct pages, areas, islands, status, year, or a note's text; saving confirms it) or
  **×** (reject) each row, or **Confirm all** for the document (optionally with the nativity values
  it set) after checking.
- **Quick review** (tab): the **direct children** of the selected taxon, one card each with all
  they hold (nativity and its source, records per island group, islands, literature with
  machine-read marks, notes, hosts, other names, links, tags, source). Tick the ones to accept (those
  with something waiting start ticked) and press **Accept**: the `new` flag is cleared and their
  machine-read rows and machine-set nativity are confirmed. Only the children ticked, nothing
  underneath. "below ›" goes down a level; the tree on the left changes the parent.
- **Changes** lists every operation with its author and an Undo. They are kept in the
  browser (localStorage) until committed, and offered again after a reload.
- **Commit** warns that it triggers a rebuild, then:
  - *GitHub with your token*: a fine-grained personal access token for this repository with
    **Contents: read and write** (github.com/settings/personal-access-tokens/new). One commit
    through the Git Data API, straight onto `main`. If someone committed meanwhile, the editor
    reloads their version, replays your operations on it and tries again; an operation that no
    longer applies is shown for you to undo or redo.
  - *This clone* (`uv run guaminsects edit`): the local server checks the files with
    `dataset.check`, commits with your git (author: your editor name), and pushes (rebasing
    once if main moved). `--no-push` keeps the commit local.
  - *Folder* or *download*: the changed files, to commit yourself.
  After a commit the dialog follows the rebuild's workflow run.

## How an edit is stored

The editor edits the dataset tables directly (`dataset/`, docs/REFACTOR.md): there is no
override layer, and git is the history. It writes each table exactly as Python's
`dataset.write` does (sorted rows, BOM, `\n`), so a commit changes only what was edited.
Rows that point at a synonym keep pointing at it after a merge; the build follows
`accepted_id`, so a merge is one cell and undoing it loses nothing.

| operation | writes |
|---|---|
| set a field | the cell in taxa.csv (+ `modified_by`, `modified`) |
| tag | distribution.csv row (place, status, a note or URL, `doc_id` = a reference, added_by) |
| new / edit / remove a reference | documents.csv row (the citation is rewritten from its fields); a reference still cited cannot be removed |
| cite a source | a literature.csv row for the taxon and reference (`method manual`, `review editor`) |
| voucher | vouchers.csv `inat_observation` / `gbif_occurrence` row |
| link | links.csv `editor` row (value = URL, label) |
| nativity | `nativity`, `nativity_source` (a document or `editor`), `nativity_review editor` |
| confirm nativity | `nativity_review editor` |
| synonymize | `status synonym`, `accepted_id`, `parent_id` cleared; its children's `parent_id` and its other names' `accepted_id` move to the accepted taxon |
| split | `status accepted`, `accepted_id` cleared, `parent_id` set |
| move | `parent_id` |
| add | taxa.csv row with the next `IOG-n` |
| add a name | taxa.csv `IOG-n` synonym row |
| hide / show | `hidden` (+ reason) on it and everything under it |
| confirm | `verified`, `verified_by`, `verified_date`, `verification_source` |
| review | literature / notes / hosts rows `review = editor` (+ `reviewed_by`, `reviewed`) |
| accept children | each ticked direct child: `flag` cleared, `nativity_review editor` where a tool set it, its machine-read literature/notes/hosts rows confirmed |
| correct a row | a literature row or note edited in place and confirmed |
| review a document | the same for every machine-made row from one document (and, if ticked, the nativity values it set) |
| reject | the literature / notes / hosts row is deleted |
| clear flag | `flag` emptied |
| place | an unplaced name becomes a taxa.csv row; its line leaves review/unplaced.csv |
| exclude | a taxon in the tree: `hidden` (reason `excluded: ...`) on it and everything under it; the name goes on the Excluded page (unplaced.csv `status excluded`, with the reason, who and when). A bare unplaced name just becomes excluded. `match`, `sync` and `lit` never add an excluded name or its species again. **Restore** undoes it |
| merge an unplaced name | it becomes a synonym row (`IOG-n`, `accepted_id` = the valid taxon); its line leaves review/unplaced.csv. Later `sync`, `match` and `lit scan` find the name here and file its records under the valid taxon |
| delete | the `IOG-` row and the rows that point at it go |

**List cells** in the table (items separated by ` | `):
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
| `editor/assets/spec.js` | **generated** by `uv run guaminsects editor-spec` from schema.py and geo.py (tables, columns, enums, places); `tests/test_editor.py` fails when it is stale |
| `editor/assets/csv.js` | CSV exactly as Python's csv module writes it |
| `editor/assets/model.js` | the base tables + operations → the current state; checks (the JavaScript mirror of `dataset.check`); the files to commit. No DOM |
| `editor/assets/io.js` | loading and committing: GitHub API, the local server, File System Access, files |
| `editor/assets/ui.js` | the page |
| `src/guaminsects/editor.py` | the spec, and `guaminsects edit` (serves only `editor/` and the dataset tables it uses; commit + push) |
| `.github/workflows/rebuild.yml`, `ops/ci_rebuild.sh` | the rebuild after a push |

`tests/test_editor.py` runs the editor's own JavaScript in Chromium against the fixture world
and checks that **what the editor commits passes `dataset.check`, is already canonical
(Python writing the tables again changes no byte), and builds showing the edit**; that bad
edits are refused without a trace; that the local server commits, credits and pushes; and
that the whole page works from `file://`.

## The rebuild (CI)

`.github/workflows/rebuild.yml` runs on every push to `main` that touches the dataset, media,
code, editor or web app:

1. `uv sync`, Chromium, `guaminsects dataset check` and `pytest`.
2. Unless the Vercel secrets are missing (then it stops with a notice): `ops/ci_rebuild.sh`
   (dataset check, build, `check_site` in Chromium, Vercel CLI 65.4.0 with the token).

No snapshot and no restore: the repository is the whole input.

**Secrets** (repository settings → Secrets and variables → Actions): `VERCEL_TOKEN`
(vercel.com/account/tokens), `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` (from
`site.nosync/public/.vercel/project.json` on the data machine: `orgId`, `projectId`).

## Not yet

- The literature text is never published, so a reviewer cannot read the page a machine-read
  row came from in the editor; the citation and page are shown, and the PDF is on the data
  machine (and in whatever copy the reviewer has).
- Firefox: the page uses nothing Chromium/WebKit-specific except the optional folder
  picker, but Playwright's Firefox does not start on the development Mac (macOS 27), so it
  is untested there.
