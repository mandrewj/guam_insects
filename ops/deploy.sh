#!/usr/bin/env bash
# Build the public site, check it, and deploy it to Vercel with the CLI.
#
#   ops/deploy.sh            # preview deployment (a private-ish URL to look at first)
#   ops/deploy.sh --prod     # production: insects-of-guam.vercel.app
#
# The public build only: openly licensed content, no PDF text, no admin page. Vercel Hobby
# accepts 100 MB and 15,000 files per CLI deploy (site.PUBLIC_BUDGET_MB keeps us under the
# first; --archive=tgz covers the second). The project link lives in site/public/.vercel,
# which the build leaves alone and git never sees.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=insects-of-guam

uv run guaminsects build public
uv run python ops/check_site.py --browsers chrome
files=$(find site/public -type f -not -path '*/.vercel/*' | wc -l | tr -d ' ')
size=$(du -sm site/public | cut -f1)
echo "site/public: ${files} files, ${size} MB"

# Static files only: no framework, no build step on Vercel's side.
cat > site/public/vercel.json <<'JSON'
{
  "cleanUrls": false,
  "headers": [
    { "source": "/data/(.*)", "headers": [{ "key": "Cache-Control", "value": "public, max-age=3600" }] },
    { "source": "/media/(.*)", "headers": [{ "key": "Cache-Control", "value": "public, max-age=604800" }] }
  ]
}
JSON

if [ ! -d site/public/.vercel ]; then
  vercel link --yes --project "$PROJECT" --cwd site/public
fi
args=(deploy --yes --cwd site/public)
[ "$files" -gt 14000 ] && args+=(--archive=tgz)
[ "${1:-}" = "--prod" ] && args+=(--prod)
vercel "${args[@]}"
