#!/bin/bash
# Daily refresh, run from this Mac by launchd (see README "Daily updates").
# cdn.nba.com blocks GitHub's runners, so the data is pulled here through
# stats.nba.com, then pushed; Vercel redeploys on the push.
#
#   daily.sh            morning: last night's box scores, ratings, projections, picks
#   daily.sh pregame    afternoon: projections again with the latest injury report
#                       (no new box scores; picks already made stay locked)
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

MODE="${1:-morning}"
cd "$(dirname "$0")/.."
PY=.venv/bin/python
echo "=== $(date) ($MODE) ==="

# Retry flaky network steps a few times before giving up.
retry() {
  local n
  for n in 1 2 3; do
    "$@" && return 0
    echo "failed (try $n): $*"
    sleep $((30 * n))
  done
  return 1
}

retry git pull --rebase --quiet origin main

if [ "$MODE" = morning ]; then
  # Current season's box scores (one stats.nba.com request per season type).
  YEAR=$($PY -c "from nbaelo.statsapi import current_season; print(current_season()[:4])")
  $PY -m scripts.backfill_players "$YEAR" "$YEAR"
  MSG="Daily update $(date +%F)"
else
  MSG="Pre-game update $(date '+%F %H:%M')"
fi

$PY -m scripts.build
$PY -m scripts.build_props --no-fetch $([ "$MODE" = pregame ] && echo --odds)

git add site/*.json site/players data/player_logs.csv data/picks.csv
if [ -f data/book_lines.csv ]; then git add data/book_lines.csv; fi
if git diff --cached --quiet; then
  echo "no changes"
  exit 0
fi
git commit --quiet -m "$MSG"

# Someone may have pushed while this ran. Replay this commit on top; where data files
# conflict, keep what's already published (so posted picks never change).
for n in 1 2 3; do
  if git push --quiet origin main; then
    echo "pushed"
    exit 0
  fi
  echo "push rejected (try $n); rebasing onto the remote"
  sleep $((20 * n))
  retry git fetch --quiet origin
  git rebase --quiet -X ours origin/main || { git rebase --abort; echo "rebase failed"; exit 1; }
done
echo "gave up pushing"
exit 1
