"""Project-wide settings. Paths are relative to the repository root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LITERATURE_DIR = ROOT / "literature"       # the PDF library (git-ignored; copyrighted)
PRIVATE_DIR = ROOT / "private.nosync"      # never synced, never committed: API cache, PDF text, staging
API_CACHE_DIR = PRIVATE_DIR / "api"
STAGING_DIR = PRIVATE_DIR / "staging"
SITE_DIR = ROOT / "site.nosync"                 # built output: site.nosync/public (opened locally and deployed)

CONTACT = "m.andrew.johnston@gmail.com"
USER_AGENT = f"guam-insects-research ({CONTACT})"

SITE_TITLE = "Insects of Guam"
SITE_SUBTITLE = "(and Micronesia)"

# The five areas, Guam first everywhere it matters (default filter, record ordering).
# gbif = GBIF `country` code; inat = iNaturalist place id (all verified 2026-11-13).
AREAS = [
    {"code": "GU", "name": "Guam", "gbif": "GU", "inat": 7316},
    {"code": "MP", "name": "Northern Mariana Islands", "gbif": "MP", "inat": 8355},
    {"code": "PW", "name": "Palau", "gbif": "PW", "inat": 7320},
    {"code": "FM", "name": "Federated States of Micronesia", "gbif": "FM", "inat": 10322},
    {"code": "MH", "name": "Marshall Islands", "gbif": "MH", "inat": 10324},
]
AREA_CODES = [a["code"] for a in AREAS]

# Scope is Hexapoda. The GBIF backbone has no Hexapoda node: these four classes sit
# directly under Arthropoda (54).
HEXAPOD_CLASSES = {216: "Insecta", 10713444: "Collembola", 11377931: "Protura",
                   11374670: "Diplura"}
INAT_HEXAPODA = 372739
