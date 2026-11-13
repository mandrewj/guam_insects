"""Per-page text for every PDF in literature/, OCRing only the pages that are scans.

Ported from scripts/pdf_ingest.py. Output is data/pdf_text/<sha256>.jsonl, one line per page:
    {"file": "insects of micronesia/IOM 6-5 Cicadellidae.pdf", "sha256": "...", "page": 12,
     "method": "text"|"ocr", "text": "..."}
Named by content hash, so renaming a PDF does not redo it. A page with fewer than MIN_CHARS
characters of embedded text is rendered at 300 dpi and OCRed with tesseract. The IOM scans
already carry Adobe Paper Capture text, so OCR is mostly for the one-page UOG pest sheets.

The text is copyrighted like the PDFs (CLAUDE.md rule 4): it stays in data/, is used to find
names and facts, and is never published.
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import config

TEXT_DIR = config.DATA_DIR / "pdf_text"
MIN_CHARS = 200


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def page_count(pdf: Path) -> int:
    m = re.search(r"^Pages:\s+(\d+)", _run(["pdfinfo", str(pdf)]), re.M)
    return int(m.group(1)) if m else 0


def page_text(pdf: Path, n: int) -> tuple[str, str]:
    text = _run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(pdf), "-"]).strip()
    if len(text) >= MIN_CHARS:
        return text, "text"
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "p"
        subprocess.run(["pdftoppm", "-r", "300", "-f", str(n), "-l", str(n), "-png", str(pdf),
                        str(stem)], check=True, capture_output=True)
        png = next(Path(tmp).glob("p*.png"), None)
        if png is None:
            return text, "text"
        ocr = _run(["tesseract", str(png), "-", "-l", "eng", "--psm", "1"]).strip()
    return (ocr, "ocr") if len(ocr) > len(text) else (text, "text")


def extract_one(pdf: Path, out_dir: Path = TEXT_DIR) -> tuple[str, str, int]:
    digest = sha256(pdf)
    target = out_dir / f"{digest}.jsonl"
    if target.exists():
        return str(pdf), digest, -1
    rel = str(pdf.relative_to(config.LITERATURE_DIR))
    tmp = target.with_suffix(f".{digest[:6]}.part")
    ocr = 0
    with tmp.open("w") as f:
        for n in range(1, page_count(pdf) + 1):
            text, method = page_text(pdf, n)
            ocr += method == "ocr"
            f.write(json.dumps({"file": rel, "sha256": digest, "page": n, "method": method,
                                "text": text}) + "\n")
    tmp.rename(target)                     # a half-written file never looks finished
    return str(pdf), digest, ocr


def extract_all(workers: int = 4) -> int:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(config.LITERATURE_DIR.rglob("*.pdf"))
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(extract_one, p) for p in pdfs]
        for fut in as_completed(futures):
            try:
                path, _, ocr = fut.result()
            except Exception as e:           # a broken PDF must not stop the rest
                print(f"  failed: {e}", file=sys.stderr)
                continue
            done += 1
            if ocr >= 0:
                print(f"  [{done}/{len(pdfs)}] {Path(path).name}: {ocr} OCR page(s)",
                      file=sys.stderr)
    return done


def current() -> dict[str, str]:
    """{path under literature/: sha256} for the PDFs there now, whose text is extracted.

    The path inside a .jsonl is where the file was when it was read; files get moved and
    renamed, so the scans go through this instead. Hashes are cached by size and mtime in
    data/pdf_text/index.json, so only new or changed files are read."""
    index_path = TEXT_DIR / "index.json"
    try:
        cache = json.loads(index_path.read_text())
    except (OSError, ValueError):
        cache = {}
    out, fresh = {}, {}
    for pdf in sorted(config.LITERATURE_DIR.rglob("*.pdf")):
        rel = str(pdf.relative_to(config.LITERATURE_DIR))
        st = pdf.stat()
        hit = cache.get(rel)
        digest = hit["sha256"] if hit and hit["size"] == st.st_size and \
            hit["mtime"] == st.st_mtime else sha256(pdf)
        fresh[rel] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": digest}
        if (TEXT_DIR / f"{digest}.jsonl").exists():
            out[rel] = digest
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(fresh, indent=0))
    return out


def pages(digest: str):
    path = TEXT_DIR / f"{digest}.jsonl"
    with path.open() as f:
        for line in f:
            yield json.loads(line)
