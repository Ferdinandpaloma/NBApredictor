"""One-time backfill of player box scores into data/player_logs.csv.

Run this LOCALLY (stats.nba.com often blocks cloud IPs like GitHub Actions):

    pip install nba_api pandas
    python -m scripts.backfill_players 2018 2026

That fetches the 2018-19 through 2026-27 seasons, one request per season
type. The daily build keeps the current season up to date from the CDN.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.players import load_logs, merge_logs, parse_minutes, save_logs  # noqa: E402
from scripts.backfill_history import season_str  # noqa: E402

LOGS = ROOT / "data" / "player_logs.csv"

# nba_api column for each of our stat columns.
API_COLS = {
    "pts": "PTS", "reb": "REB", "oreb": "OREB", "dreb": "DREB", "ast": "AST",
    "stl": "STL", "blk": "BLK", "tov": "TOV", "fgm": "FGM", "fga": "FGA",
    "fg3m": "FG3M", "fg3a": "FG3A", "ftm": "FTM", "fta": "FTA", "pf": "PF",
    "plus_minus": "PLUS_MINUS",
}


def fetch_season(season: str) -> list[dict]:
    from nba_api.stats.endpoints import leaguegamelog

    rows: list[dict] = []
    for stype in ("Regular Season", "PlayIn", "Playoffs"):
        df = leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=stype,
            player_or_team_abbreviation="P",
            league_id="00",
            timeout=90,
        ).get_data_frames()[0]
        time.sleep(1.5)  # be polite; the API rate-limits
        for r in df.itertuples(index=False):
            r = r._asdict()
            mins = parse_minutes(r["MIN"])
            if mins <= 0:
                continue
            # "LAL vs. BOS" = home game against BOS, "LAL @ BOS" = away.
            home = " vs. " in r["MATCHUP"]
            opp = r["MATCHUP"].split(" vs. " if home else " @ ")[-1].strip()
            row = {
                "game_id": r["GAME_ID"], "date": str(r["GAME_DATE"])[:10], "season": season,
                "player_id": str(r["PLAYER_ID"]), "player": r["PLAYER_NAME"],
                "team": r["TEAM_ABBREVIATION"], "opp": opp, "home": int(home),
                "min": round(mins, 2),
            }
            row.update({k: int(r[v] or 0) for k, v in API_COLS.items()})
            rows.append(row)
    return rows


def main() -> None:
    start, end = (int(x) for x in sys.argv[1:3]) if len(sys.argv) >= 3 else (2018, 2026)
    rows = load_logs(LOGS)
    for year in range(start, end + 1):
        s = season_str(year)
        new = fetch_season(s)
        print(f"{s}: {len(new)} player-games")
        rows = merge_logs(rows, new)
        save_logs(LOGS, rows)  # save as we go so a later failure keeps progress
    print(f"saved {len(rows)} rows to {LOGS}")


if __name__ == "__main__":
    main()
