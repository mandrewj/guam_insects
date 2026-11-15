"""GBIF's occurrence density map as data: one species -> a coarse world grid.

The Maps API serves vector tiles; at zoom 0 in EPSG:4326 the world is two tiles (west and
east halves, 180 x 180 degrees each) and `bin=square&squareSize=64` cuts each into 64 x 64
cells, so a cell is 2.8125 degrees and the world is 128 x 64 cells, row 0 at 90 N. Only the
cells with records matter: a species is a short list of (column, row, count). The tiles are
a few kB each, so two requests per species (cached in private.nosync/api/)."""

from . import gbif as gbifapi

MAPS = "https://api.gbif.org/v2/map/occurrence/density"
CELLS = 64                 # per tile side
COLS, ROWS = 128, 64       # the whole grid
DEG = 180 / CELLS          # 2.8125


def _varint(b: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        if c < 0x80:
            return n, i
        shift += 7


def _fields(b: bytes):
    """(field number, wire type, value) for a protobuf message: a varint, or a byte string."""
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif w == 1:
            v, i = b[i:i + 8], i + 8
        elif w == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"protobuf wire type {w}")
        yield f, w, v


def _packed(b: bytes) -> list[int]:
    out, i = [], 0
    while i < len(b):
        n, i = _varint(b, i)
        out.append(n)
    return out


def _zig(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def decode(tile: bytes) -> list[tuple[int, int, int]]:
    """A Mapbox vector tile of density squares -> [(column, row, records)] inside the tile."""
    cells: list[tuple[int, int, int]] = []
    for f, _, layer in _fields(tile):
        if f != 3:
            continue
        keys: list[str] = []
        values: list[int] = []
        feats: list[bytes] = []
        extent = 4096
        for lf, _, v in _fields(layer):
            if lf == 3:
                keys.append(v.decode())
            elif lf == 4:
                n = 0
                for vf, _, x in _fields(v):      # 4 int, 5 uint, 6 sint, 7 bool
                    if vf in (4, 5, 6, 7):
                        n = _zig(x) if vf == 6 else x
                values.append(n)
            elif lf == 2:
                feats.append(v)
            elif lf == 5:
                extent = v
        unit = extent / CELLS
        for feat in feats:
            tags: list[int] = []
            geom: list[int] = []
            for ff, _, v in _fields(feat):
                if ff == 2:
                    tags = _packed(v)
                elif ff == 4:
                    geom = _packed(v)
            props = {keys[tags[j]]: values[tags[j + 1]] for j in range(0, len(tags), 2)}
            n = props.get("total", 0)
            xs, ys, x, y, i = [], [], 0, 0, 0
            while i < len(geom):
                cmd, count = geom[i] & 7, geom[i] >> 3
                i += 1
                for _ in range(count if cmd != 7 else 0):
                    x += _zig(geom[i])
                    y += _zig(geom[i + 1])
                    i += 2
                    xs.append(x)
                    ys.append(y)
            if xs and n:
                cells.append((int(min(xs) // unit), int(min(ys) // unit), n))
    return cells


def species_grid(client, key: str, in_col: bool) -> list[tuple[int, int, int]]:
    """The world grid of one species (or subspecies): [(column 0-127, row 0-63, records)]."""
    params = [("srs", "EPSG:4326"), ("bin", "square"), ("squareSize", 64), ("taxonKey", key),
              ("hasGeospatialIssue", "false"), ("occurrenceStatus", "PRESENT")]
    if in_col:
        params.append(("checklistKey", gbifapi.COL_CHECKLIST))
    params += [("basisOfRecord", b) for b in gbifapi.BASIS]
    out: dict[tuple[int, int], int] = {}
    for tx in (0, 1):
        body = client.get_bytes(f"/0/{tx}/0.mvt", params)
        for c, r, n in decode(body) if body else []:
            out[(tx * CELLS + c, r)] = out.get((tx * CELLS + c, r), 0) + n
    return sorted((c, r, n) for (c, r), n in out.items())


def encode(cells: list[tuple[int, int, int]]) -> str:
    return " ".join(f"{c}.{r}.{n}" for c, r, n in cells)


def parse(s: str) -> list[tuple[int, int, int]]:
    return [tuple(int(x) for x in t.split(".")) for t in s.split()]    # type: ignore[misc]

