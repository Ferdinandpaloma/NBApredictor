"""One-time backfill of past seasons into data/history.csv.

Run this LOCALLY (stats.nba.com often blocks cloud IPs like GitHub Actions):

    pip install nba_api pandas
    python -m scripts.backfill_history 2018 2025

That fetches the 2018-19 through 2025-26 seasons. Commit the CSV; the
daily build only needs the CDN feed for the current season after that.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.data import load_history, merge, save_history  # noqa: E402
from nbaelo.elo import Game  # noqa: E402

HISTORY = ROOT / "data" / "history.csv"


def season_str(start: int) -> str:
    return f"{start}-{str(start + 1)[-2:]}"


def fetch_season(season: str) -> list[Game]:
    from nba_api.stats.endpoints import leaguegamefinder

    games: list[Game] = []
    for stype in ("Regular Season", "PlayIn", "Playoffs"):
        df = leaguegamefinder.LeagueGameFinder(
            season_nullable=season,
            league_id_nullable="00",
            season_type_nullable=stype,
            timeout=60,
        ).get_data_frames()[0]
        time.sleep(1.5)  # be polite; the API rate-limits
        if df.empty:
            continue
        # One row per team per game. "LAL vs. BOS" = home, "LAL @ BOS" = away.
        home = df[df["MATCHUP"].str.contains(" vs. ")]
        away = df[df["MATCHUP"].str.contains(" @ ")]
        merged = home.merge(away, on="GAME_ID", suffixes=("_h", "_a"))
        for _, r in merged.iterrows():
            games.append(Game(
                game_id=r["GAME_ID"],
                date=str(r["GAME_DATE_h"])[:10],
                season=season,
                home=r["TEAM_ABBREVIATION_h"],
                away=r["TEAM_ABBREVIATION_a"],
                home_pts=int(r["PTS_h"]),
                away_pts=int(r["PTS_a"]),
            ))
    return games


def main() -> None:
    start, end = (int(x) for x in sys.argv[1:3]) if len(sys.argv) >= 3 else (2018, 2025)
    games = load_history(HISTORY)
    for year in range(start, end + 1):
        s = season_str(year)
        new = fetch_season(s)
        print(f"{s}: {len(new)} games")
        games = merge(games, new)
    save_history(HISTORY, games)
    print(f"saved {len(games)} games to {HISTORY}")


if __name__ == "__main__":
    main()
