#!/usr/bin/env bash
# The rebuild after a push to main (.github/workflows/rebuild.yml): check the dataset, build
# the site from it, check the site, deploy. Needs nothing but the repository and the Vercel
# variables (see deploy.sh); it never needs the data machine.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run guaminsects dataset check
ops/deploy.sh --prod
