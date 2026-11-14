"""Search indexes for the app, from the records (the tokenizer lives in ../search.py and is
mirrored in app.js; ops/check_site.py checks they agree).

    data/s/names.js   one row per taxon for as-you-type suggestions       loaded on the first search
    data/s/<x>.js     full-text index: terms starting with <x>            loaded for the query's terms
"""

import json
from collections import defaultdict

from .. import search as s
from .bundle import write_if_changed


def build(records: dict[int, dict], out) -> dict:
    data = out / "data" / "s"
    # [id, name, every name for matching, rank, order > family, hidden, the common name shown,
    #  the direct parent shown]: matching uses all the names, the list shows only these two.
    rows = [[tid, r["name"], " | ".join(s._names(r)), r["rank"], s._context(r),
             int(r["hidden"] or r["status"] == "synonym"), r["common"] or "",
             r["lineage"][-1]["name"] if r["lineage"] else ""] for tid, r in sorted(records.items())]
    write_if_changed(data / "names.js", f"{s.JS_GLOBAL}.names("
                     + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ");\n")
    docs = s.documents(None, records)
    index: dict[str, dict[str, dict[int, int]]] = defaultdict(lambda: defaultdict(dict))
    for tid, counts in docs.items():
        for term, tf in counts.items():
            index[term[:1]][term][tid] = tf
    keys = []
    for key, terms in sorted(index.items()):
        body = {term: s.encode_postings(p) for term, p in sorted(terms.items())}
        write_if_changed(data / f"{key}.js", f"{s.JS_GLOBAL}.ft({json.dumps(key)},"
                         + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + ");\n")
        keys.append(key)
    for stale in data.glob("*.js"):
        if stale.stem != "names" and stale.stem not in index:
            stale.unlink()
    return {"docs": len(docs), "shards": keys, "stopwords": s.STOPWORDS}
