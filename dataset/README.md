# The dataset

Generated from `src/guaminsects/schema.py` (`uv run guaminsects dataset readme`); do not edit.

UTF-8 with a BOM, `\n` line endings, minimal quoting, a header row, the column order below. Lists inside a cell are separated by ` | `. Rows are sorted (taxa depth-first), so writing a table twice gives identical bytes.

No PDF text appears anywhere here: `notes.note` is a paraphrase of at most 200 characters.


## `taxa.csv`: every taxon and every name (synonym rows follow their taxon)

Unique key: `id`

| column | kind | |
|---|---|---|
| `id` | id | required; the id in URLs (#/t/<id>); never reused |
| `parent_id` | id | a `taxa` key; accepted rows; empty only for the root |
| `accepted_id` | id | a `taxa` key; synonym rows: the taxon it is shown as |
| `rank` | str | required; one of Subphylum, Class, Order, Family, Genus, Species, Subspecies, Variety |
| `name` | str | required |
| `authorship` | str |  |
| `status` | str | required; one of accepted, synonym, doubtful, morphospecies |
| `common_name` | str | the English name shown |
| `other_common_names` | list | other English names, for search |
| `nativity` | str | one of native, introduced, unknown; accepted rows: required; native, introduced or unknown (Micronesia as a whole) |
| `nativity_source` | str | a doc_id, or 'editor'; empty for unknown |
| `nativity_review` | str | one of machine, editor; machine: set by a tool; editor: confirmed |
| `iucn` | str | IUCN category (Wikidata P141) |
| `superfamily` | str |  |
| `subfamily` | str |  |
| `tribe` | str |  |
| `in_col` | bool | required; yes/no: in the Catalogue of Life |
| `gbif_key` | int | the GBIF Backbone key where one matches |
| `name_match` | str | how the name was matched or merged |
| `match_note` | str |  |
| `name_sources` | str |  |
| `hidden` | bool |  |
| `hidden_reason` | str |  |
| `verified` | bool |  |
| `verified_by` | str |  |
| `verified_date` | date |  |
| `verification_source` | str |  |
| `flag` | str | one of new; new: added by a tool, not yet reviewed |
| `note` | str | shown on the page |
| `added_by` | str |  |
| `added` | date |  |
| `modified_by` | str |  |
| `modified` | date |  |

## `keys.csv`: source keys -> taxon

Unique key: `source`, `key`

| column | kind | |
|---|---|---|
| `source` | str | required; one of gbif, col, inat, literature, plazi, checklist |
| `key` | str | required; the key the source used |
| `name` | str |  |
| `taxon_id` | id | required; a `taxa` key |
| `how` | str | same, COL synonym, spelling variant, curated merge, ... |

## `names.csv`: other names, for search and the page

Unique key: `taxon_id`, `name`, `kind`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `name` | str | required |
| `kind` | str | required; one of gbif synonym, col synonym, english |
| `source` | str |  |

## `records.csv`: counts per taxon, island group and source

Unique key: `taxon_id`, `area`, `source`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `area` | str | required; one of GU, MP, PW, FM, MH |
| `source` | str | required; one of gbif, gbif_specimens, inat |
| `records` | int | required |
| `first_year` | int |  |
| `last_year` | int |  |
| `query_key` | str | the key(s) the count was asked under |
| `refreshed` | date |  |

## `islands.csv`: islands named per taxon, by source

Unique key: `taxon_id`, `area`, `island`, `source`, `doc_id`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `area` | str | required; one of GU, MP, PW, FM, MH |
| `island` | str | required |
| `source` | str | required; one of gbif, literature, editor |
| `records` | int |  |
| `doc_id` | str | a `documents` key |

## `documents.csv`: the bibliography

Unique key: `doc_id`

| column | kind | |
|---|---|---|
| `doc_id` | str | required; short and stable: iom-08-1, schreiner-1991, plazi-<key> |
| `file` | str | relative to literature/; empty for an online-only document |
| `title` | str | required |
| `authors` | str |  |
| `year` | int |  |
| `container` | str | journal or series |
| `volume` | str |  |
| `pages` | str |  |
| `doi` | str |  |
| `url` | url | public address; the site links here, never to the file |
| `licence` | str |  |
| `kind` | str | one of monograph, paper, fact sheet, checklist, dataset, report, map, other |
| `region` | bool | the title supports presence in Micronesia |
| `citation` | str | formatted |
| `added_by` | str |  |
| `added` | date |  |

## `literature.csv`: taxon x document

Unique key: `taxon_id`, `doc_id`, `kind`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `doc_id` | str | required; a `documents` key |
| `kind` | str | required; one of account, mention, checklist; account = a species section |
| `pages` | str | page numbers, ' | ' separated |
| `name_printed` | str |  |
| `areas` | list | one of GU, MP, PW, FM, MH; island groups the document records it from |
| `islands` | list |  |
| `status` | str | one of native, introduced, endemic, invasive, cryptogenic, unknown |
| `status_area` | list | one of GU, MP, PW, FM, MH |
| `first_record_year` | int |  |
| `status_page` | int | page of the status statement |
| `method` | str | one of text, ocr, plazi, checklist, manual |
| `review` | str | one of machine, editor; machine: read by a tool; editor: confirmed; empty: from a published checklist |
| `reviewed_by` | str |  |
| `reviewed` | date |  |
| `added_by` | str |  |
| `added` | date |  |

## `notes.csv`: short paraphrased notes

Unique key: `taxon_id`, `doc_id`, `topic`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `doc_id` | str | required; a `documents` key |
| `pages` | str |  |
| `topic` | str | one of biology, habitat, pest, distribution, identification |
| `note` | str | required; at most 200 characters; paraphrased, never a copied sentence |
| `review` | str | required; one of machine, editor |
| `written_by` | str | the Claude model, or an editor's name |
| `added` | date |  |

## `hosts.csv`: host plants

Unique key: `taxon_id`, `host`, `doc_id`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `host` | str | required |
| `doc_id` | str | a `documents` key |
| `pages` | str |  |
| `review` | str | one of machine, editor |

## `photos.csv`: the photos a page shows (an inherited row carries only the pointer)

Unique key: `taxon_id`, `position`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `position` | int | required |
| `photo_id` | str | required; inat:..., commons:..., gbif:... |
| `role` | str | required; one of own, inherited; inherited: the photo of a species below, shown on a group |
| `from_id` | id | a `taxa` key; inherited: the taxon whose photo it is |
| `source` | str | one of inaturalist, commons, gbif |
| `page_url` | url |  |
| `display_url` | url |  |
| `thumb` | str | file in media/thumbs |
| `thumb_url` | url | remote thumbnail |
| `width` | int |  |
| `height` | int |  |
| `licence` | str | one of cc0, cc-by, cc-by-sa, cc-by-nc, cc-by-nc-sa |
| `licence_url` | url |  |
| `attribution` | str |  |
| `rights_holder` | str |  |
| `retrieved` | date |  |

## `links.csv`: external pages

Unique key: `taxon_id`, `system`, `value`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `system` | str | required; one of inaturalist, wikidata, wikispecies, wikipedia, commons, bugguide, editor |
| `value` | str | required; an id or a URL |
| `label` | str |  |
| `confidence` | str | one of high, medium, review |
| `note` | str |  |
| `added_by` | str |  |
| `added` | date |  |

## `distribution.csv`: editors' distribution tags

Unique key: `taxon_id`, `place`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `place` | str | required; one of 80 values (geo.PLACES) |
| `status` | str | required; one of present, absent, doubtful |
| `source` | str | a free-text note or URL |
| `doc_id` | str | a `documents` key; the reference the record comes from (documents.csv) |
| `added_by` | str | required |
| `added` | date |  |

## `vouchers.csv`: editors' vouchers

Unique key: `taxon_id`, `kind`, `ref`

| column | kind | |
|---|---|---|
| `taxon_id` | id | required; a `taxa` key |
| `kind` | str | required; one of inat_observation, gbif_occurrence, photo_file, photo_url |
| `ref` | str | required |
| `note` | str |  |
| `licence` | str |  |
| `credit` | str |  |
| `added_by` | str | required |
| `added` | date |  |

## `review/unplaced.csv`: names with records that could not be placed, and names excluded

Unique key: `name`, `source`, `key`

| column | kind | |
|---|---|---|
| `name` | str | required |
| `rank` | str |  |
| `source` | str | one of gbif, inat, literature, checklist, plazi, editor, other |
| `key` | str |  |
| `records` | int |  |
| `note` | str | why it is unplaced, or why it is excluded |
| `status` | str | one of unplaced, excluded; empty/unplaced: waiting for a person; excluded: deliberately kept out (an extinct fossil, not a hexapod): never added by match, sync or lit |
| `added_by` | str |  |
| `added` | date |  |

## `wikipedia.jsonl`

One JSON object per line, sorted by taxon_id: `taxon_id`, `title`, `url`, `revid`, `rev_timestamp`, `retrieved`, `lead_only`, `html`. CC BY-SA text with its revision and retrieval date.
