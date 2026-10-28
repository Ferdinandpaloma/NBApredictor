"""Build static predictions.

    python -m scripts.build                     # fetch live schedule
    python -m scripts.build --schedule FILE     # use a saved schedule JSON

Writes:
    site/predictions.json   upcoming games with win probabilities
    site/ratings.json       current Elo ratings, sorted
    site/meta.json          build time + backtest metrics
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.data import fetch_schedule, load_history, merge, now_iso, parse_schedule  # noqa: E402
from nbaelo.elo import EloModel, backtest  # noqa: E402

HISTORY = ROOT / "data" / "history.csv"
SITE = ROOT / "site"
DAYS_AHEAD = 7


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", type=Path, help="local schedule JSON (skips the network)")
    ap.add_argument("--out", type=Path, default=SITE)
    args = ap.parse_args()

    raw = json.loads(args.schedule.read_text()) if args.schedule else fetch_schedule()
    finished, upcoming = parse_schedule(raw)
    games = merge(load_history(HISTORY), finished)
    print(f"{len(games)} finished games, {len(upcoming)} upcoming")

    # Replay every finished game to get current ratings.
    model = EloModel()
    for g in games:
        model.update(g)

    # Carry ratings into the new season even before its first game.
    season = raw["leagueSchedule"]["seasonYear"]
    model._new_season(season)

    # Predict the next week of games (dates are sorted, so take the window).
    dates = sorted({g.date for g in upcoming})[:DAYS_AHEAD]
    preds = [
        {"game_id": g.game_id, "date": g.date, "home": g.home, "away": g.away, **model.predict(g)}
        for g in upcoming
        if g.date in dates
    ]

    ratings = sorted(
        ({"team": t, "elo": round(r, 1)} for t, r in model.ratings.items()),
        key=lambda x: -x["elo"],
    )
    meta = {"built_at": now_iso(), "season": season, "backtest": backtest(games)}

    write_json(args.out / "predictions.json", preds)
    write_json(args.out / "ratings.json", ratings)
    write_json(args.out / "meta.json", meta)
    print(f"wrote {len(preds)} predictions; backtest: {meta['backtest']}")


if __name__ == "__main__":
    main()
