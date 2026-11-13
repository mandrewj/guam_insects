# Hand curation

The site's tree is GBIF's backbone (taxa with records in Micronesia) **plus the edits in this
folder**. `uv run guaminsects resolve` applies them on every build, so a pipeline re-run never
loses them. Edit these files in a spreadsheet, a text editor, the local admin page, or through
`taxonomy.csv` (below); all of them end up here, and git keeps the history.

## `taxa.csv`: one row per taxon you touched

| column | meaning |
|---|---|
| `taxon_id` | A GBIF key to **change** that taxon. **Blank** to **add** a new one: it gets an id (900000002, 900000003, ...) on the next `resolve`, written back here. Never reuse or renumber an id: it is the taxon's URL. |
| `rank` | Subphylum, Class, Order, Suborder, Superfamily, Family, Subfamily, Tribe, Genus, Subgenus, Species, Subspecies |
| `name` | Scientific name as displayed. For a morphospecies, something like `Oryctes sp. GU-1`. |
| `authorship` | "Linnaeus, 1758" |
| `parent_id` / `parent_name` | Where it hangs. `parent_name` is enough when the name is unique; `parent_id` wins when both are given. |
| `status` | `accepted`, `synonym` (then `accepted_id` is required), `doubtful`, `morphospecies` |
| `common_name` | English common name |
| `establishment` | `native`, `endemic`, `introduced`, `invasive`, `unknown` |
| `hidden` | `1` hides the taxon and everything under it (nothing is deleted) |
| `verified` | `1`: an editor confirmed the taxon is in Micronesia ("editor confirmed" in `taxonomy.csv`) |
| `note` | Shown on the taxon page |
| `editor`, `edited`, `reason`, `citation` | Who, when (YYYY-MM-DD), why, and the source for the change |

For a GBIF taxon, a blank cell means "keep GBIF's value". `resolve` checks every row and
lists all the problems at once (unknown rank, a parent that is not in the tree, a cycle,
duplicate ids) without changing anything until they are fixed.

Examples:

```csv
taxon_id,rank,name,authorship,parent_id,parent_name,status,accepted_id,common_name,establishment,hidden,note,editor,edited,reason,citation
4995642,,,,,,,,coconut rhinoceros beetle,invasive,,,MAJ,2026-11-14,,Moore et al. 2018
,Species,Oryctes sp. GU-1,,,Oryctes,morphospecies,,,,,Larger than O. rhinoceros; Ritidian.,MAJ,2026-11-14,new morphospecies,
```

## `evidence.csv`: what supports a taxon

One row per piece of evidence. Several rows with the same `taxon_id` make a set.

| `kind` | `ref` | notes |
|---|---|---|
| `inat_observation` | observation id (`123456789`) | photos and locality come from iNaturalist; only CC-licensed photos are shown |
| `gbif_occurrence` | occurrence key | a specimen or record on GBIF |
| `photo_file` | path under `data/curated_photos/` | your own photo; `license` (e.g. `cc-by`) and `credit` are required |
| `photo_url` | a URL | someone else's openly licensed photo; `license` and `credit` required |

Allowed licences: `cc0`, `cc-by`, `cc-by-sa`, `cc-by-nc`, `cc-by-nc-sa`.

## `taxonomy.csv`: the whole taxonomy, one row per taxon

At the top of the project folder. Every `guaminsects build` (and `guaminsects taxonomy`)
rewrites it from the tree, so it is always current; it is the same table the site's
"Download taxonomy" box gives, for the whole tree or for one taxon and everything under it.
It opens in Excel or Numbers (UTF-8 with a BOM). Rows run depth first, children by name.

**Editing it.** Change cells in the editable columns, or add a row with a blank `taxonID`,
save it as CSV, then build (or run `uv run guaminsects taxonomy`). The build compares the file
with the copy it last wrote (`data.nosync/taxonomy.last.csv`), turns each changed cell into a
`curation/taxa.csv` row (editor: your git name, or `GUAMINSECTS_EDITOR`), and only then
rewrites the file. A change that would break the tree (a cycle, an unknown parent) stops the
build with the list of problems, and nothing is saved. Changes to computed columns are
counted and ignored. A downloaded copy goes back in with `uv run guaminsects import <file>`
(`--dry-run` to see the changes first); it is compared with the current tree. To remove a
taxon set `hidden` to 1. Deleting a row does nothing. A blank cell on a GBIF taxon means "GBIF's value",
so blanking a cell does not clear it.

| column | Darwin Core | editable | meaning |
|---|---|---|---|
| `taxonID` | taxonID | (blank = new) | GBIF key, or 900000001+ for a hand-added taxon; the page URL is `#/t/<taxonID>` |
| `parentNameUsageID`, `parentNameUsage` | yes | yes | the parent, by id or by name (the id wins if both change) |
| `acceptedNameUsageID`, `acceptedNameUsage` | yes | id only | for a synonym, its accepted name |
| `scientificName` | yes | yes | the name without authorship |
| `scientificNameAuthorship` | yes | yes | "(Linnaeus, 1758)" |
| `taxonRank` | yes | yes | Subphylum … Species, Subspecies |
| `taxonomicStatus` | yes | yes | accepted, synonym, doubtful, morphospecies |
| `vernacularName` | yes | yes | English common name |
| `kingdom` … `genus` | yes | no | the classification; **`family` is filled on every row at or below family** |
| `establishmentMeans` | yes | yes | native, endemic, introduced, invasive, unknown (curated, else a machine-read statement) |
| `recordedIn` | | no | island groups with any record: GU, MP, PW, FM, MH (Guam first) |
| `islands` | | no | islands named in records (genus and below) |
| `verificationStatus` | | see below | the best evidence for the taxon or anything under it |
| `verifiedBy`, `verifiedDate` | | no | who confirmed it, when (from `curation/taxa.csv`) |
| `verificationSource` | | yes | the source for an editor's confirmation |
| `literatureRecords`, `literatureSources` | | no | documents naming the taxon: checklists, species accounts, fact sheets (citation, pages) |
| `specimenRecords` | | no | GBIF preserved specimens and material samples in Micronesia |
| `gbifRecords`, `inatObservations` | | no | all GBIF records; iNaturalist research-grade observations |
| `nameAccordingTo`, `references` | yes | no | GBIF Backbone Taxonomy or this site's curator; the GBIF page |
| `taxonRemarks` | yes | yes | note shown on the taxon page |
| `hidden`, `curatedFields` | | hidden only | 1 = hidden from the site; which fields were set by hand |

Lists inside a cell are separated by ` | `.

**verificationStatus**, highest first (a genus or family takes the best of anything under it):

1. `editor confirmed`: a curator confirmed it (set this value in the file, or `verified` = 1 here).
   Setting any other value on a confirmed taxon removes the confirmation.
2. `literature records`: a checklist or species account places it in Micronesia (Plazi's
   digitised checklists, the crop pest list, the PDF library's species accounts; the last
   are machine-read until reviewed in `pdf_decisions.csv`).
3. `specimen records`: a preserved specimen or material sample on GBIF (`guaminsects specimens`).
4. `unconfirmed`: observations only (GBIF observations, iNaturalist).

Levels 2 to 4 follow from the sources and cannot be set by hand.
