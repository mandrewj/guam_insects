---
name: ingest-literature
description: Add a directory of PDFs (papers, fact sheets, monograph parts) to the Insects of Guam dataset - names, pages, islands, native/introduced status, host plants, first-record years and short paraphrased notes - then commit and push. Data machine only (needs the PDFs, poppler and tesseract). Use when the user says /ingest-literature <directory> or asks to add literature.
---

# /ingest-literature `<directory>`

Run on the data machine only, from the repository root, with `uv run guaminsects ...`. You do the
reading; the commands do everything deterministic. The records go in flagged **machine-read**
(notes **machine-written**) with no approval step; a person confirms them later in the editor.

## Rules that never bend

- **The PDFs are in copyright** (CLAUDE.md rule 4). Nothing quoted goes into `dataset/`: a note is
  your own paraphrase, at most 200 characters, never a copied sentence (`dataset check` rejects a
  note that shares eight consecutive words with the document). The text and staging files stay in
  `private.nosync/`. Never commit, upload or paste a PDF or its text anywhere (including an Artifact).
- Never overwrite what a person decided: `lit apply` leaves rows with `review editor` and an
  editor's nativity alone. Do not edit `dataset/*.csv` by hand to get around that.
- One machine at a time: `git pull` first, commit and push when done.
- Polite APIs only (matching asks GBIF); check `ps` for `entobase` jobs before a long run.

## Steps

1. **Add.** `uv run guaminsects lit add <directory>`. Each new PDF (by content hash) is copied into
   `literature/`, its text extracted (OCR where a page is a scan) and a row drafted in
   `dataset/documents.csv`. It prints each `doc_id`.
2. **Complete the citation.** For each new document read the first pages:
   `uv run guaminsects lit pages <doc_id> --pages 1-3`. Then
   `uv run guaminsects lit cite <doc_id> --authors "Surname, I." --year 1991 --title "..." --container "Micronesica" --volume 24 --cite-pages 1-12 --doi ... --url <public URL> --kind paper|monograph|fact\ sheet|report --region yes|no`.
   `--region yes` only if the title supports presence in Micronesia (Guam, the Marianas, Palau,
   FSM, Marshalls); it decides whether islands named in the text count. Ask the user only when the
   document does not say (authors, year) and you cannot tell. The `--url` is where the document is
   public (a publisher or repository page), never the file.
3. **Scan.** `uv run guaminsects lit scan <doc_id>` (add `--pages 100-180` for a part of a large
   monograph; do monographs in batches so you read species accounts, not whole volumes; add
   `--match` to let it match unknown heading names to the Catalogue of Life, which needs the
   network). It writes `private.nosync/staging/lit-<doc_id>.json` and prints counts. Read that file:
   each candidate has the taxon, `kind` (`account` = a species section, `mention` = in passing),
   pages, areas/islands the finder saw, hints (status words, years, host-like phrases) and the
   section text (private).
4. **Read the candidates** (accounts first; mentions in passing get a literature row and **no** note),
   and write an apply file `private.nosync/staging/lit-<doc_id>-apply.json`:

   ```json
   {"doc_id": "...", "written_by": "<your model id>",
    "records": [{"taxon_id": "KVC9L", "kind": "account", "pages": [4, 5],
                 "areas": ["GU"], "islands": ["Guam", "Rota"],
                 "status": "introduced", "status_area": ["GU"], "status_page": 4,
                 "first_record_year": 1984, "method": "text", "name_printed": "Oryctes rhinoceros",
                 "hosts": ["coconut palm"],
                 "notes": [{"topic": "biology", "text": "<= 200 characters, paraphrased", "pages": "4"}]}],
    "new_names": [{"name": "Genus species", "rank": "species", "kind": "account", "pages": [9],
                   "areas": ["PW"], "islands": ["Koror"]}]}
   ```
   - `areas`: GU MP PW FM MH, only those the document records the taxon from (regional documents).
     `islands`: names from `geo.ISLAND_COORDS`. Correct the finder where the section says otherwise
     (a different island, a locality in another country).
   - `status`: only a clear statement that the species is native, introduced (adventive, established,
     invasive), endemic, cryptogenic in Micronesia or an island group. `status_area` is where it
     applies. No statement, no status. Never infer from the species' reputation.
   - `notes`: one per topic (biology, habitat, pest, distribution, identification), what the account
     says in your words. Skip taxonomy-only text.
   - A name the finder could not match is in `unmatched`; a plausible real name goes in `new_names`
     (it is matched to COL, or added under its genus flagged `new`); noise (OCR splits, prose) is
     dropped.
5. **Apply.** `uv run guaminsects lit apply private.nosync/staging/lit-<doc_id>-apply.json --dry-run`
   first, then without `--dry-run`. It validates (schema, references, the eight-word copy check
   against the text, the 200-character limit), writes `literature.csv`, `notes.csv`, `hosts.csv`,
   `islands.csv` (all `review machine`), sets a taxon's nativity only while it is `unknown`
   (`nativity_review machine`, source the document), then runs `dataset check`. Fix what it reports
   and rerun; it is idempotent.
6. **Report and commit.** Tell the user: the document, records written, new taxa, unplaced names
   (`dataset/review/unplaced.csv`), notes written, nativity values set, anything skipped.
   Then `uv run guaminsects dataset check && uv run pytest -q`, and commit **only** `dataset/`
   (and `media/` if photos changed) with
   `Literature: <short citation>: <n> records, <n> new taxa, <n> notes` and the trailer
   from the session's attribution reminder, then `git push`. The push rebuilds and redeploys the
   site; the records show as machine-read until someone confirms them in the editor.

A first run on a new kind of document: do one short fact sheet and show the user the staged
candidates and the apply file before applying; then a monograph.
