#!/usr/bin/env bash
# The rebuild after a push to main (.github/workflows/rebuild.yml): the data snapshot, the
# tree with the committed curation, the site, its check, the deploy. Runs anywhere with the
# Vercel variables set (see deploy.sh); it never needs the data machine.
#
# Edits arrive as curation/*.csv rows (the editor writes them with taxonomy.csv). A
# taxonomy.csv that matches its commit is never read as edits (taxonomy.sync), so the
# regeneration below cannot turn pipeline values into curation.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run guaminsects restore --force
uv run guaminsects resolve
ops/deploy.sh --prod
