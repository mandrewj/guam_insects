#!/usr/bin/env python3
"""Turn a folder of PDFs into per-page text, OCRing the pages that are scans.

    uv run python scripts/pdf_ingest.py extract pdfs/ -o data/pdf_text/
    uv run python scripts/pdf_ingest.py find data/pdf_text/ names.txt -o data/pdf_hits.jsonl

`extract` writes one JSONL per PDF (named by the PDF's sha256, so a renamed file is not redone):
    {"pdf": "Gressitt1952.pdf", "sha256": "...", "page": 12, "method": "text"|"ocr", "text": "..."}
A page with fewer than MIN_CHARS characters of embedded text is rendered at 300 dpi and OCRed with
tesseract. Needs `pdftotext`/`pdftoppm` (poppler) and `tesseract` on PATH (`brew install poppler
tesseract`). Old taxonomic papers OCR badly on italics and ligatures: keep the OCR text but treat
a name found only in OCR text as a *lead* until a person or a second source confirms it.

`find` scans that text for names from a file (one scientific name per line, e.g. the GBIF
checklist's canonical names, plus synonyms) and writes one hit per (name, pdf, page) with a
snippet, which is the unit the site cites ("Gressitt 1952, p. 12"). Matching is case-sensitive on
the genus initial ("O. rhinoceros" after the first mention is NOT matched here: the follow-up step
should resolve abbreviated binomials within a page against the page's full ones).
Not tested against your PDFs; the scan path was tested on one synthetic page only.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_CHARS = 200          # fewer embedded characters than this and the page is treated as a scan


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def page_count(pdf: Path) -> int:
    m = re.search(r"^Pages:\s+(\d+)", run(["pdfinfo", str(pdf)]), re.M)
    return int(m.group(1)) if m else 0


def page_text(pdf: Path, n: int) -> tuple[str, str]:
    text = run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(pdf), "-"]).strip()
    if len(text) >= MIN_CHARS:
        return text, "text"
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "p"
        subprocess.run(["pdftoppm", "-r", "300", "-f", str(n), "-l", str(n), "-png", str(pdf), str(stem)],
                       check=True, capture_output=True)
        png = next(Path(tmp).glob("p*.png"), None)
        if png is None:
            return text, "text"
        ocr = run(["tesseract", str(png), "-", "-l", "eng", "--psm", "1"]).strip()
    return (ocr, "ocr") if len(ocr) > len(text) else (text, "text")


def extract(src: Path, out: Path) -> int:
    for tool in ("pdftotext", "pdftoppm", "pdfinfo", "tesseract"):
        if not shutil.which(tool):
            print(f"missing {tool}: brew install poppler tesseract", file=sys.stderr)
            return 1
    out.mkdir(parents=True, exist_ok=True)
    pdfs = [src] if src.is_file() else sorted(src.rglob("*.pdf"))
    for pdf in pdfs:
        digest = sha256(pdf)
        target = out / f"{digest}.jsonl"
        if target.exists():
            continue
        tmp = target.with_suffix(".part")
        with tmp.open("w") as f:
            for n in range(1, page_count(pdf) + 1):
                text, method = page_text(pdf, n)
                f.write(json.dumps({"pdf": pdf.name, "sha256": digest, "page": n,
                                    "method": method, "text": text}) + "\n")
        tmp.rename(target)                     # a half-written file never looks finished
        print(f"{pdf.name}: done", file=sys.stderr)
    return 0


def find(text_dir: Path, names_file: Path, out: Path) -> int:
    names = sorted({n.strip() for n in names_file.read_text().splitlines() if n.strip()},
                   key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
    with out.open("w") as o:
        for jl in sorted(text_dir.glob("*.jsonl")):
            for line in jl.open():
                page = json.loads(line)
                seen = set()
                for m in pattern.finditer(page["text"]):
                    if m.group(1) in seen:
                        continue
                    seen.add(m.group(1))
                    s = max(0, m.start() - 120)
                    snippet = re.sub(r"\s+", " ", page["text"][s:m.end() + 240])
                    o.write(json.dumps({"name": m.group(1), "pdf": page["pdf"], "sha256": page["sha256"],
                                        "page": page["page"], "method": page["method"],
                                        "snippet": snippet}) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("src", type=Path)
    e.add_argument("-o", "--out", type=Path, default=Path("data/pdf_text"))
    f = sub.add_parser("find")
    f.add_argument("text_dir", type=Path)
    f.add_argument("names", type=Path)
    f.add_argument("-o", "--out", type=Path, default=Path("data/pdf_hits.jsonl"))
    a = ap.parse_args()
    return extract(a.src, a.out) if a.cmd == "extract" else find(a.text_dir, a.names, a.out)


if __name__ == "__main__":
    sys.exit(main())
