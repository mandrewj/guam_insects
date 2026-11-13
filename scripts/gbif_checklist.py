#!/usr/bin/env python3
"""Species checklist for one or more Micronesian countries, straight from GBIF.

    uv run python scripts/gbif_checklist.py                 # GU MP PW FM MH, Arthropoda
    uv run python scripts/gbif_checklist.py GU --taxon 216  # Guam, Insecta only
    uv run python scripts/gbif_checklist.py GU -o data/gbif_gu.csv

One facet request per country pages `speciesKey` (never one request per species: that is the
mistake that would cost 40,000 calls). Output: species_key, records, country. Names come from a
second step (`/species?key=` in batches, or `species/match`), kept out of here on purpose so this
stays a cheap, resumable first look at how big the job is.

Facts checked 2026-11-13: Insecta records, GU 25,869; MP 5,702; PW 11,069; FM 8,601; MH 1,125.
Arthropoda (taxonKey 54) in Guam alone: 32,194 records. Mind `facetLimit` (max 1000 per page,
use `facetOffset`) and that facet counts are *records*, not distinct species.
"""
import argparse
import csv
import sys
import time

import httpx

API = "https://api.gbif.org/v1/occurrence/search"
UA = {"User-Agent": "guam-insects-research (m.andrew.johnston@gmail.com)"}
COUNTRIES = ["GU", "MP", "PW", "FM", "MH"]


def species_facet(client: httpx.Client, country: str, taxon: int, page: int = 1000):
    offset = 0
    while True:
        r = client.get(API, params={"country": country, "taxonKey": taxon, "limit": 0,
                                    "facet": "speciesKey", "facetLimit": page,
                                    "facetOffset": offset})
        r.raise_for_status()
        counts = (r.json().get("facets") or [{}])[0].get("counts", [])
        yield from ((int(c["name"]), c["count"]) for c in counts)
        if len(counts) < page:
            return
        offset += page
        time.sleep(0.4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("countries", nargs="*", default=COUNTRIES)
    ap.add_argument("--taxon", type=int, default=54, help="GBIF taxonKey (54 Arthropoda, 216 Insecta)")
    ap.add_argument("-o", "--out", help="CSV path (default: stdout)")
    args = ap.parse_args()
    out = open(args.out, "w", newline="") if args.out else sys.stdout
    w = csv.writer(out)
    w.writerow(["species_key", "records", "country"])
    with httpx.Client(headers=UA, timeout=60) as client:
        for country in args.countries:
            n = 0
            for key, count in species_facet(client, country, args.taxon):
                w.writerow([key, count, country])
                n += 1
            print(f"{country}: {n} species", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
