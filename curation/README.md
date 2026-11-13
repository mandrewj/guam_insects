# Hand curation

The site's tree is GBIF's backbone (taxa with records in Micronesia) **plus the edits in this
folder**. `uv run guaminsects resolve` applies them on every build, so a pipeline re-run never
loses them. Edit these files in a spreadsheet, a text editor, or (soon) the local admin page;
all three write the same files, and git keeps the history.

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
