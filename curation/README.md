# Hand curation

The site's tree is the **Catalogue of Life** (COL eXtended Release, through GBIF), restricted
to taxa with records in Micronesia, **plus the names COL lacks** that a record has (flagged),
**plus the edits in this folder**. `uv run guaminsects resolve` applies them on every build,
so a pipeline re-run never loses them. Edit these files in a spreadsheet, a text editor, or
through `taxonomy.csv` (below); all of them end up here, and git keeps
the history.

## Ids

Every taxon and every name has one id, the one in its page URL (`#/t/<id>`):

| id | what |
|---|---|
| `KVC9L` | a Catalogue of Life taxon (digits and capitals) |
| `gbif:1045882` | a GBIF Backbone name: a taxon COL lacks, or a name merged into a COL taxon |
| `name-12` | a name only a source used (iNaturalist, a literature heading), numbered in `sources/names.csv` |
| `IOG-3` | a taxon you added here |

## `taxa.csv`: one row per taxon you touched

| column | meaning |
|---|---|
| `taxon_id` | The id of the taxon (or name) to **change**. **Blank** to **add** a new one: it gets `IOG-1`, `IOG-2`, ... on the next `resolve`, written back here. Never reuse or renumber an id: it is the taxon's URL. |
| `rank` | Subphylum, Class, Order, Family, Genus, Species, Subspecies (the ranks the site shows) |
| `name` | Scientific name as displayed. For a morphospecies, something like `Oryctes sp. GU-1`. |
| `authorship` | "Linnaeus, 1758" |
| `parent_id` / `parent_name` | Where it hangs. `parent_name` is enough when the name is unique; `parent_id` wins when both are given. |
| `status` | `accepted`, `synonym` (with `accepted_id`: **merge** it into that taxon, shown as one), `doubtful`, `morphospecies`. `accepted` on a merged name **splits** it out as its own taxon (give `parent_id`). |
| `accepted_id` | For `synonym`: the taxon it is the same as |
| `common_name` | English common name |
| `establishment` | `native`, `endemic`, `introduced`, `invasive`, `unknown` |
| `hidden` | `1` hides the taxon and everything under it (nothing is deleted) |
| `verified` | `1`: an editor confirmed the taxon is in Micronesia ("editor confirmed" in `taxonomy.csv`) |
| `note` | Shown on the taxon page |
| `editor`, `edited`, `reason`, `citation` | Who, when (YYYY-MM-DD), why, and the source for the change |

For a taxon from COL (or a source), a blank cell means "keep the source's value". `resolve`
checks every row and lists all the problems at once (unknown rank, a parent that is not in
the tree, a cycle, duplicate ids) without changing anything until they are fixed.

Examples:

```csv
taxon_id,rank,name,authorship,parent_id,parent_name,status,accepted_id,common_name,establishment,hidden,verified,note,editor,edited,reason,citation
4CGSL,,,,,,,,globe skimmer,,,1,,MAJ,2026-11-14,,Buden 2004
KVR6P,,,,,,synonym,KV3JN,,,,,,MAJ,2026-11-13,records labelled Rhipiceridae are Callirhipis,Zimmerman 1942
name-3,,,,KVC9L,,accepted,,,,,,,MAJ,2026-11-14,a different species after all,
,Species,Oryctes sp. GU-1,,,Oryctes,morphospecies,,,,,,Larger than O. rhinoceros; Ritidian.,MAJ,2026-11-14,new morphospecies,
```

## How names are matched (and merged)

`guaminsects match` puts every name a source used on COL (`name_matches`):

- **the same name**, or a **COL synonym** (an old combination: *Icerya pattersoni* is shown as
  *Gigantococcus pattersoni*): the COL taxon;
- a **spelling variant** COL recognises (*Gonocephalum adpressiformis*), or a near spelling in
  the same genus: the COL taxon, with a note;
- a near spelling in **another genus**: held for review, shown as its own taxon;
- **not in COL** (*Callirhipis onoi*): added under the COL genus (or the source's own genus,
  itself added if COL lacks it), flagged "not in the Catalogue of Life".

Two names COL lacks under the same parent that differ by one letter or a gender ending are
merged, with a note. Every merged name is a row in `taxonomy.csv` and listed on the taxon's
page under "Names merged here". `ops/review.py` lists the merges, the names held for review,
names that could not be placed, and families with family-level records only.

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

Each accepted taxon is followed by its **other names** (rows with `taxonomicStatus`
synonym): COL synonyms, spelling variants and duplicate entries the sources used, with how
they were matched. The site shows them as one taxon.

**Editing it.** Change cells in the editable columns, or add a row with a blank `taxonID`,
save it as CSV, then build (or run `uv run guaminsects taxonomy`). The build compares the file
with the copy it last wrote (`data.nosync/taxonomy.last.csv`), turns each changed cell into a
`curation/taxa.csv` row (editor: your git name, or `GUAMINSECTS_EDITOR`), and only then
rewrites the file. A change that would break the tree (a cycle, an unknown parent) stops the
build with the list of problems, and nothing is saved. Changes to computed columns are
counted and ignored. A downloaded copy goes back in with `uv run guaminsects import <file>`
(`--dry-run` to see the changes first); it is compared with the current tree. To remove a
taxon set `hidden` to 1. Deleting a row does nothing. A blank cell means "the source's value",
so blanking a cell does not clear it.

- **Merge** two taxa: put the id of the one to keep in the other's `acceptedNameUsageID`.
- **Split** a merged name out: set its `taxonomicStatus` to `accepted` (and a
  `parentNameUsageID`, else it goes under its accepted taxon's parent).

| column | Darwin Core | editable | meaning |
|---|---|---|---|
| `taxonID` | yes | (blank = new) | the id (see Ids above); the page URL is `#/t/<taxonID>` |
| `parentNameUsageID`, `parentNameUsage` | yes | yes | the parent, by id or by name (the id wins if both change) |
| `acceptedNameUsageID`, `acceptedNameUsage` | yes | id only | for a synonym row, the taxon it is shown as |
| `scientificName` | yes | yes | the name without authorship |
| `scientificNameAuthorship` | yes | yes | "(Linnaeus, 1758)" |
| `taxonRank` | yes | yes | Subphylum … Species, Subspecies |
| `taxonomicStatus` | yes | yes | accepted, synonym, doubtful, morphospecies |
| `vernacularName` | yes | yes | English common name |
| `kingdom` … `genus` | yes | no | the classification, with COL's `superfamily`, `subfamily` and `tribe`; **`family` is filled on every row at or below family** |
| `establishmentMeans` | yes | yes | native, endemic, introduced, invasive, unknown (curated, else a machine-read statement) |
| `recordedIn` | | no | island groups with any record: GU, MP, PW, FM, MH (Guam first) |
| `islands` | | no | islands named in records (genus and below) |
| `inCatalogueOfLife` | | no | yes, or no for a name COL lacks |
| `nameMatch`, `matchRemarks` | | no | how the name was matched (Catalogue of Life, not in COL, COL synonym, spelling variant, same name, curated merge) and the note |
| `nameSources` | | no | for a synonym row: the sources that used the name |
| `verificationStatus` | | see below | the best evidence for the taxon or anything under it |
| `verificationRemarks` | | no | "literature records machine-read only", or "from taxa under it" |
| `verifiedBy`, `verifiedDate` | | no | who confirmed it, when (from `curation/taxa.csv`) |
| `verificationSource` | | yes | the source for an editor's confirmation |
| `literatureRecords`, `literatureSources` | | no | documents naming the taxon (citation, pages); **`[machine-read]`** marks citations the PDF name finder made that no person has checked |
| `specimenRecords` | | no | GBIF preserved specimens and material samples in Micronesia |
| `gbifRecords`, `inatObservations` | | no | all GBIF records; iNaturalist research-grade observations |
| `nameAccordingTo`, `references` | yes | no | Catalogue of Life (or GBIF Backbone / source name / curator); the COL or GBIF page |
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
