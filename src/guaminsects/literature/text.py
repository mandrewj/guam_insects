"""Per-page text for PDFs, OCRing only the pages that are scans.

Output is private.nosync/pdf_text/<sha256>.jsonl, one line per page:
    {"file": "Micronesica/Schreiner 1991 - ....pdf", "sha256": "...", "page": 12,
     "method": "text"|"ocr", "text": "..."}
Named by content hash, so renaming a PDF does not redo it. A page with fewer than MIN_CHARS
characters of embedded text is rendered at 300 dpi and OCRed with tesseract (the IOM scans
already carry Adobe Paper Capture text, so OCR is mostly for one-page fact sheets).

The text is copyrighted like the PDFs (CLAUDE.md rule 4): it stays in private.nosync/, is used
to find names and facts, and is never published.
"""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .. import config

TEXT_DIR = config.PRIVATE_DIR / "pdf_text"
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


def extract(pdf: Path, rel: str, out_dir: Path | None = None) -> tuple[str, int]:
    """Text of every page into <sha>.jsonl (skipped when it exists); returns (sha, OCR pages,
    -1 when already done)."""
    out_dir = out_dir or TEXT_DIR
    digest = sha256(pdf)
    target = out_dir / f"{digest}.jsonl"
    if target.exists():
        return digest, -1
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{digest[:6]}.part")
    ocr = 0
    with tmp.open("w") as f:
        for n in range(1, page_count(pdf) + 1):
            text, method = page_text(pdf, n)
            ocr += method == "ocr"
            f.write(json.dumps({"file": rel, "sha256": digest, "page": n, "method": method,
                                "text": text}) + "\n")
    tmp.rename(target)                     # a half-written file never looks finished
    return digest, ocr


def pages(digest: str, out_dir: Path | None = None):
    path = (out_dir or TEXT_DIR) / f"{digest}.jsonl"
    with path.open() as f:
        for line in f:
            yield json.loads(line)


def index(out_dir: Path | None = None) -> dict[str, dict]:
    """{path under literature/: {size, mtime, sha256}} for the PDFs read so far."""
    out_dir = out_dir or TEXT_DIR
    try:
        return json.loads((out_dir / "index.json").read_text())
    except (OSError, ValueError):
        return {}


def remember(rel: str, pdf: Path, digest: str, out_dir: Path | None = None) -> None:
    out_dir = out_dir or TEXT_DIR
    idx = index(out_dir)
    st = pdf.stat()
    idx[rel] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": digest}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(idx, indent=0))


def digest_of(rel: str, out_dir: Path | None = None) -> str | None:
    """The hash of a library file, whose text is extracted."""
    out_dir = out_dir or TEXT_DIR
    hit = index(out_dir).get(rel)
    return hit["sha256"] if hit and (out_dir / f"{hit['sha256']}.jsonl").exists() else None
