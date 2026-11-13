#!/usr/bin/env bash
# Refresh every source and rebuild both sites. One stream per host (docs/LESSONS.md): the
# GBIF steps run in sequence in one stream; Wikidata, Wikipedia, Commons and iNaturalist
# each run in their own, alongside. Every step is resumable, so a failed run can be rerun.
#
#   ops/refresh_all.sh            # everything
#   ops/refresh_all.sh --no-inat  # skip iNaturalist (e.g. while entobase jobs use it)
#
# Logs: data.nosync/logs/refresh-<step>.log. Check `ps` for entobase jobs first: they share
# this IP with iNaturalist.
set -uo pipefail
cd "$(dirname "$0")/.."
LOG=data.nosync/logs
mkdir -p "$LOG"
run() { local name=$1; shift; echo "$(date +%H:%M) $name"; uv run guaminsects "$@" > "$LOG/refresh-$name.log" 2>&1 || echo "  $name FAILED (see $LOG/refresh-$name.log)"; }

main() {
  # GBIF stream: presence, classification, literature checklists, island presence.
  ( run checklist checklist; run taxa taxa; run plazi plazi; run croppests croppests
    run islands islands ) &
  gbif=$!
  if [ "${1:-}" != "--no-inat" ]; then
    ( run inat-sweep inat --sweep-only ) &
    inat=$!
  fi
  run library library
  run pdftext pdftext
  wait "$gbif"
  [ -n "${inat:-}" ] && wait "$inat" && run inat-link inat --link-only
  run literature literature          # GBIF matching of new names: after the GBIF stream
  run establishment establishment
  run resolve resolve
  ( run wikidata wikidata; run wikipedia wikipedia ) &
  wiki=$!
  run bugguide bugguide
  wait "$wiki"
  if [ "${1:-}" != "--no-inat" ]; then run photos photos; else run photos photos commons select thumbs; fi
  run resolve-2 resolve
  run build build public local
  uv run python ops/check_site.py --browsers chrome
  uv run python ops/review.py
}
main "$@"
