from guaminsects.sources import gbifmap


def _v(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _ld(field, body):
    return _v(field << 3 | 2) + _v(len(body)) + body


def _tile(cells):
    """A vector tile of density squares: (x, y, count) in 4096-unit tile coordinates."""
    layer = _ld(1, b"occurrence") + _ld(3, b"total")
    for i, (x, y, n) in enumerate(cells):
        layer += _ld(4, _v(6 << 3) + _v(n << 1))
        geom = _v(9) + _v(x << 1) + _v(y << 1) + _v(2 | 3 << 3) + _v(64 << 1) + _v(0) + _v(0) + _v(64 << 1) + _v(127) + _v(0) + _v(15)
        layer += _ld(2, _ld(2, _v(0) + _v(i)) + _v(3 << 3) + _v(3) + _ld(4, geom))
    return _ld(3, layer + _v(5 << 3) + _v(4096))


def test_decode_cells():
    tile = _tile([(2816, 2816, 12), (0, 128, 3)])
    assert sorted(gbifmap.decode(tile)) == [(0, 2, 3), (44, 44, 12)]


def test_encode_parse_round_trip():
    cells = [(0, 2, 3), (44, 44, 12), (127, 63, 1)]
    assert gbifmap.parse(gbifmap.encode(cells)) == cells
