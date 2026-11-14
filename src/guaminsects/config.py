"""Project-wide settings. Paths are relative to the repository root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# data/ is synced by iCloud (~/Documents): cached API responses, photo copies, extracted PDF
# text. data.nosync/ stays local: iCloud must not sync a live SQLite database, and logs are
# machine-specific. Everything the database holds can be rebuilt from data/ and curation/.
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                 # cached API answers, one file per request
MEDIA_DIR = DATA_DIR / "media"
CURATED_PHOTOS_DIR = DATA_DIR / "curated_photos"   # the administrator's own photos
LOCAL_DIR = ROOT / "data.nosync"
DB_PATH = LOCAL_DIR / "guam.sqlite"
LOGS_DIR = LOCAL_DIR / "logs"
LITERATURE_DIR = ROOT / "literature"       # the PDF library (git-ignored; copyrighted)
# Hand curation lives in git: it is the one thing a pipeline re-run must never overwrite.
CURATION_DIR = ROOT / "curation"
SOURCES_DIR = ROOT / "sources"             # manifests of downloaded documents (git-tracked)
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
# directly under Arthropoda (54), so the tree root is a curated "Hexapoda" taxon above them.
ARTHROPODA_KEY = 54
HEXAPOD_CLASSES = {216: "Insecta", 10713444: "Collembola", 11377931: "Protura",
                   11374670: "Diplura"}
INAT_HEXAPODA = 372739

# Ids of taxa added by hand start here, far above any GBIF key (~13 million in 2026), so a
# curated taxon never collides with a backbone key and its URL (#/t/<id>) never changes.
CURATED_ID_BASE = 900_000_000
HEXAPODA_ID = CURATED_ID_BASE + 1
