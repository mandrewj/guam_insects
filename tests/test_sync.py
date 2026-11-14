"""sync check / apply against fake GBIF, iNaturalist and COL clients (no network)."""

from test_match import CLASSIFICATION, FakeCol, answer, base_ds, usage

from guaminsects import dataset, match, sync
from guaminsects.sources import gbif as gbifapi

TODAY = "2026-11-20"


class FakeGbif:
    """Facet answers from a table {(country, facet, kind): {key: n}}; kind is col / backbone /
    specimens."""

    def __init__(self, table):
        self.table, self.requests = table, []

    def get(self, path, params=None):
        p = list(params)
        self.requests.append(p)
        d = dict(p)
        country, facet = d["country"], d.get("facet")
        bases = {v for k, v in p if k == "basisOfRecord"}
        kind = "specimens" if bases == set(gbifapi.SPECIMEN_BASIS) else \
            "col" if "checklistKey" in d else "backbone"
        counts = self.table.get((country, facet, kind), {})
        return {"facets": [{"counts": [{"name": k, "count": n} for k, n in counts.items()]}]}

    def get_cached(self, path, params=None, refresh=False):
        return {"key": 777, "canonicalName": "Oryctes marianus", "rank": "SPECIES",
                "taxonomicStatus": "ACCEPTED", "classKey": 216}


class FakeInat:
    def __init__(self, results):
        self.results = results

    def get(self, path, params=None):
        if params.get("place_id") == 7316:                       # Guam
            return {"results": self.results, "total_results": len(self.results)}
        return {"results": [], "total_results": 0}


def world():
    ds = base_ds()
    ds["records"] = [
        {"taxon_id": "ORRHI", "area": "GU", "source": "gbif", "records": "90"},
        {"taxon_id": "ORRHI", "area": "GU", "source": "inat", "records": "30"},
        {"taxon_id": "ORYCT", "area": "GU", "source": "gbif", "records": "95"},
        {"taxon_id": "SCARB", "area": "GU", "source": "gbif", "records": "300"}]
    cols = dataset.schema.table("records").names
    ds["records"] = [{c: r.get(c, "") for c in cols} for r in ds["records"]]
    return ds


def clients():
    gbif = FakeGbif({
        ("GU", "speciesKey", "col"): {"ORRHI": 120, "ORGIG": 4},      # ORGIG is not in the dataset
        ("GU", "genusKey", "col"): {"ORYCT": 130},                    # SCARB vanished from GU
        ("GU", "speciesKey", "specimens"): {"ORRHI": 7},
        ("GU", "speciesKey", "backbone"): {"777": 3}})                # a name COL lacks
    inat = FakeInat([{"taxon": {"id": 1, "name": "Oryctes rhinoceros", "rank": "species",
                                "preferred_common_name": "Coconut Rhinoceros Beetle"}, "count": 31}])
    return gbif, inat


def test_check_stages_the_counts_and_summarizes_them():
    ds = world()
    gbif, inat = clients()
    staging = sync.check(ds, gbif, inat, areas=["GU"], today=TODAY, progress=lambda *_: None)
    assert staging["areas"]["GU"]["col"]["ORRHI"] == 120
    assert staging["areas"]["GU"]["inat"][0]["count"] == 31
    s = sync.summarize(ds, staging)
    assert s["areas"] == ["GU"]
    assert s["new_keys"] == {"col": 1, "backbone": 1, "inat": 0}      # ORGIG, 777
    assert s["changed"] == 3                                           # 90->120, 95->130, 30->31
    assert s["gone_to_zero"] == 1 and s["vanished"][0]["taxon"] == "SCARB"
    assert s["largest_changes"][0]["now"] - s["largest_changes"][0]["was"] == 35


def test_apply_updates_counts_adds_new_taxa_and_never_removes():
    ds = world()
    gbif, inat = clients()
    staging = sync.check(ds, gbif, inat, areas=["GU"], today=TODAY, progress=lambda *_: None)
    gigas = usage("ORGIG", "Oryctes gigas", "SPECIES")

    class Col(FakeCol):
        def get_cached(self, path, params=None, refresh=False):
            if params.get("usageKey") == "ORGIG":
                return answer(gigas, classification=CLASSIFICATION)
            return super().get_cached(path, params, refresh)

    m = match.Matcher(ds, Col({}), gbif, by="the sync", today=TODAY)
    seen = []
    report = sync.apply(ds, staging, m, gbif=None, today=TODAY,
                        refresh_new=lambda d, new: seen.append(new), progress=lambda *_: None)
    rec = {(r["taxon_id"], r["area"], r["source"]): r for r in ds["records"]}
    assert rec[("ORRHI", "GU", "gbif")]["records"] == "120"
    assert rec[("ORRHI", "GU", "gbif")]["refreshed"] == TODAY
    assert rec[("ORRHI", "GU", "inat")]["records"] == "31"
    assert rec[("ORRHI", "GU", "gbif_specimens")]["records"] == "7"
    assert rec[("ORGIG", "GU", "gbif")]["records"] == "4"               # the new COL species
    assert ("SCARB", "GU", "gbif") not in rec                           # its count is gone ...
    assert any(r["id"] == "SCARB" for r in ds["taxa"])                  # ... the taxon is not
    assert report["vanished"] == [{"taxon": "SCARB", "area": "GU", "source": "gbif", "was": 300}]
    new = {r["id"]: r for r in ds["taxa"] if r["flag"] == "new"}
    assert "ORGIG" in new and new["ORGIG"]["added_by"] == "the sync" and new["ORGIG"]["nativity"] == "unknown"
    assert seen and "ORGIG" in seen[0] and report["new_taxa"] == len(report["new_ids"])
    assert dataset.check(ds).items == []
    # asking again changes nothing
    again = sync.summarize(ds, staging)
    assert again["changed"] == 0 and again["new_rows"] == 0 and again["gone_to_zero"] == 0


def test_backbone_counts_do_not_double_count_a_col_taxon():
    ds = world()
    ds["keys"] = [{"source": "gbif", "key": "1063", "name": "Oryctes", "taxon_id": "ORYCT", "how": "same"}]
    staging = {"date": TODAY, "areas": {"GU": {"col": {"ORYCT": 130}, "specimens": {},
                                              "backbone": {"1063": 95}, "inat": []}}}
    want, _ = sync.desired(ds, staging)
    assert want[("ORYCT", "GU", "gbif")] == 130          # not 225: ORYCT is in COL
