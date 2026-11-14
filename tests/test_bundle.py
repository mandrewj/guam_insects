"""Chunking: a family and everything under it share a chunk; big families split by genus;
small neighbours merge; taxa above Family have chunks of their own."""

from guaminsects.build import bundle


def world():
    """root > Insecta > Order O1 > families F1 (small), F2 (small), F3 (huge: genera G1, G2)."""
    recs, sizes = {}, {}

    def add(tid, name, rank, parent, size):
        lineage = [] if parent is None else recs[parent]["lineage"] + [
            {"id": parent, "name": recs[parent]["name"], "rank": recs[parent]["rank"]}]
        recs[tid] = {"id": tid, "name": name, "rank": rank, "lineage": lineage}
        sizes[tid] = size

    add(1, "Hexapoda", "Subphylum", None, 1000)
    add(2, "Insecta", "Class", 1, 1000)
    add(3, "O1", "Order", 2, 5000)
    add(10, "F1", "Family", 3, 10_000)
    add(11, "F1a", "Genus", 10, 10_000)
    add(20, "F2", "Family", 3, 10_000)
    add(30, "F3", "Family", 3, 1000)
    add(31, "G1", "Genus", 30, 300_000)
    add(32, "G2", "Genus", 30, 300_000)
    add(33, "G1s", "Species", 31, 5000)
    return recs, sizes


def test_chunks():
    recs, sizes = world()
    chunk = bundle.assign_chunks(recs, sizes)
    assert set(chunk) == set(recs)                       # everything is in a chunk
    assert len({chunk[1], chunk[2], chunk[3]}) == 3      # above Family: one each
    assert chunk[10] == chunk[11]                        # a family with what is under it
    assert chunk[10] == chunk[20]                        # small neighbours merge
    assert chunk[30] != chunk[31] and chunk[31] != chunk[32]   # a big family splits by genus
    assert chunk[31] == chunk[33]                        # a genus keeps its species
    assert chunk[10] not in (chunk[3], chunk[2], chunk[1])


def test_index_round_trips():
    recs, sizes = world()
    chunk = bundle.assign_chunks(recs, sizes)
    text = bundle.index_script(chunk)
    import json
    body = json.loads(text[len("guaminsects.index("):text.rindex(");")])
    seen = {}
    for n, enc in body.items():
        tid = 0
        for part in enc.split(","):
            tid += int(part, 36)
            seen[tid] = int(n)
    assert seen == chunk
