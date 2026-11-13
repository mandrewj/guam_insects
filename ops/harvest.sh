#!/usr/bin/env bash
# Finish the data after the sweeps: match names, fill in links, photos and COL details, then
# rebuild and redeploy. Incremental (every step skips what it already has), one stream per
# host, so it can run any time new names arrive. ops/refresh_all.sh re-sweeps everything.
#
#   ops/harvest.sh            # harvest, rebuild both sites, check, deploy to production
#   ops/harvest.sh --no-deploy
#
# Logs: data.nosync/logs/harvest-<step>.log; progress in data.nosync/logs/harvest.log.
set -uo pipefail
cd "$(dirname "$0")/.."
LOG=data.nosync/logs
mkdir -p "$LOG"
run() { local name=$1; shift; echo "$(date +%H:%M) $name start"
        if uv run guaminsects "$@" > "$LOG/harvest-$name.log" 2>&1; then
          echo "$(date +%H:%M) $name done: $(grep -v '^ ' "$LOG/harvest-$name.log" | tail -1)"
        else echo "$(date +%H:%M) $name FAILED (see $LOG/harvest-$name.log)"; fi; }

# 1. Names. GBIF (api.gbif.org) in one stream; ChecklistBank (COL's API) alongside.
( run literature literature; run match match; run col col; run synonyms synonyms ) &
gbif=$!
( run colinfo colinfo ) &
clb=$!
wait "$gbif"; wait "$clb"
run establishment establishment
run resolve resolve
# 2. Links and photos: Wikidata first (it names the Wikipedia articles, Commons images and
#    iNat taxa), then each host in its own stream.
run wikidata wikidata --refresh
( run wikipedia wikipedia ) &
wiki=$!
( run photos-fetch photos commons inat ) &
pics=$!
( run colinfo-2 colinfo ) &                  # COL details for taxa new since step 1
clb=$!
run bugguide bugguide
wait "$wiki"; wait "$pics"; wait "$clb"
# 3. The tree once more (COL's extinct list and new names), photos, and both sites.
run resolve-2 resolve
run photos photos select thumbs
run build build public local
echo "$(date +%H:%M) check"; uv run python ops/check_site.py 2>&1 | tail -6
uv run python ops/review.py | tail -1
uv run guaminsects stats 2>&1 | tail -12
if [ "${1:-}" != "--no-deploy" ]; then echo "$(date +%H:%M) deploy"; ops/deploy.sh --prod 2>&1 | grep -E "Aliased|ready|error|FAILED|https://" | tail -4; fi
echo "$(date +%H:%M) harvest done"
