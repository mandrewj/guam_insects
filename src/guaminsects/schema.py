"""Every table of the dataset (`dataset/`): columns, types, enums, references, sort keys.

This is the one declaration. `dataset.py` reads, checks and writes from it, the editor's
`spec.js` is generated from it, and `dataset/README.md` is generated from it, so the
documentation cannot drift. docs/REFACTOR.md describes the design.

Column kinds:
    str     free text (one line)            int     whole number         date  YYYY-MM-DD
    url     http(s) address                 bool    "yes" or empty       list  items joined by " | "
    id      a taxon id as the site shows it (KVC9L, gbif:1045882, name-12, IOG-3)
"""

from dataclasses import dataclass, field

from . import geo

SEP = " | "

RANKS = ["Subphylum", "Class", "Order", "Family", "Genus", "Species", "Subspecies"]
# Variety is in the Catalogue of Life data for a few taxa; it ranks with Subspecies.
RANK_ORDER = {"Subphylum": 0, "Class": 1, "Order": 2, "Family": 3, "Genus": 4, "Species": 5,
              "Subspecies": 6, "Variety": 6}
ALL_RANKS = RANKS + ["Variety"]
STATUSES = ["accepted", "synonym", "doubtful", "morphospecies"]
NATIVITY = ["native", "introduced", "unknown"]
REVIEW = ["machine", "editor"]
AREAS = ["GU", "MP", "PW", "FM", "MH"]
LICENCES = ["cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"]   # CLAUDE.md rule 3
PLACE_STATUS = ["present", "absent", "doubtful"]
DOC_KINDS = ["monograph", "paper", "fact sheet", "checklist", "dataset", "report", "map", "other"]
LIT_KINDS = ["account", "mention", "checklist"]
LIT_STATUS = ["native", "introduced", "endemic", "invasive", "cryptogenic", "unknown"]
LIT_METHODS = ["text", "ocr", "plazi", "checklist", "manual"]
NOTE_TOPICS = ["biology", "habitat", "pest", "distribution", "identification"]
RECORD_SOURCES = ["gbif", "gbif_specimens", "inat"]
ISLAND_SOURCES = ["gbif", "literature", "editor"]
LINK_SYSTEMS = ["inaturalist", "wikidata", "wikispecies", "bugguide", "editor"]
CONFIDENCE = ["high", "medium", "review"]
VOUCHER_KINDS = ["inat_observation", "gbif_occurrence", "photo_file", "photo_url"]
PHOTO_ROLES = ["own", "inherited"]
PHOTO_SOURCES = ["inaturalist", "commons", "gbif"]
UNPLACED_SOURCES = ["gbif", "inat", "literature", "checklist", "plazi", "other"]
KEY_SOURCES = ["gbif", "col", "inat", "literature", "plazi", "checklist"]
NOTE_MAX = 200


@dataclass(frozen=True)
class Col:
    name: str
    kind: str = "str"
    required: bool = False
    enum: tuple = ()
    ref: str = ""            # "taxa" | "documents": the value must be a key of that table
    maxlen: int = 0
    doc: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    file: str
    cols: tuple
    key: tuple               # unique columns
    title: str = ""
    sort: tuple = ()         # defaults to key

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.cols]


def C(name, kind="str", required=False, enum=(), ref="", maxlen=0, doc=""):
    return Col(name, kind, required, tuple(enum), ref, maxlen, doc)


_BY = [C("added_by", doc="who added it (a person or a tool)"), C("added", "date")]

TABLES: list[Table] = [
    Table("taxa", "taxa.csv", (
        C("id", "id", True, doc="the id in URLs (#/t/<id>); never reused"),
        C("parent_id", "id", ref="taxa", doc="accepted rows; empty only for the root"),
        C("accepted_id", "id", ref="taxa", doc="synonym rows: the taxon it is shown as"),
        C("rank", required=True, enum=ALL_RANKS),
        C("name", required=True), C("authorship"),
        C("status", required=True, enum=STATUSES),
        C("common_name", doc="the English name shown"),
        C("other_common_names", "list", doc="other English names, for search"),
        C("nativity", enum=NATIVITY,
          doc="accepted rows: required; native, introduced or unknown (Micronesia as a whole)"),
        C("nativity_source", doc="a doc_id, or 'editor'; empty for unknown"),
        C("nativity_review", enum=REVIEW, doc="machine: set by a tool; editor: confirmed"),
        C("iucn", doc="IUCN category (Wikidata P141)"),
        C("superfamily"), C("subfamily"), C("tribe"),
        C("in_col", "bool", True, doc="yes/no: in the Catalogue of Life"),
        C("gbif_key", "int", doc="the GBIF Backbone key where one matches"),
        C("name_match", doc="how the name was matched or merged"),
        C("match_note"), C("name_sources"),
        C("hidden", "bool"), C("hidden_reason"),
        C("verified", "bool"), C("verified_by"), C("verified_date", "date"),
        C("verification_source"),
        C("flag", enum=("new",), doc="new: added by a tool, not yet reviewed"),
        C("note", doc="shown on the page"),
        C("added_by"), C("added", "date"), C("modified_by"), C("modified", "date"),
    ), key=("id",), title="every taxon and every name (synonym rows follow their taxon)"),

    Table("keys", "keys.csv", (
        C("source", required=True, enum=KEY_SOURCES),
        C("key", required=True, doc="the key the source used"),
        C("name"),
        C("taxon_id", "id", True, ref="taxa"),
        C("how", doc="same, COL synonym, spelling variant, curated merge, ..."),
    ), key=("source", "key"), title="source keys -> taxon"),

    Table("names", "names.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("name", required=True),
        C("kind", required=True, enum=("gbif synonym", "col synonym", "english")),
        C("source"),
    ), key=("taxon_id", "name", "kind"), title="other names, for search and the page"),

    Table("records", "records.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("area", required=True, enum=AREAS),
        C("source", required=True, enum=RECORD_SOURCES),
        C("records", "int", True),
        C("first_year", "int"), C("last_year", "int"),
        C("query_key", doc="the key(s) the count was asked under"),
        C("refreshed", "date"),
    ), key=("taxon_id", "area", "source"), title="counts per taxon, island group and source"),

    Table("islands", "islands.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("area", required=True, enum=AREAS),
        C("island", required=True),
        C("source", required=True, enum=ISLAND_SOURCES),
        C("records", "int"),
        C("doc_id", ref="documents"),
    ), key=("taxon_id", "area", "island", "source", "doc_id"),
        title="islands named per taxon, by source"),

    Table("documents", "documents.csv", (
        C("doc_id", required=True, doc="short and stable: iom-08-1, schreiner-1991, plazi-<key>"),
        C("file", doc="relative to literature/; empty for an online-only document"),
        C("title", required=True), C("authors"), C("year", "int"),
        C("container", doc="journal or series"), C("volume"), C("pages"), C("doi"),
        C("url", "url", doc="public address; the site links here, never to the file"),
        C("licence"),
        C("kind", enum=DOC_KINDS),
        C("region", "bool", doc="the title supports presence in Micronesia"),
        C("citation", doc="formatted"),
        C("added_by"), C("added", "date"),
    ), key=("doc_id",), title="the bibliography"),

    Table("literature", "literature.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("doc_id", required=True, ref="documents"),
        C("kind", required=True, enum=LIT_KINDS, doc="account = a species section"),
        C("pages", doc="page numbers, ' | ' separated"),
        C("name_printed"),
        C("areas", "list", enum=AREAS, doc="island groups the document records it from"),
        C("islands", "list"),
        C("status", enum=LIT_STATUS), C("status_area", "list", enum=AREAS),
        C("first_record_year", "int"), C("status_page", "int", doc="page of the status statement"),
        C("method", enum=LIT_METHODS),
        C("review", enum=REVIEW, doc="machine: read by a tool; editor: confirmed; "
          "empty: from a published checklist"),
        C("reviewed_by"), C("reviewed", "date"),
        C("added_by"), C("added", "date"),
    ), key=("taxon_id", "doc_id", "kind"), title="taxon x document"),

    Table("notes", "notes.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("doc_id", required=True, ref="documents"),
        C("pages"),
        C("topic", enum=NOTE_TOPICS),
        C("note", required=True, maxlen=NOTE_MAX, doc="paraphrased, never a copied sentence"),
        C("review", enum=REVIEW, required=True),
        C("written_by", doc="the Claude model, or an editor's name"),
        C("added", "date"),
    ), key=("taxon_id", "doc_id", "topic"), title="short paraphrased notes"),

    Table("hosts", "hosts.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("host", required=True),
        C("doc_id", ref="documents"),
        C("pages"),
        C("review", enum=REVIEW),
    ), key=("taxon_id", "host", "doc_id"), title="host plants"),

    Table("photos", "photos.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("position", "int", True),
        C("photo_id", required=True, doc="inat:..., commons:..., gbif:..."),
        C("role", required=True, enum=PHOTO_ROLES,
          doc="inherited: the photo of a species below, shown on a group"),
        C("from_id", "id", ref="taxa", doc="inherited: the taxon whose photo it is"),
        C("source", enum=PHOTO_SOURCES),
        C("page_url", "url"), C("display_url", "url"),
        C("thumb", doc="file in media/thumbs"), C("thumb_url", "url", doc="remote thumbnail"),
        C("width", "int"), C("height", "int"),
        C("licence", enum=LICENCES), C("licence_url", "url"),
        C("attribution"), C("rights_holder"), C("retrieved", "date"),
    ), key=("taxon_id", "position"),
        title="the photos a page shows (an inherited row carries only the pointer)"),

    Table("links", "links.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("system", required=True, enum=LINK_SYSTEMS),
        C("value", required=True, doc="an id or a URL"),
        C("label"), C("confidence", enum=CONFIDENCE),
        C("note"), C("added_by"), C("added", "date"),
    ), key=("taxon_id", "system", "value"), title="external pages"),

    Table("distribution", "distribution.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("place", required=True, enum=sorted(geo.PLACES)),
        C("status", required=True, enum=PLACE_STATUS),
        C("source"), C("added_by", required=True), C("added", "date"),
    ), key=("taxon_id", "place"), title="editors' distribution tags"),

    Table("vouchers", "vouchers.csv", (
        C("taxon_id", "id", True, ref="taxa"),
        C("kind", required=True, enum=VOUCHER_KINDS),
        C("ref", required=True), C("note"),
        C("licence"), C("credit"),
        C("added_by", required=True), C("added", "date"),
    ), key=("taxon_id", "kind", "ref"), title="editors' vouchers"),

    Table("unplaced", "review/unplaced.csv", (
        C("name", required=True), C("rank"),
        C("source", enum=UNPLACED_SOURCES), C("key"),
        C("records", "int"), C("note"),
    ), key=("name", "source", "key"), title="names with records that could not be placed"),
]

BY_NAME = {t.name: t for t in TABLES}
WIKIPEDIA_FILE = "wikipedia.jsonl"
WIKIPEDIA_FIELDS = ["taxon_id", "title", "url", "revid", "rev_timestamp", "retrieved",
                    "lead_only", "html"]


def table(name: str) -> Table:
    return BY_NAME[name]


def readme() -> str:
    """dataset/README.md: generated, so it cannot drift from the code."""
    out = ["# The dataset\n",
           "Generated from `src/guaminsects/schema.py` (`uv run guaminsects dataset readme`); "
           "do not edit.\n",
           "UTF-8 with a BOM, `\\n` line endings, minimal quoting, a header row, the column "
           "order below. Lists inside a cell are separated by ` | `. Rows are sorted "
           "(taxa depth-first), so writing a table twice gives identical bytes.\n",
           "No PDF text appears anywhere here: `notes.note` is a paraphrase of at most "
           f"{NOTE_MAX} characters.\n"]
    for t in TABLES:
        out.append(f"\n## `{t.file}`: {t.title}\n")
        out.append("Unique key: " + ", ".join(f"`{k}`" for k in t.key) + "\n")
        out.append("| column | kind | |\n|---|---|---|")
        for c in t.cols:
            bits = []
            if c.required:
                bits.append("required")
            if c.enum:
                shown = [e for e in c.enum if e]
                bits.append("one of " + (", ".join(shown) if len(shown) < 12 else
                                         f"{len(shown)} values (geo.PLACES)"))
            if c.ref:
                bits.append(f"a `{c.ref}` key")
            if c.maxlen:
                bits.append(f"at most {c.maxlen} characters")
            if c.doc:
                bits.append(c.doc)
            out.append(f"| `{c.name}` | {c.kind} | {'; '.join(bits)} |")
    out.append(f"\n## `{WIKIPEDIA_FILE}`\n\nOne JSON object per line, sorted by taxon_id: "
               + ", ".join(f"`{f}`" for f in WIKIPEDIA_FIELDS)
               + ". CC BY-SA text with its revision and retrieval date.\n")
    return "\n".join(out)


@dataclass
class Problems:
    items: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def __bool__(self) -> bool:
        return bool(self.items)
