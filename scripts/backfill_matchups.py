"""Download who-guarded-whom for every game in data/player_logs.csv (stats.nba.com).

    python -m scripts.backfill_matchups            # resumable: skips games already saved
    python -m scripts.backfill_matchups --limit 50

One row per (game, offensive player, defender) with at least one partial
possession: how long the defender was on him and what he did against him.
Appends to data/matchups.csv as it goes, so it can be stopped and restarted.
stats.nba.com is only reachable from a home connection, not GitHub's runners.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "player_logs.csv"
OUT = ROOT / "data" / "matchups.csv"
FIELDS = ["game_id", "off_id", "def_id", "poss", "secs", "pts", "ast", "tov", "fgm", "fga",
          "fg3m", "fg3a", "ftm", "fta"]
STATS = {"pts": "playerPoints", "ast": "matchupAssists", "tov": "matchupTurnovers",
         "fgm": "matchupFieldGoalsMade", "fga": "matchupFieldGoalsAttempted",
         "fg3m": "matchupThreePointersMade", "fg3a": "matchupThreePointersAttempted",
         "ftm": "matchupFreeThrowsMade", "fta": "matchupFreeThrowsAttempted"}
PAUSE = 1.0  # seconds between requests


def parse(raw: dict) -> list[dict]:
    g = raw["boxScoreMatchups"]
    rows = []
    for side in ("homeTeam", "awayTeam"):
        for off in g[side]["players"]:
            for m in off.get("matchups", []):
                s = m["statistics"]
                if s["partialPossessions"] < 1:
                    continue
                rows.append({"game_id": g["gameId"], "off_id": off["personId"], "def_id": m["personId"],
                             "poss": s["partialPossessions"], "secs": round(s["matchupMinutesSort"]),
                             **{k: s[v] for k, v in STATS.items()}})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="stop after this many games")
    args = ap.parse_args()
    from nba_api.stats.library.http import NBAStatsHTTP  # nba_api's own request, minus its parser,
    # which crashes on games without tracking data

    with LOGS.open() as f:
        games = sorted({r["game_id"] for r in csv.DictReader(f)})
    done = set()
    if OUT.exists():
        with OUT.open() as f:
            done = {r["game_id"] for r in csv.DictReader(f)}
    todo = [g for g in games if g not in done][:args.limit]
    print(f"{len(games)} games, {len(done)} saved, {len(todo)} to fetch", flush=True)

    new = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for i, gid in enumerate(todo, 1):
            for attempt in range(3):
                try:
                    rows = parse(NBAStatsHTTP().send_api_request(
                        endpoint="boxscorematchupsv3", parameters={"GameID": gid}, timeout=30).get_dict())
                    break
                except Exception as e:  # noqa: BLE001 - retry, then skip the game
                    print(f"  {gid}: {type(e).__name__} (try {attempt + 1})", flush=True)
                    time.sleep(10 * (attempt + 1))
            else:
                continue
            if not rows:  # older games can be missing tracking; mark them done anyway
                rows = [{"game_id": gid, "off_id": "", "def_id": "", **{k: 0 for k in FIELDS[3:]}}]
            w.writerows(rows)
            f.flush()
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
            time.sleep(PAUSE)
    print("done", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
