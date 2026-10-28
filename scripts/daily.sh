#!/bin/bash
# Daily refresh, run from this Mac by launchd (see README "Daily updates").
# cdn.nba.com blocks GitHub's runners, so the data is pulled here through
# stats.nba.com, then pushed; Vercel redeploys on the push.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$(dirname "$0")/.."
PY=.venv/bin/python
echo "=== $(date) ==="

git pull --rebase --quiet origin main

# Current season's box scores (one stats.nba.com request per season type).
YEAR=$($PY -c "from nbaelo.statsapi import current_season; print(current_season()[:4])")
$PY -m scripts.backfill_players "$YEAR" "$YEAR"

$PY -m scripts.build
$PY -m scripts.build_props --no-fetch

git add site/*.json site/players data/player_logs.csv data/picks.csv
if git diff --cached --quiet; then
  echo "no changes"
else
  git commit --quiet -m "Daily update $(date +%F)"
  git push --quiet origin main
  echo "pushed"
fi
