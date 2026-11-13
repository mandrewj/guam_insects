"""Taxon ids: the external form (URLs, CSV files) and the internal integer (database, record
files, search index), convertible both ways without a lookup. webapp/assets/app.js has the
same two functions (tidOf / extOf); ops/check_site.py checks they agree.

    KVC9L       a Catalogue of Life taxon (COL ids: digits and capitals)  COL_BASE + base 36
    gbif:1045882 a GBIF Backbone key, for a name COL does not have         the key itself
    name-12     a name only a source used (literature, iNaturalist),      NAME_BASE + 12
                numbered in sources/names.csv
    IOG-3       a taxon the curator added by hand (curation/taxa.csv)     LOCAL_BASE + 3

The ranges do not overlap (GBIF keys are below 10^9), and everything stays below 2^53, so
JavaScript numbers hold them exactly.
"""

import re

COL_BASE = 10**11
NAME_BASE = 3 * 10**11
LOCAL_BASE = 5 * 10**11
_COL = re.compile(r"[0-9A-Z]{1,7}")
_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def from_col(col_id: str) -> int:
    if not _COL.fullmatch(col_id):
        raise ValueError(f"not a Catalogue of Life id: {col_id!r}")
    return COL_BASE + int(col_id, 36)


def col_of(i: int) -> str | None:
    if not COL_BASE <= i < NAME_BASE:
        return None
    n, out = i - COL_BASE, ""
    while True:
        n, d = divmod(n, 36)
        out = _DIGITS[d] + out
        if not n:
            return out


def to_ext(i: int) -> str:
    if i < COL_BASE:
        return f"gbif:{i}"
    if i < NAME_BASE:
        return col_of(i)
    if i < LOCAL_BASE:
        return f"name-{i - NAME_BASE}"
    return f"IOG-{i - LOCAL_BASE}"


def to_int(ext: str | int) -> int:
    """Any external id (or an internal one, unchanged) -> the internal integer."""
    if isinstance(ext, int):
        return ext
    s = ext.strip()
    if s.startswith("gbif:") and s[5:].isdigit():
        return int(s[5:])
    if s.startswith("name-") and s[5:].isdigit():
        return NAME_BASE + int(s[5:])
    if s.startswith("IOG-") and s[4:].isdigit():
        return LOCAL_BASE + int(s[4:])
    if s.isdigit() and len(s) > 7:             # an internal id written out
        return int(s)
    return from_col(s)


def valid(ext: str) -> bool:
    try:
        to_int(ext)
        return True
    except ValueError:
        return False


def kind(i: int) -> str:
    return ("gbif" if i < COL_BASE else "col" if i < NAME_BASE else
            "name" if i < LOCAL_BASE else "curated")
