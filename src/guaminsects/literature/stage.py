"""The literature tool's four steps (`guaminsects lit ...`), driven by the /ingest-literature skill:

add     a directory of PDFs -> a copy in the library, their text (OCR where needed) in
        private.nosync/pdf_text/, a drafted row in documents.csv. Claude completes the
        citation (`lit pages` shows the first pages; `lit cite` writes the fields).
scan    the name finder over one document -> private.nosync/staging/lit-<doc_id>.json: one
        candidate per taxon and section with its pages, islands, status/year/host hints and the
        section's text (private: it never leaves the machine).
apply   what Claude decided after reading the candidates -> literature.csv, notes.csv,
        hosts.csv, islands.csv (all `review machine`), and nativity where a taxon's is still
        unknown. Nothing is quoted: a note is a paraphrase of at most 200 characters, and
        `dataset.check` rejects one that shares eight consecutive words with the document.

An apply file is JSON:

    {"doc_id": "...", "written_by": "claude-sonnet-5-5",
     "records": [{"taxon_id": "KVC9L", "kind": "account|mention", "pages": [4, 5],
                  "areas": ["GU"], "islands": ["Guam"], "status": "introduced",
                  "status_area": ["GU"], "status_page": 4, "first_record_year": 1984,
                  "method": "text|ocr", "name_printed": "Oryctes rhinoceros",
                  "hosts": ["coconut palm"],
                  "notes": [{"topic": "biology", "text": "...", "pages": "4"}]}],
     "new_names": [{"name": "Genus species", "rank": "species", ...the same fields...}]}

`new_names` are matched first (guaminsects match: COL, then flagged-new taxa inside a genus the
dataset or COL has); a record's `taxon_id` is then the match.
"""

import json
import re
import subprocess
import unicodedata
from pathlib import Path

from .. import config, geo, schema
from ..dataset import join
from . import finder, text

NATIVITY_OF = {"native": "native", "endemic": "native", "introduced": "introduced",
               "invasive": "introduced"}


class ApplyError(ValueError):
    pass


def slug(s: str, limit: int = 56) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:limit].strip("-")


def new_doc_id(ds, base: str) -> str:
    used = {d["doc_id"] for d in ds["documents"]}
    doc_id, n = base or "document", 2
    while doc_id in used:
        doc_id, n = f"{base}-{n}", n + 1
    return doc_id


def citation(r: dict) -> str:
    """'Linnavuori, R. 1960. Homoptera: Cicadellidae. Insects of Micronesia 6(5): 231-344.'"""
    head = ". ".join(x for x in (r["authors"].rstrip("."), r["year"]) if x)
    head += ". " if head else ""
    where = (r["container"] + (f" {r['volume']}" if r["volume"] else "") +
             (f": {r['pages']}" if r["pages"] else "")) if r["container"] else ""
    return f"{head}{r['title'].rstrip('.')}." + (f" {where}." if where else "")


# --- add --------------------------------------------------------------------------------------

def _title_of(pdf: Path) -> str:
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"^Title:\s+(.+)$", out, re.M)
        if m and len(m.group(1).strip()) > 5:
            return m.group(1).strip()
    except OSError:
        pass
    return pdf.stem


def add(ds, inbox: Path, today: str, library: Path | None = None, extract: bool = True,
        progress=print) -> list[dict]:
    """Each PDF in `inbox` not seen before (by content hash): copied into the library under
    its file name, text extracted, a documents.csv row drafted for Claude to complete."""
    library = library or config.LITERATURE_DIR
    known = {v["sha256"]: rel for rel, v in text.index().items()}
    done = []
    for pdf in sorted(inbox.rglob("*.pdf")):
        digest = text.sha256(pdf)
        if digest in known:
            progress(f"  already known: {pdf.name} ({known[digest]})")
            done.append({"file": known[digest], "doc_id": next(
                (d["doc_id"] for d in ds["documents"] if d["file"] == known[digest]), ""),
                "new": False})
            continue
        try:
            rel = str(pdf.relative_to(library))          # already in the library
            dest = pdf
        except ValueError:
            rel = f"{inbox.name}/{pdf.name}"
            dest = library / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(pdf.read_bytes())
        ocr = -1
        if extract:
            _, ocr = text.extract(dest, rel)
        text.remember(rel, dest, digest)
        yr = re.search(r"\b(1[89]\d\d|20[0-2]\d)\b", pdf.stem)
        row = {c: "" for c in schema.table("documents").names} | {
            "doc_id": new_doc_id(ds, slug(pdf.stem)), "file": rel, "title": _title_of(pdf),
            "year": yr.group(1) if yr else "", "kind": "paper", "added_by": "lit add",
            "added": today}
        row["citation"] = citation(row)
        ds["documents"].append(row)
        done.append({"file": rel, "doc_id": row["doc_id"], "new": True, "ocr_pages": ocr})
        progress(f"  added {row['doc_id']} ({rel})")
    return done


CITE_FIELDS = ["title", "authors", "year", "container", "volume", "pages", "doi", "url",
               "licence", "kind", "region"]


def cite(ds, doc_id: str, **fields) -> dict:
    """Set citation fields of a document and rewrite its formatted citation."""
    row = next((d for d in ds["documents"] if d["doc_id"] == doc_id), None)
    if row is None:
        raise ApplyError(f"no document {doc_id}")
    for k, v in fields.items():
        if k not in CITE_FIELDS:
            raise ApplyError(f"{k} is not a citation field ({', '.join(CITE_FIELDS)})")
        if v is not None:
            row[k] = str(v).strip()
    row["citation"] = citation(row)
    return row


def doc_pages(ds, doc_id: str) -> list[dict]:
    row = next((d for d in ds["documents"] if d["doc_id"] == doc_id), None)
    if row is None or not row["file"]:
        raise ApplyError(f"no library file for {doc_id}")
    digest = text.digest_of(row["file"])
    if not digest:
        raise ApplyError(f"the text of {row['file']} is not extracted here: run `lit add` on this machine")
    return list(text.pages(digest))


def text_of(ds):
    """doc_id -> the document's full text (or None), for the note-copying check."""
    files = {d["doc_id"]: d["file"] for d in ds["documents"] if d["file"]}
    cache: dict[str, str | None] = {}

    def get(doc_id: str) -> str | None:
        if doc_id not in cache:
            digest = text.digest_of(files.get(doc_id, ""))
            cache[doc_id] = " ".join(p["text"] for p in text.pages(digest)) if digest else None
        return cache[doc_id]

    return get


# --- scan -------------------------------------------------------------------------------------

def parse_pages(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    a, _, b = spec.partition("-")
    return int(a), int(b or a)


def scan(ds, doc_id: str, pages: tuple[int, int] | None = None, matcher=None) -> dict:
    doc = next((d for d in ds["documents"] if d["doc_id"] == doc_id), None)
    if doc is None:
        raise ApplyError(f"no document {doc_id}")
    allpages = doc_pages(ds, doc_id)
    if pages:
        allpages = [p for p in allpages if pages[0] <= p["page"] <= pages[1]]
    lex = finder.Lexicon(ds)
    found = finder.scan_pages(allpages, lex, in_region=doc["region"] == "yes")
    if matcher is not None:
        still = []
        for u in found["unmatched"]:
            rank = {1: "GENUS", 2: "SPECIES", 3: "SUBSPECIES"}.get(len(u["name"].split()), "SPECIES")
            tid = matcher.resolve(u["name"], rank, "literature", key=u["name"], origin="literature")
            if tid:
                found["candidates"].append({**u, "taxon_id": tid})
            else:
                still.append(u)
        found["unmatched"] = still
    return {"doc_id": doc_id, "citation": doc["citation"], "region": doc["region"] == "yes",
            "pages": [allpages[0]["page"], allpages[-1]["page"]] if allpages else [],
            "candidates": found["candidates"], "unmatched": found["unmatched"]}


def save_staging(staged: dict, doc_id: str) -> Path:
    path = config.STAGING_DIR / f"lit-{doc_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(staged, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# --- apply ------------------------------------------------------------------------------------

def island_area(name: str) -> str | None:
    for area, d in geo.ISLAND_COORDS.items():
        if name in d:
            return area
    return None


def apply(ds, spec: dict, today: str, matcher=None) -> dict:
    """Write an apply file's records into the dataset (in memory); the caller checks
    (`dataset.check`, with `text_of`) and writes."""
    doc_id = spec.get("doc_id", "")
    if not any(d["doc_id"] == doc_id for d in ds["documents"]):
        raise ApplyError(f"no document {doc_id!r} in documents.csv")
    by = spec.get("written_by") or "Claude"
    taxa = {r["id"]: r for r in ds["taxa"]}
    before = {r["id"] for r in ds["taxa"]}
    records = list(spec.get("records") or [])
    for n in spec.get("new_names") or []:
        if matcher is None:
            raise ApplyError("new_names need the matcher (network): run `lit apply` without --offline")
        rank = (n.get("rank") or "species").upper()
        tid = matcher.resolve(n["name"], rank, "literature", key=n["name"], origin="literature")
        if tid:
            records.append({**n, "taxon_id": tid})
        taxa = {r["id"]: r for r in ds["taxa"]}
    stats = {"records": 0, "notes": 0, "hosts": 0, "islands": 0, "nativity_set": 0, "skipped": []}
    litcols = schema.table("literature").names
    for r in records:
        tid = r.get("taxon_id")
        row = taxa.get(tid)
        if row is None:
            stats["skipped"].append(f"{tid}: not in taxa.csv")
            continue
        if row["status"] == "synonym":                  # a merged name: file it under its taxon
            tid = row["accepted_id"]
            row = taxa[tid]
        kind = r.get("kind") or "mention"
        pages = join(str(p) for p in sorted({int(p) for p in r.get("pages", [])}))
        new = {"taxon_id": tid, "doc_id": doc_id, "kind": kind, "pages": pages,
               "name_printed": r.get("name_printed", ""), "areas": join(r.get("areas", [])),
               "islands": join(r.get("islands", [])), "status": r.get("status", ""),
               "status_area": join(r.get("status_area", [])),
               "first_record_year": str(r["first_record_year"]) if r.get("first_record_year") else "",
               "status_page": str(r["status_page"]) if r.get("status_page") else "",
               "method": r.get("method") or "text", "review": "machine",
               "added_by": "ingest-literature", "added": today}
        existing = next((x for x in ds["literature"] if x["taxon_id"] == tid and
                         x["doc_id"] == doc_id and x["kind"] == kind), None)
        if existing and existing["review"] == "editor":
            stats["skipped"].append(f"{tid} {kind}: an editor confirmed that row; left as it is")
            continue
        if existing:
            existing.update({k: v for k, v in new.items() if v != ""})
        else:
            ds["literature"].append({c: new.get(c, "") for c in litcols})
        stats["records"] += 1
        for isl in r.get("islands", []):
            area = island_area(isl)
            if area and not any(i["taxon_id"] == tid and i["island"] == isl and
                                i["source"] == "literature" and i["doc_id"] == doc_id
                                for i in ds["islands"]):
                ds["islands"].append({"taxon_id": tid, "area": area, "island": isl,
                                      "source": "literature", "records": "", "doc_id": doc_id})
                stats["islands"] += 1
        for host in r.get("hosts", []):
            if not any(h["taxon_id"] == tid and h["host"] == host and h["doc_id"] == doc_id
                       for h in ds["hosts"]):
                ds["hosts"].append({"taxon_id": tid, "host": host, "doc_id": doc_id,
                                    "pages": pages, "review": "machine"})
                stats["hosts"] += 1
        for n in r.get("notes", []):
            nrow = {"taxon_id": tid, "doc_id": doc_id, "pages": str(n.get("pages", pages)),
                    "topic": n.get("topic", "biology"), "note": " ".join(n["text"].split()),
                    "review": "machine", "written_by": by, "added": today}
            old = next((x for x in ds["notes"] if x["taxon_id"] == tid and x["doc_id"] == doc_id
                        and x["topic"] == nrow["topic"]), None)
            if old and old["review"] == "editor":
                continue
            if old:
                old.update(nrow)
            else:
                ds["notes"].append({c: nrow.get(c, "") for c in schema.table("notes").names})
            stats["notes"] += 1
        nat = NATIVITY_OF.get(r.get("status") or "")
        if nat and row["nativity"] == "unknown":
            # a person's value is never overwritten; only an unassessed taxon takes a statement
            row["nativity"], row["nativity_source"], row["nativity_review"] = nat, doc_id, "machine"
            stats["nativity_set"] += 1
    stats["new_taxa"] = len({r["id"] for r in ds["taxa"]} - before)
    return stats

